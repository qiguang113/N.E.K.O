"""neko-plugin create - one-sentence plugin generation and startup diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from ..core import build_plugin
from ..core.plugin_source import load_plugin_source
from ..paths import CliDefaults
from ..templates.generator import PluginSpec, generate_plugin

_PLUGIN_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOG_MARKERS = (
    "traceback",
    "exception",
    "error",
    "failed",
    "cannot import",
    "no module named",
    "startup",
    "pluginexecutionerror",
)


def register(subparsers: argparse._SubParsersAction, *, defaults: CliDefaults) -> None:
    parser = subparsers.add_parser(
        "create",
        help="Create and package a full plugin from a one-sentence brief",
    )
    parser.add_argument("brief", help="One sentence describing the plugin to generate")
    parser.add_argument("--plugin-id", help="Plugin ID; derived from the brief when omitted")
    parser.add_argument("--name", help="Display name; derived from the brief when omitted")
    parser.add_argument("--description", help="Plugin description; defaults to the brief")
    parser.add_argument("--plugins-root", help="Plugin root directory (default: N.E.K.O/plugin/plugins)")
    parser.add_argument("-t", "--target-dir", default=str(defaults.target_dir), help="Output directory for .neko-plugin")
    parser.add_argument("--model", default="default", help="Model name recorded in the generated plugin config")
    parser.add_argument("--provider", default="neko", help="Model provider recorded in the generated plugin config")
    parser.add_argument("--base-url", default="", help="Optional custom model API base URL")
    parser.add_argument("--api-key-env", default="NEKO_PLUGIN_MODEL_API_KEY", help="Environment variable for the model API key")
    parser.add_argument("--no-build", action="store_true", help="Only generate source files; skip .neko-plugin packaging")
    parser.add_argument("--no-readme", action="store_true", help="Do not generate README.md")
    parser.add_argument("--no-tests", action="store_true", help="Do not generate tests/test_smoke.py")
    parser.add_argument("--no-gitignore", action="store_true", help="Do not generate .gitignore")
    parser.add_argument("--no-vscode", action="store_true", help="Do not generate VSCode files")
    parser.set_defaults(handler=handle_create, _defaults=defaults)

    doctor_parser = subparsers.add_parser(
        "doctor-start",
        help="Read plugin startup logs and ask whether to prepare a repair prompt",
    )
    doctor_parser.add_argument("plugin", help="Plugin ID, plugin directory, or plugin.toml path")
    doctor_parser.add_argument("--logs-dir", help="Explicit log directory to scan")
    doctor_parser.add_argument("--lines", type=int, default=200, help="Log lines to inspect per file")
    doctor_parser.add_argument("-t", "--target-dir", default=str(defaults.target_dir), help="Directory for repair prompt output")
    doctor_parser.add_argument("--write-repair-prompt", action="store_true", help="Write the repair prompt without asking")
    doctor_parser.add_argument("--model", default="default", help="Repair model name to include in the prompt")
    doctor_parser.set_defaults(handler=handle_doctor_start, _defaults=defaults)


def handle_create(args: argparse.Namespace) -> int:
    defaults: CliDefaults = args._defaults
    brief = str(args.brief or "").strip()
    if not brief:
        print("[FAIL] brief must not be empty", file=sys.stderr)
        return 1

    plugin_id = args.plugin_id or derive_plugin_id(brief)
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        print(f"[FAIL] invalid plugin ID: '{plugin_id}'", file=sys.stderr)
        return 1

    plugins_root = _resolve_plugins_root(args, defaults=defaults)
    target_dir = plugins_root / plugin_id
    if target_dir.exists():
        print(f"[FAIL] directory already exists: {target_dir}", file=sys.stderr)
        return 1

    display_name = args.name or derive_display_name(brief, plugin_id)
    description = args.description or brief
    spec = PluginSpec(
        plugin_id=plugin_id,
        name=display_name,
        plugin_type="plugin",
        description=description,
        intent=brief,
        generation_model=args.model,
        generation_provider=args.provider,
        generation_base_url=args.base_url,
        generation_api_key_env=args.api_key_env,
        features=[
            "assistant_scaffold",
            "lifecycle",
            "entry_point",
            "store",
            "static_ui",
            "settings",
        ],
        quick_start=False,
        create_readme=not args.no_readme,
        create_tests=not args.no_tests,
        create_gitignore=not args.no_gitignore,
        create_vscode=not args.no_vscode,
    )

    try:
        created = generate_plugin(spec, target_dir)
        package_path: Path | None = None
        if not args.no_build:
            output_dir = Path(args.target_dir).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            package_path = output_dir / f"{plugin_id}.neko-plugin"
            build_plugin(target_dir, package_path)
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] created {target_dir}")
    for path in created:
        print(f"  - {path.relative_to(target_dir)}")
    print(f"  entry: {spec.entry_point}")
    print(f"  model: {args.provider}/{args.model}")
    if package_path is not None:
        print(f"[OK] built {package_path}")
    return 0


def handle_doctor_start(args: argparse.Namespace) -> int:
    defaults: CliDefaults = args._defaults
    try:
        plugin_id = resolve_plugin_id(args.plugin, defaults=defaults)
        log_text = read_startup_logs(plugin_id, logs_dir=args.logs_dir, lines=max(1, int(args.lines)))
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if not log_text.strip():
        print(f"[WARN] no log lines found for {plugin_id}")
        return 1

    diagnosis = diagnose_log_text(log_text)
    if not diagnosis["needs_repair"]:
        print(f"[OK] {plugin_id}: no startup error markers found")
        return 0

    print(f"[WARN] {plugin_id}: startup/runtime error markers found")
    print(f"  markers: {', '.join(diagnosis['markers'])}")
    print("  latest excerpt:")
    for line in diagnosis["excerpt"].splitlines()[-8:]:
        print(f"    {line}")

    should_write = bool(args.write_repair_prompt)
    if not should_write and sys.stdin.isatty():
        answer = input("Plugin may be unable to start. Create a repair prompt from logs? [y/N] ").strip().lower()
        should_write = answer in {"y", "yes"}

    if should_write:
        output_dir = Path(args.target_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = output_dir / f"{plugin_id}.repair-prompt.md"
        prompt_path.write_text(
            render_repair_prompt(plugin_id, log_text=log_text, model=args.model),
            encoding="utf-8",
            newline="\n",
        )
        print(f"[OK] repair prompt written: {prompt_path}")
    else:
        print("[INFO] repair prompt not written")
    return 2


def derive_plugin_id(brief: str) -> str:
    digest = hashlib.sha1(brief.encode("utf-8")).hexdigest()[:8]
    words = re.findall(r"[A-Za-z0-9]+", brief.lower())
    parts: list[str] = []
    for word in words:
        if word in {"a", "an", "the", "and", "or", "to", "for", "with", "plugin"}:
            continue
        parts.append(word[:20])
        if len(parts) >= 4:
            break
    slug = "_".join(parts).strip("_")
    if not slug:
        slug = f"generated_{digest}"
    if slug[0].isdigit():
        slug = f"plugin_{slug}"
    slug = re.sub(r"[^A-Za-z0-9_]", "_", slug)[:48].strip("_")
    return slug or f"generated_{digest}"


def derive_display_name(brief: str, plugin_id: str) -> str:
    first_line = " ".join(str(brief).strip().split())
    if 0 < len(first_line) <= 42:
        return first_line
    if first_line:
        return first_line[:39].rstrip() + "..."
    return plugin_id.replace("_", " ").title()


def resolve_plugin_id(raw: str, *, defaults: CliDefaults) -> str:
    candidate = Path(raw).expanduser()
    plugin_dir: Path | None = None
    if candidate.exists():
        plugin_dir = candidate.parent if candidate.is_file() else candidate
    else:
        by_name = defaults.plugins_root / raw
        if by_name.exists():
            plugin_dir = by_name

    if plugin_dir is not None:
        source = load_plugin_source(plugin_dir)
        return source.plugin_id

    if not re.fullmatch(r"^[A-Za-z0-9_-]+$", raw):
        raise ValueError(f"invalid plugin id: {raw!r}")
    return raw


def read_startup_logs(plugin_id: str, *, logs_dir: str | None = None, lines: int = 200) -> str:
    root: Path
    if logs_dir:
        root = Path(logs_dir).expanduser().resolve()
    else:
        from plugin.server.logs import get_plugin_log_dir

        root = get_plugin_log_dir(plugin_id)
    if not root.exists():
        return ""

    patterns = [
        f"N.E.K.O_Plugin_{plugin_id}_*.log*",
        f"N.E.K.O_Plugin_{plugin_id}_error.log*",
        f"*{plugin_id}*.log*",
        "*.log",
    ]
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    chunks = []
    for path in files[:4]:
        chunks.append(f"--- {path.name} ---")
        chunks.extend(_tail_text(path, lines=lines))
    return "\n".join(chunks)


def diagnose_log_text(log_text: str) -> dict[str, object]:
    lowered = log_text.lower()
    markers = [marker for marker in _LOG_MARKERS if marker in lowered]
    excerpt = "\n".join(log_text.splitlines()[-40:])
    return {
        "needs_repair": bool(markers),
        "markers": markers,
        "excerpt": excerpt,
    }


def render_repair_prompt(plugin_id: str, *, log_text: str, model: str) -> str:
    excerpt = "\n".join(log_text.splitlines()[-160:])
    return f"""# Repair N.E.K.O Plugin Startup Failure

Plugin ID: `{plugin_id}`
Repair model: `{model}`

The plugin appears unable to start or has runtime errors. Read the log excerpt,
identify the smallest safe fix, and keep unrelated files unchanged.

```text
{excerpt}
```
"""


def _tail_text(path: Path, *, lines: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError as exc:
        return [f"<failed to read {path.name}: {exc}>"]


def _resolve_plugins_root(args: argparse.Namespace, *, defaults: CliDefaults) -> Path:
    plugins_root = getattr(args, "plugins_root", None)
    if plugins_root:
        return Path(plugins_root).expanduser().resolve()
    return defaults.plugins_root
