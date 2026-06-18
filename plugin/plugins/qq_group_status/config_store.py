from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from utils.file_utils import atomic_write_json_async, read_json_async

from .monitor import (
    DEFAULT_PROJECT_KEYWORDS,
    DEFAULT_QUESTION_KEYWORDS,
    as_string_list,
    normalize_probability,
    normalize_responsible_people,
    normalize_sticker_library,
    normalize_sticker_rules,
)


USER_TARGET_PREFIXES = ("user:", "private:", "friend:", "qq:", "用户:", "好友:", "私聊:", "用户：", "好友：", "私聊：")
GROUP_TARGET_PREFIXES = ("group:", "群:", "群聊:", "群：", "群聊：")


def normalize_issue_forward_target(target_id: Any, target_type: Any = "group") -> tuple[str, str]:
    raw_id = str(target_id or "").strip()
    raw_type = str(target_type or "group").strip().lower()
    normalized_type = "user" if raw_type in {"user", "private", "friend", "qq", "用户", "好友", "私聊"} else "group"
    lowered = raw_id.lower()
    for prefix in USER_TARGET_PREFIXES:
        if lowered.startswith(prefix):
            return raw_id[len(prefix):].strip(), "user"
    for prefix in GROUP_TARGET_PREFIXES:
        if lowered.startswith(prefix):
            return raw_id[len(prefix):].strip(), "group"
    return raw_id, normalized_type


class QQGroupStatusConfigStore:
    FILE_NAME = "group_status_config.json"

    def __init__(self, base_dir: Path):
        self._path = Path(base_dir) / self.FILE_NAME
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def default_config(self) -> dict[str, Any]:
        return {
            "onebot_url": "ws://127.0.0.1:3001",
            "token": "",
            "auto_start_monitor": False,
            "monitored_groups": [],
            "authorized_qq_numbers": [],
            "responsible_people": [],
            "project_keywords": list(DEFAULT_PROJECT_KEYWORDS),
            "question_keywords": list(DEFAULT_QUESTION_KEYWORDS),
            "question_detection_enabled": True,
            "archive_detection_enabled": True,
            "media_detection_enabled": False,
            "mention_reply_enabled": True,
            "daily_chat_reply_enabled": True,
            "daily_chat_requires_mention": True,
            "issue_forwarding_enabled": False,
            "issue_forward_group_id": "",
            "issue_forward_target_id": "",
            "issue_forward_target_type": "group",
            "mention_staff_on_question": True,
            "popup_notifications": True,
            "use_llm_reply": True,
            "sticker_enabled": True,
            "sticker_cooldown_seconds": 60,
            "sticker_library": [],
            "sticker_rules": [],
            "notify_cooldown_seconds": 90,
            "reply_cooldown_seconds": 45,
            "staff_mention_cooldown_seconds": 30,
            "catgirl_reply_template": "我看到啦，{sender_name}。这个问题已经提醒相关成员了喵，请把现象、截图和复现步骤也发一下喵。",
            "daily_chat_reply_template": "我在的喵，{sender_name}～",
            "staff_ping_template": "这条消息可能需要处理，麻烦看一下喵。",
        }

    async def exists(self) -> bool:
        return self._path.is_file()

    async def load(self) -> dict[str, Any]:
        if not self._path.is_file():
            return self.default_config()
        payload = await read_json_async(self._path)
        if not isinstance(payload, dict):
            return self.default_config()
        return self.normalize(payload)

    async def create_default(self) -> dict[str, Any]:
        config = self.default_config()
        await self.save(config)
        return config

    async def save(self, config: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            normalized = self.normalize(config)
            await atomic_write_json_async(self._path, normalized)
            return normalized

    def normalize(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self.default_config()
        normalized.update(dict(config or {}))

        normalized["onebot_url"] = str(normalized.get("onebot_url") or "").strip() or "ws://127.0.0.1:3001"
        normalized["token"] = str(normalized.get("token") or "")
        normalized["monitored_groups"] = as_string_list(normalized.get("monitored_groups"))
        normalized["authorized_qq_numbers"] = as_string_list(normalized.get("authorized_qq_numbers"))
        target_id = normalized.get("issue_forward_target_id") or normalized.get("issue_forward_group_id")
        target_id, target_type = normalize_issue_forward_target(target_id, normalized.get("issue_forward_target_type"))
        normalized["issue_forward_target_id"] = target_id
        normalized["issue_forward_group_id"] = target_id
        normalized["issue_forward_target_type"] = target_type
        normalized["project_keywords"] = as_string_list(normalized.get("project_keywords")) or list(DEFAULT_PROJECT_KEYWORDS)
        normalized["question_keywords"] = as_string_list(normalized.get("question_keywords")) or list(DEFAULT_QUESTION_KEYWORDS)
        normalized["responsible_people"] = [item.to_dict() for item in normalize_responsible_people(normalized.get("responsible_people"))]
        normalized["sticker_library"] = [item.to_dict() for item in normalize_sticker_library(normalized.get("sticker_library"))]
        normalized["sticker_rules"] = [item.to_dict() for item in normalize_sticker_rules(normalized.get("sticker_rules"))]

        for key in (
            "auto_start_monitor",
            "question_detection_enabled",
            "archive_detection_enabled",
            "media_detection_enabled",
            "mention_reply_enabled",
            "daily_chat_reply_enabled",
            "daily_chat_requires_mention",
            "issue_forwarding_enabled",
            "mention_staff_on_question",
            "popup_notifications",
            "use_llm_reply",
            "sticker_enabled",
        ):
            normalized[key] = bool(normalized.get(key))

        for key, minimum, default in (
            ("notify_cooldown_seconds", 0, 90),
            ("reply_cooldown_seconds", 0, 45),
            ("staff_mention_cooldown_seconds", 0, 30),
            ("sticker_cooldown_seconds", 0, 60),
        ):
            try:
                value = int(normalized.get(key))
            except Exception:
                value = default
            normalized[key] = max(minimum, value)

        normalized["catgirl_reply_template"] = str(normalized.get("catgirl_reply_template") or "").strip() or self.default_config()["catgirl_reply_template"]
        normalized["daily_chat_reply_template"] = str(normalized.get("daily_chat_reply_template") or "").strip() or self.default_config()["daily_chat_reply_template"]
        normalized["staff_ping_template"] = str(normalized.get("staff_ping_template") or "").strip() or self.default_config()["staff_ping_template"]
        for sticker in normalized["sticker_rules"]:
            sticker["probability"] = normalize_probability(sticker.get("probability"), default=1.0)
        return normalized
