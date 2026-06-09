"""Textractor-based memory reader for galgame text extraction.

Uses TextractorCLI to hook into the game process and read text directly from
the game's memory, avoiding the need for OCR/screen capture.

Architecture:
    - ``MemoryReaderManager`` runs TextractorCLI as a subprocess
    - A background thread drains stdout lines into a thread-safe queue
    - The async ``poll()`` method reads lines with minimal latency
    - Text is deduplicated via a sliding window of recent line hashes
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_TEXT_EXTRACT_PATTERN = re.compile(r"^(?:\[\d{2}:\d{2}:\d{2}\] )?(.*)$")
_MEMORY_READER_DEFAULT_ENGINE = "unity"


# ── Data types ───────────────────────────────────────────────────────────────
@dataclass
class MemoryLine:
    """A single line read from game memory."""

    text: str
    raw: str = ""
    hash: str = ""
    timestamp: float = 0.0
    engine: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.monotonic()
        if not self.hash and self.text:
            self.hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass
class ReaderState:
    """Snapshot of the memory reader's current state."""

    running: bool = False
    process_pid: int = 0
    engine: str = ""
    hook_code: str = ""
    lines_read: int = 0
    last_line_at: float = 0.0
    error: str = ""
    recent_lines: list[MemoryLine] = field(default_factory=list)


# ── Textractor handle ────────────────────────────────────────────────────────


def _decode_textractor_line(raw: bytes) -> str:
    """Decode a raw stdout line from TextractorCLI.

    Textractor may emit lines in UTF-8, UTF-16-LE, or with embedded null bytes.
    This tries multiple decoding strategies and returns cleaned text.
    """
    payload = bytes(raw or b"").rstrip(b"\r\n")
    if not payload:
        return ""

    # Try UTF-16-LE first (common for Japanese locale Windows processes)
    if b"\x00" in payload or len(payload) % 2 == 0:
        candidates = [payload]
        if payload.startswith(b"\x00"):
            candidates.append(payload[1:])
        if len(payload) % 2:
            candidates.append(payload[:-1])
            if payload.startswith(b"\x00"):
                candidates.append(payload[1:-1])
        for candidate in candidates:
            if not candidate:
                continue
            try:
                text = candidate.decode("utf-16-le", errors="replace")
            except Exception:
                continue
            cleaned = text.replace("\x00", "").replace("�", "").strip()
            if cleaned:
                return cleaned

    # Fall back to UTF-8
    return payload.decode("utf-8", errors="replace").replace("\x00", "").replace("�", "").strip()


def _extract_text_content(raw_line: str) -> str:
    """Extract the meaningful text content from a Textractor output line.

    Textractor may prefix lines with timestamps like ``[12:34:56] ``.
    """
    line = raw_line.strip()
    match = _TEXT_EXTRACT_PATTERN.match(line)
    if match:
        text = match.group(1).strip()
    else:
        text = line
    # Normalize: collapse whitespace, strip control chars
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("​", "").replace("‌", "").replace("‍", "").replace("﻿", "")
    return text.strip()


def _find_textractor_binary() -> str | None:
    """Search for TextractorCLI in common locations."""
    candidates = [
        # Bundled with the existing galgame_plugin
        "plugin/plugins/galgame_plugin/bin/TextractorCLI.exe",
        "plugin/plugins/galgame_plugin/bin/Textractor/TextractorCLI.exe",
        # Common install paths
        os.path.expandvars("%APPDATA%\\Textractor\\TextractorCLI.exe"),
        os.path.expandvars("%LOCALAPPDATA%\\Textractor\\TextractorCLI.exe"),
        # System PATH
        "TextractorCLI.exe",
    ]
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded):
            return expanded
    # Check PATH
    found = shutil.which("TextractorCLI")
    if found:
        return found
    found = shutil.which("TextractorCLI.exe")
    if found:
        return found
    return None


def _build_hook_command(code: str, pid: int) -> str:
    """Build a Textractor hook command string."""
    normalized = str(code or "").strip()
    if not normalized:
        return ""
    if re.search(r"(?:^|\s)-P\d+\b", normalized):
        return normalized
    return f"{normalized} -P{int(pid)}"


# ── Memory Reader Manager ────────────────────────────────────────────────────


