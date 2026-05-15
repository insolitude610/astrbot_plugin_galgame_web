# AI Galgame 虚拟伙伴

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，在浏览器中呈现 Galgame 风格的 AI 虚拟伙伴界面。支持多层 PNG 伪 Live2D 独立动画、AI 驱动情绪表情切换、TTS 语音朗读、快速点击检测等交互特性。

## 功能亮点

- **多层 PNG 伪 Live2D** —— 身体/头发/脸部/嘴部各自独立动画，不依赖 Live2D SDK
- **情绪实时切换** —— AI 回复中标记 `[emotion:happy]` 等标签，立绘表情自动淡入淡出
- **复用 AstrBot 人格系统** —— 直接选择已配置的 Persona，无需重复设定角色性格
- **TTS 语音朗读** —— 接入 AstrBot 内置或第三方 TTS Provider（Edge/OpenAI/Azure/DashScope 等）
- **打字机效果** —— 回复文字逐字显示
- **嘴型同步** —— 播放语音时嘴部自动开合
- **快速点击检测** —— 用户频繁点击鼠标/键盘时 AI 主动关心
- **双层渲染模式** —— 支持完整分层 PNG 或单张立绘 + 表情差分降级
- **纯 CSS 动画** —— 呼吸、头发摆动、球体漂浮、对话框滑入，零依赖
- **SSE 实时通信** —— 文本逐段推送、情绪即时切换、音频流式播放
- **会话持久化** —— 对话历史自动存盘，重启/重载后保留；浏览器 localStorage 记录 session_id，关掉页面再打开可继续对话
- **可配置场景背景图** —— 插件设置页直接指定背景图

## 快速开始

### 安装

1. 在 AstrBot WebUI 中打开**插件市场**
2. 搜索 `astrbot_plugin_galgame_web` 并安装
3. 启用插件

### 配置

在插件详情页配置以下内容：

| 配置项 | 说明 | 推荐 |
|--------|------|------|
| 角色显示名 | 对话框上方显示的名称 | 你的角色名 |
| 角色人格 | 选择已在 AstrBot 配置好的 Persona | 可先用 AstrBot 预设或自建 |
| LLM Provider | 驱动对话的 AI 模型 | deepseek / gpt-4o 等 |
| TTS Provider | 语音合成 | Edge TTS（免费） |
| 场景背景图 | `assets/` 下的背景图文件名 | `bg.png` |
| 表情立绘 | 各情绪对应的 PNG 文件名 | 至少填写 neutral |
| 分层立绘 | 身体/头发/脸部/嘴部等文件名 | layered 模式 |
| 会话保留天数 | 超过该天数未活跃的会话自动清理 | 默认 7 天，设 0 永不清理 |
| 立绘渲染模式 | `single` 单图 或 `layered` 多层 | layered 效果更好 |

### 准备立绘

