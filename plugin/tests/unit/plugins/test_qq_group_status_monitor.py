from __future__ import annotations

import pytest

from plugin.plugins.qq_group_status import (
    _build_forward_issue_nodes,
    _decode_sticker_payload,
    _extract_sticker_choice,
    _sanitize_reply_text,
    _strip_emoji,
)
from plugin.plugins.qq_group_status.config_store import QQGroupStatusConfigStore
from plugin.plugins.qq_group_status.qq_client import QQGroupOneBotClient
from plugin.plugins.qq_group_status.monitor import (
    evaluate_group_message,
    group_id_from_entry,
    group_label_for,
    normalize_responsible_people,
    normalize_sticker_library,
    normalize_sticker_rules,
    select_sticker_rule,
)


pytestmark = pytest.mark.plugin_unit


def _message(
    text: str,
    *,
    at_targets: list[str] | None = None,
    media_types: list[str] | None = None,
    file_names: list[str] | None = None,
) -> dict[str, object]:
    segments: list[dict[str, object]] = [{"type": "text", "data": {"text": text}}]
    for qq in at_targets or []:
        segments.append({"type": "at", "data": {"qq": qq}})
    for media_type in media_types or []:
        segments.append({"type": media_type, "data": {"file": f"demo.{media_type}", "summary": "猫娘计划截图"}})
    for file_name in file_names or []:
        segments.append({"type": "file", "data": {"name": file_name, "file": file_name}})
    return {
        "message_type": "group",
        "group_id": "10001",
        "user_id": "20002",
        "user_nickname": "测试用户",
        "content": text,
        "message_id": "30003",
        "timestamp": 123456,
        "raw": {
            "message_type": "group",
            "group_id": "10001",
            "user_id": "20002",
            "raw_message": text,
            "message": segments,
        },
    }


def test_question_message_alerts_with_all_responsible_candidates() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [
            {"qq": "111", "name": "安装同学", "keywords": ["安装", "启动"]},
            {"qq": "222", "name": "模型同学", "keywords": ["模型"]},
        ],
    })

    decision = evaluate_group_message(_message("猫娘计划安装后为什么启动不了？"), config)

    assert decision.should_alert is True
    assert decision.is_question is True
    assert decision.reasons == ["question"]
    assert [person.qq for person in decision.responsible_people] == ["111", "222"]


def test_bare_question_mark_does_not_alert() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(_message("？"), config)

    assert decision.should_alert is False
    assert decision.is_question is False
    assert decision.reasons == []
    assert decision.responsible_people == []


def test_repeated_question_marks_do_not_alert() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(_message("？？？"), config)

    assert decision.should_alert is False
    assert decision.is_question is False
    assert decision.reasons == []
    assert decision.responsible_people == []


def test_question_mark_with_text_before_it_does_not_alert() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(_message("这个？"), config)

    assert decision.should_alert is False
    assert decision.is_question is False
    assert decision.reasons == []
    assert decision.responsible_people == []


def test_project_related_media_does_not_alert_without_question() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(_message("猫娘计划这里显示这样", media_types=["image"]), config)

    assert decision.should_alert is False
    assert decision.is_project_related is True
    assert decision.media_types == ["image"]
    assert decision.reasons == []
    assert decision.responsible_people == []


def test_media_message_ignores_question_rule() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(_message("这个怎么回事？", media_types=["image"]), config)

    assert decision.should_alert is False
    assert decision.is_question is False
    assert decision.media_types == ["image"]
    assert decision.responsible_people == []


def test_media_url_query_string_does_not_trigger_question_alert() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })
    message = _message("", media_types=["image"])
    image_data = message["raw"]["message"][1]["data"]
    image_data["summary"] = "怎么回事"
    image_data["url"] = "https://example.com/sticker.png?keyword=怎么"

    decision = evaluate_group_message(message, config)

    assert decision.should_alert is False
    assert decision.is_question is False
    assert decision.reasons == []


def test_archive_file_alerts_with_all_responsible_candidates() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [
            {"qq": "111", "name": "日志同学", "keywords": ["日志"]},
            {"qq": "222", "name": "其他同学", "keywords": ["界面"]},
        ],
    })

    decision = evaluate_group_message(_message("日志在附件", file_names=["client-logs.zip"]), config)

    assert decision.should_alert is True
    assert decision.archive_files == ["client-logs.zip"]
    assert decision.reasons == ["archive_file"]
    assert [person.qq for person in decision.responsible_people] == ["111", "222"]


def test_forward_issue_nodes_include_source_and_question_text() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [],
    })
    message = _message("猫娘计划启动不了怎么办")
    decision = evaluate_group_message(message, config)

    nodes = _build_forward_issue_nodes(message, decision)

    assert nodes[0]["type"] == "node"
    assert nodes[1]["type"] == "node"
    source_text = nodes[0]["data"]["content"][0]["data"]["text"]
    assert "来源群：10001" in source_text
    assert "时间戳：123456" in source_text
    assert "消息 ID" not in source_text
    assert nodes[1]["data"]["name"] == "测试用户"
    assert nodes[1]["data"]["content"][0]["data"]["text"] == "猫娘计划启动不了怎么办"


