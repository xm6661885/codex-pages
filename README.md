# Codex Pages

**English** | [简体中文](README.zh-CN.md)

A tiny, self-hosted publishing portal. Drop in a static page, a WSGI app or an ASGI app and get a stable URL under one port, a home page that lists everything, and a password-protected admin UI. The portal itself is **pure Python standard library** — no `pip install`, no build step.

## Features

- **Static sites** – publish a directory or a single `.html` file, served from `/p/<endpoint>/`.
- **WSGI apps** – run any WSGI callable via `wsgiref`, reverse-proxied by the portal.
- **ASGI apps** – run FastAPI / Starlette / etc. via `uvicorn` (provided by the sub-project's own environment).
- **Lazy backends** – dynamic apps are started on the first request, bound to `127.0.0.1` only, with state and logs under `runtime/`.
- **Home page** – lists enabled projects (can be hidden per project).
- **Admin UI** – log in with a password, upload an HTML page, rename, edit description, enable/disable, toggle home-page visibility, delete.
- **CLI** – `deploy`, `list`, `url`, `delete`, `admin-password`, `run`, `install-service`.
- **systemd user service** – one command to install and enable, auto-picks a free port.
- **IPv6-first** – listens on `::` and prints an IPv6 URL for the host.

## Requirements

- Python 3.8+ (standard library only for the portal)
- Linux with `systemd --user` (only for `install-service`)
- `uvicorn` (+ your framework) in the Python environment, only if you deploy ASGI projects

## Quick start

```bash
git clone https://github.com/XMWML/codex-pages.git
cd codex-pages

python3 portal.py init      # creates the admin password and prints it
python3 portal.py run       # foreground server on the configured port
```

Open the printed URL (`python3 portal.py url` prints it again). The default port is `8765`, overridable in `config.json`.

### Run as a service

```bash
python3 portal.py install-service --port 8765
```

This picks the first free port starting at the preferred one, writes it to `config.json`, creates `~/.config/systemd/user/codex-pages.service`, then runs `systemctl --user enable --now codex-pages.service`. To keep it running after logout: `loginctl enable-linger $USER`.

## Deploying projects

```bash
# static directory
python3 portal.py deploy ./site --name "My Site" --type static

# a single HTML file
python3 portal.py deploy ./index.html --name "Landing Page" --type static

# WSGI (module:object, default app:app)
python3 portal.py deploy ./app --name "Flask Demo" --type wsgi --wsgi app:app

# ASGI (module:object, default app:app)
python3 portal.py deploy ./app --name "API" --type asgi --asgi app:app
```

Options: `--description`, `--endpoint` (custom URL slug), `--type auto|static|wsgi|asgi`.

- The endpoint is derived from `--name` if omitted; it must match `[a-z0-9-]{1,63}` (starting with a letter or digit). For non-ASCII names pass `--endpoint` explicitly.
- `deploy` **copies** the source into `projects/<endpoint>/code/`; the original directory is never run in place. Re-deploying an existing endpoint is refused — delete it first.
- `--type auto` is only a heuristic (`app.py` containing `fastapi` → ASGI, other `app.py` → WSGI, otherwise static). Pass `--type` explicitly when it matters.
- The published project is then available at `http://[<host-ipv6>]:<port>/p/<endpoint>/`.

### CLI reference

| Command | Purpose |
| --- | --- |
| `init` | Create the admin password file if missing and print it |
| `run` | Run the portal in the foreground |
| `install-service [--port N]` | Install and start the systemd user service |
| `deploy <source> --name ...` | Publish a project |
| `list` | List projects (endpoint, on/off, type, name) |
| `url` | Print the portal URL |
| `delete <endpoint> [-y]` | Delete a project and its files (asks for confirmation unless `-y`) |
| `admin-password <pw> --confirm` | Change the admin password |

## Admin UI

Visit `/admin/` and sign in with the password from `init` (stored in `.codex-pages-admin-password`). From there you can:

- upload a `.html` / `.htm` file (non-empty, ≤ 5 MiB) — it becomes a new static project, with a unique endpoint derived from the filename;
- edit display name and description;
- enable / disable a project (disabled projects return 404);
- show or hide a project on the home page;
- delete a project (also stops its backend).

## Dynamic apps: how they run

- WSGI projects are launched by `wsgi_runner.py`, ASGI projects by `asgi_runner.py`, with the project's `code/` as working directory and import path.
- The runner listens on a random `127.0.0.1` port; the portal proxies `GET`/`POST` requests (including query strings) to it, with a 30 s timeout.
- Process state is stored in `runtime/<endpoint>.json`, output in `runtime/<endpoint>.log` — check the log when you get a *backend failed to start* page.
- ASGI needs `uvicorn` importable by the interpreter running the portal: `uv pip install uvicorn fastapi` (or `pip install`).
- Apps are mounted under `/p/<endpoint>/`, so use **relative URLs** in your pages and routes; the prefix is not stripped from generated absolute links.

## Project layout

```
portal.py          HTTP server, admin UI, proxy and CLI (single file)
wsgi_runner.py     entry point for WSGI sub-projects
asgi_runner.py     entry point for ASGI sub-projects
config.json        {"port": 8765}
projects/<slug>/   project.json + code/            (runtime data, git-ignored)
runtime/           <slug>.json state, <slug>.log   (runtime data, git-ignored)
.codex-pages-admin-password                        (secret, git-ignored)
```

`project.json` fields: `slug`, `name`, `description`, `type`, `wsgi`, `asgi`, `enabled`, `show_on_home`, `created_at`.

## Security notes

- Admin auth is a single shared password with an HMAC-signed, `HttpOnly`, `SameSite=Strict` cookie valid for about a day. The server speaks plain HTTP and the cookie is not marked `Secure` — **put it behind an HTTPS reverse proxy (Caddy, nginx, …) if exposed to the internet**.
- Published WSGI/ASGI code runs as the same OS user as the portal with no sandbox. Only deploy code you trust.
- The portal binds to all interfaces (`::`). Firewall it if it should stay private.
- Never commit `.codex-pages-admin-password`; it is git-ignored.

## Limitations

- Only `GET` and `POST` are handled; no WebSocket proxying; responses are buffered in memory.
- Backends are not stopped when idle; they stop on project delete.
- No automated tests or lint configuration in this repo.

## Contributing

Issues and PRs are welcome. Keep the portal dependency-free (standard library only).