class MemoryReaderManager:
    """Manages a TextractorCLI subprocess for memory-based text extraction.

    Usage::

        reader = MemoryReaderManager(
            textractor_path="/path/to/TextractorCLI.exe",
            dedupe_window=32,
        )
        await reader.start(target_pid=12345, hook_code="/HQ14+3C@GameAssembly.dll#0x33A440")
        async for line in reader.poll_iter():
            print(line.text)
        await reader.stop()
    """

    def __init__(
        self,
        *,
        textractor_path: str = "",
        dedupe_window: int = 32,
        logger: logging.Logger | None = None,
    ) -> None:
        self._textractor_path = textractor_path
        self._dedupe_window = max(1, int(dedupe_window))
        self._logger = logger or _LOGGER
        self._process: subprocess.Popen | None = None
        self._line_queue: queue.Queue[str | None] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._lines_read = 0
        self._last_line_at = 0.0
        self._error = ""
        self._engine = ""
        self._seen_hashes: deque[str] = deque(maxlen=self._dedupe_window)

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def lines_read(self) -> int:
        return self._lines_read

    @property
    def last_line_at(self) -> float:
        return self._last_line_at

    @property
    def error(self) -> str:
        return self._error

    def get_state(self) -> ReaderState:
        """Return a snapshot of the reader's current state."""
        return ReaderState(
            running=self._running,
            process_pid=self._process.pid if self._process else 0,
            engine=self._engine,
            hook_code=getattr(self, "_active_hook_code", ""),
            lines_read=self._lines_read,
            last_line_at=self._last_line_at,
            error=self._error,
        )

    async def start(
        self,
        *,
        target_pid: int,
        hook_code: str = "",
        engine: str = "",
    ) -> bool:
        """Start TextractorCLI and attach to the target process.

        Args:
            target_pid: PID of the game process to hook into.
            hook_code: Textractor hook code (e.g. ``/HQ14+3C@GameAssembly.dll#0x33A440``).
            engine: Game engine hint (``unity``, ``kirikiri``, ``renpy``, etc.).
        """
        if self._running:
            await self.stop()

        binary = self._resolve_binary()
        if not binary:
            self._error = "TextractorCLI not found"
            self._logger.error(self._error)
            return False

        self._engine = str(engine or "").strip().lower() or _MEMORY_READER_DEFAULT_ENGINE
        self._active_hook_code = hook_code

        try:
            cmd = [binary]
            if hook_code:
                cmd.append(_build_hook_command(hook_code, target_pid))
            else:
                # Auto-attach mode: Textractor will try to find the process
                cmd.append(f"-P{target_pid}")

            self._logger.info("Starting TextractorCLI: %s", " ".join(cmd))

            # Start the subprocess
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            # Start the reader thread
            self._running = True
            self._lines_read = 0
            self._last_line_at = time.monotonic()
            self._error = ""
            self._seen_hashes.clear()
            self._line_queue = queue.Queue()

            self._reader_thread = threading.Thread(
                target=self._drain_stdout,
                daemon=True,
                name="textractor-reader",
            )
            self._reader_thread.start()

            self._logger.info(
                "TextractorCLI started (pid=%d, target_pid=%d)",
                self._process.pid,
                target_pid,
            )
            return True

        except Exception as exc:
            self._error = f"Failed to start TextractorCLI: {exc}"
            self._logger.exception(self._error)
            self._running = False
            return False

    async def stop(self) -> None:
        """Stop the TextractorCLI subprocess and clean up."""
        self._running = False

        # Signal the reader thread to stop
        self._line_queue.put(None)

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)

        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3.0)
            except Exception as exc:
                self._logger.warning("Error stopping TextractorCLI: %s", exc)
            finally:
                self._process = None

        self._reader_thread = None
        self._logger.info("TextractorCLI stopped (lines_read=%d)", self._lines_read)

    async def poll(self, timeout: float = 0.1) -> MemoryLine | None:
        """Poll for the next line of text from the game.

        Returns ``None`` if no line is available within the timeout.
        Deduplicates lines based on a hash of the normalized text.
        """
        if not self._running:
            return None

        try:
            raw = await asyncio.to_thread(self._line_queue.get, timeout=timeout)
        except queue.Empty:
            return None

        if raw is None:  # Stop signal
            return None

        text = _extract_text_content(raw)
        if not text:
            return None

        # Deduplicate
        line_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        if line_hash in self._seen_hashes:
            return None
        self._seen_hashes.append(line_hash)

        self._lines_read += 1
        self._last_line_at = time.monotonic()

        return MemoryLine(
            text=text,
            raw=raw,
            hash=line_hash,
            timestamp=self._last_line_at,
            engine=self._engine,
        )

    async def poll_iter(self):
        """Async generator that yields new lines as they arrive."""
        while self._running:
            line = await self.poll(timeout=0.5)
            if line is not None:
                yield line
            await asyncio.sleep(0)

    # ── Internals ────────────────────────────────────────────────────────────

    def _resolve_binary(self) -> str | None:
        if self._textractor_path:
            expanded = os.path.expanduser(self._textractor_path)
            if os.path.isfile(expanded):
                return expanded
            self._logger.warning(
                "Configured textractor_path not found: %s",
                self._textractor_path,
            )
        return _find_textractor_binary()

    def _drain_stdout(self) -> None:
        """Read stdout lines from the TextractorCLI subprocess.

        Runs in a dedicated daemon thread. Pushes decoded lines into the queue.
        """
        if self._process is None or self._process.stdout is None:
            return
        try:
            while self._running:
                raw = self._process.stdout.readline()
                if not raw:
                    break
                line = _decode_textractor_line(raw)
                if line:
                    self._line_queue.put(line)
        except Exception as exc:
            self._error = f"stdout read error: {exc}"
            self._logger.debug("Textractor stdout drain error: %s", exc)
        finally:
            if self._running:
                self._line_queue.put(None)
