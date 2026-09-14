"""diary 加载日志版本号读取单测（2026-09-14 部署验证盲区修复）。

背景：``plugin.py`` 的加载日志曾写死 ``"mai-diary v1 已加载"`` —— 这个 "v1" 与真实
版本号无关，**传旧版本的 config.py 也会打印同样的文案**，导致每次部署都无法用日志
确认远端是否真的更新了（9/14 部署 v1.4.1 时才发现这个盲区）。现改为从
``_manifest.json`` 读版本，与 narrative 侧口径一致。

三条保证：
1. 正常读到 manifest 里的版本号，且不产生任何告警；
2. manifest 读不到 / version 字段为空 → 返回"未知"并**告警**（不静默降级）；
3. 源码级护栏：加载日志不得再写死版本号。

运行（项目根）：

    .venv/Scripts/python.exe -m pytest plugins/glcoge-mai-diary/pytests/test_manifest_version.py -q
    .venv/Scripts/python.exe plugins/glcoge-mai-diary/pytests/test_manifest_version.py
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# 插件目录名含连字符，挂到合法标识符的合成包下加载
_SYNTH = "_diary_version_probe"


def _load_plugin():
    """加载 plugin.py（含其相对依赖 config；utils 注入最小 stub）。

    ``utils`` 是一个依赖链较深的包（``_logging``/``_envelope``/``ctx_config``/
    ``date``/``tokens``…），而本测试只关心"版本号怎么读"和"日志文案长什么样"，
    故对它注入最小 stub —— utils 的真实行为由 ``test_diary.py`` 覆盖。
    """
    key = f"{_SYNTH}.plugin"
    if key in sys.modules:
        return sys.modules[key]
    pkg = types.ModuleType(_SYNTH)
    pkg.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
    sys.modules[_SYNTH] = pkg

    utils_stub = types.ModuleType(f"{_SYNTH}.utils")
    utils_stub.get_logger = logging.getLogger  # type: ignore[attr-defined]
    sys.modules[f"{_SYNTH}.utils"] = utils_stub

    for rel, file_name in (("config", "config.py"), ("plugin", "plugin.py")):
        spec = importlib.util.spec_from_file_location(
            f"{_SYNTH}.{rel}", str(PLUGIN_ROOT / file_name)
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_SYNTH}.{rel}"] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


_PLUGIN = _load_plugin()
_manifest_version = _PLUGIN._manifest_version


class _LoggerStub:
    """只记录 warning 的假 logger（被测函数只用到这一个方法）。"""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args) -> None:  # noqa: ANN002
        self.warnings.append(msg)


# ===== 正常路径 =====


def test_reads_version_from_manifest():
    """版本号从 _manifest.json 读出，且与 manifest 实际内容一致。"""
    logger = _LoggerStub()
    version = _manifest_version(logger)
    expected = json.loads((PLUGIN_ROOT / "_manifest.json").read_text(encoding="utf-8"))["version"]
    assert version == expected
    assert version != "未知"
    assert logger.warnings == []


# ===== 异常路径：必须告警，不能静默降级 =====


def test_missing_manifest_reports_unknown_and_warns():
    """manifest 读不到 → "未知" + 告警（旧写死 "v1" 正是掩盖了这类失败）。"""
    logger = _LoggerStub()
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "nope.json"
        assert _manifest_version(logger, missing) == "未知"
    assert len(logger.warnings) == 1


def test_empty_version_reports_unknown_and_warns():
    """version 字段为空 → "未知" + 告警。"""
    logger = _LoggerStub()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "_manifest.json"
        path.write_text(json.dumps({"version": ""}), encoding="utf-8")
        assert _manifest_version(logger, path) == "未知"
    assert len(logger.warnings) == 1


def test_broken_json_reports_unknown_and_warns():
    """manifest 不是合法 JSON → "未知" + 告警（不抛异常阻塞插件加载）。"""
    logger = _LoggerStub()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "_manifest.json"
        path.write_text("{ 这不是 json", encoding="utf-8")
        assert _manifest_version(logger, path) == "未知"
    assert len(logger.warnings) == 1


# ===== 源码级护栏 =====


def test_load_log_is_not_hardcoded():
    """加载日志必须走 `%s` 占位符 + manifest 读取，不得再把版本号写死。

    断言写成"占位符形态必须存在"+"写死形态必须不存在"两条，而不是简单的子串
    匹配 —— 后者会被描述这段历史的 docstring 自己命中（本测试第一版就翻过车）。
    """
    source = (PLUGIN_ROOT / "plugin.py").read_text(encoding="utf-8")
    assert "mai-diary v%s 已加载" in source, "加载日志不再使用版本占位符"
    assert "_manifest_version(self.ctx.logger)" in source, "加载日志不再从 manifest 取版本"
    hardcoded = re.findall(r'"mai-diary v(?!%s)[^"\n]*已加载', source)
    assert not hardcoded, f"加载日志里的版本号又被写死了: {hardcoded}"


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
