# AI Galgame 虚拟伙伴

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 插件，在浏览器中呈现 Galgame 风格的 AI 虚拟伙伴界面。支持多层 PNG 伪 Live2D 独立动画、AI 驱动情绪表情切换、TTS 语音朗读、快速点击检测等交互特性。

![screenshot](screenshot.png)

## 功能亮点

- **多层 PNG 伪 Live2D** —— 身体/头发/脸部/嘴部各自独立动画，不依赖 Live2D SDK
- **情绪实时切换** —— AI 回复中标记 `[emotion:happy]` 等标签，立绘表情自动淡入淡出
- **TTS 语音朗读** —— 复用 AstrBot 内置或第三方 TTS Provider（Edge/OpenAI/Azure/DashScope 等）
- **打字机效果** —— 回复文字逐字显示
- **嘴型同步** —— 播放语音时嘴部自动开合
- **快速点击检测** —— 用户频繁点击鼠标/键盘时 AI 主动关心
- **双层渲染模式** —— 支持完整分层 PNG 或单张立绘 + 表情差分降级
- **纯 CSS 动画** —— 呼吸、头发摆动、球体漂浮、对话框滑入，零依赖
- **SSE 实时通信** —— 文本逐段推送、情绪即时切换、音频流式播放

## 快速开始

### 安装

1. 在 AstrBot WebUI 中打开**插件市场**
2. 搜索 `astrbot_plugin_galgame` 并安装
3. 启用插件

### 配置

在插件详情页配置以下内容：

| 配置项 | 说明 | 推荐 |
|--------|------|------|
| 角色名 | 虚拟伙伴的名字 | 你的角色名 |
| 角色性格描述 | 写入 system prompt，定义说话风格 | 友善亲切的AI伙伴 |
| LLM Provider | 驱动对话的 AI 模型 | deepseek / gpt-4o 等 |
| TTS Provider | 语音合成 | Edge TTS（免费） |
| 表情立绘 | 各情绪对应的 PNG | 至少填写 neutral |
| 分层立绘 | 身体/头发/脸部/嘴部等 | layered 模式 |

### 准备立绘

参考 [立绘生成指南](#立绘指南) 使用 AI 生成角色立绘。

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
  └─ LLM + TTS + 会话管理
```

- 前端：纯 HTML/CSS/JS，零外部依赖
- 后端：Python，仅依赖 AstrBot Core 公开 API
- CSS 动画：呼吸、头发飘动、头微倾、球体漂浮、嘴部开合、表情淡入淡出

## 开发

```bash
git clone <repo-url>
cd astrbot_plugin_galgame
# 将插件目录放到 AstrBot 的 data/plugins/ 下
# 启动 AstrBot 即可加载
```

## 许可证

MIT

---

**相关项目：**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
