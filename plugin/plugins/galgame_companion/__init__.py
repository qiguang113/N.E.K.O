"""Galgame Companion Plugin — 猫娘陪玩助手

A focused plugin that uses memory reading (Textractor) to capture galgame
dialogue text and prompts the catgirl AI to react to the story in real time.

Key features:
- Memory reading via TextractorCLI (process memory hooking)
- Configurable memory mixing: blend with catgirl's memory or keep isolated
- Scene-change detection and greeting
- Idle detection when game is paused
- Deduplication to avoid spam on repeated text
- Hosted TSX UI panel for configuration and monitoring
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time as _time
from collections import deque
from pathlib import Path
from typing import Annotated, Any

from plugin.sdk.plugin import (
    NekoPluginBase,
    Ok,
    Err,
    SdkError,
    neko_plugin,
    plugin_entry,
    lifecycle,
    timer_interval,
    ui,
    tr,
    get_plugin_logger,
)

from .memory_reader import MemoryReaderManager, MemoryLine, ReaderState
from .prompt_builder import (
    PromptBuilder,
    PromptResult,
    CompanionConfig,
)


# ── Constants ────────────────────────────────────────────────────────────────
PLUGIN_ID = "galgame_companion"
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_DEDUPE_WINDOW = 32
DEFAULT_IDLE_TIMEOUT = 120.0
SCENE_CHANGE_SIMILARITY_THRESHOLD = 0.3


# ── Helpers ──────────────────────────────────────────────────────────────────


def _simple_text_similarity(a: str, b: str) -> float:
    """Compute a quick word-overlap similarity between two texts (0.0–1.0)."""
    if not a or not b:
        return 0.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


def _detect_scene_change(
    recent_lines: list[str],
    previous_scene_signature: str,
    *,
    threshold: float = SCENE_CHANGE_SIMILARITY_THRESHOLD,
) -> bool:
    """Detect if recent lines suggest a scene change via word-overlap comparison."""
    if not recent_lines or not previous_scene_signature:
        return False
    combined = " ".join(recent_lines[-5:])
    similarity = _simple_text_similarity(combined, previous_scene_signature)
    return similarity < threshold


def _list_game_processes() -> list[dict[str, Any]]:
    """List candidate game processes for memory hooking.

    Scans for common galgame/VN engine process names.
    """
    candidates: list[dict[str, Any]] = []
    engine_keywords = [
        "unity", "renpy", "kirikiri", "krkr", "tyranos", "tyrano",
        "nscripter", "onscripter", "rpgmaker", "rpg", "wolf",
        "live2d", "yu-ris", "adv", "visual", "novel",
        ".exe", "game", "steam",
    ]

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            # Use tasklist for simplicity
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.replace('"', "").split(",")
                if len(parts) >= 2:
                    name = parts[0].strip()
                    pid_str = parts[1].strip()
                    name_lower = name.lower()
                    if any(kw in name_lower for kw in engine_keywords):
                        try:
                            pid = int(pid_str)
                            candidates.append({"name": name, "pid": pid})
                        except ValueError:
                            pass
        except Exception:
            pass
    else:
        # macOS / Linux: use ps
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,comm"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[0])
                        except ValueError:
                            continue
                        name = parts[1].strip()
                        name_lower = name.lower()
                        if any(kw in name_lower for kw in engine_keywords):
                            candidates.append({"name": name, "pid": pid})
        except Exception:
            pass

    # Also check via `ps aux` for full paths
    if sys.platform != "win32":
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) < 11:
                    continue
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                cmd = " ".join(parts[10:])
                cmd_lower = cmd.lower()
                if any(kw in cmd_lower for kw in engine_keywords):
                    # Avoid duplicates
                    if not any(c["pid"] == pid for c in candidates):
                        # Extract just the executable name
                        exe_name = os.path.basename(parts[10]) if len(parts) > 10 else cmd
                        candidates.append({"name": exe_name, "pid": pid})
        except Exception:
            pass

    return candidates


# ── Plugin ───────────────────────────────────────────────────────────────────


@neko_plugin
class GalgameCompanionPlugin(NekoPluginBase):
    """Galgame Companion Plugin.

    Uses TextractorCLI to read galgame dialogue from process memory,
    then pushes context prompts to the chat so the catgirl AI can
    react to the story in character.
    """

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.logger = get_plugin_logger(PLUGIN_ID)
        self._reader: MemoryReaderManager | None = None
        self._builder: PromptBuilder | None = None
        self._config: CompanionConfig = CompanionConfig()
        self._poll_interval: float = DEFAULT_POLL_INTERVAL
        self._dedupe_window: int = DEFAULT_DEDUPE_WINDOW
        self._idle_timeout: float = DEFAULT_IDLE_TIMEOUT
        self._textractor_path: str = ""

        # Accumulated unreplied lines
        self._pending_lines: deque[str] = deque(maxlen=64)
        self._last_reply_at: float = 0.0
        self._last_scene_change_at: float = 0.0
        self._previous_scene_signature: str = ""
        self._reply_cooldown_until: float = 0.0
        self._scene_change_cooldown_until: float = 0.0
        self._idle_notified: bool = False
        self._running: bool = False

        # Reader target state
        self._target_pid: int = 0
        self._target_hook_code: str = ""
        self._target_engine: str = ""
        self._last_error: str = ""
        self._last_push_content: str = ""
        self._last_push_time: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @lifecycle(id="startup")
    async def on_startup(self, **_):
        """Load config and initialize components."""
        self.logger.info("Galgame陪玩助手启动中...")
        await self._load_config()
        self._builder = PromptBuilder(self._config)
        self._running = True
        self.logger.info(
            "Galgame陪玩助手已就绪 (memory_mix=%s, poll_interval=%.1fs)",
            "ON" if self._config.memory_mix_enabled else "OFF",
            self._poll_interval,
        )
        return Ok({"status": "ready"})

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_):
        """Clean up resources."""
        self.logger.info("Galgame陪玩助手正在关闭...")
        self._running = False
        if self._reader and self._reader.running:
            await self._reader.stop()
        return Ok({"status": "stopped"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_):
        """Reload config when user changes settings."""
        self.logger.info("配置变更，重新加载...")
        await self._load_config()
        if self._builder:
            self._builder = PromptBuilder(self._config)
        self._reply_cooldown_until = 0.0
        self._pending_lines.clear()
        return Ok({"reloaded": True})

    # ── Hosted UI: context ───────────────────────────────────────────────────

    @ui.context(id="dashboard")
    async def dashboard(self):
        """Provide state for the TSX panel."""
        reader_state = self._build_reader_state_dict()
        config = {
            "memory_mix_enabled": self._config.memory_mix_enabled,
            "max_context_lines": self._config.max_context_lines,
            "reply_cooldown_seconds": self._config.reply_cooldown_seconds,
            "min_lines_before_reply": self._config.min_lines_before_reply,
            "greet_on_scene_change": self._config.greet_on_scene_change,
            "scene_change_cooldown_seconds": self._config.scene_change_cooldown_seconds,
            "push_priority": self._config.push_priority,
            "include_line_quote": self._config.include_line_quote,
            "max_reply_chars": self._config.max_reply_chars,
            "poll_interval": self._poll_interval,
            "idle_timeout": self._idle_timeout,
        }
        processes = _list_game_processes() if not self._reader or not self._reader.running else []

        return {
            "running": self._running,
            "reader": reader_state,
            "config": config,
            "pending_lines_count": len(self._pending_lines),
            "recent_pending_lines": list(self._pending_lines)[-15:],
            "last_push_time": self._last_push_time,
            "last_push_content": self._last_push_content[-200:] if self._last_push_content else "",
            "last_error": self._last_error,
            "candidate_processes": processes,
        }

    def _build_reader_state_dict(self) -> dict[str, Any] | None:
        if not self._reader:
            return None
        rs = self._reader.get_state()
        return {
            "running": rs.running,
            "process_pid": rs.process_pid,
            "engine": rs.engine,
            "hook_code": rs.hook_code,
            "lines_read": rs.lines_read,
            "last_line_at": rs.last_line_at,
            "error": rs.error,
        }

    # ── Config loading ───────────────────────────────────────────────────────

    async def _load_config(self) -> None:
        """Read configuration from plugin.toml sections."""
        cfg = await self.config.dump()

        mr = cfg.get("memory_reader", {})
        self._poll_interval = float(mr.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL))
        self._dedupe_window = int(mr.get("dedupe_window_size", DEFAULT_DEDUPE_WINDOW))
        self._idle_timeout = float(mr.get("idle_timeout_seconds", DEFAULT_IDLE_TIMEOUT))
        self._textractor_path = str(mr.get("textractor_path", ""))

        comp = cfg.get("companion", {})
        self._config = CompanionConfig(
            memory_mix_enabled=bool(comp.get("memory_mix_enabled", False)),
            max_context_lines=int(comp.get("max_context_lines", 20)),
            reply_cooldown_seconds=float(comp.get("reply_cooldown_seconds", 8.0)),
            min_lines_before_reply=int(comp.get("min_lines_before_reply", 4)),
            greet_on_scene_change=bool(comp.get("greet_on_scene_change", True)),
            scene_change_cooldown_seconds=float(comp.get("scene_change_cooldown_seconds", 15.0)),
            push_priority=int(comp.get("push_priority", 6)),
            include_line_quote=bool(comp.get("include_line_quote", True)),
            max_reply_chars=int(comp.get("max_reply_chars", 300)),
        )

    # ── Entry Points (with hosted UI actions) ────────────────────────────────

    @ui.action(
        label=tr("actions.toggle_memory_mix.label", default="切换记忆混合"),
        tone="primary",
        refresh_context=True,
    )
    @plugin_entry(
        id="toggle_memory_mix",
        name="切换记忆混合模式",
        description="切换是否将陪玩记忆混入猫娘的记忆库。开启后游戏对话会混入日常记忆，关闭后保持人设但记忆隔离。",
    )
    async def toggle_memory_mix(self, enabled: Annotated[bool, "是否启用记忆混合"] | None = None, **_) -> Any:
        """Toggle memory mixing on/off."""
        if enabled is not None:
            new_value = bool(enabled)
        else:
            new_value = not self._config.memory_mix_enabled

        await self.ctx.update_own_config({
            "companion": {"memory_mix_enabled": new_value}
        })
        self._config.memory_mix_enabled = new_value
        if self._builder:
            self._builder = PromptBuilder(self._config)

        status_text = (
            "记忆混合：开启 — 陪玩对话会混入猫娘的记忆库"
            if new_value
            else "记忆混合：关闭 — 保留人设，陪玩对话与日常记忆隔离"
        )
        self.logger.info(status_text)
        return Ok({
            "memory_mix_enabled": new_value,
            "message": status_text,
        })

    @ui.action(
        label=tr("actions.scan_processes.label", default="扫描游戏进程"),
        tone="secondary",
        refresh_context=True,
    )
    @plugin_entry(
        id="scan_processes",
        name="扫描游戏进程",
        description="扫描系统中正在运行的 galgame/视觉小说 引擎进程，返回候选列表。",
    )
    async def scan_processes(self, **_):
        """Scan for game processes."""
        procs = _list_game_processes()
        return Ok({
            "processes": procs,
            "count": len(procs),
            "message": f"找到 {len(procs)} 个候选进程" if procs else "未找到候选游戏进程",
        })

    @ui.action(
        label=tr("actions.start_reader.label", default="启动读取"),
        tone="success",
        refresh_context=True,
    )
    @plugin_entry(
        id="start_reader",
        name="启动内存读取",
        description="启动 Textractor 内存读取，开始捕获指定游戏进程的文本。",
        input_schema={
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "目标游戏进程 PID",
                },
                "hook_code": {
                    "type": "string",
                    "description": "Textractor hook code（如 /HQ14+3C@GameAssembly.dll#0x33A440），留空则自动检测",
                },
                "engine": {
                    "type": "string",
                    "description": "游戏引擎类型：unity / kirikiri / renpy / auto",
                },
            },
            "required": ["pid"],
        },
    )
    async def start_reader(
        self,
        pid: int,
        hook_code: str = "",
        engine: str = "",
        **_,
    ):
        """Start the memory reader for a target game process."""
        if self._reader and self._reader.running:
            await self._reader.stop()

        self._target_pid = int(pid)
        self._target_hook_code = str(hook_code or "").strip()
        self._target_engine = str(engine or "").strip()

        self._reader = MemoryReaderManager(
            textractor_path=self._textractor_path,
            dedupe_window=self._dedupe_window,
            logger=self.logger,
        )

        ok = await self._reader.start(
            target_pid=self._target_pid,
            hook_code=self._target_hook_code,
            engine=self._target_engine,
        )

        if ok:
            self._pending_lines.clear()
            self._idle_notified = False
            self._last_error = ""
            return Ok({
                "success": True,
                "message": f"已启动内存读取（PID={pid}, engine={engine or 'auto'}）",
                "pid": pid,
            })
        else:
            self._last_error = self._reader.error
            return Err(SdkError(f"启动失败: {self._reader.error}"))

    @ui.action(
        label=tr("actions.stop_reader.label", default="停止读取"),
        tone="danger",
        refresh_context=True,
    )
    @plugin_entry(
        id="stop_reader",
        name="停止内存读取",
        description="停止 Textractor 内存读取，不再捕获游戏文本。",
    )
    async def stop_reader(self, **_):
        """Stop the memory reader."""
        if not self._reader or not self._reader.running:
            return Ok({"success": True, "message": "读取器未在运行", "stopped": False})

        await self._reader.stop()
        self._target_pid = 0
        self.logger.info("内存读取已停止")
        return Ok({"success": True, "message": "内存读取已停止", "stopped": True})

    @plugin_entry(
        id="get_status",
        name="获取运行状态",
        description="获取当前插件运行状态、内存读取器状态、最近捕获的台词及配置信息。",
    )
    async def get_status(self, **_):
        """Return current plugin status."""
        reader_state = self._build_reader_state_dict()
        return Ok({
            "plugin_running": self._running,
            "memory_mix_enabled": self._config.memory_mix_enabled,
            "reader": reader_state,
            "pending_lines_count": len(self._pending_lines),
            "recent_pending_lines": list(self._pending_lines)[-10:],
            "config": {
                "poll_interval": self._poll_interval,
                "reply_cooldown": self._config.reply_cooldown_seconds,
                "min_lines_before_reply": self._config.min_lines_before_reply,
                "max_context_lines": self._config.max_context_lines,
            },
            "last_error": self._last_error,
        })

    @plugin_entry(
        id="get_recent_lines",
        name="获取最近台词",
        description="获取内存读取器最近捕获的游戏台词列表。",
        llm_result_fields=["lines", "count"],
    )
    async def get_recent_lines(self, **_):
        """Return recently captured game lines."""
        lines = list(self._pending_lines)[-20:]
        return Ok({"lines": lines, "count": len(lines)})

    # ── Main Poll Loop ───────────────────────────────────────────────────────

    @timer_interval(id="poll_loop", seconds=0.5, auto_start=True, name="主轮询循环")
    async def _poll_loop(self, **_):
        """Main polling loop: collect game text and trigger catgirl replies."""
        if not self._running:
            return Ok({"skipped": "not_running"})

        if not self._reader or not self._reader.running:
            return Ok({"skipped": "reader_not_running"})

        now = _time.monotonic()

        # Collect new lines
        new_lines: list[str] = []
        while True:
            line = await self._reader.poll(timeout=0.05)
            if line is None:
                break
            new_lines.append(line.text)

        if new_lines:
            for text in new_lines:
                self._pending_lines.append(text)
            self._idle_notified = False

        pending = list(self._pending_lines)
        if len(pending) < self._config.min_lines_before_reply:
            return Ok({"skipped": "insufficient_lines", "pending_count": len(pending)})

        # Cooldown check
        if now < self._reply_cooldown_until:
            return Ok({"skipped": "cooldown", "remaining": self._reply_cooldown_until - now})

        # Scene change detection
        scene_changed = False
        if (
            self._config.greet_on_scene_change
            and now >= self._scene_change_cooldown_until
            and len(pending) >= 3
        ):
            if _detect_scene_change(pending, self._previous_scene_signature):
                scene_changed = True
                self._previous_scene_signature = " ".join(pending[-10:])
                self._last_scene_change_at = now
                self._scene_change_cooldown_until = now + self._config.scene_change_cooldown_seconds

        # Push reply to chat
        try:
            await self._push_reply(pending, scene_change=scene_changed)
        except Exception as exc:
            self._last_error = str(exc)
            self.logger.warning("推送回复失败: %s", exc)

        self._pending_lines.clear()
        self._last_reply_at = now
        self._reply_cooldown_until = now + self._config.reply_cooldown_seconds

        return Ok({
            "pushed": True,
            "lines_consumed": len(pending),
            "scene_changed": scene_changed,
        })

    async def _push_reply(self, lines: list[str], *, scene_change: bool = False) -> None:
        """Build and push a catgirl reply prompt to the chat."""
        if not self._builder:
            return

        scene_hint = "场景似乎发生了变化" if scene_change else ""

        if scene_change and self._config.greet_on_scene_change:
            prompt = self._builder.build_scene_greet_prompt(lines)
        else:
            prompt = self._builder.build_dialogue_reply_prompt(lines, scene_hint=scene_hint)

        content = prompt.content

        if self._config.memory_mix_enabled:
            try:
                memories = await self._query_recent_memories()
                if memories:
                    memory_context = self._builder.build_memory_mix_context(memories)
                    if memory_context:
                        content = f"{memory_context}\n\n{content}"
            except Exception as exc:
                self.logger.debug("查询记忆失败（非致命）: %s", exc)

        if self._config.include_line_quote:
            content = content + PromptBuilder.format_line_quote(lines)

        self.push_message(
            source=PLUGIN_ID,
            message_type="proactive_notification",
            description=f"Galgame Companion | {prompt.kind}",
            priority=self._config.push_priority,
            content=content,
            metadata=prompt.metadata,
        )

        self._last_push_content = content
        self._last_push_time = _time.monotonic()

        self.logger.info(
            "已推送猫娘回复请求 (kind=%s, lines=%d, memory_mix=%s, chars=%d)",
            prompt.kind,
            len(lines),
            "ON" if prompt.memory_mix_enabled else "OFF",
            len(content),
        )

    async def _query_recent_memories(self, limit: int = 5) -> list[dict[str, Any]]:
        """Query recent memories from N.E.K.O's memory system."""
        try:
            result = await self.memory.query("default", "最近的对话", limit=limit)
            from plugin.sdk.plugin import unwrap_or
            return unwrap_or(result, [])
        except Exception:
            return []

    # ── Idle detection ───────────────────────────────────────────────────────

    @timer_interval(id="idle_check", seconds=30, auto_start=True, name="空闲检测")
    async def _idle_check(self, **_):
        """Periodically check if the game has gone idle and notify if needed."""
        if not self._running or self._idle_notified:
            return Ok({"skipped": "not_applicable"})

        if not self._reader or not self._reader.running:
            return Ok({"skipped": "reader_not_running"})

        now = _time.monotonic()
        last_line_at = self._reader.last_line_at
        idle_seconds = now - last_line_at if last_line_at > 0 else 0

        if idle_seconds > self._idle_timeout and self._builder:
            idle_minutes = idle_seconds / 60.0
            prompt = self._builder.build_idle_notice_prompt(idle_minutes)

            self.push_message(
                source=PLUGIN_ID,
                message_type="proactive_notification",
                description="Galgame Companion | idle_notice",
                priority=3,
                content=prompt.content,
                metadata=prompt.metadata,
            )
            self._idle_notified = True
            self.logger.info("已推送空闲提醒 (idle=%.1fmin)", idle_minutes)

        return Ok({"idle_seconds": idle_seconds, "notified": self._idle_notified})