def test_forward_issue_nodes_include_custom_source_group_label() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [],
    })
    message = _message("猫娘计划启动不了怎么办")
    decision = evaluate_group_message(message, config)

    nodes = _build_forward_issue_nodes(message, decision, source_label="一群")

    assert "来源群：一群 (10001)" in nodes[0]["data"]["content"][0]["data"]["text"]


def test_group_entries_support_custom_display_name() -> None:
    assert group_id_from_entry("1234567｜一群") == "1234567"
    assert group_id_from_entry("7654321|测试群") == "7654321"
    assert group_label_for("1234567", ["1234567｜一群", "7654321|测试群"]) == "一群"
    assert group_label_for("2222222", ["1234567｜一群"]) == "2222222"


def test_authorized_mention_marks_daily_reply_from_onebot_segments() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "authorized_qq_numbers": ["345678"],
        "responsible_people": [],
    })

    decision = evaluate_group_message(_message("在吗", at_targets=["345678"]), config)

    assert decision.should_alert is False
    assert decision.mentioned_authorized is True
    assert decision.reasons == []
    assert decision.at_targets == ["345678"]


def test_authorized_mention_skips_question_and_archive_rules() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "authorized_qq_numbers": ["345678"],
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": []}],
    })

    decision = evaluate_group_message(
        _message("启动不了怎么办？", at_targets=["345678"], file_names=["logs.zip"]),
        config,
    )

    assert decision.should_alert is False
    assert decision.mentioned_authorized is True
    assert decision.is_question is False
    assert decision.archive_files == ["logs.zip"]
    assert decision.reasons == []
    assert decision.responsible_people == []


def test_authorized_mention_marks_daily_reply_from_cq_text() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "authorized_qq_numbers": ["345678"],
    })
    msg = _message("[CQ:at,qq=345678] 在吗")
    msg["raw"]["message"] = []

    decision = evaluate_group_message(msg, config)

    assert decision.should_alert is False
    assert decision.mentioned_authorized is True
    assert decision.reasons == []


def test_new_question_keywords_alert_without_question_mark() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "responsible_people": [{"qq": "111", "name": "值班开发", "keywords": ["启动"]}],
    })

    decision = evaluate_group_message(_message("猫娘计划启动不了，帮看下"), config)

    assert decision.should_alert is True
    assert decision.is_question is True
    assert decision.reasons == ["question"]
    assert [person.qq for person in decision.responsible_people] == ["111"]


def test_strip_emoji_keeps_kaomoji() -> None:
    assert _strip_emoji("好哒😊 (。・ω・。)") == "好哒 (。・ω・。)"


def test_sanitize_reply_strips_catgirl_w_suffix_but_keeps_kaomoji() -> None:
    assert _sanitize_reply_text("好哒喵w") == "好哒喵"
    assert _sanitize_reply_text("我在的喵ｗ (。・ω・。)") == "我在的喵 (。・ω・。)"


def test_extract_sticker_choice_removes_marker_and_selects_known_sticker() -> None:
    library = normalize_sticker_library([
        {"id": "happy", "label": "开心", "file": "/tmp/happy.gif"},
        {"id": "thinking", "label": "思考", "file": "/tmp/think.png"},
    ])

    plan = _extract_sticker_choice("收到啦喵\n[表情包: 开心]", library)

    assert plan.text == "收到啦喵"
    assert plan.sticker is not None
    assert plan.sticker.file == "/tmp/happy.gif"


def test_extract_sticker_choice_ignores_unknown_sticker_name() -> None:
    library = normalize_sticker_library([
        {"id": "happy", "label": "开心", "file": "/tmp/happy.gif"},
    ])

    plan = _extract_sticker_choice("收到啦\n[表情包: 不存在]", library)

    assert plan.text == "收到啦"
    assert plan.sticker is None


def test_decode_sticker_payload_accepts_gif_data_url() -> None:
    raw, mime = _decode_sticker_payload("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")

    assert raw.startswith(b"GIF89a")
    assert mime == "image/gif"


def test_normalize_responsible_people_accepts_line_format() -> None:
    people = normalize_responsible_people([
        "123|后端|接口,报错",
        "456|前端|UI",
        "123|重复|忽略",
    ])

    assert [person.to_dict() for person in people] == [
        {"qq": "123", "name": "后端", "keywords": ["接口", "报错"]},
        {"qq": "456", "name": "前端", "keywords": ["UI"]},
    ]


