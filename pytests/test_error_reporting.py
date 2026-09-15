"""日记生成失败的「报错可见性」测试（2026-09-15，用户诉求：失败只推"返回空内容"）。

背景（真机问题）：近期 diary 多次生成失败，ntfy 推送的原因永远是
「模型返回空内容」。根因在 ``pipeline._call_model``：

    success, text = await self._llm.generate(...)
    return text if success else ""      # ← 失败时 text 就是错误原因，却被丢弃

于是上层只能写死一句"模型返回空内容"，落盘 + 推送都拿这句废话，真正的 API 报错
（超时秒数 / 异常文本 / success=False 的原因）只存在于日志里。

本测试锁定三件事：
1. LLM 调用失败时，真实原因要一路传到返回值与落盘记录（不能变成"返回空"）；
2. 「调用失败」与「调用成功但正文为空」必须区分开（两者排查方向完全不同）；
3. 完整报错（含异常堆栈、模型名、超时、prompt 长度）要落盘到
   ``data/diary/errors/YYYY-MM-DD.log``，便于事后追踪；
4. 失败通知 body 必须受 ``max_body_chars`` 约束（原本没截断，长报错会触发 ntfy 413）。

运行（项目根）：

    .venv/Scripts/python.exe -m pytest plugins/glcoge-mai-diary/pytests/test_error_reporting.py -q
    .venv/Scripts/python.exe plugins/glcoge-mai-diary/pytests/test_error_reporting.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SYNTH = "_diary_error_report_probe"


def _load(rel_name: str, file_path: Path) -> types.ModuleType:
    full = f"{_SYNTH}.{rel_name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, str(file_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


def _install_synth_package() -> None:
    """注册合成包。

    ``services`` / ``services.diary`` 注册成带 ``__path__`` 的空壳即可（只用于
    解析 ``.fetcher`` 这类相对导入）；但 ``utils`` **必须真实加载** —— storage /
    pipeline 都要 ``from ...utils import get_logger``，空壳会 ImportError。
    """
    if _SYNTH in sys.modules:
        return
    pkg = types.ModuleType(_SYNTH)
    pkg.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
    sys.modules[_SYNTH] = pkg
    for sub in ("services", "services.diary"):
        mod = types.ModuleType(f"{_SYNTH}.{sub}")
        mod.__path__ = [str(PLUGIN_ROOT / sub.replace(".", "/"))]  # type: ignore[attr-defined]
        sys.modules[f"{_SYNTH}.{sub}"] = mod


_install_synth_package()
_load("utils", PLUGIN_ROOT / "utils" / "__init__.py")
_STORAGE = _load("services.diary.storage", PLUGIN_ROOT / "services" / "diary" / "storage.py")
_PIPELINE = _load("services.diary.pipeline", PLUGIN_ROOT / "services" / "diary" / "pipeline.py")
_NTFY = _load("services.diary.ntfy_notifier", PLUGIN_ROOT / "services" / "diary" / "ntfy_notifier.py")

DiaryStorage = _STORAGE.DiaryStorage
DiaryPipeline = _PIPELINE.DiaryPipeline
NtfyNotifier = _NTFY.NtfyNotifier

_DATE = "2026-09-15"


class _FakeLLM:
    """假 LLM 能力：按 ``outcome`` 决定行为。"""

    def __init__(self, outcome: str, *, error: str = "上游 429 限流") -> None:
        self._outcome = outcome
        self._error = error

    async def generate(self, **kwargs) -> Any:  # noqa: ANN401, ARG002
        if self._outcome == "timeout":
            await asyncio.sleep(5)
            return {"success": True, "response": "永远不会到这"}
        if self._outcome == "raise":
            raise RuntimeError("connection reset by peer")
        if self._outcome == "failure":
            return {"success": False, "error": self._error}
        if self._outcome == "empty":
            return {"success": True, "response": "   "}
        return {"success": True, "response": "今天过得还不错。"}


def _make_cfg(base_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(
            target_chats="", filter_mode="all", min_messages_per_chat=0,
            min_message_count=5, per_message_max_chars=200,
        ),
        summary=SimpleNamespace(
            use_bot_personality=False, style="diary", custom_prompt="",
            self_description="", min_word_count=250, max_word_count=400,
        ),
        llm=SimpleNamespace(
            text_model="replyer", temperature=0.7, truncate_tokens=50000,
            timeout_seconds=1, show_prompt=False,
        ),
        output=SimpleNamespace(
            base_dir=base_dir, write_markdown=False, write_json=True,
            markdown_header_template="# {date} 日记\n\n",
            markdown_footer_template="\n\n---\n",
        ),
        narrative=SimpleNamespace(enabled=False, api_timeout_seconds=10),
        schedule=SimpleNamespace(generate_time="04:00", timezone_offset_hours=8),
    )


def _make_plugin(base_dir: str, llm: _FakeLLM) -> SimpleNamespace:
    ctx = SimpleNamespace(llm=llm)
    return SimpleNamespace(ctx=ctx, config=_make_cfg(base_dir))


def _run_pipeline(outcome: str, *, error: str = "上游 429 限流"):
    """在一个临时 data 目录里跑一次生成，返回 (结果, base_dir)。"""
    tmp = tempfile.mkdtemp()
    plugin = _make_plugin(tmp, _FakeLLM(outcome, error=error))
    pipeline = DiaryPipeline(plugin)
    result = asyncio.run(
        pipeline._generate_from_messages(_DATE, [], 0.0, 1.0)
    )
    return result, tmp


def _latest_json(base_dir: str) -> Dict[str, Any]:
    json_dir = Path(base_dir) / "json"
    files = sorted(json_dir.glob("*.json"))
    assert files, "没有落盘任何日记记录"
    return json.loads(files[-1].read_text(encoding="utf-8"))


# ===== 1. 真实报错必须传出去 =====


def test_llm_failure_reason_reaches_return_value():
    """LLM 返回 success=False → 原因要出现在返回值里，不能变成"返回空"。"""
    result, _ = _run_pipeline("failure", error="上游 429 限流")
    ok, message, retryable = result
    assert ok is False
    assert "429" in message, f"真实报错丢失了: {message}"
    assert "返回空" not in message


def test_llm_failure_reason_reaches_disk():
    """同一原因也要落进 JSON 的 error_message（ntfy 推送就是从这里取的）。"""
    _, base = _run_pipeline("failure", error="上游 429 限流")
    assert "429" in _latest_json(base)["error_message"]


def test_timeout_reason_is_reported():
    """超时 → 报出超时秒数，而不是"返回空"。"""
    result, _ = _run_pipeline("timeout")
    ok, message, _ = result
    assert ok is False
    assert "超时" in message, f"超时原因丢失了: {message}"


def test_exception_reason_is_reported():
    """调用抛异常 → 异常文本要带出来。"""
    result, _ = _run_pipeline("raise")
    ok, message, _ = result
    assert ok is False
    assert "connection reset" in message, f"异常原因丢失了: {message}"


# ===== 2. 两种"空"必须区分 =====


def test_empty_content_is_distinguished_from_call_failure():
    """调用成功但正文为空 ≠ 调用失败，文案必须能分辨。"""
    failed_msg = _run_pipeline("failure")[0][1]
    empty_msg = _run_pipeline("empty")[0][1]
    assert failed_msg != empty_msg
    assert "429" in failed_msg
    assert "空" in empty_msg


# ===== 3. 完整报错落盘到 data 目录 =====


def test_exception_text_written_to_error_log():
    """LLM 抛异常时，异常文本要进 data/errors/（这类异常由 LLMRunner 捕获，
    不带堆栈；堆栈只在 pipeline 捕获到未预期异常时才有，见下一个用例）。"""
    _, base = _run_pipeline("raise")
    log_path = Path(base) / "errors" / f"{_DATE}.log"
    assert log_path.exists(), f"错误日志未生成: {log_path}"
    text = log_path.read_text(encoding="utf-8")
    assert "connection reset" in text


def test_unexpected_exception_writes_traceback():
    """未预期异常（pipeline 自己捕获的）→ 完整堆栈落盘。

    这类问题光看一行 reason 无从下手，必须有堆栈。这里用「缺字段的 config」
    在生成过程中制造一个 AttributeError 来触发。
    """
    tmp = tempfile.mkdtemp()
    cfg = _make_cfg(tmp)
    cfg.summary = SimpleNamespace(
        use_bot_personality=False, custom_prompt="", self_description="",
        min_word_count=250, max_word_count=400,
    )  # 故意缺 style 字段
    plugin = SimpleNamespace(ctx=SimpleNamespace(llm=_FakeLLM("ok")), config=cfg)
    pipeline = DiaryPipeline(plugin)
    ok, message, _ = asyncio.run(pipeline._generate_from_messages(_DATE, [], 0.0, 1.0))
    assert ok is False
    text = (Path(tmp) / "errors" / f"{_DATE}.log").read_text(encoding="utf-8")
    assert "Traceback" in text, "未预期异常应当落完整堆栈"


def test_error_log_appends_across_failures():
    """同一天多次失败应追加而非覆盖（便于追踪重试过程）。"""
    tmp = tempfile.mkdtemp()
    for _ in range(2):
        plugin = _make_plugin(tmp, _FakeLLM("failure"))
        asyncio.run(DiaryPipeline(plugin)._generate_from_messages(_DATE, [], 0.0, 1.0))
    text = (Path(tmp) / "errors" / f"{_DATE}.log").read_text(encoding="utf-8")
    assert text.count("429") >= 2, f"应为追加而非覆盖: {text!r}"


def test_error_log_carries_diagnostic_context():
    """错误日志里要带模型名 / 超时 / prompt 长度等排查上下文。"""
    _, base = _run_pipeline("failure")
    text = (Path(base) / "errors" / f"{_DATE}.log").read_text(encoding="utf-8")
    assert "replyer" in text, "缺少模型名"
    assert "timeout" in text.lower(), "缺少超时配置"


def test_success_does_not_write_error_log():
    """成功时不该产生错误日志。"""
    _, base = _run_pipeline("ok")
    assert not (Path(base) / "errors" / f"{_DATE}.log").exists()


# ===== 4. 失败通知 body 必须受长度约束 =====


def _make_ntfy_cfg(max_body_chars: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True, server="https://ntfy.sh", topic="t", auth_token="",
        priority="default", tags=["diary"], click_action="",
        title_template="新日记  {date}",
        failure_title_template="❌ 日记生成失败  {date}",
        body_footer_template="", truncate_suffix="\n\n…（已截断）",
        max_body_chars=max_body_chars, timeout_seconds=5, send_on_failure=True,
    )


class _CapturingNotifier(NtfyNotifier):
    """拦截 _post，只记录将要发出的 body。"""

    def __init__(self, cfg) -> None:  # noqa: ANN001
        super().__init__(cfg)
        self.bodies: List[str] = []

    async def _post(self, *, title, body, priority, tags, click) -> bool:  # noqa: ANN001, ANN003
        self.bodies.append(body)
        return True


def test_failure_body_is_truncated():
    """长报错必须被截断，否则公共 ntfy.sh 会 413 拒收。"""
    long_error = "E" * 5000
    notifier = _CapturingNotifier(_make_ntfy_cfg(max_body_chars=200))
    asyncio.run(notifier.send_failure(date=_DATE, error=long_error))
    body = notifier.bodies[0]
    assert len(body) < 500, f"失败通知未截断: {len(body)} 字符"
    assert "E" in body


def test_failure_body_keeps_short_error_intact():
    """短报错不该被动到（截断只针对超长情况）。"""
    notifier = _CapturingNotifier(_make_ntfy_cfg(max_body_chars=2000))
    asyncio.run(notifier.send_failure(date=_DATE, error="LLM 调用超时(60s)"))
    body = notifier.bodies[0]
    assert "LLM 调用超时(60s)" in body
    assert "已截断" not in body


# ===== 独立运行入口 =====

if __name__ == "__main__":
    fns = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(0 if not failed else 1)
