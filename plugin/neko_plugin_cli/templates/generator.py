"""Generate plugin scaffolding files from collected options."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

_PYTHON_PLUGIN_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MARKET_REPO_PREFIX = "n.e.k.o_plugin_"
_DEFAULT_NEKO_REPOSITORY = "Project-N-E-K-O/N.E.K.O"


@dataclass
class PluginSpec:
    """All the information needed to generate a plugin scaffold."""

    plugin_id: str
    name: str = ""
    plugin_type: str = "plugin"  # plugin | extension | adapter
    description: str = ""
    version: str = "0.1.0"
    author_name: str = ""
    author_email: str = ""
    entry_point_override: str = ""
    intent: str = ""
    generation_model: str = "default"
    generation_provider: str = "neko"
    generation_base_url: str = ""
    generation_api_key_env: str = "NEKO_PLUGIN_MODEL_API_KEY"

    # Extension-specific
    host_plugin_id: str = ""
    host_prefix: str = ""

    # Features
    features: list[str] = field(default_factory=list)
    # Possible features:
    #   lifecycle, entry_point, timer, message, store, cross_plugin,
    #   static_ui, async_support, bus_events, settings, assistant_scaffold

    create_pyproject: bool = True
    create_readme: bool = True
    create_tests: bool = True
    create_gitignore: bool = True
    create_vscode: bool = True
    create_github_actions: bool = False
    neko_repository: str = _DEFAULT_NEKO_REPOSITORY
    neko_ref: str = "main"
    quick_start: bool = False

    @property
    def class_name(self) -> str:
        # Split on both _ and - for CamelCase conversion
        parts = re.split(r"[_-]", self.plugin_id)
        return "".join(p.capitalize() for p in parts if p) + "Plugin"

    @property
    def entry_point(self) -> str:
        if self.entry_point_override:
            return self.entry_point_override
        return f"plugins.{self.plugin_id}:{self.class_name}"

    @property
    def module_path(self) -> str:
        return f"plugins.{self.plugin_id}"


def generate_plugin(spec: PluginSpec, target_dir: Path) -> list[Path]:
    """Generate all scaffold files and return the list of created paths."""
    if not _PYTHON_PLUGIN_ID_RE.fullmatch(spec.plugin_id):
        raise ValueError(
            "plugin_id must be a valid Python package name: use letters, numbers, and underscores only"
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    # plugin.toml
    toml_path = target_dir / "plugin.toml"
    toml_path.write_text(_render_plugin_toml(spec), encoding="utf-8", newline="\n")
    created.append(toml_path)

    # __init__.py
    init_path = target_dir / "__init__.py"
    init_path.write_text(_render_init_py(spec), encoding="utf-8", newline="\n")
    created.append(init_path)

    # pyproject.toml (optional)
    if spec.create_pyproject:
        pyproject_path = target_dir / "pyproject.toml"
        pyproject_path.write_text(_render_pyproject_toml(spec), encoding="utf-8", newline="\n")
        created.append(pyproject_path)

    if spec.create_readme:
        readme_path = target_dir / "README.md"
        readme_path.write_text(_render_readme_md(spec), encoding="utf-8", newline="\n")
        created.append(readme_path)

    if "assistant_scaffold" in spec.features:
        config_path = target_dir / "config.json"
        config_path.write_text(_render_assistant_config_json(spec), encoding="utf-8", newline="\n")
        created.append(config_path)

        static_dir = target_dir / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        panel_path = static_dir / "index.html"
        panel_path.write_text(_render_assistant_panel_html(spec), encoding="utf-8", newline="\n")
        created.append(panel_path)

        docs_dir = target_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        quickstart_path = docs_dir / "quickstart.md"
        quickstart_path.write_text(_render_assistant_quickstart_md(spec), encoding="utf-8", newline="\n")
        created.append(quickstart_path)

    if spec.create_tests:
        tests_dir = target_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        smoke_path = tests_dir / "test_smoke.py"
        smoke_path.write_text(_render_smoke_test(spec), encoding="utf-8", newline="\n")
        created.append(smoke_path)

    if spec.create_gitignore:
        gitignore_path = target_dir / ".gitignore"
        gitignore_path.write_text(_render_gitignore(), encoding="utf-8", newline="\n")
        created.append(gitignore_path)

    if spec.create_vscode:
        vscode_dir = target_dir / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)
        settings_path = vscode_dir / "settings.json"
        settings_path.write_text(_render_vscode_settings(), encoding="utf-8", newline="\n")
        created.append(settings_path)

        tasks_path = vscode_dir / "tasks.json"
        tasks_path.write_text(_render_vscode_tasks(spec), encoding="utf-8", newline="\n")
        created.append(tasks_path)

    if spec.create_github_actions:
        workflow_dir = target_dir / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        workflow_path = workflow_dir / "verify.yml"
        workflow_path.write_text(_render_verify_workflow(spec), encoding="utf-8", newline="\n")
        created.append(workflow_path)
        release_workflow_path = workflow_dir / "release.yml"
        release_workflow_path.write_text(_render_release_workflow(spec), encoding="utf-8", newline="\n")
        created.append(release_workflow_path)

    return created


def generate_repo_support_files(
    spec: PluginSpec,
    target_dir: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Generate repository support files for an existing plugin directory."""
    if not target_dir.is_dir():
        raise FileNotFoundError(f"plugin directory not found: {target_dir}")

    created: list[Path] = []

    if spec.create_readme:
        _write_support_file(
            target_dir / "README.md",
            _render_readme_md(spec),
            created=created,
            overwrite=overwrite,
        )

    if spec.create_tests:
        tests_dir = target_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        _write_support_file(
            tests_dir / "test_smoke.py",
            _render_smoke_test(spec),
            created=created,
            overwrite=overwrite,
        )

    if spec.create_gitignore:
        _write_support_file(
            target_dir / ".gitignore",
            _render_gitignore(),
            created=created,
            overwrite=overwrite,
        )

    if spec.create_vscode:
        vscode_dir = target_dir / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)
        _write_support_file(
            vscode_dir / "settings.json",
            _render_vscode_settings(),
            created=created,
            overwrite=overwrite,
        )
        _write_support_file(
            vscode_dir / "tasks.json",
            _render_vscode_tasks(spec),
            created=created,
            overwrite=overwrite,
        )

    if spec.create_github_actions:
        workflow_dir = target_dir / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        _write_support_file(
            workflow_dir / "verify.yml",
            _render_verify_workflow(spec),
            created=created,
            overwrite=overwrite,
        )
        _write_support_file(
            workflow_dir / "release.yml",
            _render_release_workflow(spec),
            created=created,
            overwrite=overwrite,
        )

    return created


