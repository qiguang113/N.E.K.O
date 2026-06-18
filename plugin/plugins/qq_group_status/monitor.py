from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_PROJECT_KEYWORDS = [
    "猫娘计划",
    "猫娘",
    "N.E.K.O",
    "NEKO",
    "neko",
    "启动器",
    "客户端",
    "插件",
    "OneBot",
    "NapCat",
]

DEFAULT_QUESTION_KEYWORDS = [
    "请问",
    "怎么",
    "如何",
    "为什么",
    "为啥",
    "咋",
    "能不能",
    "可不可以",
    "有没有",
    "哪里",
    "在哪",
    "谁知道",
    "求助",
    "报错",
    "错误",
    "异常",
    "崩溃",
    "闪退",
    "卡住",
    "无法",
    "不能",
    "不会",
    "没反应",
    "启动不了",
    "打不开",
    "咋办",
    "怎么办",
    "怎么回事",
    "帮忙",
    "帮看",
    "看下",
    "看看",
    "解决",
    "有办法",
    "可以吗",
    "行吗",
]

MEDIA_TYPES = {"image", "video"}
ARCHIVE_EXTENSIONS = (
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".gz",
    ".bz2",
    ".xz",
)
QUESTION_KEYWORD_RE = re.compile(r"(" + "|".join(re.escape(item) for item in DEFAULT_QUESTION_KEYWORDS) + r")", re.IGNORECASE)
CQ_SEGMENT_RE = re.compile(r"\[CQ:(?P<type>[a-zA-Z0-9_-]+)(?P<data>[^\]]*)\]")
CQ_AT_RE = re.compile(r"\[CQ:at,qq=([^\],]+)")
ARCHIVE_RE = re.compile(r"[\w ._+\-()\u4e00-\u9fff]+(?:\.tar\.gz|\.zip|\.rar|\.7z|\.tar|\.tgz|\.gz|\.bz2|\.xz)\b", re.IGNORECASE)
GROUP_LABEL_SPLIT_RE = re.compile(r"\s*[|｜]\s*", re.UNICODE)


@dataclass(slots=True)
class ResponsiblePerson:
    qq: str
    name: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qq": self.qq,
            "name": self.name,
            "keywords": list(self.keywords),
        }


@dataclass(slots=True)
class StickerRule:
    id: str
    label: str
    file: str
    keywords: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    probability: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "file": self.file,
            "keywords": list(self.keywords),
            "reasons": list(self.reasons),
            "probability": self.probability,
        }


@dataclass(slots=True)
class MonitorDecision:
    should_alert: bool
    reasons: list[str]
    text: str
    media_types: list[str]
    archive_files: list[str]
    at_targets: list[str]
    mentioned_authorized: bool = False
    is_question: bool = False
    is_project_related: bool = False
    responsible_people: list[ResponsiblePerson] = field(default_factory=list)

    @property
    def should_mention_staff(self) -> bool:
        return bool(self.responsible_people and (self.is_question or self.archive_files))

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_alert": self.should_alert,
            "reasons": list(self.reasons),
            "text": self.text,
            "media_types": list(self.media_types),
            "archive_files": list(self.archive_files),
            "at_targets": list(self.at_targets),
            "mentioned_authorized": self.mentioned_authorized,
            "is_question": self.is_question,
            "is_project_related": self.is_project_related,
            "responsible_people": [item.to_dict() for item in self.responsible_people],
        }


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [line.strip() for line in re.split(r"[\n,，;；]+", value)]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    return [item for item in items if item]


def parse_group_entry(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    parts = GROUP_LABEL_SPLIT_RE.split(raw, maxsplit=1)
    group_id = parts[0].strip()
    label = parts[1].strip() if len(parts) > 1 else ""
    return group_id, label


def group_id_from_entry(value: Any) -> str:
    group_id, _ = parse_group_entry(value)
    return group_id


def group_label_for(group_id: Any, entries: Any) -> str:
    lookup = str(group_id or "").strip()
    if not lookup:
        return ""
    for item in as_string_list(entries):
        item_id, label = parse_group_entry(item)
        if item_id == lookup:
            return label or item_id
    return lookup


def normalize_responsible_people(value: Any) -> list[ResponsiblePerson]:
    if not isinstance(value, list):
        return []
    people: list[ResponsiblePerson] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            raw = item.strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split("|")]
            qq = parts[0] if parts else ""
            name = parts[1] if len(parts) > 1 else ""
            keywords = as_string_list(parts[2]) if len(parts) > 2 else []
        elif isinstance(item, dict):
            qq = str(item.get("qq") or item.get("qq_number") or "").strip()
            name = str(item.get("name") or item.get("nickname") or "").strip()
            keywords = as_string_list(item.get("keywords"))
        else:
            continue
        if not qq or qq in seen:
            continue
        people.append(ResponsiblePerson(qq=qq, name=name, keywords=keywords))
        seen.add(qq)
    return people


