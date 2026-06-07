[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，通过独立本地端口和 Dashboard 内嵌页提供 Galgame 风格的 AI 虚拟伙伴 WebUI。支持双图交叉渐变表情切换、打字机动画、Fish Audio 情感 TTS 语音朗读、语音输入、BGM 背景音乐、会话恢复、对话历史、语音收藏等交互特性。

> **注意**：和 webchat 平台一致，但本插件的 Web 对话 bot 暂不支持发送文件和图片（待开发）。~谁家galgame角色能给你发图片和文件啊（）~

## ⚠️ 当前状态

| 渲染模式 | 状态 | 说明 |
|---------|:----:|------|
| **Single（双图交叉渐变）** | ✅ 可用 | 每情绪一张完整 PNG 立绘，稳定推荐 |
| **VRM（3D 模型）** | 🚧 开发中 | 功能尚未完善，暂不可用 |

> **请使用 `single` 模式。** VRM 模式的 Three.js + three-vrm 集成仍在开发中，可能存在渲染异常、模型加载失败等问题。


## 效果展示

> 对话页面
> <img width="2870" height="1487" alt="image" src="https://github.com/user-attachments/assets/53f9aba9-e3ba-4599-9193-326f00a42a86" />
> 历史记录
> <img width="2880" height="1492" alt="image" src="https://github.com/user-attachments/assets/2c95e452-3624-4d5c-ad57-8babab4c5eb3" />
> 语音收藏
> <img width="2880" height="1489" alt="image" src="https://github.com/user-attachments/assets/ad57aea8-8766-46c8-a844-4d99f8902552" />
> 立绘管理/设置
> <img width="2841" height="1485" alt="image" src="https://github.com/user-attachments/assets/eb35bb37-a5a0-40ff-a995-b2cbf785678d" />
> 会话记录
> <img width="2879" height="1476" alt="image" src="https://github.com/user-attachments/assets/a731d289-5c67-44fb-bcf0-ac18391bde58" />

# 立绘需要自己做哦，可以直接AI生图或者从什么galgame里拉出来立绘

---

## 快速开始

### 安装

1. 在 AstrBot WebUI 中打开**插件市场**
2. 搜索 `astrbot_plugin_galgame_web` 并安装
3. 启用插件

### 打开界面

有两种访问方式：

1. **Dashboard 内嵌页**（推荐）：插件市场 → 点击 "AI Galgame 虚拟伙伴" 卡片 → 顶部 tab 切换「galgame」/「settings」/「voice-favorites」
2. **独立 WebUI 端口**：插件启动后自动在本机启动 HTTP 服务器（默认端口 **6186**），浏览器访问：

```
http://localhost:6186
```

也可在任意接入 AstrBot 的消息平台发送 `/galgame`，Bot 回复访问地址。

> **说明**：独立端口可通过 `web_enabled` 配置关闭；开启时可设 `web_password` 密码保护。Dashboard 内嵌页不受密码影响（依赖 Dashboard 自身登录）。

打开后在输入框输入文字即可对话，点击输入框左侧麦克风按钮可语音输入。

---

## 配置项速查

| 配置项 | 说明 | 推荐值 |
|--------|------|--------|
| `character_name` | 对话框上方显示的角色名 | 你的角色名 |
| `persona` | AstrBot 内置人格 | AstrBot 预设 |
| `llm_provider` | 驱动对话的 AI 模型 | deepseek / gpt |
| `tts_provider` | 语音合成提供商 | 选择已配置的 TTS Provider（推荐 Fish Audio S2-Pro） |
| `tts_enabled` | 启用 TTS 语音朗读 | 默认 `true`，`false` = 静音对话 |
| `audio_format` | TTS 音频格式 | `wav`=无损(≈2MB/条)；`mp3`=需 ffmpeg(≈200KB/条)，未安装自动回退 wav |
| `web_port` | 独立 WebUI 端口 | 默认 `6186`，`0` = 关闭 |
| `web_enabled` | 启用独立 WebUI | 默认 `true`，`false` = 仅 Dashboard 内嵌页 |
| `web_password` | 独立 WebUI 密码 | 留空 = 无需密码；设置后需输入才能访问 |
| `sprite_mode` | 立绘渲染模式 | **`single`**（推荐，VRM 尚不可用） |
| `sprite_scale` | 立绘整体缩放倍数 | 默认 `1.0`，建议 0.5 ~ 2.0 |
| `sprite_bottom` | 立绘距底部距离 (vh) | 默认 `28`，建议 5 ~ 45 |
| `sprite_left` | 立绘水平锚点 (%) | 默认 `50`（居中） |
| `typewriter_speed` | 打字机速度 (ms/字) | 默认 `60`，越小越快，建议 10~200 |
| `history_avatar` | 历史记录头像 | 设置页直接上传设置，留空则不显示 |
| `tts_emotion_map` | 立绘情绪→TTS情绪映射 (JSON) | 例：`{"blush":"shy","thinking":"contemplative"}`，留空直接用标签本名 |
| `background` | 场景背景图 | 留空自动匹配 |
| `expressions` | 各情绪对应立绘文件名 | 留空自动匹配 |
| `custom_emotions` | 自定义额外情绪标签 (JSON) | 例：`{"dokidoki": ""}` |
| `session_retain_days` | 会话保留天数 | 默认 `7`，`0` = 永不清理 |
| `rapid_click_threshold` | 快速点击检测阈值（次） | 默认 `5` |
| `rapid_window_seconds` | 快速点击检测窗口（秒） | 默认 `3` |
| `history_limit` | 历史面板显示条数 | 默认 `40`，建议 20~100 |

> **关于立绘/背景配置项**：所有素材字段均支持「留空 = 自动匹配」，按[文件命名约定](#文件命名约定)将 PNG 放入 `assets/` 目录，或通过[设置页面](#设置页面)上传即可，无需手动逐个填写。

---

## 功能详情

### 核心交互

- **AI 驱动表情切换** —— LLM 回复中插入 `{emotion_happy}` 等标签，前端实时切换角色表情
- **打字机效果** —— 回复文字逐字显示（60ms/字），表情随文字进度同步切换
- **TTS 情感语音** —— 按 LLM 输出的 `{emotion_xxx}` 标签边界，在纯文本前拼接 Fish Audio 方括号标签 `[xxx]`，单次调用 TTS provider 合成整段情感语音。Fish Audio S2-Pro 按句子边界自动切换情绪。立绘切换根据音频时长同步，与语音进度一致
- **BGM 背景音乐** —— 设置页上传 mp3/wav/ogg 音频，主页首次交互后循环播放；语音和 BGM 音量独立滑块调节，持久化到 `prefs.json` 不丢失
- **语音输入** —— 浏览器麦克风录音 → WAV → AstrBot STT 管道自动转文字
- **快速点击检测** —— 用户频繁点击/按键时，AI 主动关心
- **点击快进** — 打字机播放中点击对话框，文字快速弹入显示并切到最终表情，还原 galgame 手感
- **轻戳互动** — 空闲时点击角色区域可触发 AI 主动对话
- **对话历史面板** —— 顶部时钟图标进入，气泡式展示最近 N 条历史消息（条数可配置），自动滚到最新，背景色自动适配。支持 AI 消息头像显示、历史语音回放
- **会话切换面板** —— 顶部列表图标进入，浏览和切换所有历史会话，每条会话右上角 × 按钮可直接删除（同步清理 AstrBot 对话 + 关联音频）
- **AstrBot 指令兼容** —— 在输入框使用 `/reset`、`/new`、`/del` 等指令，会话状态与 AstrBot 对话生命周期完全同步，指令文本不污染对话记录
- **Dashboard 内嵌页** —— 从插件卡片入口进入，顶部 tab 可在「galgame」、「settings」（立绘/BGM/音量）、「voice-favorites」（语音收藏）之间切换，无需独立浏览器窗口。内嵌页通过 bridge SDK 自动认证
- **重播按钮** —— 对话框右上角重播按钮，可重放上次 AI 回复的完整打字机 + 表情切换动画 + TTS 语音
- **语音收藏** —— 顶部 ❤ 图标进入收藏页面，可收藏喜欢的语音片段，数据持久化不随 /reset 丢失
- **BGM 背景音乐** —— 设置页面上传 mp3/wav/ogg 等音频，主页循环播放，音量独立可调
- **音量控制** —— 语音朗读和 BGM 音量独立滑块调节，设置自动保存到服务端，重启/清缓存不丢失

### 平台集成

- **复用 AstrBot 人格系统** —— 直接选择已配置的 Persona，无需重复设定角色性格
- **全管道集成** —— 所有消息经 webchat 管道分发，记忆/感知/安全等插件全栈生效
- **会话双向同步** —— 对话历史同时保存到磁盘 JSON 文件 + AstrBot 数据库，Dashboard 对话管理可查看/导出
- **JWT 代理认证** —— API 请求自动携带 JWT Bearer 令牌，与 AstrBot Core 安全通信
- **资产迁移机制** —— 插件升级时自动搬迁 `assets/` 至 `data/plugin_data/`，升级不丢素材

### 素材管理

- **设置页面** —— 首页右上角齿轮 ⚙ 图标进入，支持 BGM 上传/选择、音量调节、立绘上传/预览/删除
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

在插件配置页的 **「自定义情绪」** 字段中写入 JSON 添加额外情绪（会同时用于立绘切换和 TTS）：

```json
{"dokidoki": "dokidoki.png", "cry": "", "smirk": "smirk.png"}
```

- **key**：情绪标签名，AI 会使用 `{emotion_key}` 标记
- **value**：`assets/` 下的文件名（留空自动匹配 `key.png`）

### 自由情绪标签（TTS 专用）

除了已配置的立绘表情，AI 还可以在回复中自由使用任意 `{emotion_xxx}` 标签来增强 TTS 表现力，支持英文和中文：

```
{emotion_excited}哇！{emotion_happy}今天真开心！{emotion_傲娇}哼！{emotion_blush}嘿嘿~
```

- 已配置的 7 种（如 happy/blush）→ 同时触发立绘切换 + TTS 情绪
- 自由标签（如 excited/傲娇）→ **仅 TTS 生效**，立绘不切（没有对应的表情图）
- Fish Audio S2-Pro 支持 15000+ 自由文本描述，`[excited]`/`[傲娇]`/`[whispering]` 等均可用
- 通过 `tts_emotion_map` 可把 galgame 标签映射到 Fish Audio 标签（如 `{"blush":"shy"}`）

---

## 设置页面

Galgame 主页面右上角点击齿轮 ⚙ 图标进入。

**功能：**
- **拖拽上传** —— PNG 图片拖入页面即可上传到 `assets/`
- **按模式分区** —— 页面显示当前模式需要的文件清单，每个槽位独立操作
- **自动重命名** —— 从槽位上传的文件自动改名为标准文件名
- **文件网格** —— 浏览、预览、删除所有已上传文件
- **批量操作** —— 多选文件一键删除
- **BGM 管理** —— 上传/预览/选择/删除背景音乐，主页循环播放
- **音量调节** —— 语音朗读和 BGM 音量独立滑块，自动保存

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
  "audio": "（Fish Audio TTS 合成语音 base64）",
  "audio_mime": "audio/wav",
  "audio_file": "abc123.wav"
}
```

前端收到后执行打字机动画显示 `reply`，`emotions` 已知项（已配置立绘的 7 种）用于立绘切换，`audio` 为单文件整段语音，TTS 文本含所有 `[xxx]` 行内情绪标签（包括 AI 自由发挥的自定义标签）。

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

- **TTS 情绪标签**：WebUI 聊天的 TTS 绕过 AstrBot pipeline 直接调用 provider，因此 meme_manager 等插件的文本处理钩子不会影响 Fish Audio 方括号情感标签。`{emotion_xxx}` 在 pipeline 处理阶段由插件剥离。除已配置的 7 种立绘表情外，AI 可自由使用任意 `{emotion_xxx}` 标签（如 `{emotion_傲娇}`），TTS 全部接收而前端立绘只按已知 7 种切换。
- **不支持发送文件/图片**：Web 对话 bot 暂不支持 AI 发送图片或文件（待开发）。meme_manager 产生的 `[IMAGE]` 引用会自动过滤。
- **Fish Audio 网络依赖**：Fish Audio API 服务器在境外，需稳定代理。代理不稳定时 TTS 会降级静默跳过，文字正常显示。
- **VRM 3D 模式**：尚未完善，暂不可用。
- **Dashboard 内嵌页无弹窗确认**：Dashboard 内嵌页运行在受限 sandbox 中，无 `confirm()`/`alert()` 权限。删除会话、取消收藏等操作设为直接生效，无浏览器弹窗确认。独立 WebUI 不受此限制。

## 许可证

MIT

---

**相关项目：**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