# ---------------------------------------------------------------------------
# plugin.toml
# ---------------------------------------------------------------------------

def _render_plugin_toml(spec: PluginSpec) -> str:
    lines = [
        "[plugin]",
        f'id = "{spec.plugin_id}"',
        f'name = "{_escape(spec.name or spec.plugin_id)}"',
    ]

    if spec.description:
        lines.append(f'description = "{_escape(spec.description)}"')

    lines.append(f'version = "{spec.version}"')
    lines.append(f'type = "{spec.plugin_type}"')
    lines.append(f'entry = "{spec.entry_point}"')

    if spec.author_name or spec.author_email:
        lines.append("")
        lines.append("[plugin.author]")
        if spec.author_name:
            lines.append(f'name = "{_escape(spec.author_name)}"')
        if spec.author_email:
            lines.append(f'email = "{_escape(spec.author_email)}"')

    lines.extend([
        "",
        "[plugin.sdk]",
        'recommended = ">=0.1.0,<0.2.0"',
        'supported = ">=0.1.0,<0.3.0"',
    ])

    if "static_ui" in spec.features or "assistant_scaffold" in spec.features:
        lines.extend([
            "",
            "[plugin.ui]",
            "enabled = true",
            "",
            "[[plugin.ui.panel]]",
            'id = "main"',
            f'title = "{_escape(spec.name or spec.plugin_id)}"',
            'entry = "static/index.html"',
            'context = "dashboard"',
            'permissions = ["state:read", "config:read", "config:write", "action:call", "logs:read", "runs:read"]',
            "",
            "[[plugin.ui.guide]]",
            'id = "quickstart"',
            f'title = "{_escape(spec.name or spec.plugin_id)} Quickstart"',
            'entry = "docs/quickstart.md"',
            'context = "dashboard"',
            'permissions = ["state:read"]',
        ])

    if "store" in spec.features or "assistant_scaffold" in spec.features:
        lines.extend(["", "[plugin.store]", "enabled = true"])

    if spec.plugin_type == "extension" and spec.host_plugin_id:
        lines.extend([
            "",
            "[plugin.host]",
            f'plugin_id = "{spec.host_plugin_id}"',
        ])
        if spec.host_prefix:
            lines.append(f'prefix = "{_escape(spec.host_prefix)}"')

    auto_start = "true" if "assistant_scaffold" in spec.features or "timer" in spec.features or "message" in spec.features else "false"
    lines.extend([
        "",
        "[plugin_runtime]",
        "enabled = true",
        f"auto_start = {auto_start}",
    ])

    if "assistant_scaffold" in spec.features:
        lines.extend([
            "",
            f"[{spec.plugin_id}]",
            "enabled = true",
            f'task_prompt = "{_escape(spec.intent or spec.description or spec.name or spec.plugin_id)}"',
            f'generation_model = "{_escape(spec.generation_model)}"',
            f'generation_provider = "{_escape(spec.generation_provider)}"',
            f'generation_base_url = "{_escape(spec.generation_base_url)}"',
            f'generation_api_key_env = "{_escape(spec.generation_api_key_env)}"',
            "timeout_seconds = 30",
            "log_tail_lines = 120",
        ])

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# __init__.py
# ---------------------------------------------------------------------------

def _render_init_py(spec: PluginSpec) -> str:
    if spec.plugin_type == "extension":
        return _render_extension_init(spec)
    if spec.plugin_type == "adapter":
        return _render_adapter_init(spec)
    if "assistant_scaffold" in spec.features:
        return _render_assistant_init(spec)
    if spec.quick_start:
        return _render_quick_start_init(spec)
    return _render_plugin_init(spec)


def _render_quick_start_init(spec: PluginSpec) -> str:
    return f'''from typing import Any
from plugin.sdk.plugin import (
    NekoPluginBase, neko_plugin, plugin_entry, lifecycle,
    Ok,
)


@neko_plugin
class {spec.class_name}(NekoPluginBase):
    """{_escape(spec.name or spec.plugin_id)}"""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = ctx.logger

    @lifecycle(id="startup")
    def on_startup(self, **_):
        self.logger.info("{spec.class_name} started")
        return Ok({{"status": "ready"}})

    @lifecycle(id="shutdown")
    def on_shutdown(self, **_):
        self.logger.info("{spec.class_name} stopped")
        return Ok({{"status": "stopped"}})

    @plugin_entry(
        id="hello",
        name="Hello",
        description="Say hello",
        input_schema={{
            "type": "object",
            "properties": {{
                "name": {{"type": "string", "default": "World"}}
            }}
        }}
    )
    def hello(self, name: str = "World", **_):
        return Ok({{"message": f"Hello, {{name}}!"}})
'''


