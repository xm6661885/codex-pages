# Codex Pages

[English](README.md) | **简体中文**

一个轻量的自托管网页发布门户。把静态页面、WSGI 应用或 ASGI 应用丢进来，就能在同一个端口下得到稳定的访问地址、一个列出所有项目的首页，以及带密码保护的管理页面。门户本身**只使用 Python 标准库**，无需 `pip install`，也没有构建步骤。

## 功能特性

- **静态站点**：发布整个目录或单个 `.html` 文件，访问路径为 `/p/<endpoint>/`。
- **WSGI 应用**：通过 `wsgiref` 运行任意 WSGI 对象，由门户反向代理。
- **ASGI 应用**：通过 `uvicorn` 运行 FastAPI / Starlette 等（`uvicorn` 由子项目自己的环境提供）。
- **按需启动后端**：动态应用在首次请求时才启动，仅绑定 `127.0.0.1`，状态与日志写入 `runtime/`。
- **项目首页**：列出已启用的项目（可逐个项目隐藏）。
- **管理页面**：密码登录后可上传 HTML、改名称/简介、启用/停用、控制首页展示、删除。
- **命令行**：`deploy`、`list`、`url`、`delete`、`admin-password`、`run`、`install-service`。
- **systemd 用户服务**：一条命令安装并启用，自动选择空闲端口。
- **IPv6 优先**：监听 `::`，并输出本机 IPv6 访问地址。

## 环境要求

- Python 3.8+（门户仅用标准库）
- 带 `systemd --user` 的 Linux（仅 `install-service` 需要）
- 仅在发布 ASGI 项目时，需要运行环境中有 `uvicorn`（及你的框架）

## 快速开始

```bash
git clone https://github.com/xm6661885/codex-pages.git
cd codex-pages

python3 portal.py init      # 生成管理密码并打印
python3 portal.py run       # 在配置端口前台运行
```

打开输出的 URL（也可随时用 `python3 portal.py url` 查看）。端口取自 `config.json`（缺省为 `8765`）。

### 作为服务运行

```bash
python3 portal.py install-service --port 8765
```

该命令从首选端口开始向上寻找空闲端口并写入 `config.json`，生成 `~/.config/systemd/user/codex-pages.service`，然后执行 `systemctl --user enable --now codex-pages.service`。如需退出登录后继续运行：`loginctl enable-linger $USER`。

## 发布项目

```bash
# 静态目录
python3 portal.py deploy ./site --name "站点名称" --type static

# 单个 HTML 文件
python3 portal.py deploy ./index.html --name "页面名称" --type static

# WSGI（模块:对象，默认 app:app）
python3 portal.py deploy ./app --name "应用名称" --type wsgi --wsgi app:app

# ASGI（模块:对象，默认 app:app）
python3 portal.py deploy ./app --name "应用名称" --type asgi --asgi app:app
```

可选参数：`--description`、`--endpoint`（自定义 URL 端点）、`--type auto|static|wsgi|asgi`。

- 未指定端点时由 `--name` 生成，须匹配 `[a-z0-9-]{1,63}`（以字母或数字开头）。名称为中文等非 ASCII 字符时，请显式传入 `--endpoint`。
- `deploy` 会把源项目**复制**到 `projects/<endpoint>/code/`，不会在原目录直接运行。端点已存在时会拒绝发布，需先删除。
- `--type auto` 只是简单启发式（`app.py` 含 `fastapi` → ASGI，其他 `app.py` → WSGI，否则静态），重要场景请显式指定 `--type`。
- 发布后可通过 `http://[<本机IPv6>]:<端口>/p/<endpoint>/` 访问。

### 命令参考

| 命令 | 用途 |
| --- | --- |
| `init` | 若不存在则创建管理密码文件并打印 |
| `run` | 前台运行门户 |
| `install-service [--port N]` | 安装并启动 systemd 用户服务 |
| `deploy <source> --name ...` | 发布项目 |
| `list` | 列出项目（端点、开关、类型、名称） |
| `url` | 输出门户 URL |
| `delete <endpoint> [-y]` | 删除项目及其文件（默认交互确认，`-y` 跳过） |
| `admin-password <密码> --confirm` | 修改管理密码 |

## 管理页面

访问 `/admin/`，使用 `init` 输出的密码登录（保存在 `.codex-pages-admin-password`）。可以：

- 上传 `.html` / `.htm` 文件（非空，≤ 5 MiB），自动创建为新的静态项目，端点由文件名生成并保证唯一；
- 修改显示名称和简介；
- 启用 / 停用项目（停用后访问返回 404）；
- 控制项目是否在首页展示；
- 删除项目（同时停止其后端）。

## 动态应用的运行方式

- WSGI 项目由 `wsgi_runner.py` 启动，ASGI 项目由 `asgi_runner.py` 启动，工作目录与导入路径均为项目的 `code/`。
- runner 监听随机的 `127.0.0.1` 端口；门户将 `GET`/`POST` 请求（含查询字符串）代理过去，超时 30 秒。
- 进程状态保存在 `runtime/<endpoint>.json`，输出在 `runtime/<endpoint>.log`；出现“后端启动失败”页面时请查看日志。
- ASGI 需要运行门户的解释器能导入 `uvicorn`：`uv pip install uvicorn fastapi`（或使用 `pip install`）。
- 应用挂载在 `/p/<endpoint>/` 之下，页面和路由中请使用**相对路径**；生成的绝对链接不会自动补上前缀。

## 目录结构

```
portal.py          HTTP 服务、管理页面、代理与 CLI（单文件）
wsgi_runner.py     WSGI 子项目入口
asgi_runner.py     ASGI 子项目入口
config.json        监听端口，如 {"port": 8766}
projects/<slug>/   project.json + code/             （运行时数据，已被 git 忽略）
runtime/           <slug>.json 状态、<slug>.log 日志  （运行时数据，已被 git 忽略）
.codex-pages-admin-password                         （机密，已被 git 忽略）
```

`project.json` 字段：`slug`、`name`、`description`、`type`、`wsgi`、`asgi`、`enabled`、`show_on_home`、`created_at`。

## 安全说明

- 管理认证为单一共享密码，使用 HMAC 签名、`HttpOnly`、`SameSite=Strict` 的 cookie，约一天有效。服务使用明文 HTTP 且 cookie 未设置 `Secure`，**若暴露到公网，请放在 HTTPS 反向代理（Caddy、nginx 等）之后**。
- 发布的 WSGI/ASGI 代码以与门户相同的系统用户运行，没有沙箱，请只部署可信代码。
- 门户绑定所有网卡（`::`），如需保持私有请配置防火墙。
- 切勿提交 `.codex-pages-admin-password`，仓库已将其忽略。

## 已知限制

- 仅处理 `GET` 和 `POST`；不支持 WebSocket 代理；响应在内存中整体缓冲。
- 后端不会因空闲而停止，仅在删除项目时停止。
- 仓库没有自动化测试或 lint 配置。

## 参与贡献

欢迎提交 Issue 和 PR。请保持门户零依赖（仅标准库）。
