# 删除确认弹层 + Toast 设计

日期：2026-08-05
状态：已评审（三轮 solution-reviewer-pro：FAIL → 修订 → FAIL → 修订 → PASS）
目标版本：v0.8.1

## 1. 背景

AstrBot Dashboard 内嵌页 iframe sandbox 为 `allow-scripts allow-forms allow-downloads`（无 `allow-modals`）→ 原生 `confirm()`/`alert()` 全部静默失效。v0.7.1 因该限制移除了内嵌页的确认，导致**所有删除操作一键直删无确认**，且错误提示静默。

## 2. 实际文件结构（已核实）

| 功能 | Dashboard 内嵌页 | 独立 WebUI | 关系 |
|------|----------------|-----------|------|
| 主页面 | `pages/galgame/app.js` | `galgame_web/galgame/app.js` | 孪生拷贝（MD5 一致） |
| 设置页 | `pages/settings/app.js`（外部 JS） | `galgame_web/galgame/settings.html`（JS 内联单文件） | 双实现 |
| 收藏页 | `pages/voice-favorites/app.js`（外部 JS） | `galgame_web/galgame/favorites.html`（JS 内联单文件） | 双实现 |

现状：独立 settings.html 3 处原生 confirm（:360/:612/:979）+ 1 alert(:620)；独立 favorites.html 1 confirm(:279) + 1 alert(:287)；Dashboard settings app.js 3 处删除无确认 + alert(:408)；Dashboard favorites 无确认 + alert(:106)；主页面双端会话删除无确认。

## 3. 需求

1. 四项删除加确认：会话删除、素材单删、素材批量删、BGM 删除
2. 取消收藏保持一键（双端一致）
3. 所有 `alert()` → 自绘 toast（内嵌页错误不再静默）
4. 独立 WebUI 与 Dashboard 内嵌页行为完全一致（都用自绘弹层，零原生 confirm/alert 残留）

## 4. 设计

### 4.1 showConfirm

每页内联实现（3 份：主页面、Dashboard 设置页、独立设置页；收藏页不需要）。重复为已声明取舍（页面独立、无共享依赖）。

- 容器 `#confirm-overlay`：fixed 全屏遮罩 + 居中卡片，z-index 1200（高于主页面 session-panel/sp-overlay/fp-overlay 的 1100）
- 结构：标题、消息（`#confirm-msg`）、可选明细（`#confirm-detail`，无则隐藏）、「取消」/「确认删除」按钮
- 交互：
  - 确认按钮 click：第一行 `disabled = true`（防双击重复请求）→ `Promise.resolve().then(onConfirm).finally(closeConfirm)`（成功/失败都自动关闭；`.then` 包装防同步抛异常泄漏）
  - 关闭：点遮罩（`e.target === overlay`）、取消按钮、Esc（`stopPropagation`）均不执行回调
  - 显示后 ~50ms `okBtn.focus()`（防 Enter 焦点泄漏到聊天输入框）
  - 单实例复用：重复调用替换文案与回调，不叠加
- 样式：内联 `<style>` 或 `element.style`，不依赖外部资源

### 4.2 showToast

每页内联（4 份：主页面、Dashboard 设置页、独立设置页、Dashboard 收藏页 + 独立收藏页 = 6 处实际都用到，函数 4 份实现）。右下角固定，3s 自动消失，清除旧 timer 防连发，type 支持 error/success。

### 4.3 主页面快速点击检测排除（关键）

`pages/galgame/app.js`：
- click 排除列表 `:1155`：`"#sp-overlay, #fp-overlay, #history-panel, #session-panel, #expand-btn"` → 追加 `, #confirm-overlay`
- keydown 监听 `:1162`：追加目标排除 `if (e.target.closest && e.target.closest("#confirm-overlay")) return;`（Esc/Enter 在弹层内时不计入快速点击）

双端孪生文件同步。

### 4.4 接入点（6 处编辑 + 5 处样式）

| 位置 | 改动 |
|------|------|
| `pages/galgame/app.js` + 镜像 `galgame_web/galgame/app.js` | 会话删除包 showConfirm（原逻辑抽为 `deleteSession(sid, el)`）；快速点击排除；失败 toast；showConfirm/showToast 函数 + 事件绑定 |
| `pages/galgame/index.html` + 镜像 | 弹层/toast DOM |
| `pages/galgame/style.css` + 镜像 | 弹层/toast 样式 |
| `pages/settings/app.js` | `deleteFile`/`batchDeleteSelected`/`deleteBgm` 包 showConfirm；:408 alert→showToast；deleteBgm 成功加 toast |
| `pages/settings/style.css` | 弹层/toast 样式 |
| `galgame_web/galgame/settings.html` | :360/:612/:979 confirm→showConfirm（文案逐字一致）；:620 alert→toast；内联 style/script 加组件 |
| `pages/voice-favorites/app.js` | :106 alert→showToast（保持一键） |
| `pages/voice-favorites/index.html` | toast DOM + style 块样式 |
| `galgame_web/galgame/favorites.html` | **移除** :279 confirm（一键）；:287 alert→toast；toast 组件 |

### 4.5 文案（双端逐字一致）

- 素材单删：`确定删除 <filename>？`
- 批量删：`确定删除 N 个文件？`
- BGM 删：`确定删除 <name>？`
- 会话删除：`删除该会话？` + 明细 `AstrBot 对话记录与关联语音将一并清除，且无法恢复。`
- BGM 删除成功：`已删除: <name>`（toast success）

## 5. 验证

- `node --check` 所有改动 JS/HTML 内联脚本
- grep 确认全项目零 `confirm(` / `alert(` 残留（排除文档）
- galgame 双端文件 MD5 一致（app.js、style.css、index.html）
- pytest 64 项回归（无后端改动，确认无意外）
- 手动清单（用户自测）：双端四项删除弹层、取消收藏一键、Esc/遮罩/取消关闭、确认才执行、快速点击不误触发、toast 显示、会话删除当前/非当前会话

## 6. 范围外

- MVP 消息删除的确认（留给多角色 MVP 实施时一并处理）
- 会话删除失败反馈由 console.warn 升级为 toast（本次包含，作为 P3 吸收）