def test_sticker_rule_selects_by_keyword_and_reason() -> None:
    rules = normalize_sticker_rules([
        "安慰|https://example.com/pat.png|报错,崩溃|question|1",
        "压缩包|https://example.com/file.gif|zip,rar|archive_file|1",
    ])

    selected = select_sticker_rule("猫娘计划报错了怎么办？", ["question"], rules, random_value=0.99)

    assert selected is not None
    assert selected.to_dict() == {
        "id": "安慰",
        "label": "安慰",
        "file": "https://example.com/pat.png",
        "keywords": ["报错", "崩溃"],
        "reasons": ["question"],
        "probability": 1.0,
    }


def test_sticker_rule_can_match_reason_without_keyword() -> None:
    rules = normalize_sticker_rules([
        {"id": "archive", "label": "压缩包", "file": "file:///tmp/file.gif", "reasons": ["archive_file"]},
    ])

    selected = select_sticker_rule("日志.zip", ["archive_file"], rules, random_value=0.5)

    assert selected is not None
    assert selected.file == "file:///tmp/file.gif"


def test_sticker_probability_zero_never_selects() -> None:
    rules = normalize_sticker_rules([
        {"id": "nope", "file": "https://example.com/nope.png", "keywords": ["报错"], "probability": 0},
    ])

    assert select_sticker_rule("这里报错了", ["question"], rules, random_value=0.0) is None


def test_config_normalizes_sticker_rules() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "sticker_rules": [
            "思考|https://example.com/think.png|怎么,为什么|question|0.5",
        ],
        "sticker_enabled": True,
        "sticker_cooldown_seconds": "12",
    })

    assert config["sticker_enabled"] is True
    assert config["sticker_cooldown_seconds"] == 12
    assert config["sticker_rules"] == [
        {
            "id": "思考",
            "label": "思考",
            "file": "https://example.com/think.png",
            "keywords": ["怎么", "为什么"],
            "reasons": ["question"],
            "probability": 0.5,
        }
    ]


def test_config_normalizes_sticker_library() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "sticker_library": [
            {"id": "ok", "label": "收到", "file": "/tmp/ok.gif", "keywords": ["ignored"]},
            {"id": "dup", "label": "收到", "file": "/tmp/dup.gif"},
        ],
    })

    assert config["sticker_library"] == [
        {
            "id": "ok",
            "label": "收到",
            "file": "/tmp/ok.gif",
            "keywords": [],
            "reasons": [],
            "probability": 1.0,
        }
    ]


def test_config_normalizes_issue_forwarding_settings() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "issue_forwarding_enabled": True,
        "issue_forward_target_id": " 好友:998877 ",
        "issue_forward_target_type": "好友",
    })

    assert config["issue_forwarding_enabled"] is True
    assert config["issue_forward_target_id"] == "998877"
    assert config["issue_forward_group_id"] == "998877"
    assert config["issue_forward_target_type"] == "user"


def test_config_mirrors_legacy_issue_forward_group_id() -> None:
    config = QQGroupStatusConfigStore(".").normalize({
        "issue_forwarding_enabled": True,
        "issue_forward_group_id": " 群聊:998877 ",
    })

    assert config["issue_forward_target_id"] == "998877"
    assert config["issue_forward_group_id"] == "998877"
    assert config["issue_forward_target_type"] == "group"


@pytest.mark.asyncio
async def test_private_message_segments_send_to_friend_with_private_action() -> None:
    client = QQGroupOneBotClient("ws://127.0.0.1:3001")
    client.ws = object()
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call_action(action: str, params: dict[str, object] | None = None, timeout: float = 10.0) -> object:
        calls.append((action, dict(params or {})))
        return {}

    client.call_action = fake_call_action  # type: ignore[method-assign]

    await client.send_private_message_segments("998877", [{"type": "text", "data": {"text": "问题转移"}}])

    assert calls == [
        (
            "send_private_msg",
            {
                "user_id": 998877,
                "message": [{"type": "text", "data": {"text": "问题转移"}}],
            },
        )
    ]


@pytest.mark.asyncio
async def test_private_forward_uses_user_params_and_private_fallback() -> None:
    client = QQGroupOneBotClient("ws://127.0.0.1:3001")
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call_action(action: str, params: dict[str, object] | None = None, timeout: float = 10.0) -> object:
        calls.append((action, dict(params or {})))
        if action == "send_private_forward_msg":
            raise RuntimeError("not supported")
        return {}

    client.call_action = fake_call_action  # type: ignore[method-assign]

    await client.send_private_forward_message_nodes("998877", [{"type": "node", "data": {}}])

    assert calls[0][0] == "send_private_forward_msg"
    assert calls[0][1]["user_id"] == 998877
    assert "group_id" not in calls[0][1]
    assert calls[1][0] == "send_forward_msg"
    assert calls[1][1]["message_type"] == "private"
    assert calls[1][1]["user_id"] == 998877
    assert "group_id" not in calls[1][1]
