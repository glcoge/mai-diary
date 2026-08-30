"""日记 prompt 模板。"""

from __future__ import annotations

import re
from typing import Any, Dict

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


__all__ = ["build_diary_prompt", "build_brief_prompt"]