def _render_assistant_init(spec: PluginSpec) -> str:
    intent = _escape(spec.intent or spec.description or spec.name or spec.plugin_id)
    model = _escape(spec.generation_model)
    provider = _escape(spec.generation_provider)
    base_url = _escape(spec.generation_base_url)
    api_key_env = _escape(spec.generation_api_key_env)
    section = _escape(spec.plugin_id)
    return f'''from __future__ import annotations

import time
import traceback
from collections import deque
from datetime import datetime
from typing import Any

from plugin.sdk.plugin import (
    NekoPluginBase,
    PluginSettings,
    SettingsField,
    SdkError,
    lifecycle,
    neko_plugin,
    plugin_entry,
    ui,
    Ok,
    Err,
)


DEFAULT_CONFIG: dict[str, Any] = {{
    "enabled": True,
    "task_prompt": "{intent}",
    "generation_model": "{model}",
    "generation_provider": "{provider}",
    "generation_base_url": "{base_url}",
    "generation_api_key_env": "{api_key_env}",
    "timeout_seconds": 30,
    "log_tail_lines": 120,
}}


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _clean_text(value: Any, *, limit: int = 1000) -> str:
    text = str(value or "").replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()
    return text[:limit].strip()


@neko_plugin
class {spec.class_name}(NekoPluginBase):
    """{_escape(spec.name or spec.plugin_id)}."""

    class Settings(PluginSettings):
        model_config = {{"toml_section": "{section}"}}

        enabled: bool = SettingsField(True, hot=True, description="Enable this plugin")
        task_prompt: str = SettingsField(DEFAULT_CONFIG["task_prompt"], hot=True, description="One sentence plugin goal")
        generation_model: str = SettingsField(DEFAULT_CONFIG["generation_model"], hot=True, description="Model used by generated workflows")
        generation_provider: str = SettingsField(DEFAULT_CONFIG["generation_provider"], hot=True, description="Model provider")
        generation_base_url: str = SettingsField(DEFAULT_CONFIG["generation_base_url"], hot=True, description="Optional custom model API base URL")
        generation_api_key_env: str = SettingsField(DEFAULT_CONFIG["generation_api_key_env"], hot=True, description="Environment variable that stores the model API key")
        timeout_seconds: int = SettingsField(30, hot=True, ge=1, le=300, description="Default action timeout")
        log_tail_lines: int = SettingsField(120, hot=True, ge=20, le=1000, description="Runtime log lines to inspect")

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = ctx.logger
        self._cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
        self._started_at = time.monotonic()
        self._call_count = 0
        self._failure_count = 0
        self._last_error = ""
        self._events: deque[dict[str, Any]] = deque(maxlen=80)

    @lifecycle(id="startup")
    async def startup(self, **_):
        await self._reload_config()
        static_ok = self.register_static_ui("static")
        self._record("INFO", f"{spec.class_name} started", static_ui=static_ok)
        return Ok({{"status": "ready", "static_ui": static_ok, "config": dict(self._cfg)}})

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        self._record("INFO", f"{spec.class_name} stopped")
        return Ok({{"status": "stopped"}})

    @lifecycle(id="config_change")
    async def config_change(self, **_):
        await self._reload_config()
        self._record("INFO", "Configuration reloaded")
        return Ok({{"status": "reloaded", "config": dict(self._cfg)}})

    async def _reload_config(self) -> None:
        try:
            payload = await self.config.dump(timeout=5.0)
        except Exception as exc:
            self._record("WARNING", f"Failed to read config; using defaults: {{exc}}")
            payload = {{}}
        section = payload.get(self.plugin_id) if isinstance(payload, dict) else {{}}
        section = section if isinstance(section, dict) else {{}}
        merged = dict(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in section:
                merged[key] = section[key]
        self._cfg = merged

    def _metrics(self) -> dict[str, Any]:
        uptime_seconds = max(0.0, time.monotonic() - self._started_at)
        return {{
            "uptime_seconds": round(uptime_seconds, 3),
            "call_count": self._call_count,
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "events_buffered": len(self._events),
        }}

    def _record(self, level: str, message: str, **extra: Any) -> None:
        entry = {{"time": _utc_now(), "level": level.upper(), "message": str(message), "extra": dict(extra)}}
        self._events.appendleft(entry)
        log_method = getattr(self.logger, level.lower(), None)
        if callable(log_method):
            try:
                log_method(message)
            except Exception:
                pass

    def _read_runtime_logs(self, *, lines: int | None = None) -> list[dict[str, Any]]:
        tail_lines = int(lines or self._cfg.get("log_tail_lines") or 120)
        try:
            from plugin.server.logs import get_plugin_logs

            result = get_plugin_logs(self.plugin_id, lines=tail_lines)
            logs = result.get("logs", []) if isinstance(result, dict) else []
            return [dict(item) for item in logs if isinstance(item, dict)]
        except Exception as exc:
            return [{{
                "timestamp": _utc_now(),
                "level": "WARNING",
                "message": f"Runtime logs are not readable from this process: {{exc}}",
            }}]

    def _diagnose(self) -> dict[str, Any]:
        logs = self._read_runtime_logs()
        messages = [str(item.get("message", "")) for item in logs]
        messages.extend(str(item.get("message", "")) for item in self._events)
        joined = "\\n".join(messages[-80:])
        lowered = joined.lower()
        error_markers = ("traceback", "exception", "error", "failed", "cannot start", "startup")
        matched = [marker for marker in error_markers if marker in lowered]
        needs_repair = bool(self._last_error or matched)
        return {{
            "ok": not needs_repair,
            "needs_repair": needs_repair,
            "matched_markers": matched,
            "question": "The plugin appears to have startup/runtime errors. Repair from logs?" if needs_repair else "",
            "metrics": self._metrics(),
            "recent_events": list(self._events)[:20],
            "recent_logs": logs[-20:],
        }}

    def _repair_prompt(self) -> str:
        diagnosis = self._diagnose()
        log_lines = []
        for item in diagnosis.get("recent_logs", []):
            if not isinstance(item, dict):
                continue
            level = item.get("level", "")
            message = item.get("message", "")
            log_lines.append(f"[{{level}}] {{message}}")
        excerpt = "\\n".join(log_lines[-60:]) or "(no log lines available)"
        return (
            "You are repairing a N.E.K.O plugin generated from a one-sentence brief.\\n"
            f"Plugin id: {{self.plugin_id}}\\n"
            f"Goal: {{self._cfg.get('task_prompt', '')}}\\n"
            f"Configured model: {{self._cfg.get('generation_provider', '')}}/{{self._cfg.get('generation_model', '')}}\\n"
            "Use the logs below to identify the smallest safe code change.\\n\\n"
            "Logs:\\n```text\\n"
            f"{{excerpt}}\\n"
            "```\\n"
        )

    @ui.context(id="dashboard", title="{_escape(spec.name or spec.plugin_id)}")
    async def dashboard_context(self) -> dict[str, Any]:
        diagnosis = self._diagnose()
        return {{
            "plugin_id": self.plugin_id,
            "config": dict(self._cfg),
            "metrics": self._metrics(),
            "diagnosis": diagnosis,
            "recent_events": list(self._events)[:20],
        }}

    @ui.action(label="Refresh status", icon="activity", group="status", order=10, refresh_context=True)
    @plugin_entry(id="status", name="Status", description="Return plugin config, metrics, and diagnostics.")
    async def status(self, **_):
        await self._reload_config()
        return Ok({{
            "config": dict(self._cfg),
            "metrics": self._metrics(),
            "diagnosis": self._diagnose(),
        }})

    @ui.action(label="Run task", icon="play", tone="success", group="actions", order=20, refresh_context=True)
    @plugin_entry(
        id="run_task",
        name="Run task",
        description="Run the generated plugin's default task.",
        input_schema={{
            "type": "object",
            "properties": {{
                "instruction": {{"type": "string", "description": "Optional user instruction override"}}
            }},
        }},
    )
    async def run_task(self, instruction: str = "", **_):
        self._call_count += 1
        if not bool(self._cfg.get("enabled", True)):
            self._failure_count += 1
            self._last_error = "Plugin is disabled by configuration"
            return Err(SdkError(self._last_error))

        task = _clean_text(instruction, limit=2000) or str(self._cfg.get("task_prompt", ""))
        try:
            result = {{
                "accepted": True,
                "task": task,
                "model": {{
                    "provider": self._cfg.get("generation_provider", ""),
                    "name": self._cfg.get("generation_model", ""),
                    "base_url": self._cfg.get("generation_base_url", ""),
                    "api_key_env": self._cfg.get("generation_api_key_env", ""),
                }},
                "message": "Replace run_task with your real plugin logic when you are ready.",
            }}
            self._record("INFO", "run_task completed", task=task[:120])
            return Ok(result)
        except Exception as exc:
            self._failure_count += 1
            self._last_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self._record("ERROR", self._last_error)
            return Err(SdkError(self._last_error))

    @ui.action(label="Save config", icon="save", group="config", order=30, refresh_context=True)
    @plugin_entry(
        id="update_config",
        name="Update config",
        description="Update generated plugin configuration.",
        input_schema={{
            "type": "object",
            "properties": {{
                "enabled": {{"type": "boolean"}},
                "task_prompt": {{"type": "string"}},
                "generation_model": {{"type": "string"}},
                "generation_provider": {{"type": "string"}},
                "generation_base_url": {{"type": "string"}},
                "generation_api_key_env": {{"type": "string"}},
                "timeout_seconds": {{"type": "integer"}},
                "log_tail_lines": {{"type": "integer"}},
            }},
            "additionalProperties": False,
        }},
    )
    async def update_config(self, **kwargs):
        updates = {{key: value for key, value in kwargs.items() if key in DEFAULT_CONFIG and not key.startswith("_")}}
        if not updates:
            return Err(SdkError("No supported config fields were provided"))
        try:
            await self.config.profile_ensure_active("default", initial={{self.plugin_id: dict(self._cfg)}}, timeout=10.0)
            await self.config.update({{self.plugin_id: updates}}, timeout=10.0)
            await self._reload_config()
        except Exception as exc:
            self._cfg.update(updates)
            self._record("WARNING", f"Config profile update failed; applied in memory only: {{exc}}")
        self._record("INFO", "Configuration updated", fields=sorted(updates))
        return Ok({{"config": dict(self._cfg)}})

    @ui.action(label="Diagnose logs", icon="wrench", group="diagnostics", order=40, refresh_context=True)
    @plugin_entry(id="diagnostics", name="Diagnostics", description="Read recent runtime logs and report whether repair is needed.")
    async def diagnostics(self, **_):
        return Ok(self._diagnose())

    @ui.action(label="Repair prompt", icon="file-text", group="diagnostics", order=50, refresh_context=False)
    @plugin_entry(id="repair_prompt", name="Repair prompt", description="Create a prompt that can be sent to a repair model.")
    async def repair_prompt(self, **_):
        diagnosis = self._diagnose()
        return Ok({{
            "needs_repair": bool(diagnosis.get("needs_repair")),
            "question": diagnosis.get("question") or "",
            "prompt": self._repair_prompt(),
        }})
'''


