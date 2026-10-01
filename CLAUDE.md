# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Codex Pages 是一个自托管的网页发布门户，用于集中托管静态页面，并代理运行 WSGI/ASGI 项目。项目本身使用 Python 标准库实现 HTTP 服务、管理 UI 和 CLI；ASGI 子项目由其自身依赖提供 `uvicorn`。

## 常用命令

以下命令均在仓库根目录执行。仓库没有依赖清单、构建脚本、测试套件或 lint/格式化配置；门户本身不需要安装 Python 包。

| 用途 | 命令 |
| --- | --- |
| 初始化管理配置 | `python3 portal.py init` |
| 本地前台启动 | `python3 portal.py run` |
| 安装并启动用户级 systemd 服务 | `python3 portal.py install-service` |
| 选择首选服务端口 | `python3 portal.py install-service --port 8765` |
| 列出已发布项目 | `python3 portal.py list` |
| 查看门户 URL | `python3 portal.py url` |
| 发布静态目录 | `python3 portal.py deploy ./site --name "站点名称" --type static` |
| 发布单个 HTML 文件 | `python3 portal.py deploy ./index.html --name "页面名称" --type static` |
| 发布 WSGI 项目 | `python3 portal.py deploy ./app --name "应用名称" --type wsgi --wsgi app:app` |
| 发布 ASGI 项目 | `python3 portal.py deploy ./app --name "应用名称" --type asgi --asgi app:app` |
| 删除项目（交互确认） | `python3 portal.py delete <endpoint>` |
| 修改管理密码（显式确认） | `python3 portal.py admin-password <新密码> --confirm` |

`deploy` 还支持 `--description` 和 `--endpoint`；端点仅允许 1–63 位小写字母、数字和连字符。自动类型识别只检查目录下的 `app.py` 是否含 `fastapi`，不适合作为可靠的项目检测。

没有定义单测或单用例运行命令，也没有迁移命令。门户配置及项目元数据是 JSON 文件，当前代码通过写文件直接更新。

## 高层架构

- `portal.py` 同时承载门户 HTTP 服务、管理页面、发布 CLI 和代理逻辑。`Handler` 分派首页、管理路由和 `/p/<endpoint>/...`；静态项目从项目的 `code/` 目录读文件，动态项目按需启动后端并通过 loopback HTTP 转发请求及查询字符串。
- 每个已发布项目位于 `projects/<endpoint>/`，由 `project.json` 描述名称、类型、可见状态和 WSGI/ASGI 导入目标；实际项目文件放在 `code/`。门户首页只列出启用且 `show_on_home` 不为 false 的项目，路由也会拒绝服务已停用项目。
- 动态服务进程以项目 `code/` 为工作目录，状态和日志分别写入 `runtime/<endpoint>.json` 与 `runtime/<endpoint>.log`。WSGI 由 `wsgi_runner.py` 使用标准库 `wsgiref` 启动；ASGI 由 `asgi_runner.py` 通过 `uvicorn` 启动。两个 runner 均绑定 `127.0.0.1`，外部请求由门户代理。
- 管理认证使用仓库根目录的 `.codex-pages-admin-password` 作为密码来源，登录后以签名 cookie 会话认证。上传 HTML 的管理路由会在项目目录中创建静态项目及其元数据。
- `asgi_runner.py` 与 `wsgi_runner.py` 是子项目进程入口，不是门户的部署/启动入口；门户命令由 `portal.py` 的 argparse CLI 提供。

## 仓库特有约定与易踩的坑

- `config.json` 保存门户监听端口；当前仓库值为 `8766`，缺省回退端口为 `8765`。`run` 使用配置端口；`install-service` 会从首选端口向上寻找可用端口并更新配置，然后安装并启用用户级 systemd 服务。
- WSGI 与 ASGI 导入目标格式均为 `模块:对象`，默认为 `app:app`。ASGI 项目需在其运行环境提供 `uvicorn`；runner 的错误提示给出 `uv pip install uvicorn fastapi` 示例。
- 上传入口只接受非空 `.html`/`.htm` 文件，大小上限为 5 MiB。上传名称会转换为端点并在重名时追加数字；CLI 发布则可用 `--endpoint` 指定端点。
- `projects/` 和 `runtime/` 是运行时数据目录：前者含发布的项目副本及元数据，后者含动态服务状态与日志。CLI `deploy` 会复制源项目，不会在原目录直接运行。
- `portal.py` 内嵌管理 UI 的 CSS/JavaScript 和 HTML 模板；门户界面调整应检查同文件中的 `PAGE_CSS`、`PAGE_JS` 和页面生成函数。
- 仓库未发现 README、CONTRIBUTING、`docs/` 开发说明、CI、代码规范配置或其他 AI 指令文件；因此没有可依据的额外提交格式、分支规则或测试约定。