参考 [立绘指南](#立绘指南) 使用 AI 生成角色立绘。

将 PNG 文件放入 `pages/galgame/assets/` 目录，然后在配置中填写文件名。

### 使用

1. 在插件详情页点击**「Galgame」**页面
2. 浏览器独立窗口打开虚拟伙伴界面
3. 在输入框输入文字，回车发送
4. 角色以打字机效果回复，表情随情绪变化，语音同步播放

### 发送指令

在任意支持 AstrBot 的消息平台发送：

```
/galgame
```

查看使用说明。

## 会话持久化说明

每次与 AI 对话后，对话历史会保存到 `data/plugin_data/astrbot_plugin_galgame_web/sessions/` 目录。浏览器端会将当前 `session_id` 存入 localStorage。下次打开页面时自动恢复。

### 会导致会话消失的情况

| 情况 | 是否丢失 | 原因 |
|------|:--:|------|
| 重载/重启 AstrBot | 否 | 从磁盘恢复 |
| 插件升级/重装 | 否 | 会话文件不受影响 |
| 关闭浏览器再打开 | 否 | localStorage 记录 session_id |
| 同一台电脑数十天内多次打开 | 否 | 保留期内可恢复 |
| 超过保留天数的旧会话 | **是** | GC 自动清理（默认 7 天） |
| 手动删除 `sessions/` 目录下的 JSON | **是** | 物理删除 |
| 更换浏览器 | **是** | localStorage 不共享 |
| 无痕/隐私模式 | **是** | localStorage 不持久化 |
| 清除浏览器缓存 | **是** | localStorage 被清 |
| 换个电脑/设备 | **是** | 无跨设备同步 |

> 如需关闭自动清理，将"会话保留天数"设为 `0`。
> 如需跨设备同步，可自行备份 `sessions/` 目录。

## 立绘指南

### 推荐生成方式

使用 AI 图片生成（如 gpt-image-2、Stable Diffusion）生成角色立绘：

**主体立绘（半身、正面）：**

```
2D anime-style character illustration, half-body portrait,
front-facing, standing pose with relaxed posture.
[你的角色描述]
Clean lineart, soft anime cel-shading, game character
sprite style. Solid light-gray background.
Aspect ratio 3:4, centered composition.
No dialog box, no text, no UI elements.
```

**表情差分（复用同一角色描述，仅改表情）：**

```
Same character. Identical appearance: [外观要点].
Facial expression: [表情描述].
Same light-gray background, same 3:4 composition.
```

建议准备 7 种表情：`neutral`、`happy`、`sad`、`angry`、`surprised`、`blush`、`thinking`。

### 获取分层图

AI 只能出单张完整图。分层 PNG 需要通过图像编辑工具（GIMP/Photoshop）在完整图上擦除/分离各层：

1. **身体层** — 擦除头部 → 保存为 `body.png`
2. **头发后层** — 擦除头发以外的部分 → 保存为 `hair_back.png`
3. **头部层**（含五官） — 保留脸部区域 → 保存为 `head.png`
4. **头发前层** — 保留刘海等前置发丝 → 保存为 `hair_front.png`
5. **嘴部差分** — 从表情图抠出嘴部，修出张嘴/闭嘴两版 → `mouth_open.png` / `mouth_closed.png`
6. **球体**（如有） — 单独抠出 → `orb.png`

> 如果不想拆层，使用 `single` 渲染模式即可，只需提供整张立绘的表情差分。

## SSE 事件协议

前端通过 `bridge.subscribeSSE("stream", ...)` 订阅 SSE 事件流：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type: "emotion"` | 切换情绪 | `value` 为情绪标签（`happy`/`sad`/...） |
| `type: "text"` | 文本流 | `value` 为逐段推送的回复文字 |
| `type: "audio"` | 语音 | `value` 为 base64 编码的 WAV 音频 |
| `type: "end"` | 回复完毕 | 无额外字段 |
| `type: "error"` | 错误 | `message` 为错误描述 |

## 技术架构

```
浏览器 (Galgame UI)
  ↕ Bridge API + SSE
AstrBot Dashboard (Quart)
  ↕ register_web_api
插件后端 main.py
  ↕ context.llm_generate / context.get_provider_by_id
AstrBot Core
  └─ LLM + TTS + Persona + 会话管理
```

- 前端：纯 HTML/CSS/JS，零外部依赖
- 后端：Python，仅依赖 AstrBot Core 公开 API
- CSS 动画：呼吸、头发飘动、头微倾、球体漂浮、嘴部开合、表情淡入淡出

## 变更记录

### v0.2.0

- 角色人格改用 AstrBot 内置 Persona 系统，无需手动填写性格描述
- 新增场景背景图配置
- 新增会话持久化（磁盘 + localStorage），支持断点续聊
- 新增会话保留天数配置（0 = 永不清除）
- 插件名改为 `astrbot_plugin_galgame_web`

### v0.1.0

- 首次发布，基础 Galgame 交互功能

## 许可证

MIT

---

**相关项目：**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
