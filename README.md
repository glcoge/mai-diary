# mai-diary

> MaiBot 第三方插件。每天 **04:00 自动总结** 上一日 04:00 至今日 04:00 的聊天记录，**08:00 通过 ntfy 推送** 至手机，同时落盘本地日记（Markdown + JSON）。

## 重要：边界约束

**日记正文只以本地文件形式留存，不会通过任何命令 / Tool / API 回传。**

若需阅读，请直接打开：

```
plugins/glcoge-mai-diary/data/diary/markdown/YYYY-MM-DD.md
```

命令与跨插件 API **只**返回元信息（日期 / 字数 / 状态 / 文件路径）。本插件**不**提供：
- `query_diary` Tool（已删除）
- `get_diary_api` 跨插件 API（已删除）
- `/diary v` 的正文回显（改为只回元信息）

**ntfy 推送（v1.2.0+）是一个 opt-in 例外**：用户**明确**将 `[ntfy].enabled` 设为 `true` 后，日记正文才会经 ntfy 服务器到达手机。请在启用前确认接受此边界破坏，详见 [ntfy 推送](#ntfy-推送) 章节。

## 功能

- 每天 **04:00** 自动生成昨日日记（可配 `schedule.generate_time`）
- 抓取昨日 04:00 – 今日 04:00 的聊天记录
- 按时间线整理，注入 LLM 生成日记
- 落盘两份：
  - `data/diary/markdown/YYYY-MM-DD.md`（**仅本地留存**，不通过任何接口输出）
  - `data/diary/json/YYYY-MM-DD_HHMMSS.json`（结构化记录）
- 生成失败时：`error_message` 记一行短原因（用于 ntfy 推送），**完整报错**
  （含异常堆栈 + 模型名 / 超时 / prompt 长度）追加到
  `data/diary/errors/YYYY-MM-DD.log`，同一天多次失败追加不覆盖
- 每天 **08:00** 通过 ntfy 推送至手机（可配 `schedule.push_time`，可关闭）
- 提供命令：`/diary help|gen|push|ls|v|status`（仅返回元信息；需在 `admin_qq` 白名单中）
- 提供 API：`generate_diary_api`（仅返回元信息；不含 content）

## 安装

1. 把整个 `glcoge-mai-diary` 目录放到 MaiBot 的 `plugins/` 下。
2. 启动 MaiBot，插件会自动加载并在 `data/diary/` 下创建文件。
3. （可选）编辑 `config.toml` 的 `[ntfy]` 段，启用 ntfy 推送。

## 配置示例

```toml
[plugin]
enabled = true
admin_qq = ["123456"]

[schedule]
generate_time = "04:00"
push_time = "08:00"
check_interval_seconds = 60
timezone_offset_hours = 8
persist_state = true

[message]
filter_mode = "all"           # all / whitelist / blacklist
target_chats = ""             # 例: "group:123456\nprivate:789012"
min_message_count = 5
per_message_max_chars = 200

[summary]
min_word_count = 250
max_word_count = 400
style = "diary"               # diary / brief / custom
self_description = ""

[llm]
text_model = "replyer"
temperature = 0.7
truncate_tokens = 50000       # 超过该 token 数会按句末截断
timeout_seconds = 60          # 单次 LLM 调用超时

[output]
base_dir = "data/diary"
write_markdown = true
write_json = true

[ntfy]
enabled = false               # 默认关闭
server = "https://ntfy.sh"
topic = ""                    # 必填
auth_token = ""
priority = "default"
tags = ["diary", "📔"]
title_template = "新日记  {date}"
failure_title_template = "❌ 日记生成失败  {date}"
body_footer_template = "\n\n—— mai-diary • {word_count}字"
max_body_chars = 2000
truncate_suffix = "\n\n…（已截断，全文见本地文件）"
click_action = ""
send_on_failure = true
timeout_seconds = 10

[retry]
enabled = true                # 失败延迟重试总开关
max_attempts = 3              # 重试次数上限（不含首次尝试）
base_delay_minutes = 10       # 首次重试延迟，指数退避：10 / 20 / 40 …
max_delay_minutes = 120       # 单次重试延迟上限
```

## 时间窗说明

- **生成触发**：每日 `schedule.generate_time`（默认 04:00）
- **推送触发**：每日 `schedule.push_time`（默认 08:00），仅当 [ntfy] 启用且昨日日记存在时触发
- **窗口**：`[昨日 04:00, 今日 04:00)`，24 小时滚动
- **日记日期**：归到**昨天**

示例：2026-07-28 04:00 触发 → 抓取 2026-07-27 04:00 – 2026-07-28 04:00 的消息 → 写入 `2026-07-27.md` / `2026-07-27_*.json` → 2026-07-28 08:00 推送 `2026-07-27` 的日记。

## 命令一览（**仅返回元信息**）

| 命令 | 说明 |
|------|------|
| `/diary help` | 查看帮助 |
| `/diary gen [日期]` | 手动触发生成（默认昨天），返回字数 + 文件路径。**不**触发立即推送；将在下一次 `push_time` 统一推送 |
| `/diary push [日期]` | 手动把指定日期（默认昨天）的日记推送到 ntfy，绕过每日限流（仍写推送状态） |
| `/diary ls` | 列出最近 10 篇（日期 / 字数 / 状态 / 文件路径） |
| `/diary v [日期] [编号]` | 返回该日日记的元信息 + 文件路径（**不**回显正文） |
| `/diary status` | 调度器状态、生成/推送时间、上次生成、双频道上次推送、重试状态、下次触发时间、ntfy 状态 |

`/diary` 系列命令要求发送者在 `[plugin].admin_qq` 白名单内。

## 跨插件 API

| API | 描述 | 返回字段 |
|-----|------|----------|
| `generate_diary_api` | 触发指定日期的日记生成 | `ok`, `date`, `word_count`, `status`, `file_path_markdown`, `file_path_json` |

调用示例（其他插件）：

```python
result = await ctx.api.call(
    "glcoge.mai-diary.generate_diary_api",
    date="2026-07-26",
)
# result = {"ok": True, "date": "2026-07-26", "word_count": 312,
#           "status": "生成成功",
#           "file_path_markdown": "data/diary/markdown/2026-07-26.md",
#           "file_path_json": "data/diary/json/2026-07-26_*.json"}
```

调用方拿到 `file_path_*` 后若要阅读正文，**必须**自己读本地文件，不应通过本插件获取。

## ntfy 推送

每天 `schedule.push_time`（默认 08:00），插件会从本地 storage 读取"昨天"日期的日记，POST 到 ntfy 服务器，手机端 ntfy app 订阅对应 topic 即可收到通知。

### 启用步骤

1. 手机安装 ntfy app（[Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347)）
2. 在 app 中订阅一个 topic，建议使用**随机字符串**（如 `mai-diary-xxxx-xxxx`）
3. 编辑 `config.toml`：

   ```toml
   [ntfy]
   enabled = true
   topic = "mai-diary-xxxx-xxxx"     # 与手机订阅一致
   ```
4. 重启 MaiBot 或等待 `on_config_update` 热重载

### 通知内容

**成功**（默认模板）：
- 标题：`新日记  2026-07-27`
- 正文：完整日记正文 + `\n\n—— mai-diary • 312字`

**失败**（默认模板）：
- 标题：`❌ 日记生成失败  2026-07-27`
- 正文：`日记生成失败：<错误信息>\n\n可执行 /diary gen 2026-07-27 手动重试。\n\n—— mai-diary`

### ⚠️ 隐私警告

- **公共 ntfy.sh**：topic 名 = 密码。任何知道 topic 的人都能订阅并接收你的日记。务必使用随机字符串 topic，不要用 `mai-diary` 这种易猜的名字。
- **公共 ntfy.sh 的 4KB 限制**：单次请求总大小上限约 4KB（包含 headers + body）。中文 UTF-8 占 3 字节。`max_body_chars = 2000` 是较保守的默认值；超过会自动按句末截断。
- **自建 ntfy**：无大小限制，且不经第三方服务器。推荐对隐私敏感的用户使用。配置 `server = "https://ntfy.yourdomain.com"` 与 `auth_token = "..."`。
- **失败重试**：HTTP 错误（含 413）只 warn，不重试；下一次 `push_time` 会自动重试（若 last_pushed_date 仍未写入）。
- **手动 `/diary gen`**：不会立即推送；将在下一次 `push_time` 统一推送（避免一天内多次打扰）。

### 模板占位符

`title_template` / `failure_title_template` / `body_footer_template` 支持的占位符：

| 占位符 | 说明 |
|---|---|
| `{date}` | 日记日期 YYYY-MM-DD |
| `{word_count}` | 日记字数 |
| `{weather}` | 推断的天气（晴 / 多云 / 阴 / 雨…） |
| `{error}` | 失败信息（仅 `failure_title_template`） |

## 落盘示例

`data/diary/markdown/2026-07-27.md`：

```markdown
# 2026-07-27 日记

[日记正文]

---

*由 mai-diary 插件于 2026-07-28 04:00:12 生成*
```

`data/diary/json/2026-07-27_040012.json`：

```json
{
  "date": "2026-07-27",
  "diary_content": "...",
  "word_count": 312,
  "generation_time": 1690420812.0,
  "weather": "多云转晴",
  "bot_messages": 48,
  "user_messages": 84,
  "window_start": 1690387200.0,
  "window_end": 1690473600.0,
  "style": "diary",
  "status": "生成成功",
  "error_message": ""
}
```

## 开发与测试

详见 `pytests/test_diary.py`，包含：

- `test_parse_target_chats`：白/黑名单解析
- `test_timeline_build`：消息 → 时间线文本
- `test_smart_truncate` / `test_truncate_by_tokens`：截断
- `test_storage_roundtrip`：写盘 → 读盘
- `test_diary_window_for_date`：时间窗计算
- `test_storage_last_diary_date`：防重复状态

## 边界与已知限制

- **.md 文件只本地留存**，本插件不提供任何回传正文的接口。阅读请直接打开文件。
- **ntfy 推送是 opt-in 例外**：启用 `[ntfy]` 后日记正文会离开本机，请确认接受。
- LLM 30s 硬上限（host RPC 桥接层）仍然存在；若 LLM 经常超时，把 `llm.timeout_seconds` 调小并把 `llm.truncate_tokens` 调小。
- 多实例部署需要自行加文件锁（当前仅做进程内 `asyncio.Lock` + 持久化日期）。
- 插件仅做文件存储，不写主程序数据库，卸载后可直接删除 `data/diary/` 目录。

## 许可

MIT
