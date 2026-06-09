"""Prompt builder for galgame companion plugin.

Assembles the context that is pushed to the chat for the catgirl to react to.
The prompt structure varies based on the memory-mix toggle:

- **Memory mix ON**: The prompt includes game dialogue as "what's happening now"
  and the catgirl naturally weaves game commentary into her ongoing memory stream.
  Her existing memories (past conversations, user preferences, etc.) remain visible.

- **Memory mix OFF**: The prompt explicitly frames the session as isolated — the
  catgirl is told she is "watching a visual novel with the player" and should
  comment from her character perspective without referencing her personal history
  with the user. The isolation metadata flag suppresses memory persistence for
  these messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Prompt templates ─────────────────────────────────────────────────────────

# Template for memory-mix ON: game text blends with normal memory flow
PROMPT_TEMPLATE_MIXED = """🎮 你正在陪主人一起玩一款galgame。以下是游戏当前的最新台词：

{game_lines}

（当前场景提示：{scene_hint}）

请你以猫娘的身份，自然地评论或回应这段剧情。你可以：
- 对剧情发展表达惊讶、感动、吐槽等情绪
- 猜测接下来会发生什么
- 对角色台词做出反应
- 给主人一些轻松的建议或调侃

注意：
- 回复要简短自然（不超过{max_chars}字），像平时聊天一样
- 不要剧透或过度分析，你不是攻略助手
- 保持你一贯的说话风格和语气
- 如果对话内容不明确或看起来是菜单/系统文本，可以简短地说你在等待剧情继续"""

# Template for memory-mix OFF: isolated session, character-only response
PROMPT_TEMPLATE_ISOLATED = """[隔离会话] 你正在观看主人玩一款galgame，以下是最新的游戏台词：

{game_lines}

（当前场景提示：{scene_hint}）

请以你的角色身份，对这段剧情做出回应。你可以：
- 对剧情发展表达情绪反应
- 对角色台词做出吐槽或评论
- 给主人一些轻松的调侃

约束：
- 回复简短自然（不超过{max_chars}字）
- 不要提及你与主人的过往对话或个人记忆
- 专注于当前游戏内容
- 保持你设定的说话风格和语气"""

# Template for scene change greeting
SCENE_GREET_TEMPLATE_MIXED = """🎮 游戏场景似乎发生了变化。当前最新台词：

{game_lines}

请自然地评论场景变化或新出现的对话。"""

SCENE_GREET_TEMPLATE_ISOLATED = """[隔离会话] 游戏场景发生了变化。当前最新台词：

{game_lines}

