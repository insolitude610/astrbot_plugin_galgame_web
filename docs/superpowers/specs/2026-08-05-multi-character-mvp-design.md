# 多角色轮流对话 + 消息编辑 MVP 设计

日期：2026-08-05
状态：已评审（五节设计逐节确认）
目标版本：v0.8.0

## 1. 背景与目标

插件（astrbot_plugin_galgame_web）当前支持单人 galgame 对话（立绘 + 情绪切换 + TTS + BGM + 会话持久化）。用户希望获得类 SillyTavern（酒馆）的体验，但表现形式保持 galgame 风格。本 MVP 实现：

1. **多角色固定循环轮流对话**：角色 1 开场白 → 用户回复 → 角色 2 接话 → 用户回复 → 依次循环（角色间不直接对话）。
2. **消息编辑三项**：重新生成最后一条 AI 回复、编辑任意消息（用户消息自动重生成、AI 消息改写历史）、删除任意消息（含其后所有）。
3. **场景随角色切换**：当前发言角色切换时，立绘/背景/BGM 随之切换（galgame 式）。
4. **人格与 AstrBot 人格系统匹配**：角色卡可绑定 AstrBot persona（自动注入 system_prompt + begin_dialogs），也可完全自定义人格 prompt（不依赖 AstrBot 人格系统），二者可叠加。

长期愿景（不在本 MVP）：自由群聊（角色间互相对话，需"导演"调度机制）、剧本演出式剧情、角色专属 TTS 音色。

## 2. 总体架构

```
现有单角色链路（保持不变）
  session → pipeline → LLM(persona) → TTS → 前端

新增多角色链路（同一管道，额外两个钩子）
  multi session ──每轮发送前──▶ update_conversation(persona_id=当前角色)
                                │ AstrBot 自动注入该角色人格
                                ▼
  pipeline → LLM(角色人格) → TTS → 响应{text, emotions, audio, next_character}
                                                        ▼
                                前端：切立绘/背景/BGM 到下一角色
```

- 所有对话仍经 webchat 管道（webchat_queue_mgr），记忆/感知/安全插件全栈生效。
- 单角色会话所有路径保持零改动（判断分支 `session.get("mode") == "multi"`）。

## 3. 数据模型

### 3.1 会话 JSON（sessions/*.json）新增字段

```json
{
  "mode": "multi",
  "characters": ["alice", "bob"],
  "next_char_idx": 1,
  "history": [{
    "id": "uuid",
    "role": "assistant",
    "character": "alice",
    "content": "...",
    "audio_file": "..."
  }]
}
```

- `mode`：`"single"`（默认，等于缺失）| `"multi"`。
- `characters`：角色 id 列表，按此顺序轮流。
- `next_char_idx`：下一位发言角色下标（发送后 `(idx+1) % len` 推进）。
- history 条目新增 `id`（uuid）与 `character` 字段。旧会话加载时惰性补生成 id（`load_session` 兼容填充）；single 会话 `character` 为空。

### 3.2 角色卡文件 characters.json（插件数据目录，原子写入）

```json
[{
  "id": "alice",
  "name": "爱丽丝",
  "persona_id": "",
  "custom_prompt": "你是爱丽丝，...",
  "expressions": {"neutral": "alice_neutral.png", "happy": "alice_happy.png"},
  "background": "bg_forest.png",
  "bgm": "bgm1.mp3",
  "opening": "你好呀，我是爱丽丝~",
  "tts_provider": ""
}]
```

- `id`：合法字符 `[a-z0-9-]`，长度限制（防路径穿越，风格同 `is_valid_session_id`），作为立绘上传前缀。
- `persona_id`：AstrBot persona id，空 = 不绑定。
- `custom_prompt`：插件级自定义人格，空 = 无。
- `expressions/background/bgm`：空 = 回退全局配置（保证单角色零改动）。
- `tts_provider`：本 MVP 不实现（共用一个 TTS），字段预留。
- 存插件自有文件（不依赖 AstrBot config 持久化——现有 `register_asset` 直接改 `self.config` 内存字典不落盘，角色卡避开此坑）。

