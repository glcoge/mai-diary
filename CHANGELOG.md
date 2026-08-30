# Changelog

## 1.3.0 - 2026-08-30

### 剧本人设系统适配（mai-diary ↔ glcoge.mai-narrative 握手）

- **人格来源会话分诊**：`DiaryPipeline._resolve_personality` 增加剧本人设「会话分诊」。
  若时间窗内存在剧本模式会话（`mode_user_ids` 私聊白名单或 `mode_stream_ids` 显式白名单），
  日记作者人格改从剧本「自我层」读取（锚定 `identity.name/creature/world` +
  `immutable_traits` 表达风格），避免「聊天里是剧本人格、日记里是默认人格」的割裂；
  否则沿用主程序全局 `personality.*` 旧逻辑，兼容不变。
- **自我层当日状态注入 prompt**：剧本路径时把自我层心情/精力/作息注入日记 prompt
  （`narrative_status`），让日记口吻与当日剧本人设一致。
  `today_mood_track`（每日情绪轨迹）为 Round 3 预留字段，当前返回空并打 TODO。
- **编年史写入（幂等）**：日记成功落盘后，把成品追加到自我层编年史（`scope=self, kind=diary`）；
  同一天重跑不重复写（写入判重），关掉 `narrative.chronicle_enabled` 或 narrative 未启用时自动跳过。
- **握手降级**：narrative 插件未加载 / 未启用 / 跨插件调用失败 → 全部降级回旧逻辑，
  不阻塞日记生成与 ntfy 推送；新增 `[narrative]` 配置段（`enabled` / `api_timeout_seconds`）。
- **接口稳定**：`/diary` 命令、`generate_diary_api`、`data/diary/{markdown,json}` 输出与路径约定
  均未改动；manifest 新增 `api.call` / `api.list` capability。

### 开发

- 新增 `services/diary/narrative_bridge.py`（NarrativeBridge：可用性探测 + 会话分诊 + 编年史写入手）。
- `services/diary/prompts.py` 的 `build_diary_prompt` / `build_brief_prompt` 新增可选参数
  `narrative_status`（自定义模板支持 `{narrative_status}` 占位符，缺失自动空串）。
- `pytests/test_diary.py` 新增 9 个用例：会话分诊静态判定、剧本模式人格替换、
  无模式会话沿用全局人格、联动关闭不握手、narrative 不可用降级、编年史幂等（narrative store 层 +
  bridge 透传层）、`_build_narrative_status` 组装（45 个测试全通过）。

## 1.2.0 - 2026-07-30

### 用户感知功能

- **新增 ntfy 推送（opt-in）**：每天 08:00（可配 `schedule.push_time`）自动将昨日日记正文通过 ntfy.sh 或自建 ntfy 服务器推送到手机。
  - 默认 `enabled = false`，需用户显式开启并配置 `topic`。
  - 通知内容：标题 `新日记  YYYY-MM-DD`，正文 = 完整日记 + `—— mai-diary • 字数` 尾巴。
  - 失败通知（`status` 以"报错"开头）也按 `send_on_failure` 决定是否推送，标题前缀 `❌`。
  - 公共 ntfy.sh 有 4KB 总请求大小限制；超出按句末截断并附"已截断"提示。
  - 边界：启用后日记正文会离开本机，请确认接受此边界破坏。

### 关键 Bug 修复（UTF-8 header）

- 修复 NtfyNotifier 在发送中文 Title / emoji Tags 时抛 `UnicodeEncodeError: 'latin-1'` 的问题。原因是 stdlib `urllib.request` / `http.client` 的 `putheader` 默认用 latin-1 编码 header value，无法承载非 ASCII。改用 `http.client` + 自定义 `_Utf8HTTP(S)Connection` 子类（旁路 putheader 的编码逻辑）实现纯 stdlib 方案，**零新依赖**。
- 新增 `scripts/e2e_test_ntfy.py` 端到端冒烟测试脚本（无需 SDK / MaiBot 运行）。

### 时间调度重构

- `schedule` 新增 `push_time`（默认 `08:00`），与 `generate_time`（默认 `04:00`）解耦。
- 调度循环现在同时跟踪"下一次生成"与"下一次推送"两个时间点，取较早的唤醒。
- 启动补跑逻辑扩展：若已过 `generate_time` 且未生成 → 补生成；若已过 `push_time` 且昨日日记未推送 → 补推送。
- `last_pushed_date.txt` 持久化防重推送，进程重启安全。
- 手动 `/diary gen` **不**触发立即推送（避免一天内多次打扰），会在下一次 `push_time` 统一推送。

### 命令与状态

- `/diary status` 新增显示：`push_time`、`last_pushed_date`、`next_push_at`、`ntfy_configured`。

### 开发

- 新增 `services/diary/ntfy_notifier.py`（NtfyNotifier）。
- `DiaryStorage` 新增 `read_last_pushed_date` / `write_last_pushed_date`。
- `DiaryScheduler` 重写：双时间点 loop、`_push_safe`、`_has_unpushed_yesterday` 判定。
- 配置文件 `config.toml` 新增 `[ntfy]` 默认段（全部默认/关闭）。
- `pytests/test_diary.py` 新增 14 个 ntfy_notifier / push 状态的单测（37 个测试全通过）。

## 1.1.0 - 2026-07-27

### ⚠️ 严格本地留存（breaking 变更）

按用户约束加固边界，**任何命令 / Tool / API 都不再回传日记正文**。

- 删除 `@Tool("query_diary")`
- 删除 `@API("get_diary_api")`
- `/diary gen`：从「回显前 800 字正文」改为「字数 + 文件路径」
- `/diary v`：从「回显正文」改为「字数 + 文件路径」
- `/diary ls`：每行追加 markdown 文件路径
- `@API("generate_diary_api")`：返回值去掉 `content`，新增 `file_path_markdown` / `file_path_json` / `status`

要阅读日记，必须直接打开本地 `data/diary/markdown/YYYY-MM-DD.md`。

## 1.0.0 - 2026-07-27

### 功能

- 每天 04:00 自动总结上一日 04:00 – 今日 04:00 的聊天记录
- 落盘 `data/diary/markdown/YYYY-MM-DD.md`（仅本地留存）
- 落盘 `data/diary/json/YYYY-MM-DD_HHMMSS.json`（结构化）
- `/diary help|gen|ls|v|status` 命令（需 admin_qq 白名单）
- `query_diary` Tool（让 LLM 主动查询日记）  ← 1.1.0 已删除
- `generate_diary_api` / `get_diary_api` 跨插件 API  ← 1.1.0 get_diary_api 已删除，generate_diary_api 改为只返元信息
- 启动时若 last_diary_date < 昨天且已过 trigger 时间，自动补一次

### 开发

- 使用 `maibot-plugin-sdk>=2.7.0` 的 `@Command` / `@Tool` / `@API`
- 全部配置走 Pydantic `PluginConfigBase` 段式定义
- LLM 限制（`truncate_tokens` / `timeout_seconds`）可配
- 包含 `pytests/test_diary.py` 单元测试