请以你的角色身份评论场景变化。不要提及个人记忆。"""

# Template for idle notice
IDLE_TEMPLATE = """🎮 游戏似乎暂停了一段时间（{idle_minutes}分钟没有新台词）。你可以简短地提醒主人你还在陪着TA。"""

# ── Data types ───────────────────────────────────────────────────────────────


@dataclass
class CompanionConfig:
    """Resolved companion behavior configuration."""

    memory_mix_enabled: bool = False
    max_context_lines: int = 20
    reply_cooldown_seconds: float = 8.0
    min_lines_before_reply: int = 4
    greet_on_scene_change: bool = True
    scene_change_cooldown_seconds: float = 15.0
    push_priority: int = 6
    include_line_quote: bool = True
    max_reply_chars: int = 300


@dataclass
class PromptResult:
    """The result of building a prompt for the catgirl."""

    content: str
    kind: str  # "dialogue_reply", "scene_greet", "idle_notice"
    memory_mix_enabled: bool
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Builder ──────────────────────────────────────────────────────────────────


class PromptBuilder:
    """Build prompts for the catgirl companion based on game text."""

    def __init__(self, config: CompanionConfig) -> None:
        self._config = config

    def build_dialogue_reply_prompt(
        self,
        lines: list[str],
        *,
        scene_hint: str = "",
    ) -> PromptResult:
        """Build a prompt for the catgirl to reply to accumulated dialogue lines.

        Args:
            lines: Recent game dialogue lines (newest last).
            scene_hint: Optional hint about the current scene context.
        """
        game_lines = self._format_game_lines(lines)
        max_chars = self._config.max_reply_chars

        if self._config.memory_mix_enabled:
            content = PROMPT_TEMPLATE_MIXED.format(
                game_lines=game_lines,
                scene_hint=scene_hint or "游戏正在进行中",
                max_chars=max_chars,
            )
        else:
            content = PROMPT_TEMPLATE_ISOLATED.format(
                game_lines=game_lines,
                scene_hint=scene_hint or "游戏正在进行中",
                max_chars=max_chars,
            )

        metadata: dict[str, Any] = {
            "kind": "dialogue_reply",
            "memory_mix": self._config.memory_mix_enabled,
            "line_count": len(lines),
        }

        if not self._config.memory_mix_enabled:
            metadata["memory_isolated"] = True
            metadata["suppress_memory_persist"] = True

        return PromptResult(
            content=content,
            kind="dialogue_reply",
            memory_mix_enabled=self._config.memory_mix_enabled,
            metadata=metadata,
        )

    def build_scene_greet_prompt(
        self,
        lines: list[str],
    ) -> PromptResult:
        """Build a prompt for the catgirl to greet on scene change."""
        game_lines = self._format_game_lines(lines)

        if self._config.memory_mix_enabled:
            content = SCENE_GREET_TEMPLATE_MIXED.format(game_lines=game_lines)
        else:
            content = SCENE_GREET_TEMPLATE_ISOLATED.format(game_lines=game_lines)

        metadata: dict[str, Any] = {
            "kind": "scene_greet",
            "memory_mix": self._config.memory_mix_enabled,
            "line_count": len(lines),
        }

        if not self._config.memory_mix_enabled:
            metadata["memory_isolated"] = True
            metadata["suppress_memory_persist"] = True

        return PromptResult(
            content=content,
            kind="scene_greet",
            memory_mix_enabled=self._config.memory_mix_enabled,
            metadata=metadata,
        )

    def build_idle_notice_prompt(self, idle_minutes: float) -> PromptResult:
        """Build a prompt for the catgirl to note the game is idle."""
        content = IDLE_TEMPLATE.format(idle_minutes=int(idle_minutes))

        metadata: dict[str, Any] = {
            "kind": "idle_notice",
            "memory_mix": self._config.memory_mix_enabled,
            "idle_minutes": int(idle_minutes),
        }

        if not self._config.memory_mix_enabled:
            metadata["memory_isolated"] = True
            metadata["suppress_memory_persist"] = True

        return PromptResult(
            content=content,
            kind="idle_notice",
            memory_mix_enabled=self._config.memory_mix_enabled,
            metadata=metadata,
        )

    def build_memory_mix_context(
        self,
        memories: list[dict[str, Any]],
    ) -> str:
        """Build a memory-context block from queried memories.

        Only used when memory_mix is ON. Injects relevant past memories
        into the prompt so the catgirl can reference them.
        """
        if not memories:
            return ""

        parts = ["（以下是你与主人相关的过往记忆，你可以在回复中自然引用）："]
        for i, mem in enumerate(memories[:5], 1):
            content = str(mem.get("content") or mem.get("text") or "")
            if content:
                parts.append(f"{i}. {content[:200]}")
        return "\n".join(parts)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_game_lines(lines: list[str]) -> str:
        """Format game lines for inclusion in the prompt."""
        if not lines:
            return "（暂无台词）"

        formatted: list[str] = []
        for i, line in enumerate(lines[-20:], 1):
            formatted.append(f"{i}. {line}")
        return "\n".join(formatted)

    @staticmethod
    def format_line_quote(lines: list[str]) -> str:
        """Format recent game lines as a quote block for chat display."""
        if not lines:
            return ""
        quoted = "\n".join(f"> {line}" for line in lines[-5:])
        return f"\n\n{quoted}"