### 3.3 人格注入逻辑（on_llm_request 钩子）

- 绑定 `persona_id` → 发送前 `update_conversation(umo, conv_id, persona_id=...)`，AstrBot 自动注入该人格（system_prompt + begin_dialogs）。
- 有 `custom_prompt` → 插件追加到 `req.system_prompt`。
- 两者都空 → 回退全局 `persona` 配置。
- multi 会话注入定位语："你正在扮演《角色名》"。

## 4. 多角色轮流机制与管道集成

### 4.1 会话生命周期

1. 前端点「多角色」→ `POST session/init {mode: "multi"}` → 服务端创建会话（`characters` 顺序、`next_char_idx=0`），返回角色列表。
2. 首条消息 = 角色 0 开场白（`opening`，无则取 persona `begin_dialogs` 尾部，再无则跳过），作为历史第一条 assistant 消息写入插件 JSON；前端展示"角色 0 登场"场景。**不走管道、不创建 AstrBot 对话**（沿用现有延迟建对话机制）。
3. 用户发消息 → 当前角色（next_char_idx）回复 → 服务端推进 `next_char_idx` → 响应带 `next_character`（下一角色名/立绘/背景/BGM）→ 前端预先切场景。

### 4.2 后端改动点

| 位置 | 改动 |
|------|------|
| `_api_send` 新子步骤 `_send_switch_persona` | 发送前：multi 会话且有 `persona_id` → `update_conversation(umo, conv_id, persona_id=...)`；首次无对话时 `init_astrbot_conv` 带 persona 建对话（不得覆盖其写入的 conv_id）。仅持 `_send_lock` 时调用 |
| `_inject_galgame_rules`（现有钩子） | multi 会话额外注入当前角色 `custom_prompt` + 角色名定位语 |
| `_do_send` 保存步骤 | history 条目带 `character`（append 时未推进，直接记 `chars[next_char_idx]`）；推进 `next_char_idx = (idx+1) % len` |
| 轮转一致性 `_send_recalc_next_char` | 编辑/删除截断后从剩余 history 最后一条 assistant 的 `character` 重算 next_char_idx（无 assistant 则重置 0），保证轮转不与历史脱节 |
| 重生成 `_api_regenerate` | 截断前记录被删 assistant 消息的 `character`，截断后设 `next_char_idx` 为该角色 → **由同一角色重新回答** |
| `_api_send` 响应 | 新增 `next_character: {name, expressions, background, bgm} \| null`（single 为 null，前端零改动） |

### 4.3 TTS

- MVP：所有角色共用当前 TTS provider（同一音色）。
- 角色卡 `tts_provider` 字段预留，后续按角色选 provider。

## 5. 消息编辑三项

### 5.1 通用基础

- history 条目带 `id`（uuid），旧会话惰性补生成。
- 同步：截断后的插件 history 经现有 `sync_conv_to_db` 写 AstrBot conversation；管道重跑时 contexts 从 conversation.history 加载，天然只见截断后历史。
- `_send_lock` 串行化防并发编辑。

### 5.2 API

| API | 行为 |
|-----|------|
| `POST session/regenerate` `{session_id}` | 仅当"最后一条是 assistant 且其前一条是 user"（否则 400）。**由被删消息的同一角色重新回答**（截断前记录其 character）：删最后一条 assistant（插件 JSON + DB 同步截断）→ 重放用户输入走管道 → 新回复 + TTS |
| `POST session/edit` `{session_id, message_id, new_text}` | 目标可为 user 或 assistant 消息。改文本 → 截断其后所有 → 同步 DB → 若目标是 user 消息则自动重走管道生成新回复；assistant 消息不自动重生成（改写历史，可继续对话或手动重生成） |
| `POST session/message-delete` `{session_id, message_id}` | 删该条及其后所有 → 同步 DB → 不自动重生成（酒馆行为） |

- message_id 不存在 → 404；越界/非法 → 400。
- 被截断旧音频经现有引用感知 GC 回收。
- 重生成/编辑后走现有 `_send_synthesize_tts` 流程。

## 6. 前端改动

### 6.1 设置页新增「角色管理」分区（settings.html/app.js）