def _render_plugin_init(spec: PluginSpec) -> str:
    imports = ["NekoPluginBase", "neko_plugin", "Ok"]
    decorators_needed: list[str] = []

    if "lifecycle" in spec.features or "entry_point" in spec.features:
        # Always include these for non-quick-start plugins
        pass
    if "lifecycle" in spec.features:
        imports.append("lifecycle")
    if "entry_point" in spec.features:
        imports.append("plugin_entry")
    if "timer" in spec.features:
        imports.append("timer_interval")
    if "message" in spec.features:
        imports.append("message")

    extra_imports: list[str] = []
    if "store" in spec.features:
        extra_imports.append("from plugin.sdk.plugin import PluginStore")
    if "settings" in spec.features:
        extra_imports.append("from plugin.sdk.plugin import PluginSettings")

    is_async = "async_support" in spec.features

    lines = [
        "from typing import Any",
        f"from plugin.sdk.plugin import (",
        f"    {', '.join(imports)},",
        ")",
    ]
    for imp in extra_imports:
        lines.append(imp)

    lines.extend([
        "",
        "",
        "@neko_plugin",
        f"class {spec.class_name}(NekoPluginBase):",
        f'    """{_escape(spec.name or spec.plugin_id)}"""',
        "",
        "    def __init__(self, ctx: Any):",
        "        super().__init__(ctx)",
        "        self.logger = ctx.logger",
    ])

    if "store" in spec.features:
        lines.append("        self.store = PluginStore(ctx)")

    # lifecycle
    if "lifecycle" in spec.features:
        if is_async:
            lines.extend([
                "",
                '    @lifecycle(id="startup")',
                "    async def on_startup(self, **_):",
                f'        self.logger.info("{spec.class_name} started")',
                '        return Ok({"status": "ready"})',
                "",
                '    @lifecycle(id="shutdown")',
                "    async def on_shutdown(self, **_):",
                f'        self.logger.info("{spec.class_name} stopped")',
                '        return Ok({"status": "stopped"})',
            ])
        else:
            lines.extend([
                "",
                '    @lifecycle(id="startup")',
                "    def on_startup(self, **_):",
                f'        self.logger.info("{spec.class_name} started")',
                '        return Ok({"status": "ready"})',
                "",
                '    @lifecycle(id="shutdown")',
                "    def on_shutdown(self, **_):",
                f'        self.logger.info("{spec.class_name} stopped")',
                '        return Ok({"status": "stopped"})',
            ])

    # entry point
    if "entry_point" in spec.features:
        async_kw = "async " if is_async else ""
        lines.extend([
            "",
            "    @plugin_entry(",
            f'        id="example",',
            f'        name="Example Entry",',
            f'        description="An example entry point",',
            "        input_schema={",
            '            "type": "object",',
            '            "properties": {',
            '                "input": {"type": "string", "default": ""}',
            "            }",
            "        }",
            "    )",
            f"    {async_kw}def example(self, input: str = \"\", **_):",
            '        return Ok({"result": input})',
        ])

    # timer
    if "timer" in spec.features:
        lines.extend([
            "",
            '    @timer_interval(id="heartbeat", seconds=60, auto_start=True)',
            "    def heartbeat(self, **_):",
            '        self.logger.debug("heartbeat")',
            '        return Ok({"alive": True})',
        ])

    # message
    if "message" in spec.features:
        async_kw = "async " if is_async else ""
        lines.extend([
            "",
            '    @message(id="handle_message", auto_start=True)',
            f"    {async_kw}def handle_message(self, text: str = \"\", **_):",
            '        self.logger.info(f"Received: {text}")',
            '        return Ok({"handled": True})',
        ])

    lines.append("")
    return "\n".join(lines)


