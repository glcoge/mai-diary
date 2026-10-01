"""日记 prompt 模板。"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ...config import _DEFAULT_BRIEF_PROMPT, _DEFAULT_DIARY_PROMPT
from ...utils import get_logger

logger = get_logger(__name__)


def _self_description_line(self_description: str) -> str:
    """构造'自我描述'附加行。空则返回空串。"""
    desc = (self_description or "").strip()
    if not desc:
        return ""
    if not desc.endswith(("。", ".", "！", "!", "？", "?")):
        desc += "。"
    return f"\n关于我：{desc}"


def _render_narrative_status(narrative_status: str) -> str:
    """渲染剧本人设当日状态附加段。空则返回空串。"""
    text = (narrative_status or "").strip()
    if not text:
        return ""
    return f"\n{text}\n"


def _life_material_lines(self_state: Dict[str, Any]) -> List[str]:
    """当日生活素材行（高光在前，普通片段在后）。

    narrative 侧自 2026-10-01 起在 ``self_state`` 回 ``today_highlights`` /
    ``today_life_fragments``（各自已按时间升序）。旧版 narrative 没有这两个键
    → 取到空列表即**静默跳过**（跨插件降级纪律：握手是附加动作，缺素材不能
    影响日记生成）。

    为什么单独成段而不是塞进"状态"（2026-10-01 用户反馈）：此前这两个字段
    存在于返回值里却**无人消费**，日记通篇只剩私聊/群聊话题；作者"自己的
    一天"完全缺席。故单独给一段，并明确写出「以这些为主线」。
    """
    lines: List[str] = []
    highlights = [
        str(item).strip() for item in (self_state.get("today_highlights") or [])
        if str(item).strip()
    ]
    if highlights:
        lines.append("印象深刻：" + "；".join(highlights))
    fragments = [
        str(item).strip() for item in (self_state.get("today_life_fragments") or [])
        if str(item).strip()
    ]
    if fragments:
        lines.append("其他片段：" + "；".join(fragments))
    return lines


def build_narrative_status(narrative_ctx: Dict[str, Any]) -> str:
    """把剧本自我层的当日状态渲染成 prompt 附加上下文（供日记口吻对齐）。

    两段结构（有则输出，无则整段省略）：

    1. ``〔作者当日状态…〕``：心情 / 作息 / 情绪轨迹；
    2. ``〔她今天自己的生活…〕``：当日高光 + 普通生活片段（本次接线的新段）。

    TODO(Round 3)：``today_mood_track``（每日情绪轨迹）表未建，v0.1 只注入
    当前心情快照；轨迹字段已在 narrative API 预留，当前返回空列表，此处透传
    最近条目（未实现，未来 Round 3 填表后自动生效）。
    """
    data = narrative_ctx.get("data") or {}
    self_state = data.get("self_state") or {}
    parts: List[str] = []

    mood_label = str(self_state.get("mood_label") or "")
    try:
        energy = float(self_state.get("mood_energy") or 0.0)
    except (TypeError, ValueError):
        energy = 0.0
    if mood_label:
        parts.append(f"心情：{mood_label}（精力 {energy * 10:.0f}/10）")
    phase = str(self_state.get("routine_phase") or "")
    if phase:
        parts.append(f"作息：{phase}")
    # 2026-09-26：原「心里挂着：hot_thread」行已随 narrative 侧输出字段一并删除。
    # 该字段自 narrative v0.1.3 起无写入点（恒空），本行从不触发 → 删除为零行为变化。

    track = data.get("today_mood_track") or []
    if isinstance(track, list):
        track_text = "；".join(str(item) for item in track[-6:] if str(item).strip())
        if track_text:
            parts.append(f"今日情绪轨迹：{track_text}")

    life_lines = _life_material_lines(self_state)

    blocks: List[str] = []
    if parts:
        blocks.append("〔作者当日状态（来自剧本人设自我层）：" + "，".join(parts) + "〕")
    if life_lines:
        blocks.append(
            "〔她今天自己的生活（来自剧本人设自我层，与聊天无关；"
            "写本篇时以这些为主线，聊天内容只作点缀）：" + "；".join(life_lines) + "〕"
        )
    return "\n".join(blocks)


def build_diary_prompt(
    *,
    date: str,
    timeline: str,
    date_with_weather: str,
    target_length: int,
    bot_personality: str,
    style_desc: str,
    self_description: str = "",
    current_time: str = "",
    narrative_status: str = "",
    template: str = "",
) -> str:
    """日记体 prompt。

    Args:
        template: 自定义模板（含占位符）。为空时使用 diary 默认模板。
        narrative_status: 剧本人设自我层当日状态段（剧本模式会话时注入，
            帮助日记口吻与聊天人格一致）；无则空串。
    """
    self_line = _self_description_line(self_description)
    ctx: Dict[str, Any] = {
        "date": date,
        "timeline": timeline,
        "date_with_weather": date_with_weather,
        "target_length": str(target_length),
        "bot_personality": bot_personality or "一个活泼的角色",
        "style_desc": style_desc or "",
        "self_description_line": self_line,
        "current_time": current_time or "",
        "narrative_status": _render_narrative_status(narrative_status),
    }
    if template and template.strip():
        return _render_custom_prompt(template, ctx)
    return _DEFAULT_DIARY_PROMPT.format(**ctx)


def build_brief_prompt(
    *,
    date: str,
    timeline: str,
    date_with_weather: str,
    target_length: int,
    bot_personality: str,
    style_desc: str,
    self_description: str = "",
    current_time: str = "",
    narrative_status: str = "",
    template: str = "",
) -> str:
    """简短记叙 prompt。

    Args:
        narrative_status: 同 :func:`build_diary_prompt`。
    """
    self_line = _self_description_line(self_description)
    ctx: Dict[str, Any] = {
        "date": date,
        "timeline": timeline,
        "date_with_weather": date_with_weather,
        "target_length": str(target_length),
        "bot_personality": bot_personality or "一个活泼的角色",
        "style_desc": style_desc or "",
        "self_description_line": self_line,
        "current_time": current_time or "",
        "narrative_status": _render_narrative_status(narrative_status),
    }
    if template and template.strip():
        return _render_custom_prompt(template, ctx)
    return _DEFAULT_BRIEF_PROMPT.format(**ctx)


def _render_custom_prompt(template: str, ctx: Dict[str, Any]) -> str:
    """自定义模板渲染。占位符缺失自动空字符串兜底。"""
    if not template or not template.strip():
        raise ValueError("custom_prompt 为空")
    placeholders = set(re.findall(r"\{(\w+)\}", template))
    for ph in placeholders:
        ctx.setdefault(ph, "")
    try:
        result = template.format(**ctx)
    except Exception as exc:
        raise ValueError(f"custom_prompt 格式化失败: {exc}") from exc
    if not result.strip():
        raise ValueError("custom_prompt 渲染结果为空")
    return result


__all__ = ["build_diary_prompt", "build_brief_prompt", "build_narrative_status"]
