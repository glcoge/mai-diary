"""手动推送一篇已有日记到 ntfy。

模仿 DiaryScheduler._push_safe 的判定逻辑：
- 从 data/diary/json 找指定日期（或最新一篇）的日记
- 读 status 决定走 send_diary 还是 send_failure
- 推送成功则更新 last_pushed_date.txt

用法：
    python scripts/push_diary.py                    # 推最新一篇
    python scripts/push_diary.py latest             # 同上
    python scripts/push_diary.py yesterday          # 推昨天（按 configured 时区）
    python scripts/push_diary.py 2026-07-29         # 推指定日期最新一条
    python scripts/push_diary.py --dry-run          # 只看会推什么，不真发
"""
import argparse
import asyncio
import datetime
import importlib.util
import json
import sys
import types
from pathlib import Path

if hasattr(sys.stdout, "buffer") and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

# ---- 加载插件模块（合成包名） ----
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SYNTH_PKG = "_mai_diary_push_cli"


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


# 加载最小依赖
_load("utils", PLUGIN_ROOT / "utils" / "__init__.py")
_load("utils._envelope", PLUGIN_ROOT / "utils" / "_envelope.py")
_load("utils._logging", PLUGIN_ROOT / "utils" / "_logging.py")
_load("utils.date", PLUGIN_ROOT / "utils" / "date.py")
_load("utils.tokens", PLUGIN_ROOT / "utils" / "tokens.py")
_ntfy_mod = _load("services.diary.ntfy_notifier", PLUGIN_ROOT / "services" / "diary" / "ntfy_notifier.py")
NtfyNotifier = _ntfy_mod.NtfyNotifier

# ---- 读 config.toml（不依赖 SDK，只解析 [ntfy] 段） ----

def _load_ntfy_cfg(config_path: Path):
    """轻量解析 config.toml 的 [ntfy] 段 + [schedule].timezone_offset_hours。"""
    import tomllib
    with config_path.open("rb") as f:
        cfg = tomllib.load(f)
    ntfy_raw = cfg.get("ntfy", {})
    sched = cfg.get("schedule", {})
    # 构造 NtfySection-like 对象
    from types import SimpleNamespace
    ns = SimpleNamespace()
    for k, v in ntfy_raw.items():
        ns.__dict__[k] = v
    # 补默认值（与 config.py 对齐）
    ns.__dict__.setdefault("enabled", False)
    ns.__dict__.setdefault("server", "https://ntfy.sh")
    ns.__dict__.setdefault("topic", "")
    ns.__dict__.setdefault("auth_token", "")
    ns.__dict__.setdefault("priority", "default")
    ns.__dict__.setdefault("tags", ["diary", "📔"])
    ns.__dict__.setdefault("title_template", "新日记  {date}")
    ns.__dict__.setdefault("failure_title_template", "❌ 日记生成失败  {date}")
    ns.__dict__.setdefault("body_footer_template", "\n\n—— mai-diary • {word_count}字")
    ns.__dict__.setdefault("max_body_chars", 2000)
    ns.__dict__.setdefault("truncate_suffix", "\n\n…（已截断，全文见本地文件）")
    ns.__dict__.setdefault("click_action", "")
    ns.__dict__.setdefault("send_on_failure", True)
    ns.__dict__.setdefault("timeout_seconds", 10)
    return ns, int(sched.get("timezone_offset_hours", 8))


# ---- 找指定日期的日记 ----

def _list_diary_files(json_dir: Path):
    return sorted(json_dir.glob("*.json"))


def _read_diary(json_path: Path) -> dict:
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def pick_diary(target: str, json_dir: Path, tz_offset_hours: int):
    """target: "yesterday" | "today" | "latest" | "YYYY-MM-DD" """
    files = _list_diary_files(json_dir)
    if not files:
        return None, None

    if target == "latest":
        # 按 generation_time 取最新一份
        latest = max(files, key=lambda p: p.stat().st_mtime)
        return latest, _read_diary(latest)

    if target in ("yesterday", "today"):
        now_utc = datetime.datetime.utcnow()
        local = now_utc + datetime.timedelta(hours=tz_offset_hours)
        delta = -1 if target == "yesterday" else 0
        date_str = (local + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")
    else:
        # YYYY-MM-DD
        try:
            datetime.datetime.strptime(target, "%Y-%m-%d")
        except ValueError:
            return None, None
        date_str = target

    matched = sorted(
        [p for p in files if p.name.startswith(date_str + "_")],
        key=lambda p: p.stat().st_mtime,
    )
    if not matched:
        return None, None
    return matched[-1], _read_diary(matched[-1])


# ---- 主流程 ----

async def main():
    ap = argparse.ArgumentParser(description="手动推送日记到 ntfy")
    ap.add_argument(
        "target", nargs="?", default="yesterday",
        help="推送目标: yesterday | today | latest | YYYY-MM-DD (默认 yesterday)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="只看会推什么，不真发",
    )
    ap.add_argument(
        "--config", type=Path, default=PLUGIN_ROOT / "config.toml",
        help="config.toml 路径（默认 <plugin>/config.toml）",
    )
    args = ap.parse_args()

    cfg, tz_offset = _load_ntfy_cfg(args.config)
    print(f"[配置] server={cfg.server}, topic={cfg.topic}, enabled={cfg.enabled}")
    if not cfg.enabled:
        print("⚠️  [ntfy].enabled = false，仍可手动推送（脚本强制开启）")
    if not cfg.topic:
        print("❌  [ntfy].topic 为空，无法推送")
        return 1
    print()

    notifier = NtfyNotifier(cfg)
    if not notifier.is_configured():
        print("❌  NtfyNotifier 未正确配置（需要 enabled + topic）")
        return 1

    # 找日记
    base_dir = PLUGIN_ROOT / "data" / "diary"
    json_dir = base_dir / "json"
    path, diary = pick_diary(args.target, json_dir, tz_offset)
    if not diary:
        print(f"❌  找不到 {args.target} 的日记（目录: {json_dir}）")
        return 1

    date = diary.get("date", "?")
    status = diary.get("status", "?")
    word_count = int(diary.get("word_count") or 0)
    weather = str(diary.get("weather") or "")
    content = str(diary.get("diary_content") or "")
    error_msg = str(diary.get("error_message") or "")
    print(f"[日记] {path.name}")
    print(f"       date={date}, status={status}, word_count={word_count}, weather={weather}")
    print()

    if "报错" in status:
        channel = "error"
        print(f"[推送] 走 send_failure 分支（send_on_failure={cfg.send_on_failure}）")
        if not cfg.send_on_failure:
            print("❌  send_on_failure=false，已跳过")
            return 1
        if args.dry_run:
            print("  [dry-run] 不真发")
            return 0
        ok = await notifier.send_failure(date=date, error=error_msg or status)
    else:
        channel = "diary"
        if not content:
            print("❌  日记内容为空，跳过")
            return 1
        print(f"[推送] 走 send_diary 分支（{word_count} 字）")
        if args.dry_run:
            print("  [dry-run] 不真发")
            return 0
        ok = await notifier.send_diary(
            date=date, content=content, word_count=word_count, weather=weather,
        )

    print(f"[结果] send_*: {ok}")
    if ok:
        # 按频道写推送标记，模拟 scheduler 双通道行为（v1.4.0）
        state_file = base_dir / ("last_pushed_error_date.txt" if channel == "error" else "last_pushed_diary_date.txt")
        state_file.write_text(date + "\n", encoding="utf-8")
        print(f"[状态] 已更新 {state_file.name} = {date}")
    else:
        print(f"[状态] 未更新 last_pushed_{channel}_date，下次可重试")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