def _render_extension_init(spec: PluginSpec) -> str:
    return f'''from plugin.sdk.extension import (
    NekoExtensionBase, extension, extension_entry,
    Ok,
)


@extension
class {spec.class_name}(NekoExtensionBase):
    """{_escape(spec.name or spec.plugin_id)}"""

    @extension_entry(id="example", description="An example extension entry")
    def example(self, param: str = "", **_):
        return Ok({{"extended": True, "param": param}})
'''


def _render_adapter_init(spec: PluginSpec) -> str:
    return f'''from typing import Any
from plugin.sdk.plugin import neko_plugin, plugin_entry, lifecycle, Ok
from plugin.sdk.adapter import AdapterGatewayCore, NekoAdapterPlugin


@neko_plugin
class {spec.class_name}(NekoAdapterPlugin):
    """{_escape(spec.name or spec.plugin_id)}"""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = ctx.logger

    @lifecycle(id="startup")
    async def on_startup(self, **_):
        self.logger.info("{spec.class_name} started")
        return Ok({{"status": "ready"}})

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_):
        self.logger.info("{spec.class_name} stopped")
        return Ok({{"status": "stopped"}})

    @plugin_entry(id="handle_request")
    async def handle_request(self, raw_data: dict = None, **_):
        return Ok({{"received": raw_data}})
'''


def _render_assistant_config_json(spec: PluginSpec) -> str:
    return f'''{{
  "plugin_id": "{_escape(spec.plugin_id)}",
  "name": "{_escape(spec.name or spec.plugin_id)}",
  "intent": "{_escape(spec.intent or spec.description or spec.plugin_id)}",
  "generation": {{
    "provider": "{_escape(spec.generation_provider)}",
    "model": "{_escape(spec.generation_model)}",
    "base_url": "{_escape(spec.generation_base_url)}",
    "api_key_env": "{_escape(spec.generation_api_key_env)}"
  }},
  "surfaces": ["panel", "quickstart"],
  "entries": ["status", "run_task", "update_config", "diagnostics", "repair_prompt"]
}}
'''