- 角色卡片列表：名字/编辑/删除/上下移（调整轮流顺序）。
- 新建角色表单：名字、立绘槽位上传（key 前缀 = 角色 id，如 `alice_neutral.png`，复用 upload-key）、背景、BGM、开场白、绑定 AstrBot persona（下拉，从新 API 拉取 persona 列表）、自定义人格 prompt 文本框。
- 保存 → `POST /characters`。

### 6.2 主页面多角色会话（app.js）

- 会话面板加「多角色」按钮（characters ≥ 2 时显示）→ 创建 multi 会话。
- 会话条目显示 mode 徽标（"群聊"）。
- 当前角色指示：对话框顶部角色名区域显示当前发言角色，立绘切换为其表情图。
- 新增 `setActiveCharacter(char)` 集中切换立绘源/背景/BGM（复用 applyBackground/_setBgmSrc/expressions 机制）。
- 响应 `next_character` → 预先切换场景。

### 6.3 消息操作 UI

- AI 消息 hover：「🔄 重生成」（仅最后一条生效）、「🗑 删除」；用户消息 hover：「✏ 编辑」「🗑 删除」。
- 编辑态：用户消息行内输入框；AI 消息 textarea；确认/取消。
- 删除/编辑后从服务端重拉 history 渲染（复用 toggleHistory）。
- 重生成/编辑期间显示"重新思考中…"并禁用输入。

### 6.4 兼容

- 独立 WebUI 与 Dashboard 内嵌页共用同一份 app.js/settings（现有 IS_DASHBOARD() 模式），改动天然双端生效。

## 7. 新增 API 汇总

| 方法 | 路由 | 说明 |
|------|------|------|
| GET | `/characters` | 读取角色列表 |
| POST | `/characters` | 保存角色列表（校验后整体原子写） |
| GET | `/personas` | AstrBot persona 列表（角色卡绑定用） |
| POST | `/session/init` | 新增 `mode` 参数（"multi"） |
| POST | `/session/regenerate` | 重生成最后一条 AI 回复 |
| POST | `/session/edit` | 编辑任意消息 |
| POST | `/session/message-delete` | 删除任意消息（含其后） |
| POST | `/session/delete` | 已有（整会话删除，不动） |

## 8. 测试策略

扩展现有 pytest mock 体系（conftest 已具备模拟 astrbot 模块能力）：

1. **轮流逻辑**：next_char_idx 推进、循环回绕、开场白初始化（mock 管道）。
2. **消息编辑**：regenerate 截断+重放、edit 用户/AI 消息两条路径、message-delete、旧会话无 id 惰性补生成、非法 message_id/越界 400/404。
3. **角色配置**：characters.json 读写、原子写、id 合法性校验（防路径穿越）、persona 绑定解析。
4. **兼容回归**：单角色会话所有路径不变（现有 64 测试全绿为基线）。
5. **前端**：node --check + 手动验证清单（立绘切换、双端、编辑流）。

## 9. 已知限制（写入 README）

- 切换人格后旧人格痕迹残留上下文历史（AstrBot 机制限制）。
- 角色间不直接对话（后续版本做"导演"调度）。
- 多角色共用同一 TTS 音色（角色卡留 tts_provider 字段，后续支持）。
- 编辑 AI 消息不自动重生成。

## 10. 实施顺序

1. 后端：characters API + personas API + 会话 mode/角色字段（含 load_session 兼容）。
2. 后端：管道集成（persona 切换、custom_prompt 注入、next_character 响应、轮流推进）。
3. 后端：regenerate/edit/message-delete + DB 同步。
4. 前端：设置页角色管理。
5. 前端：主页面多角色场景切换 + 消息操作 UI。
6. 测试 + README + CHANGELOG + 版本号 v0.8.0。

## 11. 前置已完成事项（v0.7.14 → 0.8.0 之间）

- 64 项测试全绿基线确认。
- ruff 17 项修复 + 格式化（7 文件）。
- 高风险缺陷修复：scheduleExpressionTimers NaN duration 保护（app.js:91）、loadExpressionToSingle onerror 兜底（app.js:713）、session.py 日志文案 120s→300s。
