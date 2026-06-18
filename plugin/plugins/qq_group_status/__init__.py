from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugin.sdk.plugin import Err, Ok, SdkError, lifecycle, neko_plugin, plugin_entry
from plugin.sdk.plugin import NekoPluginBase

from .config_store import QQGroupStatusConfigStore
from .config_store import normalize_issue_forward_target
from .monitor import (
    MonitorDecision,
    StickerRule,
    evaluate_group_message,
    group_id_from_entry,
    group_label_for,
    normalize_sticker_library,
    normalize_sticker_rules,
    select_sticker_rule,
)
from .qq_client import QQGroupOneBotClient


EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\ufe0f"
    "\u200d"
    "]+"
)
CATGIRL_W_SUFFIX_RE = re.compile(
    r"(?<=[\u4e00-\u9fffぁ-んァ-ン。！？!？，,、~～）\)])\s*[wWｗＷ]+(?=$|[\s。！？!？，,、~～])"
)
STICKER_CHOICE_RE = re.compile(
    r"(^|\n)\s*[\[【]?\s*(?:表情包|sticker)\s*[:：]\s*([^\]】\n]+?)\s*[\]】]?\s*(?=$|\n)",
    re.IGNORECASE,
)
SAFE_STICKER_NAME_RE = re.compile(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+")
MAX_STICKER_BYTES = 10 * 1024 * 1024
STICKER_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass(slots=True)
class ReplyPlan:
    text: str
    sticker: StickerRule | None = None


def _mask_token(token: str) -> str:
    token = str(token or "")
    if not token:
        return ""
    if len(token) <= 6:
        return "*" * len(token)
    return f"{token[:3]}***{token[-3:]}"


def _strip_emoji(text: str) -> str:
    cleaned = EMOJI_RE.sub("", str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _sanitize_reply_text(text: str) -> str:
    cleaned = _strip_emoji(text)
    cleaned = CATGIRL_W_SUFFIX_RE.sub("", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _format_source_group_label(source_group_id: str, source_label: str = "") -> str:
    group_id = str(source_group_id or "").strip()
    label = str(source_label or "").strip()
    if label and label != group_id:
        return f"{label} ({group_id})"
    return group_id or label or "未知群"


def _format_message_timestamp(message: dict[str, Any]) -> str:
    raw_timestamp = message.get("timestamp")
    if raw_timestamp in (None, ""):
        raw_timestamp = dict(message.get("raw") or {}).get("time")
    try:
        timestamp = int(float(raw_timestamp))
    except Exception:
        timestamp = 0
    if timestamp <= 0:
        return "未知"
    readable = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    return f"{timestamp}（{readable}）"


def _normalize_sticker_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip()).casefold()


def _safe_sticker_stem(label: str) -> str:
    stem = SAFE_STICKER_NAME_RE.sub("_", str(label or "").strip()).strip("._-")
    return stem[:48] or "sticker"


def _decode_sticker_payload(payload: str, filename: str = "") -> tuple[bytes, str]:
    raw_payload = str(payload or "").strip()
    if not raw_payload:
        raise ValueError("表情包内容为空")
    mime = ""
    encoded = raw_payload
    if raw_payload.lower().startswith("data:"):
        header, separator, body = raw_payload.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("表情包 data URL 格式不正确")
        mime = header[5:].split(";", 1)[0].lower()
        encoded = body
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ValueError("表情包不是有效的 base64") from exc
    if not data:
        raise ValueError("表情包内容为空")
    if len(data) > MAX_STICKER_BYTES:
        raise ValueError("单个表情包不能超过 10MB")
    detected_mime = _detect_sticker_mime(data)
    if not detected_mime:
        suffix = Path(str(filename or "")).suffix.lower()
        detected_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "")
    if not detected_mime:
        raise ValueError("只支持 PNG、JPG、GIF、WebP 表情包")
    if mime and mime not in STICKER_MIME_EXTENSIONS:
        raise ValueError("只支持 PNG、JPG、GIF、WebP 表情包")
    return data, detected_mime


def _detect_sticker_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _extract_sticker_choice(text: str, library: list[StickerRule]) -> ReplyPlan:
    raw = str(text or "")
    selected: StickerRule | None = None
    labels = {_normalize_sticker_label(item.label): item for item in library}

    def remove_marker(match: re.Match[str]) -> str:
        nonlocal selected
        label = _normalize_sticker_label(match.group(2))
        if selected is None and label in labels:
            selected = labels[label]
        return match.group(1)

    cleaned = STICKER_CHOICE_RE.sub(remove_marker, raw)
    return ReplyPlan(text=_sanitize_reply_text(cleaned), sticker=selected)


def _build_forward_issue_nodes(
    message: dict[str, Any],
    decision: MonitorDecision,
    *,
    source_label: str = "",
) -> list[dict[str, Any]]:
    source_group_id = str(message.get("group_id") or "")
    sender = str(message.get("user_nickname") or message.get("user_id") or "未知用户")
    sender_id = str(message.get("user_id") or "10000") or "10000"
    source_text = (
        f"来源群：{_format_source_group_label(source_group_id, source_label)}\n"
        f"发送者：{sender} ({sender_id})\n"
        f"时间戳：{_format_message_timestamp(message)}"
    )
    question_text = decision.text[:1200] if decision.text else "（无文本内容）"
    return [
        {
            "type": "node",
            "data": {
                "name": "QQ 群问题转移",
                "uin": sender_id,
                "content": [{"type": "text", "data": {"text": source_text}}],
            },
        },
        {
            "type": "node",
            "data": {
                "name": sender,
                "uin": sender_id,
                "content": [{"type": "text", "data": {"text": question_text}}],
            },
        },
    ]


@neko_plugin
class QQGroupStatusPlugin(NekoPluginBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.file_logger = self.enable_file_logging(log_level="INFO")
        self.logger = self.file_logger
        self.config_store = QQGroupStatusConfigStore(self.data_path())
        self._settings: dict[str, Any] = self.config_store.default_config()
        self.qq_client: QQGroupOneBotClient | None = None
        self._running = False
        self._message_task: asyncio.Task | None = None
        self._handler_tasks: set[asyncio.Task] = set()
        self._message_concurrency = asyncio.Semaphore(4)
        self._cooldowns: dict[str, float] = {}
        self._recent_events: list[dict[str, Any]] = []

    @lifecycle(id="startup")
    async def startup(self, **_):
        if not await self.config_store.exists():
            self._settings = await self.config_store.create_default()
        else:
            self._settings = await self.config_store.load()
        self.qq_client = self._build_client()
        self.register_static_ui("static")
        self.set_list_actions([
            {
                "id": "open_ui",
                "label": "打开 QQ 群状态监控",
                "kind": "ui",
                "target": f"/plugin/{self.plugin_id}/ui/",
                "open_in": "new_tab",
            }
        ])
        auto_start_result: dict[str, Any] | None = None
        if self._settings.get("auto_start_monitor"):
            try:
                await self._start_monitor_runtime()
                auto_start_result = {"status": "started"}
            except Exception as exc:
                auto_start_result = {"status": "failed", "error": str(exc)}
                self.logger.warning(f"QQ group status auto start failed: {exc}")
        return Ok({"status": "ready", "auto_start": auto_start_result, "monitor": self._build_status()})

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        await self._stop_monitor_runtime()
        return Ok({"status": "shutdown"})

    def _build_client(self) -> QQGroupOneBotClient:
        return QQGroupOneBotClient(
            onebot_url=str(self._settings.get("onebot_url") or "ws://127.0.0.1:3001"),
            token=str(self._settings.get("token") or ""),
            logger=self.logger,
        )

    def _public_config(self) -> dict[str, Any]:
        config = dict(self._settings or {})
        config["token_masked"] = _mask_token(str(config.get("token") or ""))
        config["token_configured"] = bool(config.get("token"))
        return config

    def _build_status(self) -> dict[str, Any]:
        return {
            "plugin_running": True,
            "monitor_running": self._running,
            "onebot_connected": bool(self.qq_client and self.qq_client.connected),
            "setup_checks": self._build_setup_checks(),
            "config": self._public_config(),
            "recent_events": list(self._recent_events),
            "ui": {
                "available": True,
                "path": f"/plugin/{self.plugin_id}/ui/",
            },
        }

    def _build_setup_checks(self) -> dict[str, Any]:
        napcat_shell_path = Path(__file__).resolve().parent.parent / "qq_auto_reply" / "NapCat.Shell"
        monitored_groups = [
            group_id_from_entry(item)
            for item in self._settings.get("monitored_groups") or []
            if group_id_from_entry(item)
        ]
        authorized = [str(item).strip() for item in self._settings.get("authorized_qq_numbers") or [] if str(item).strip()]
        responsible = [
            item for item in self._settings.get("responsible_people") or []
            if isinstance(item, dict) and str(item.get("qq") or "").strip()
        ]
        onebot_url = str(self._settings.get("onebot_url") or "").strip()
        forward_target_id = self._issue_forward_target_id()
        forward_target_type = self._issue_forward_target_type()
        forwarding_configured = bool(self._settings.get("issue_forwarding_enabled") and forward_target_id)
        return {
            "napcat": {
                "detected": napcat_shell_path.exists(),
                "path": str(napcat_shell_path),
                "download_url": "https://github.com/NapNeko/NapCatQQ/releases",
                "recommended_package": "NapCat.Shell.zip",
            },
            "onebot_url_configured": onebot_url.startswith(("ws://", "wss://")),
            "onebot_connected": bool(self.qq_client and self.qq_client.connected),
            "monitored_groups_configured": bool(monitored_groups),
            "monitor_scope": "configured_groups" if monitored_groups else "all_groups",
            "authorized_qq_configured": bool(authorized),
            "responsible_people_configured": bool(responsible),
            "issue_forwarding_configured": forwarding_configured,
            "issue_forward_target_type": forward_target_type,
            "sticker_library_configured": bool(self._settings.get("sticker_library")),
            "sticker_rules_configured": bool(self._settings.get("sticker_rules") or self._settings.get("sticker_library")),
            "ready": bool(onebot_url.startswith(("ws://", "wss://")) and (forwarding_configured or (authorized and responsible))),
        }

    @plugin_entry(
        id="get_status",
        name="获取 QQ 群监控状态",
        description="读取 QQ 群状态监控插件的运行状态、配置和最近触发事件。",
        input_schema={"type": "object", "properties": {}},
    )
    async def get_status(self, **_):
        return Ok(self._build_status())

    @plugin_entry(
        id="save_config",
        name="保存 QQ 群监控配置",
        description="保存 OneBot 地址、监控群、授权 QQ、疑问关键词、问题转移和相关负责人等配置。",
        input_schema={
            "type": "object",
            "properties": {
                "config": {"type": "object"},
            },
            "additionalProperties": True,
        },
    )
    async def save_config(self, config: dict[str, Any] | None = None, **kwargs):
        old_connection = (
            str(self._settings.get("onebot_url") or ""),
            str(self._settings.get("token") or ""),
        )
        incoming = dict(self._settings or {})
        if isinstance(config, dict):
            incoming.update(config)
        for key, value in kwargs.items():
            if key != "config":
                incoming[key] = value
        self._settings = await self.config_store.save(incoming)
        new_connection = (
            str(self._settings.get("onebot_url") or ""),
            str(self._settings.get("token") or ""),
        )
        reconnect_required = self._running and old_connection != new_connection
        if not self._running:
            self.qq_client = self._build_client()
        return Ok({**self._build_status(), "persisted": True, "reconnect_required": reconnect_required})

    @plugin_entry(
        id="import_stickers",
        name="导入 QQ 群表情包",
        description="导入 PNG、JPG、GIF 或 WebP 表情包，保存到表情包库供猫娘按名称选择。",
        input_schema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "filename": {"type": "string"},
                            "data_url": {"type": "string"},
                            "content_base64": {"type": "string"},
                        },
                    },
                },
            },
            "additionalProperties": True,
        },
    )
    async def import_stickers(self, files: list[dict[str, Any]] | None = None, **_):
        if not isinstance(files, list) or not files:
            return Err(SdkError("IMPORT_STICKERS_FAILED: 请选择至少一个表情包文件"))
        stickers_dir = self.data_path("stickers")
        await asyncio.to_thread(stickers_dir.mkdir, parents=True, exist_ok=True)

        library = normalize_sticker_library(self._settings.get("sticker_library"))
        by_label = {_normalize_sticker_label(item.label): item for item in library}
        imported: list[dict[str, Any]] = []

        for item in files:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or item.get("name") or "").strip()
            label = str(item.get("name") or Path(filename).stem or "").strip()
            payload = str(item.get("data_url") or item.get("content_base64") or "")
            try:
                raw, mime = _decode_sticker_payload(payload, filename=filename)
            except ValueError as exc:
                return Err(SdkError(f"IMPORT_STICKERS_FAILED: {filename or label or '未命名文件'}：{exc}"))
            label = label or Path(filename).stem or "表情包"
            digest = hashlib.sha256(raw).hexdigest()
            extension = STICKER_MIME_EXTENSIONS[mime]
            target = stickers_dir / f"{_safe_sticker_stem(label)}-{digest[:12]}{extension}"
            await asyncio.to_thread(target.write_bytes, raw)
            sticker = StickerRule(
                id=digest[:16],
                label=label,
                file=str(target),
                keywords=[],
                reasons=[],
                probability=1.0,
            )
            by_label[_normalize_sticker_label(label)] = sticker
            imported.append(sticker.to_dict())

        self._settings = await self.config_store.save({
            **self._settings,
            "sticker_library": [item.to_dict() for item in by_label.values()],
        })
        return Ok({**self._build_status(), "imported": imported})

    @plugin_entry(
        id="start_monitor",
        name="启动 QQ 群状态监控",
        description="连接 OneBot WebSocket 并开始监听群聊消息。",
        input_schema={"type": "object", "properties": {}},
    )
    async def start_monitor(self, **_):
        if self._running:
            return Ok({"status": "already_running", **self._build_status()})
        try:
            await self._start_monitor_runtime()
            return Ok({"status": "started", **self._build_status()})
        except Exception as exc:
            self.logger.exception("Failed to start QQ group status monitor")
            return Err(SdkError(f"START_FAILED: {exc}"))

    @plugin_entry(
        id="stop_monitor",
        name="停止 QQ 群状态监控",
        description="停止监听群聊消息并断开 OneBot WebSocket。",
        input_schema={"type": "object", "properties": {}},
    )
    async def stop_monitor(self, **_):
        await self._stop_monitor_runtime()
        return Ok({"status": "stopped", **self._build_status()})

    @plugin_entry(
        id="test_evaluate_message",
        name="测试群消息命中规则",
        description="用一条模拟群消息测试当前配置会命中哪些 QQ 群状态监控规则。",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "group_id": {"type": "string"},
                "sender_id": {"type": "string"},
                "at_targets": {"type": "array", "items": {"type": "string"}},
                "media_types": {"type": "array", "items": {"type": "string"}},
                "file_names": {"type": "array", "items": {"type": "string"}},
            },
        },
    )
    async def test_evaluate_message(
        self,
        text: str = "",
        group_id: str = "10000",
        sender_id: str = "20000",
        at_targets: list[str] | None = None,
        media_types: list[str] | None = None,
        file_names: list[str] | None = None,
        **_,
    ):
        segments: list[dict[str, Any]] = [{"type": "text", "data": {"text": text}}]
        for qq in at_targets or []:
            segments.append({"type": "at", "data": {"qq": str(qq)}})
        for media_type in media_types or []:
            segments.append({"type": str(media_type), "data": {"file": f"demo.{media_type}"}})
        for file_name in file_names or []:
            segments.append({"type": "file", "data": {"name": str(file_name), "file": str(file_name)}})
        message = {
            "message_type": "group",
            "group_id": str(group_id),
            "user_id": str(sender_id),
            "user_nickname": "测试用户",
            "content": text,
            "message_id": "test-message",
            "timestamp": int(time.time()),
            "raw": {
                "group_id": group_id,
                "user_id": sender_id,
                "raw_message": text,
                "message": segments,
            },
        }
        decision = evaluate_group_message(message, self._settings)
        return Ok(decision.to_dict())

    async def _start_monitor_runtime(self) -> None:
        self.qq_client = self._build_client()
        await self.qq_client.connect()
        self._running = True
        self._message_task = asyncio.create_task(self._message_loop())

    async def _stop_monitor_runtime(self) -> None:
        self._running = False
        if self._message_task:
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
            self._message_task = None
        if self._handler_tasks:
            tasks = list(self._handler_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._handler_tasks.clear()
        if self.qq_client:
            await self.qq_client.disconnect()

    async def _message_loop(self) -> None:
        while self._running and self.qq_client:
            try:
                message = await self.qq_client.receive_message(timeout=1.0)
                if not message:
                    continue
                task = asyncio.create_task(self._run_message_handler(message))
                self._handler_tasks.add(task)
                task.add_done_callback(self._handler_tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning(f"QQ group status message loop error: {exc}")
                await asyncio.sleep(1.0)

    async def _run_message_handler(self, message: dict[str, Any]) -> None:
        async with self._message_concurrency:
            await self._handle_group_message(message)

    def _group_is_monitored(self, group_id: str) -> bool:
        monitored = {
            group_id_from_entry(item)
            for item in self._settings.get("monitored_groups") or []
            if group_id_from_entry(item)
        }
        return not monitored or str(group_id) in monitored

    def _cooldown_allows(self, key: str, seconds: int) -> bool:
        if seconds <= 0:
            return True
        now = time.time()
        last = self._cooldowns.get(key, 0.0)
        if now - last < seconds:
            return False
        self._cooldowns[key] = now
        return True

    async def _handle_group_message(self, message: dict[str, Any]) -> None:
        group_id = str(message.get("group_id") or "").strip()
        sender_id = str(message.get("user_id") or "").strip()
        self_id = str(message.get("self_id") or "").strip()
        if not group_id or not self._group_is_monitored(group_id):
            return
        if self_id and sender_id == self_id:
            return

        decision = evaluate_group_message(message, self._settings)
        if self._issue_forwarding_requested():
            if self._issue_forwarding_enabled():
                forward_decision = evaluate_group_message(message, {
                    **self._settings,
                    "authorized_qq_numbers": [],
                })
                if forward_decision.is_question:
                    await self._maybe_forward_issue(message, forward_decision)
            else:
                self.logger.warning("QQ group status issue forwarding is enabled but target group is not configured")
            return

        if not decision.should_alert:
            if self._should_daily_chat_reply(decision):
                await self._maybe_reply_catgirl(message, decision)
            return

        event = self._build_event(message, decision)
        self._recent_events = ([event] + self._recent_events)[:100]

        if self._settings.get("popup_notifications", True):
            await self._maybe_push_alert(message, decision, event)
        if decision.should_mention_staff and self._settings.get("mention_staff_on_question", True):
            await self._maybe_ping_staff(message, decision)

    def _should_daily_chat_reply(self, decision: MonitorDecision) -> bool:
        if self._issue_forwarding_requested():
            return False
        if not self._settings.get("daily_chat_reply_enabled", True):
            return False
        if decision.media_types and not decision.mentioned_authorized:
            return False
        if self._settings.get("daily_chat_requires_mention", True):
            return bool(decision.mentioned_authorized)
        return True

    def _issue_forwarding_requested(self) -> bool:
        return bool(self._settings.get("issue_forwarding_enabled"))

    def _issue_forwarding_enabled(self) -> bool:
        return bool(
            self._settings.get("issue_forwarding_enabled")
            and self._issue_forward_target_id()
        )

    def _issue_forward_target_id(self) -> str:
        target_id, _ = normalize_issue_forward_target(
            self._settings.get("issue_forward_target_id") or self._settings.get("issue_forward_group_id"),
            self._settings.get("issue_forward_target_type"),
        )
        return target_id

    def _issue_forward_target_type(self) -> str:
        _, target_type = normalize_issue_forward_target(
            self._settings.get("issue_forward_target_id") or self._settings.get("issue_forward_group_id"),
            self._settings.get("issue_forward_target_type"),
        )
        return target_type

    def _build_event(self, message: dict[str, Any], decision: MonitorDecision) -> dict[str, Any]:
        return {
            "id": f"{message.get('group_id')}:{message.get('message_id')}:{int(time.time() * 1000)}",
            "group_id": str(message.get("group_id") or ""),
            "sender_id": str(message.get("user_id") or ""),
            "sender_name": str(message.get("user_nickname") or message.get("user_id") or ""),
            "message_id": str(message.get("message_id") or ""),
            "timestamp": int(time.time()),
            "decision": decision.to_dict(),
        }

    async def _maybe_push_alert(self, message: dict[str, Any], decision: MonitorDecision, event: dict[str, Any]) -> None:
        group_id = str(message.get("group_id") or "")
        sender_id = str(message.get("user_id") or "")
        message_id = str(message.get("message_id") or "").strip()
        digest = re.sub(r"\s+", " ", decision.text)[:48]
        key = f"notify:{group_id}:{message_id or (sender_id + ':' + ','.join(decision.reasons) + ':' + digest)}"
        if not self._cooldown_allows(key, int(self._settings.get("notify_cooldown_seconds") or 0)):
            return
        text = self._build_alert_text(message, decision)
        self.push_message(
            source=self.plugin_id,
            visibility=["hud"],
            ai_behavior="blind",
            parts=[{"type": "text", "text": text}],
            priority=7,
            coalesce_key=f"qq-group-status:{group_id}",
            metadata={
                "delivery_semantics": "passive",
                "kind": "qq_group_status_alert",
                "event": event,
            },
        )

    async def _maybe_forward_issue(self, message: dict[str, Any], decision: MonitorDecision) -> None:
        target_id = self._issue_forward_target_id()
        target_type = self._issue_forward_target_type()
        source_group_id = str(message.get("group_id") or "").strip()
        if not target_id or not source_group_id:
            return
        if target_type == "group" and target_id == source_group_id:
            self.logger.warning("QQ group status issue forwarding target matches source group; skipped")
            return
        digest = re.sub(r"\s+", " ", decision.text)[:80]
        key = f"forward:{source_group_id}:{target_type}:{target_id}:{digest}"
        if not self._cooldown_allows(key, int(self._settings.get("notify_cooldown_seconds") or 0)):
            return
        source_label = group_label_for(source_group_id, self._settings.get("monitored_groups"))
        text = self._build_forward_issue_text(message, decision, source_label=source_label)
        try:
            if target_type == "user":
                await self._send_private_transfer_issue(target_id, text)
            else:
                await self._send_forward_issue(target_id, target_type, message, decision, source_label=source_label)
        except Exception as exc:
            if target_type == "user":
                self.logger.warning(f"QQ group status private issue transfer failed: {exc}")
                return
            self.logger.warning(f"QQ group status merged forward failed, fallback to text: {exc}")
            await self._send_group_segments(target_id, [{"type": "text", "data": {"text": text}}])

    async def _send_private_transfer_issue(self, target_id: str, text: str) -> None:
        if not self.qq_client or not self.qq_client.connected:
            raise RuntimeError("OneBot is not connected")
        await self.qq_client.send_private_message_segments(target_id, [{"type": "text", "data": {"text": text}}])

    async def _send_forward_issue(
        self,
        target_id: str,
        target_type: str,
        message: dict[str, Any],
        decision: MonitorDecision,
        *,
        source_label: str = "",
    ) -> None:
        if not self.qq_client or not self.qq_client.connected:
            raise RuntimeError("OneBot is not connected")
        nodes = _build_forward_issue_nodes(message, decision, source_label=source_label)
        if target_type == "user":
            await self.qq_client.send_private_forward_message_nodes(target_id, nodes)
        else:
            await self.qq_client.send_group_forward_message_nodes(target_id, nodes)

    def _build_forward_issue_text(
        self,
        message: dict[str, Any],
        decision: MonitorDecision,
        *,
        source_label: str = "",
    ) -> str:
        source_group_id = str(message.get("group_id") or "")
        sender = str(message.get("user_nickname") or message.get("user_id") or "未知用户")
        sender_id = str(message.get("user_id") or "")
        preview = decision.text[:500] if decision.text else "（无文本内容）"
        return (
            "[QQ 群问题转移]\n"
            f"来源群：{_format_source_group_label(source_group_id, source_label)}\n"
            f"发送者：{sender} ({sender_id})\n"
            f"时间戳：{_format_message_timestamp(message)}\n"
            f"内容：{preview}"
        )

    def _build_alert_text(self, message: dict[str, Any], decision: MonitorDecision) -> str:
        reason_labels = {
            "question": "疑问句",
            "archive_file": "压缩包文件",
        }
        reasons = "、".join(reason_labels.get(item, item) for item in decision.reasons)
        sender = str(message.get("user_nickname") or message.get("user_id") or "未知用户")
        group_id = str(message.get("group_id") or "")
        preview = decision.text[:180] if decision.text else "（无文本内容）"
        archive_text = f"\n压缩包：{', '.join(decision.archive_files[:3])}" if decision.archive_files else ""
        staff = "、".join(item.name or item.qq for item in decision.responsible_people) or "未配置"
        return (
            f"[QQ 群状态提醒] 群 {group_id} 触发：{reasons}\n"
            f"发送者：{sender} ({message.get('user_id')})\n"
            f"内容：{preview}{archive_text}\n"
            f"建议处理人：{staff}"
        )

    async def _maybe_reply_catgirl(self, message: dict[str, Any], decision: MonitorDecision) -> None:
        group_id = str(message.get("group_id") or "")
        sender_id = str(message.get("user_id") or "")
        key = f"reply:{group_id}:{sender_id}"
        if not self._cooldown_allows(key, int(self._settings.get("reply_cooldown_seconds") or 0)):
            return
        reply = await self._generate_catgirl_reply(message, decision)
        segments = self._reply_prefix_segments(message)
        reply_text = reply.text
        if sender_id:
            segments.append({"type": "at", "data": {"qq": sender_id}})
            reply_text = f" {reply_text}"
        segments.append({"type": "text", "data": {"text": reply_text}})
        await self._send_group_segments(group_id, segments)
        sticker = self._select_optional_sticker(message, decision, channel="reply", preferred=reply.sticker)
        if sticker:
            await self._send_group_sticker(group_id, sticker)

    async def _maybe_ping_staff(self, message: dict[str, Any], decision: MonitorDecision) -> None:
        group_id = str(message.get("group_id") or "")
        message_id = str(message.get("message_id") or "").strip()
        key = f"staff:{group_id}:{message_id or (str(message.get('user_id') or '') + ':' + ','.join(decision.reasons))}"
        if not self._cooldown_allows(key, int(self._settings.get("staff_mention_cooldown_seconds") or 0)):
            return
        segments = self._reply_prefix_segments(message)
        selected_person = random.choice(decision.responsible_people) if decision.responsible_people else None
        if selected_person:
            segments.append({"type": "at", "data": {"qq": selected_person.qq}})
        text = _strip_emoji(str(self._settings.get("staff_ping_template") or "这条消息可能需要处理，麻烦看一下喵。").strip())
        if not text:
            text = "这条消息可能需要处理，麻烦看一下喵。"
        segments.append({"type": "text", "data": {"text": f" {text}" if selected_person else text}})
        await self._send_group_segments(group_id, segments)
        sticker = self._select_optional_sticker(message, decision, channel="staff")
        if sticker:
            await self._send_group_sticker(group_id, sticker)

    def _select_optional_sticker(
        self,
        message: dict[str, Any],
        decision: MonitorDecision,
        *,
        channel: str,
        preferred: StickerRule | None = None,
    ) -> StickerRule | None:
        if not self._settings.get("sticker_enabled", True):
            return None
        rule = preferred
        if not rule and channel != "reply":
            rules = normalize_sticker_rules(self._settings.get("sticker_rules"))
            rule = select_sticker_rule(
                decision.text,
                decision.reasons,
                rules,
                random_value=random.random(),
            )
        if not rule and channel == "reply" and not normalize_sticker_library(self._settings.get("sticker_library")):
            rules = normalize_sticker_rules(self._settings.get("sticker_rules"))
            rule = select_sticker_rule(
                decision.text,
                decision.reasons,
                rules,
                random_value=random.random(),
            )
        if not rule:
            return None
        group_id = str(message.get("group_id") or "")
        sender_id = str(message.get("user_id") or "")
        key = f"sticker:{channel}:{group_id}:{sender_id}:{rule.id}"
        if not self._cooldown_allows(key, int(self._settings.get("sticker_cooldown_seconds") or 0)):
            return None
        return rule

    def _reply_prefix_segments(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        message_id = str(message.get("message_id") or "").strip()
        if not message_id:
            return []
        return [{"type": "reply", "data": {"id": message_id}}]

    async def _send_group_segments(self, group_id: str, segments: list[dict[str, Any]]) -> None:
        if not self.qq_client or not self.qq_client.connected:
            self.logger.warning("QQ group status skipped send: OneBot is not connected")
            return
        try:
            await self.qq_client.send_group_message_segments(group_id, segments)
        except Exception as exc:
            self.logger.warning(f"QQ group status send failed: {exc}")

    async def _send_private_segments(self, user_id: str, segments: list[dict[str, Any]]) -> None:
        if not self.qq_client or not self.qq_client.connected:
            self.logger.warning("QQ group status skipped private send: OneBot is not connected")
            return
        try:
            await self.qq_client.send_private_message_segments(user_id, segments)
        except Exception as exc:
            self.logger.warning(f"QQ group status private send failed: {exc}")

    async def _send_group_sticker(self, group_id: str, sticker: StickerRule) -> None:
        await asyncio.sleep(0.15)
        await self._send_group_segments(group_id, [{"type": "image", "data": {"file": sticker.file}}])

    async def _generate_catgirl_reply(self, message: dict[str, Any], decision: MonitorDecision) -> ReplyPlan:
        fallback = ReplyPlan(text=_sanitize_reply_text(self._format_template_reply(message, decision)))
        if not self._settings.get("use_llm_reply", True):
            return fallback
        try:
            from utils.config_manager import get_config_manager
            from utils.llm_client import create_chat_llm, strip_thinking_segments

            model_config = get_config_manager().get_model_api_config("agent")
            base_url = str(model_config.get("base_url") or "").strip()
            model = str(model_config.get("model") or "").strip()
            api_key = str(model_config.get("api_key") or "").strip()
            if not base_url or not model:
                return fallback
            sticker_library = normalize_sticker_library(self._settings.get("sticker_library"))
            sticker_names = "、".join(item.label for item in sticker_library[:30])
            sticker_instruction = ""
            if sticker_names:
                sticker_instruction = (
                    f"可选表情包名称：{sticker_names}。"
                    "如果某个表情包很适合当前回复，可以在回复最后单独一行写 [表情包: 名称]；"
                    "如果不适合就不要写表情包标记。正文里不要解释表情包。"
                )
            llm = create_chat_llm(
                model=model,
                base_url=base_url,
                api_key=api_key,
                max_completion_tokens=120,
                timeout=20.0,
            )
            try:
                if decision.should_alert:
                    task_instruction = "说明你已经看到并会提醒相关人员"
                else:
                    task_instruction = "像日常群聊一样自然回应对方，轻快一点"
                response = await llm.ainvoke([
                    {
                        "role": "system",
                        "content": (
                            "你是 N.E.K.O 项目的猫娘助手。"
                            "现在有人在 QQ 群里 @ 了授权账号。"
                            f"请用温柔、轻快、猫娘语气回复，{task_instruction}。"
                            "不要使用 Markdown，不要超过 80 个中文字符。"
                            "禁止使用 emoji，可以使用普通颜文字。"
                            "不要在句尾添加 w、W、ｗ 或类似网络语尾巴。"
                            f"{sticker_instruction}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"群号：{message.get('group_id')}\n"
                            f"发言人：{message.get('user_nickname') or message.get('user_id')}\n"
                            f"消息：{decision.text}"
                        ),
                    },
                ])
                raw_text = strip_thinking_segments(str(getattr(response, "content", "") or "")).strip()
                plan = _extract_sticker_choice(raw_text, sticker_library)
                plan.text = plan.text[:160]
                if plan.text:
                    return plan
                if plan.sticker:
                    return ReplyPlan(text=fallback.text, sticker=plan.sticker)
                return fallback
            finally:
                aclose = getattr(llm, "aclose", None)
                if callable(aclose):
                    await aclose()
        except Exception as exc:
            self.logger.warning(f"QQ group status LLM catgirl reply failed, using template: {exc}")
            return fallback

    def _format_template_reply(self, message: dict[str, Any], decision: MonitorDecision) -> str:
        template_key = "catgirl_reply_template" if decision.should_alert else "daily_chat_reply_template"
        template = str(self._settings.get(template_key) or "")
        sender_name = str(message.get("user_nickname") or message.get("user_id") or "这位朋友")
        try:
            return template.format(
                sender_name=sender_name,
                sender_id=message.get("user_id") or "",
                group_id=message.get("group_id") or "",
                message=decision.text,
            )
        except Exception:
            return f"我看到啦，{sender_name}。这个问题已经提醒相关成员了喵。"
