"""端到端 ntfy 推送测试。

用插件真实的 NtfyNotifier 类发一条测试通知到 https://ntfy.sh/<topic>。
无需 SDK、无需 MaiBot 运行。验证完整代码路径（含中文 Title 旁路逻辑）。
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

# 复用 pytests 的合成包加载机制
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SYNTH_PKG = "_mai_diary_e2e"


def _load(rel: str, file: Path):
    if SYNTH_PKG not in sys.modules:
        mod = types.ModuleType(SYNTH_PKG)
        mod.__path__ = [str(PLUGIN_ROOT)]
        sys.modules[SYNTH_PKG] = mod
    parts = rel.split(".")
    for i in range(1, len(parts) + 1):
        full = f"{SYNTH_PKG}." + ".".join(parts[:i])
        if full not in sys.modules:
            m = types.ModuleType(full)
            m.__path__ = [str(PLUGIN_ROOT / "/".join(parts[:i]))]
            sys.modules[full] = m
    full_name = f"{SYNTH_PKG}.{rel}"
    spec = importlib.util.spec_from_file_location(full_name, str(file))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# 加载依赖
_utils = _load("utils", PLUGIN_ROOT / "utils" / "__init__.py")
_date = _load("utils.date", PLUGIN_ROOT / "utils" / "date.py")
_tokens = _load("utils.tokens", PLUGIN_ROOT / "utils" / "tokens.py")
_envelope = _load("utils._envelope", PLUGIN_ROOT / "utils" / "_envelope.py")
_logging = _load("utils._logging", PLUGIN_ROOT / "utils" / "_logging.py")
_ntfy = _load("services.diary.ntfy_notifier", PLUGIN_ROOT / "services" / "diary" / "ntfy_notifier.py")

NtfyNotifier = _ntfy.NtfyNotifier

# 强制 stdout UTF-8（Windows GBK 控制台）
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)


def make_cfg(topic: str):
    from types import SimpleNamespace
    return SimpleNamespace(
        enabled=True,
        server="https://ntfy.sh",
        topic=topic,
        auth_token="",
        priority="high",
        tags=["diary", "📔"],
        title_template="新日记  {date}",
        failure_title_template="❌ 日记生成失败  {date}",
        body_footer_template="\n\n—— mai-diary • {word_count}字",
        max_body_chars=2000,
        truncate_suffix="\n\n…（已截断，全文见本地文件）",
        click_action="",
        send_on_failure=True,
        timeout_seconds=10,
    )


async def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "glcoge-mai-diary"
    cfg = make_cfg(topic)
    n = NtfyNotifier(cfg)
    print(f"is_configured: {n.is_configured()}")
    print(f"server:        {n.server}")
    print(f"topic:         {n.topic}")
    print("---")
    ok = await n.send_diary(
        date="2026-07-30",
        content=(
            "【E2E 测试】这是用 mai-diary 插件真实的 NtfyNotifier 类发出的测试通知，"
            "中文 Title / emoji Tags 走 http.client putheader 旁路。\n"
            "如果你的手机收到这条通知，说明：\n"
            "1) ntfy.sh 链路可达\n"
            "2) topic 订阅正确\n"
            "3) UTF-8 header 编码修复生效\n"
        ),
        word_count=86,
        weather="晴",
    )
    print(f"send_diary 返回: {ok}")


if __name__ == "__main__":
    asyncio.run(main())
