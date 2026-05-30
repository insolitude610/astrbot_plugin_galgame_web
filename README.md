# AI Galgame 虚拟伙伴

> ⚠️ **注意：本插件不建议和消息合并/防抖插件一同使用！！！会产生莫名其妙的 bug！！！**
>
> ⚠️ **注意：本插件不建议和消息合并/防抖插件一同使用！！！会产生莫名其妙的 bug！！！**
>
> ⚠️ **注意：本插件不建议和消息合并/防抖插件一同使用！！！会产生莫名其妙的 bug！！！**
>
> 如已安装 `astrbot_plugin_combine_messages` 等消息合并/防抖类插件，请在 AstrBot WebUI 的自定义规则中，为 Galgame 的 webchat 会话禁用该类插件。

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，通过独立本地端口提供 Galgame 风格的 AI 虚拟伙伴 WebUI。支持双图交叉渐变表情切换、打字机动画、TTS 语音朗读、语音输入、会话恢复、对话历史等交互特性。

> **注意**：和 webchat 平台一致，但本插件的 Web 对话 bot 暂不支持发送文件和图片（待开发）。~谁家galgame角色能给你发图片和文件啊（）~

## ⚠️ 当前状态

| 渲染模式 | 状态 | 说明 |
|---------|:----:|------|
| **Single（双图交叉渐变）** | ✅ 可用 | 每情绪一张完整 PNG 立绘，稳定推荐 |
| **VRM（3D 模型）** | 🚧 开发中 | 功能尚未完善，暂不可用 |

> **请使用 `single` 模式。** VRM 模式的 Three.js + three-vrm 集成仍在开发中，可能存在渲染异常、模型加载失败等问题。

---

## 快速开始

### 安装

1. 在 AstrBot WebUI 中打开**插件市场**
2. 搜索 `astrbot_plugin_galgame_web` 并安装
3. 启用插件

### 最小配置

在插件详情页设置以下三项即可开始使用：

| 配置项 | 说明 |
|--------|------|
| 角色显示名 | 对话框上方显示的名称 |
| 角色人格 | 选择 AstrBot 已配置的 Persona |
| LLM Provider | 驱动对话的 AI 模型（deepseek / gpt-4o 等） |

其他配置项（立绘、背景、端口等）保持默认即可，详见下方配置表。

### 打开界面

插件启动后会自动在本机启动 HTTP 服务器（默认端口 **6186**），浏览器访问：

```
http://localhost:6186
```

也可以在任意接入 AstrBot 的消息平台发送 `/galgame`，Bot 会回复访问地址。

> **说明**：WebUI 通过独立端口访问，不在 AstrBot Dashboard 内嵌显示。端口可在插件配置中修改（设为 `0` 关闭服务器）。

打开后在输入框输入文字即可对话，点击输入框左侧麦克风按钮可语音输入。

---

## 配置项速查

| 配置项 | 说明 | 推荐值 |
|--------|------|--------|
| `character_name` | 对话框上方显示的角色名 | 你的角色名 |
| `persona` | AstrBot 内置人格 | AstrBot 预设 |
| `llm_provider` | 驱动对话的 AI 模型 | deepseek / gpt |
| `tts_provider` | 语音合成提供商 | 选择已配置的 TTS Provider，配合 TTS 插件使用 |
| `web_port` | 独立 WebUI 端口 | 默认 `6186`，`0` = 关闭 |
| `sprite_mode` | 立绘渲染模式 | **`single`**（推荐，VRM 尚不可用） |
| `sprite_scale` | 立绘整体缩放倍数 | 默认 `1.0`，建议 0.5 ~ 2.0 |
| `sprite_bottom` | 立绘距底部距离 (vh) | 默认 `28`，建议 5 ~ 45 |
| `sprite_left` | 立绘水平锚点 (%) | 默认 `50`（居中） |
| `typewriter_speed` | 打字机速度 (ms/字) | 默认 `60`，越小越快，建议 10~200 |
| `history_avatar` | 历史记录头像 | 立绘管理页直接上传设置，留空则不显示 |
| `tts_emotion_map` | 立绘情绪→TTS情绪映射 (JSON) | 例：`{"blush":"shy","thinking":"contemplative"}`，留空直接用标签本名 |
| `background` | 场景背景图 | 留空自动匹配 |
| `expressions` | 各情绪对应立绘文件名 | 留空自动匹配 |
| `custom_emotions` | 自定义额外情绪标签 (JSON) | 例：`{"dokidoki": ""}` |
| `session_retain_days` | 会话保留天数 | 默认 `7`，`0` = 永不清理 |
| `rapid_click_threshold` | 快速点击检测阈值（次） | 默认 `5` |
| `rapid_window_seconds` | 快速点击检测窗口（秒） | 默认 `3` |