def normalize_probability(value: Any, default: float = 1.0) -> float:
    try:
        probability = float(value)
    except Exception:
        probability = default
    return min(1.0, max(0.0, probability))


def normalize_sticker_rules(value: Any) -> list[StickerRule]:
    if not isinstance(value, list):
        return []
    rules: list[StickerRule] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            raw = item.strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split("|")]
            label = parts[0] if parts else ""
            file = parts[1] if len(parts) > 1 else ""
            keywords = as_string_list(parts[2]) if len(parts) > 2 else []
            reasons = as_string_list(parts[3]) if len(parts) > 3 else []
            probability = normalize_probability(parts[4], default=1.0) if len(parts) > 4 else 1.0
            rule_id = label or f"sticker_{index + 1}"
        elif isinstance(item, dict):
            rule_id = str(item.get("id") or item.get("name") or item.get("label") or f"sticker_{index + 1}").strip()
            label = str(item.get("label") or item.get("name") or rule_id).strip()
            file = str(item.get("file") or item.get("url") or item.get("path") or "").strip()
            keywords = as_string_list(item.get("keywords"))
            reasons = as_string_list(item.get("reasons"))
            probability = normalize_probability(item.get("probability"), default=1.0)
        else:
            continue
        if not rule_id or not file:
            continue
        if rule_id in seen:
            continue
        rules.append(StickerRule(
            id=rule_id,
            label=label or rule_id,
            file=file,
            keywords=keywords,
            reasons=reasons,
            probability=probability,
        ))
        seen.add(rule_id)
    return rules


def normalize_sticker_library(value: Any) -> list[StickerRule]:
    if not isinstance(value, list):
        return []
    stickers: list[StickerRule] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            raw = item.strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split("|")]
            label = parts[0] if parts else ""
            file = parts[1] if len(parts) > 1 else ""
            rule_id = label or f"sticker_{index + 1}"
        elif isinstance(item, dict):
            rule_id = str(item.get("id") or item.get("name") or item.get("label") or f"sticker_{index + 1}").strip()
            label = str(item.get("label") or item.get("name") or rule_id).strip()
            file = str(item.get("file") or item.get("url") or item.get("path") or "").strip()
        else:
            continue
        if not rule_id or not label or not file:
            continue
        key = label.casefold()
        if key in seen:
            continue
        stickers.append(StickerRule(
            id=rule_id,
            label=label,
            file=file,
            keywords=[],
            reasons=[],
            probability=1.0,
        ))
        seen.add(key)
    return stickers


def select_sticker_rule(
    text: str,
    reasons: list[str],
    rules: list[StickerRule],
    *,
    random_value: float | None = None,
) -> StickerRule | None:
    if not rules:
        return None
    reason_set = {str(reason or "").strip() for reason in reasons if str(reason or "").strip()}
    for rule in rules:
        matches_keyword = bool(rule.keywords and contains_keyword(text, rule.keywords))
        matches_reason = bool(rule.reasons and reason_set.intersection(rule.reasons))
        if not rule.keywords and not rule.reasons:
            matched = True
        else:
            matched = matches_keyword or matches_reason
        if not matched:
            continue
        threshold = normalize_probability(rule.probability, default=1.0)
        roll = 0.0 if random_value is None else normalize_probability(random_value, default=0.0)
        if threshold >= 1.0 or roll < threshold:
            return rule
    return None


def iter_message_segments(raw: dict[str, Any]) -> list[dict[str, Any]]:
    message = raw.get("message")
    if isinstance(message, list):
        return [seg for seg in message if isinstance(seg, dict)]
    return []


