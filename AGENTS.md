# AGENTS.md

AstrBot 插件：galgame 风格 AI 虚拟伙伴 WebUI（当前 v0.8.3）。双端（Dashboard 内嵌页 + 独立 WebUI）共享大部分前端代码但结构不同，改动时极易踩坑。以下均为已验证事实。

## 测试 / Lint

- 测试：`python -m pytest tests/ -q`（**全局** Python 3.12.2，已装 pytest/pyjwt；AstrBot venv 没有 pytest）
- 测试用 `tests/conftest.py` mock 掉 astrbot/quart 模块，不依赖真实 AstrBot 运行
- **测试导入陷阱**：测试文件必须用包名导入，如 `importlib.import_module(f"{PACKAGE_NAME}.api.session")`（PACKAGE_NAME = 插件目录名）。用 `from api.session import ...` 会让 `..galgame_web` 相对导入崩溃
- Lint/格式：ruff 只在 AstrBot venv：`D:\AstrBotLauncher-0.1.5.5\AstrBot\venv\Scripts\python.exe -m ruff check .` 和 `ruff format .`
- 修改 Python 后跑：`pytest` + `ruff check` + `ruff format`

## 双端文件结构（最高踩坑率）

| 功能 | Dashboard 内嵌页（`pages/`） | 独立 WebUI（`galgame_web/galgame/`） | 关系 |
|------|------------------------------|-------------------------------------|------|
| 主页面 | `pages/galgame/app.js`、`style.css` | `galgame_web/galgame/app.js`、`style.css` | **孪生，必须 MD5 一致**，改完立即复制同步 |
| 主页面 index.html | `pages/galgame/index.html` | `galgame_web/galgame/index.html` | **结构不同**！独立版有 settings-link/favorites-link/sp-overlay/fp-overlay iframe 入口。**禁止整体复制覆盖**，只能手工同步相同部分 |
| 设置页 | `pages/settings/app.js` + `style.css` + `index.html` | `galgame_web/galgame/settings.html`（**JS 内联单文件**） | 双实现，逻辑同步但不可复制 |
| 收藏页 | `pages/voice-favorites/app.js` + `index.html` | `galgame_web/galgame/favorites.html`（JS 内联） | 同上 |

改主页面 JS/CSS 后：复制到孪生 + `Get-FileHash pages\galgame\app.js, galgame_web\galgame\app.js` 验证一致（index.html 不要求一致）。

## Dashboard 内嵌页约束（易踩坑）

- iframe sandbox = `allow-scripts allow-forms allow-downloads`：**无 allow-modals**（原生 confirm/alert 静默失效，已全部替换为自绘 `showConfirm`/`showToast`）、**无 allow-same-origin**（cookie 不发送）
- **内嵌页 `<img src="/api/plug/...">` 直连 URL 会 401**（SameSite=strict cookie 不随 opaque origin 发送）→ 内嵌页素材必须走 bridge（`AstrBotPluginPage.apiGet/apiPost`）base64。独立 WebUI 用 URL 直载
- 前端判定：`IS_DASHBOARD()`（主页面）/ `window.AstrBotPluginPage`（设置/收藏页）
- 快速点击检测（主页面）必须把弹层 `#confirm-overlay` 加入排除列表（click + keydown 两处）

## 提交约定

- commit message 用**英文** conventional commits（`feat:`/`fix:`/`docs:`/`chore:`）；CHANGELOG.md 用中文
- 版本号：`metadata.yaml` 与 `CHANGELOG.md` 同步更新
- push 需要代理：`git -c http.proxy=http://127.0.0.1:10808 push`（用户日常用 GitHub Desktop；改写过历史，再次改写需 force push 并告知用户）

## 开发流程

- 设计/实施计划在 `docs/superpowers/specs/`、`docs/superpowers/plans/`（已提交）
- 多角色 MVP 计划：`docs/superpowers/plans/2026-08-05-multi-character-mvp.md`。已完成 Task 1/3/6（纯后端地基，无用户可见行为）。**依赖链**：Task 7/8（消息编辑 API）依赖 Task 5 的方法（`_send_switch_persona`、`_send_recalc_next_char`、`_send_save_and_return` 签名）；Task 5 是核心难点
- 计划基于 v0.7.14 编写：前端任务（Task 9/10/11）的代码引用/行号已过时，实施前先核对当前 app.js

## 环境 / 工具

- 独立 WebUI 端口：**7890**（用户配置，非默认 6186）
- 视觉验证：`agent-browser` 截图 + `vision-analyzer` 子代理审查（主模型不支持图像输入）
- 游戏素材解包：`D:\galtool\garbro_mod\GARbro.Console.exe`（xp3 归档；`-x <arc> <entry>` 精确条目解包，输出到当前工作目录；ENTRIES 不支持通配符）。ATRI 游戏在 `D:\SteamLibrary\steamapps\common\ATRI -My Dear Moments-`；已解包素材在 `D:\Code\games\atri_ui\`、演示页在 `D:\Code\opendemo\`
- OpenPencil（`op` CLI）：PowerShell 下 `op.ps1` 会剥双引号——**JSON 参数必须写文件用 `@file` 传入**；应用 UI 自动化不可靠，设计验证靠 `.op` 文件 + HTML demo 渲染
- 数据目录：`data/plugin_data/astrbot_plugin_galgame_web/`（assets/audio/bgm/sessions/characters.json/prefs.json/favorites.json）

## 代码风格

- 后端注释/日志英文；前端 JS 注释英文；UI 文案中文
- 前端为原生 JS（ES5 风格 var/function），无构建工具，无框架