> **关于立绘/背景配置项**：所有素材字段均支持「留空 = 自动匹配」，按[文件命名约定](#文件命名约定)将 PNG 放入 `assets/` 目录，或通过[立绘管理页面](#立绘管理页面)上传即可，无需手动逐个填写。

---

## 功能详情

### 核心交互

- **AI 驱动表情切换** —— LLM 回复中插入 `{emotion_happy}` 等标签，前端实时切换角色表情
- **打字机效果** —— 回复文字逐字显示（60ms/字），表情随文字进度同步切换
- **TTS 分段情感语音** —— 按 LLM 输出的 `{emotion_xxx}` 标签边界自动分段，每段文本前拼接 Fish Audio 方括号标签 `[xxx]`，逐段调用 AstrBot TTS provider 独立合成不同情绪语音，前端打字机播放时语音与立绘同步切换
- **语音输入** —— 浏览器麦克风录音 → WAV → AstrBot STT 管道自动转文字
- **快速点击检测** —— 用户频繁点击/按键时，AI 主动关心
- **点击快进** — 打字机播放中点击对话框，文字快速弹入显示并切到最终表情，还原 galgame 手感
- **轻戳互动** — 空闲时点击角色区域可触发 AI 主动对话
- **对话历史面板** —— 顶部时钟图标进入，气泡式展示历史消息，背景色自动适配角色立绘。支持 AI 消息头像显示、历史语音回放
- **AstrBot 指令兼容** —— 在输入框直接使用 `/reset`、`/new` 等指令，经管道分发执行
- **重播按钮** —— 对话框右上角重播按钮，可重放上次 AI 回复的完整打字机 + 表情切换动画 + TTS 语音
- **语音收藏** —— 顶部 ❤ 图标进入收藏页面，可收藏喜欢的语音片段，数据持久化不随 /reset 丢失

### 平台集成

- **复用 AstrBot 人格系统** —— 直接选择已配置的 Persona，无需重复设定角色性格
- **全管道集成** —— 所有消息经 webchat 管道分发，记忆/感知/安全等插件全栈生效
- **会话双向同步** —— 对话历史同时保存到磁盘 JSON 文件 + AstrBot 数据库，Dashboard 对话管理可查看/导出
- **JWT 代理认证** —— API 请求自动携带 JWT Bearer 令牌，与 AstrBot Core 安全通信
- **资产迁移机制** —— 插件升级时自动搬迁 `assets/` 至 `data/plugin_data/`，升级不丢素材

### 素材管理

- **立绘管理页面** —— 首页右上角齿轮 ⚙ 图标进入，支持拖拽上传、预览、删除
- **槽位自动重命名** —— 从表情槽位上传的文件自动改名为标准文件名
- **批量删除** —— 多选文件一键批量删除
- **位置可调** —— 立绘缩放比例、底部距离、水平位置均可配置

---

## 立绘与渲染模式

### Single 模式（推荐）

**原理**：每个情绪对应一张完整的半身角色 PNG，情绪切换时直接交叉渐变替换。

**素材要求**：每种情绪一张完整半身立绘（身体+头+衣服+头发全在一张图）。至少准备 `neutral` 表情图，其他情绪缺省时回落此图。

| 表情 | 推荐文件名 | 触发场景 |
|------|-----------|---------|
| neutral | `single_neutral.png` | 日常对话（**必须**，缺省回落图） |
| happy | `single_happy.png` | 用户夸奖、好消息 |
| sad | `single_sad.png` | 用户诉苦、坏消息 |
| angry | `single_angry.png` | 用户不礼貌、冲突 |
| surprised | `single_surprised.png` | 突然的信息、意外 |
| blush | `single_blush.png` | 用户调侃、暧昧 |
| thinking | `single_thinking.png` | 被问到难题、认真思考 |

**视觉效果**：角色整体缓慢上下浮动（CSS 呼吸动画），表情切换时 0.6s 交叉渐变过渡。

### VRM 模式（🚧 开发中）

> **VRM 模式目前尚未完善，暂不可用。以下为规划特性。**

原理：上传 `.vrm` 3D 模型文件，Three.js + three-vrm 在浏览器实时渲染 3D 动漫角色。

规划特性：
- 自动眨眼（VRM 原生 autoBlink）
- 视线跟踪（眼睛跟随鼠标位置）
- Blend shape 表情切换
- 骨骼呼吸微动
- 3D 旋转拖拽

模型来源：[VRoid Studio](https://vroid.com/en/studio) 免费捏脸导出，或 [VRoid Hub](https://hub.vroid.com/) 下载现成模型。

---

## 情绪与表情系统

### 工作原理

插件后端在 system prompt 中要求 AI 在回复中插入情绪标签，格式固定为 `{emotion_xxx}`：

```
{emotion_happy}今天天气真好！{emotion_blush}谢谢主人~
```

- ✅ 正确：`{emotion_happy}文字内容`
- ❌ 错误：`{happy}文字`（缺少 `emotion_` 前缀）
- ❌ 错误：`文字(开心)`（不能用括号写法）

后端解析标签后，将纯文本和情绪序列一并返回前端，前端在打字机动画中随文字进度实时切换立绘。

### 默认情绪标签

| 标签 | 含义 | 典型触发 |
|------|------|---------|
| `{emotion_neutral}` | 普通 | 日常对话 |
| `{emotion_happy}` | 开心 | 好消息、夸奖 |
| `{emotion_sad}` | 悲伤 | 坏消息、诉苦 |
| `{emotion_angry}` | 生气 | 冲突、不礼貌 |
| `{emotion_surprised}` | 惊讶 | 意外信息 |
| `{emotion_blush}` | 害羞 | 调侃、暧昧 |
| `{emotion_thinking}` | 思考 | 难题、认真想 |

### 自定义情绪

在插件配置页的 **「自定义情绪」** 字段中写入 JSON 添加额外情绪：

```json
{"dokidoki": "dokidoki.png", "cry": "", "smirk": "smirk.png"}
```

- **key**：情绪标签名，AI 会使用 `{emotion_key}` 标记
- **value**：`assets/` 下的文件名（留空自动匹配 `key.png`）

后端自动合并默认 7 种 + 自定义情绪，system prompt 会列出全部可用标签。注意：新增情绪后需上传对应的表情图。

---

## 立绘管理页面

Galgame 主页面右上角点击齿轮 ⚙ 图标进入。

**功能：**
- **拖拽上传** —— PNG 图片拖入页面即可上传到 `assets/`
- **按模式分区** —— 页面显示当前模式需要的文件清单，每个槽位独立操作
- **自动重命名** —— 从槽位上传的文件自动改名为标准文件名
- **文件网格** —— 浏览、预览、删除所有已上传文件
- **批量操作** —— 多选文件一键删除

### 文件命名约定

上传到 `assets/` 后，按文件名子串匹配自动关联到对应配置项：

| 配置项 | 推荐文件名 | 匹配关键字 |
|--------|-----------|----------|
| neutral | `single_neutral.png` | `neutral` |
| happy | `single_happy.png` | `happy` |
| sad | `single_sad.png` | `sad` |
| angry | `single_angry.png` | `angry` |
| surprised | `single_surprised.png` | `surprised` |
| blush | `single_blush.png` | `blush` |
| thinking | `single_thinking.png` | `thinking` |
| background | `bg_background.png` | `background` 或 `bg` |

---

## 会话持久化

对话历史保存到 `data/plugin_data/astrbot_plugin_galgame_web/sessions/`。浏览器 `localStorage` 记录 `session_id`，下次打开页面自动恢复。

### 会话丢失场景

| 情况 | 是否丢失 | 原因 |
|------|:--:|------|
| 重载/重启 AstrBot | 否 | 从磁盘恢复 |
| 插件升级/重装 | 否 | 会话文件不受影响 |
| 关闭浏览器再打开 | 否 | localStorage 记录 session_id |
| 超过保留天数未活跃 | **是** | GC 自动清理（默认 7 天） |
| 手动删除 `sessions/` | **是** | 物理删除 |
| 更换浏览器 | **是** | localStorage 不共享 |
| 无痕/隐私模式 | **是** | localStorage 不持久化 |
| 换电脑/设备 | **是** | 无跨设备同步 |

> 将会话保留天数设为 `0` 则永不清理。同时注意 AstrBot Dashboard 对话管理中也可查看/导出 Galgame 对话记录。


---

## API 响应格式

`POST /api/plug/astrbot_plugin_galgame_web/send` 返回：

```json
{
  "reply": "AI 回复文本（已去除情绪标签）",
  "emotion": "happy",
  "emotions": [["neutral", 0], ["happy", 8], ["blush", 18]],
  "audio": "（pipeline 管道 TTS 音频 base64，有分段时置空）",
  "audio_segments": [
    {"b64": "...", "mime": "audio/wav", "char_pos": 0},
    {"b64": "...", "mime": "audio/wav", "char_pos": 8}
  ]
}
```

前端收到后执行打字机动画显示 `reply`，根据 `emotions` 序列在指定位置切换立绘，`audio_segments` 逐段播放 Fish Audio 情感语音。

---

## 技术架构

```
浏览器 (http://localhost:6186)
  ├─ 静态文件 → 插件内置 HTTP Server (ThreadingHTTPServer)
  └─ /api/* → JWT 代理至 AstrBot Core (Quart :6185) → webchat 管道
```

- **前端**: 原生 HTML/CSS/JS；Single 模式 CSS DOM 双图交叉渐变
- **后端**: Python `http.server` + AstrBot Star API
- **通信**: `fetch()` 同步请求/响应，JWT Bearer 认证代理
- **管道**: 所有对话经 webchat 管道分发，接入记忆/感知/安全等全插件栈

---

---

## 已知限制

- **TTS 情绪标签**：WebUI 聊天的 TTS 绕过了 AstrBot pipeline 直接调用 provider，因此其他插件的文本处理钩子（如 meme_manager 的方括号过滤）不会影响 Fish Audio 情感标签。`{emotion_xxx}` 标签在 pipeline 处理阶段由 `_handle_emotion_strip` 剥离，不影响消息显示。
- **不支持发送文件/图片**：Web 对话 bot 暂不支持 AI 发送图片或文件（待开发）。
- **VRM 3D 模式**：尚未完善，暂不可用。

## 许可证

MIT

---

**相关项目：**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
