"""日记 LLM 调用薄包装。"""

from __future__ import annotations

import asyncio
from typing import Any, Tuple

from ...utils import get_logger
from ...utils import peel_envelope

logger = get_logger(__name__)


class LLMRunner:
    """统一 LLM 调用入口。

    用法：
        runner = LLMRunner(plugin.ctx, plugin.config.llm.text_model,
                           timeout=plugin.config.llm.timeout_seconds)
        success, text = await runner.generate(prompt, temperature=0.7)
    """

    def __init__(
        self,
        ctx: Any,
        text_model: str = "replyer",
        *,
        timeout: int = 60,
    ) -> None:
        self._ctx = ctx
        self._text_model = text_model or "replyer"
        self._timeout = max(1, int(timeout or 60))

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Tuple[bool, str]:
        """生成文本。返回 (success, text)。"""
        if not prompt or not prompt.strip():
            return False, "空 prompt"
        try:
            result = await asyncio.wait_for(
                self._ctx.llm.generate(
                    prompt=prompt,
                    model=self._text_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("ctx.llm.generate 超时(%ds)", self._timeout)
            return False, f"LLM 调用超时({self._timeout}s)"
        except Exception as exc:
            logger.error("ctx.llm.generate 调用异常: %s", exc, exc_info=True)
            return False, f"LLM 调用异常: {exc}"

        result = peel_envelope(result)
        if not isinstance(result, dict):
            return False, f"LLM 返回非 dict: {type(result).__name__}"
        if not result.get("success", True):
            return False, str(result.get("error") or "LLM 返回 success=False")
        return True, str(result.get("response") or "").strip()


__all__ = ["LLMRunner"]