def extract_at_targets(raw: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for seg in iter_message_segments(raw):
        if seg.get("type") != "at":
            continue
        qq = str((seg.get("data") or {}).get("qq") or "").strip()
        if qq and qq not in targets:
            targets.append(qq)
    raw_message = str(raw.get("raw_message") or "")
    for qq in CQ_AT_RE.findall(raw_message):
        qq = qq.strip()
        if qq and qq not in targets:
            targets.append(qq)
    return targets


def extract_media_types(raw: dict[str, Any]) -> list[str]:
    media: list[str] = []
    for seg in iter_message_segments(raw):
        seg_type = str(seg.get("type") or "").strip().lower()
        if seg_type in MEDIA_TYPES and seg_type not in media:
            media.append(seg_type)
    raw_message = str(raw.get("raw_message") or "")
    for match in CQ_SEGMENT_RE.finditer(raw_message):
        seg_type = match.group("type").strip().lower()
        if seg_type in MEDIA_TYPES and seg_type not in media:
            media.append(seg_type)
    return media


def extract_archive_files(raw: dict[str, Any]) -> list[str]:
    filenames: list[str] = []
    for seg in iter_message_segments(raw):
        seg_type = str(seg.get("type") or "").strip().lower()
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        if seg_type != "file":
            continue
        for key in ("name", "file", "url"):
            value = str(data.get(key) or "").strip()
            if value and _looks_like_archive(value) and value not in filenames:
                filenames.append(value)
    raw_message = str(raw.get("raw_message") or "")
    for match in ARCHIVE_RE.findall(raw_message):
        filename = match.strip()
        if filename and filename not in filenames:
            filenames.append(filename)
    return filenames


def _looks_like_archive(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return bool(lowered and any(lowered.endswith(ext) for ext in ARCHIVE_EXTENSIONS))


def extract_searchable_text(message: dict[str, Any]) -> str:
    raw = dict(message.get("raw") or {})
    pieces: list[str] = []
    content = str(message.get("content") or raw.get("raw_message") or "").strip()
    if content:
        pieces.append(content)
    for seg in iter_message_segments(raw):
        seg_type = str(seg.get("type") or "").strip().lower()
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        if seg_type == "text":
            text = str(data.get("text") or "").strip()
            if text:
                pieces.append(text)
        elif seg_type == "file":
            for key in ("name", "file"):
                text = str(data.get(key) or "").strip()
                if text and _looks_like_archive(text):
                    pieces.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if piece in seen:
            continue
        deduped.append(piece)
        seen.add(piece)
    text = "\n".join(deduped)
    text = CQ_AT_RE.sub(lambda match: f"@用户{match.group(1)}", text)
    text = CQ_SEGMENT_RE.sub(lambda match: f"[{match.group('type')}]", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_keyword(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    for keyword in keywords:
        normalized = str(keyword or "").strip()
        if normalized and normalized.lower() in lowered:
            return True
    return False


def is_question_text(text: str, question_keywords: list[str] | None = None) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if question_keywords:
        keywords = [item for item in question_keywords if str(item or "").strip()]
        if keywords:
            dynamic_re = re.compile(r"(" + "|".join(re.escape(item) for item in keywords) + r")", re.IGNORECASE)
            if dynamic_re.search(normalized):
                return True
    elif QUESTION_KEYWORD_RE.search(normalized):
        return True
    return False


def select_responsible_people(text: str, people: list[ResponsiblePerson]) -> list[ResponsiblePerson]:
    return list(people)


def evaluate_group_message(message: dict[str, Any], config: dict[str, Any]) -> MonitorDecision:
    raw = dict(message.get("raw") or {})
    text = extract_searchable_text(message)
    at_targets = extract_at_targets(raw)
    media_types = extract_media_types(raw)
    archive_files = extract_archive_files(raw)

    authorized = set(as_string_list(config.get("authorized_qq_numbers")))
    project_keywords = as_string_list(config.get("project_keywords")) or list(DEFAULT_PROJECT_KEYWORDS)
    question_keywords = as_string_list(config.get("question_keywords")) or list(DEFAULT_QUESTION_KEYWORDS)
    responsible_people = normalize_responsible_people(config.get("responsible_people"))

    mentioned_authorized = bool(authorized.intersection(at_targets))
    question_enabled = bool(config.get("question_detection_enabled", True))
    mention_reply_enabled = bool(config.get("mention_reply_enabled", True))
    archive_enabled = bool(config.get("archive_detection_enabled", True))
    is_project_related = contains_keyword(text, project_keywords)

    if mentioned_authorized:
        return MonitorDecision(
            should_alert=False,
            reasons=[],
            text=text,
            media_types=media_types,
            archive_files=archive_files,
            at_targets=at_targets,
            mentioned_authorized=bool(mention_reply_enabled),
            is_question=False,
            is_project_related=is_project_related,
            responsible_people=[],
        )

    if media_types and not archive_files:
        return MonitorDecision(
            should_alert=False,
            reasons=[],
            text=text,
            media_types=media_types,
            archive_files=archive_files,
            at_targets=at_targets,
            mentioned_authorized=False,
            is_question=False,
            is_project_related=is_project_related,
            responsible_people=[],
        )

    is_question = question_enabled and is_question_text(text, question_keywords)
    archive_detected = bool(archive_enabled and archive_files)

    reasons: list[str] = []
    if is_question:
        reasons.append("question")
    if archive_detected:
        reasons.append("archive_file")

    selected_people: list[ResponsiblePerson] = []
    if bool(config.get("mention_staff_on_question", True)) and (is_question or archive_detected):
        selected_people = select_responsible_people(text, responsible_people)

    return MonitorDecision(
        should_alert=bool(reasons),
        reasons=reasons,
        text=text,
        media_types=media_types,
        archive_files=archive_files,
        at_targets=at_targets,
        mentioned_authorized=bool(mention_reply_enabled and mentioned_authorized),
        is_question=is_question,
        is_project_related=is_project_related,
        responsible_people=selected_people,
    )