def _render_assistant_panel_html(spec: PluginSpec) -> str:
    title = _escape_html(spec.name or spec.plugin_id)
    intent = _escape_html(spec.intent or spec.description or spec.plugin_id)
    plugin_id = _escape(spec.plugin_id)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d9dee8;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --danger: #b42318;
      --warning: #b54708;
      --ok: #027a48;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 32px;
    }}
    header {{
      display: grid;
      gap: 8px;
      padding: 0 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    p {{ margin: 0; color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 16px;
      margin-top: 18px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 78px;
    }}
    .metric strong {{
      display: block;
      font-size: 22px;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }}
    .metric span {{ color: var(--muted); font-size: 12px; }}
    label {{
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      color: var(--text);
      background: white;
      font: inherit;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    button {{
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 9px 12px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: white;
      color: var(--accent-strong);
      border-color: var(--accent);
    }}
    button:disabled {{ opacity: 0.55; cursor: wait; }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      width: fit-content;
      border-radius: 999px;
      padding: 5px 10px;
      background: #ecfdf3;
      color: var(--ok);
      font-weight: 700;
    }}
    .status.warn {{ background: #fffaeb; color: var(--warning); }}
    .status.bad {{ background: #fef3f2; color: var(--danger); }}
    pre {{
      max-height: 260px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      padding: 12px;
      border-radius: 8px;
      background: #101828;
      color: #eaecf0;
      font-size: 12px;
    }}
    .stack {{ display: grid; gap: 16px; }}
    .full {{ grid-column: 1 / -1; }}
    @media (max-width: 820px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      main {{ width: min(100% - 20px, 1120px); }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{title}</h1>
      <p>{intent}</p>
      <div id="health" class="status">Loading</div>
    </header>

    <div class="grid">
      <section class="stack">
        <div>
          <h2>Configuration</h2>
          <label>Task prompt
            <textarea id="taskPrompt"></textarea>
          </label>
          <label>Model
            <input id="model" type="text" autocomplete="off">
          </label>
          <label>Provider
            <input id="provider" type="text" autocomplete="off">
          </label>
          <label>Base URL
            <input id="baseUrl" type="text" autocomplete="off">
          </label>
          <label>API key env
            <input id="apiKeyEnv" type="text" autocomplete="off">
          </label>
          <div class="actions">
            <button id="saveConfig">Save config</button>
            <button id="runTask" class="secondary">Run task</button>
            <button id="refresh" class="secondary">Refresh</button>
          </div>
        </div>
      </section>

      <section>
        <h2>Performance</h2>
        <div class="metrics">
          <div class="metric"><strong id="uptime">0</strong><span>Uptime seconds</span></div>
          <div class="metric"><strong id="calls">0</strong><span>Calls</span></div>
          <div class="metric"><strong id="failures">0</strong><span>Failures</span></div>
          <div class="metric"><strong id="events">0</strong><span>Events</span></div>
        </div>
      </section>

      <section class="full">
        <h2>Logs And Diagnostics</h2>
        <div class="actions">
          <button id="diagnose" class="secondary">Diagnose logs</button>
          <button id="repairPrompt" class="secondary">Create repair prompt</button>
        </div>
        <pre id="output">Waiting for plugin context...</pre>
      </section>
    </div>
  </main>

  <script>
    const PLUGIN_ID = "{plugin_id}";
    const state = {{ context: null, busy: false }};
    const $ = (id) => document.getElementById(id);

    function setBusy(value) {{
      state.busy = value;
      document.querySelectorAll("button, input, textarea").forEach((el) => {{
        el.disabled = value;
      }});
    }}

    function show(value) {{
      $("output").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }}

    function unwrapActionPayload(payload) {{
      const result = payload && payload.result ? payload.result : payload;
      if (result && typeof result === "object") {{
        if ("value" in result) return result.value;
        if ("data" in result) return result.data;
        if ("result" in result) return result.result;
      }}
      return result;
    }}

    async function getContext() {{
      const response = await fetch(`/plugin/${{PLUGIN_ID}}/hosted-ui/context?kind=panel&id=main`, {{
        headers: {{ "Accept": "application/json" }},
      }});
      if (!response.ok) throw new Error(`Context HTTP ${{response.status}}`);
      return response.json();
    }}

    async function callAction(actionId, args = {{}}) {{
      const response = await fetch(`/plugin/${{PLUGIN_ID}}/hosted-ui/action/${{actionId}}`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "Accept": "application/json" }},
        body: JSON.stringify({{ args, kind: "panel", surface_id: "main" }}),
      }});
      const payload = await response.json().catch(() => ({{}}));
      if (!response.ok) throw new Error(payload.message || payload.detail || `Action HTTP ${{response.status}}`);
      return unwrapActionPayload(payload);
    }}

    function render(context) {{
      state.context = context;
      const data = context.state || {{}};
      const cfg = data.config || {{}};
      const metrics = data.metrics || {{}};
      const diagnosis = data.diagnosis || {{}};
      $("taskPrompt").value = cfg.task_prompt || "";
      $("model").value = cfg.generation_model || "";
      $("provider").value = cfg.generation_provider || "";
      $("baseUrl").value = cfg.generation_base_url || "";
      $("apiKeyEnv").value = cfg.generation_api_key_env || "";
      $("uptime").textContent = String(metrics.uptime_seconds || 0);
      $("calls").textContent = String(metrics.call_count || 0);
      $("failures").textContent = String(metrics.failure_count || 0);
      $("events").textContent = String(metrics.events_buffered || 0);
      const health = $("health");
      health.className = diagnosis.needs_repair ? "status bad" : "status";
      health.textContent = diagnosis.needs_repair ? "Needs repair" : "Ready";
      show({{ config: cfg, metrics, diagnosis }});
    }}

    async function refresh() {{
      setBusy(true);
      try {{
        render(await getContext());
      }} catch (error) {{
        $("health").className = "status bad";
        $("health").textContent = "Context error";
        show(error.message || String(error));
      }} finally {{
        setBusy(false);
      }}
    }}

    $("saveConfig").addEventListener("click", async () => {{
      setBusy(true);
      try {{
        const payload = await callAction("update_config", {{
          task_prompt: $("taskPrompt").value,
          generation_model: $("model").value,
          generation_provider: $("provider").value,
          generation_base_url: $("baseUrl").value,
          generation_api_key_env: $("apiKeyEnv").value,
        }});
        show(payload);
        await refresh();
      }} catch (error) {{
        show(error.message || String(error));
      }} finally {{
        setBusy(false);
      }}
    }});

    $("runTask").addEventListener("click", async () => {{
      setBusy(true);
      try {{
        show(await callAction("run_task", {{ instruction: $("taskPrompt").value }}));
        await refresh();
      }} catch (error) {{
        show(error.message || String(error));
      }} finally {{
        setBusy(false);
      }}
    }});

    $("diagnose").addEventListener("click", async () => {{
      setBusy(true);
      try {{
        show(await callAction("diagnostics", {{}}));
        await refresh();
      }} catch (error) {{
        show(error.message || String(error));
      }} finally {{
        setBusy(false);
      }}
    }});

    $("repairPrompt").addEventListener("click", async () => {{
      setBusy(true);
      try {{
        show(await callAction("repair_prompt", {{}}));
      }} catch (error) {{
        show(error.message || String(error));
      }} finally {{
        setBusy(false);
      }}
    }});

    $("refresh").addEventListener("click", refresh);
    refresh();
  </script>
</body>
</html>
'''


def _render_assistant_quickstart_md(spec: PluginSpec) -> str:
    return f'''# {_escape(spec.name or spec.plugin_id)}

This plugin was generated from a one-sentence brief.

```text
{_escape(spec.intent or spec.description or spec.plugin_id)}
```

## Entries

- `status` returns config, metrics, and diagnostics.
- `run_task` is the main entry point. Replace its body with real plugin logic.
- `update_config` saves model and runtime settings.
- `diagnostics` reads recent runtime logs and reports whether repair is needed.
- `repair_prompt` builds a log-aware prompt for a repair model.

## Package

Build a package from the N.E.K.O repository root:

```bash
uv run python -m plugin.neko_plugin_cli.cli build {spec.plugin_id}
```

The package output is `{spec.plugin_id}.neko-plugin`.
'''


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

def _render_pyproject_toml(spec: PluginSpec) -> str:
    return f'''[project]
name = "{spec.plugin_id}"
version = "{spec.version}"
dependencies = []
'''


# ---------------------------------------------------------------------------
# Repository support files
# ---------------------------------------------------------------------------

def _render_readme_md(spec: PluginSpec) -> str:
    name = spec.name or spec.plugin_id
    description = spec.description or "Describe what this plugin does and how to configure it."
    return f'''# {name}

{description}

## Development

This repository is meant to live at:

```text
N.E.K.O/plugin/plugins/{spec.plugin_id}
```

When publishing to the plugin market, use this GitHub repository name:

```text
{_market_repo_name(spec.plugin_id)}
```

From the N.E.K.O repository root:

```bash
uv run python -m plugin.neko_plugin_cli.cli check {spec.plugin_id}
uv run python -m plugin.neko_plugin_cli.cli check -r {spec.plugin_id}
```

## Market release

Push a tag matching `plugin.toml` version to create a GitHub Release asset:

```bash
git tag v{spec.version}
git push origin v{spec.version}
```

The generated `.github/workflows/release.yml` uploads `{spec.plugin_id}.neko-plugin`.
Use that GitHub Release URL when publishing a version in the plugin market.

## Entry

```toml
entry = "{spec.entry_point}"
```
'''


def _render_smoke_test(spec: PluginSpec) -> str:
    return f'''from pathlib import Path


def test_plugin_manifest_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = root / "plugin.toml"
    assert manifest.is_file()
    text = manifest.read_text(encoding="utf-8")
    assert 'id = "{spec.plugin_id}"' in text
    assert 'entry = "{spec.entry_point}"' in text
'''


def _render_gitignore() -> str:
    return '''__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
dist/
build/
*.egg-info/
store.db
.env
.DS_Store
'''


def _render_vscode_settings() -> str:
    return '''{
  "nekoPlugin.repoRoot": "../../..",
  "python.analysis.extraPaths": [
    "${workspaceFolder}/../../.."
  ]
}
'''


def _render_vscode_tasks(spec: PluginSpec) -> str:
    return f'''{{
  "version": "2.0.0",
  "tasks": [
    {{
      "label": "N.E.K.O: check {spec.plugin_id}",
      "type": "shell",
      "command": "uv run python -m plugin.neko_plugin_cli.cli check {spec.plugin_id}",
      "options": {{
        "cwd": "${{config:nekoPlugin.repoRoot}}"
      }},
      "problemMatcher": []
    }},
    {{
      "label": "N.E.K.O: check -r {spec.plugin_id}",
      "type": "shell",
      "command": "uv run python -m plugin.neko_plugin_cli.cli check -r {spec.plugin_id}",
      "options": {{
        "cwd": "${{config:nekoPlugin.repoRoot}}"
      }},
      "problemMatcher": []
    }},
    {{
      "label": "N.E.K.O: build {spec.plugin_id}",
      "type": "shell",
      "command": "uv run python -m plugin.neko_plugin_cli.cli build {spec.plugin_id}",
      "options": {{
        "cwd": "${{config:nekoPlugin.repoRoot}}"
      }},
      "problemMatcher": []
    }}
  ]
}}
'''


def _render_verify_workflow(spec: PluginSpec) -> str:
    return f'''name: Verify N.E.K.O Plugin

on:
  push:
  pull_request:
  workflow_dispatch:

env:
  PLUGIN_ID: {spec.plugin_id}
  NEKO_REPOSITORY: {spec.neko_repository}
  NEKO_REF: {spec.neko_ref}

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout plugin repository
        uses: actions/checkout@v4
        with:
          path: plugin-repo

      - name: Checkout N.E.K.O
        uses: actions/checkout@v4
        with:
          repository: ${{{{ env.NEKO_REPOSITORY }}}}
          ref: ${{{{ env.NEKO_REF }}}}
          path: neko

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Mount plugin into N.E.K.O tree
        run: |
          rm -rf "neko/plugin/plugins/${{PLUGIN_ID}}"
          mkdir -p neko/plugin/plugins
          cp -R plugin-repo "neko/plugin/plugins/${{PLUGIN_ID}}"

      - name: Release check
        working-directory: neko
        run: |
          set -o pipefail
          mkdir -p plugin/neko_plugin_cli/target
          uv run python -m plugin.neko_plugin_cli.cli check -r "${{PLUGIN_ID}}" | tee "plugin/neko_plugin_cli/target/${{PLUGIN_ID}}.check-release.txt"

      - name: Write verification summary
        working-directory: neko
        run: |
          PACKAGE="plugin/neko_plugin_cli/target/${{PLUGIN_ID}}.neko-plugin"
          test -f "$PACKAGE"
          PACKAGE_SHA256="$(sha256sum "$PACKAGE" | awk '{{print $1}}')"
          NEKO_COMMIT="$(git rev-parse HEAD)"

          {{
            echo "## N.E.K.O Plugin Verification"
            echo ""
            echo "| Field | Value |"
            echo "| --- | --- |"
            echo "| Plugin ID | ${{PLUGIN_ID}} |"
            echo "| Plugin commit | ${{GITHUB_SHA}} |"
            echo "| N.E.K.O repository | ${{NEKO_REPOSITORY}} |"
            echo "| N.E.K.O ref | ${{NEKO_REF}} |"
            echo "| N.E.K.O commit | ${{NEKO_COMMIT}} |"
            echo "| Package | ${{PLUGIN_ID}}.neko-plugin |"
            echo "| Package SHA256 | ${{PACKAGE_SHA256}} |"
            echo ""
            echo "### Release Check"
            echo '```text'
            cat "plugin/neko_plugin_cli/target/${{PLUGIN_ID}}.check-release.txt"
            echo '```'
          }} >> "$GITHUB_STEP_SUMMARY"

      - name: Upload verification artifact
        uses: actions/upload-artifact@v4
        with:
          name: ${{{{ env.PLUGIN_ID }}}}-verification
          path: |
            neko/plugin/neko_plugin_cli/target/${{{{ env.PLUGIN_ID }}}}.neko-plugin
            neko/plugin/neko_plugin_cli/target/${{{{ env.PLUGIN_ID }}}}.check-release.txt
'''


def _render_release_workflow(spec: PluginSpec) -> str:
    return f'''name: Release N.E.K.O Plugin

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

permissions:
  contents: write

env:
  PLUGIN_ID: {spec.plugin_id}
  NEKO_REPOSITORY: {spec.neko_repository}
  NEKO_REF: {spec.neko_ref}

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout plugin repository
        uses: actions/checkout@v4
        with:
          path: plugin-repo

      - name: Checkout N.E.K.O
        uses: actions/checkout@v4
        with:
          repository: ${{{{ env.NEKO_REPOSITORY }}}}
          ref: ${{{{ env.NEKO_REF }}}}
          path: neko

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Mount plugin into N.E.K.O tree
        run: |
          rm -rf "neko/plugin/plugins/${{PLUGIN_ID}}"
          mkdir -p neko/plugin/plugins
          cp -R plugin-repo "neko/plugin/plugins/${{PLUGIN_ID}}"

      - name: Market release check
        working-directory: neko
        run: |
          set -o pipefail
          mkdir -p plugin/neko_plugin_cli/target
          uv run python -m plugin.neko_plugin_cli.cli check -r --market-release "${{PLUGIN_ID}}" | tee "plugin/neko_plugin_cli/target/${{PLUGIN_ID}}.market-release-check.txt"

      - name: Write release summary
        working-directory: neko
        run: |
          PACKAGE="plugin/neko_plugin_cli/target/${{PLUGIN_ID}}.neko-plugin"
          test -f "$PACKAGE"
          PACKAGE_SHA256="$(sha256sum "$PACKAGE" | awk '{{print $1}}')"
          {{
            echo "## N.E.K.O Plugin Release"
            echo ""
            echo "| Field | Value |"
            echo "| --- | --- |"
            echo "| Plugin ID | ${{PLUGIN_ID}} |"
            echo "| Tag | ${{GITHUB_REF_NAME}} |"
            echo "| Package | ${{PLUGIN_ID}}.neko-plugin |"
            echo "| Package SHA256 | ${{PACKAGE_SHA256}} |"
          }} >> "$GITHUB_STEP_SUMMARY"

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          fail_on_unmatched_files: true
          files: |
            neko/plugin/neko_plugin_cli/target/${{{{ env.PLUGIN_ID }}}}.neko-plugin
            neko/plugin/neko_plugin_cli/target/${{{{ env.PLUGIN_ID }}}}.market-release-check.txt
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _market_repo_name(plugin_id: str) -> str:
    return f"{_MARKET_REPO_PREFIX}{plugin_id}"


def _write_support_file(path: Path, content: str, *, created: list[Path], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        return
    path.write_text(content, encoding="utf-8", newline="\n")
    created.append(path)
