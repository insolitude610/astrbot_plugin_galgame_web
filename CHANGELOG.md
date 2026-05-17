# 变更记录

## v0.2.3

- **立绘管理页面** —— 浏览器内拖拽上传 / 预览 / 删除 PNG，自动匹配情绪和图层映射，主页右上角齿轮入口
- **配置页提示优化** —— 表情/分层立绘字段标注「留空=自动」，引导使用管理页面上传，无需逐个填写
- 新增 `POST /assets/upload`、`POST /assets/delete`、`POST /assets/batch` API
- 修复管理页图片预览不显示的问题

## v0.2.2

- **对话接入 AstrBot 消息系统** —— Galgame 对话自动写入 `conversations` 和 `platform_message_history` 表，Dashboard `对话管理` 页面可查看/编辑/导出
- 旧会话 JSON 文件自动迁移至数据库，无缝兼容

## v0.2.1

- **立绘路径自动检测** —— 按命名约定放入 assets 目录即可零配置使用
- 新增 `/assets/list` API

## v0.2.0

- 前端全面改造为 Galgame 沉浸式 UI（三层结构、毛玻璃对话框、标签、底划线输入框）
- 角色人格改用 AstrBot 内置 Persona 系统
- 会话持久化（磁盘 + localStorage），可配置保留天数
- 场景背景图配置、`/galgame` 指令
- 插件名改为 `astrbot_plugin_galgame_web`

## v0.1.0

- 首次发布，基础 Galgame 交互功能
