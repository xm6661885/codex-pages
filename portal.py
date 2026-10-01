#!/usr/bin/env python3
"""Codex Pages: a small self-hosted launcher for static pages and WSGI apps."""
from __future__ import annotations

import argparse, base64, hashlib, hmac, html, json, mimetypes, os, re, secrets
import shutil, signal, socket, subprocess, sys, time, urllib.error, urllib.request
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
PROJECTS, RUNTIME = ROOT / "projects", ROOT / "runtime"
CONFIG, SECRET = ROOT / "config.json", ROOT / ".codex-pages-admin-password"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError): return default

def save(path, value):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)

def config(): return load(CONFIG, {"port": 8765})
def port_available(port):
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port)); return True
    except OSError: return False
    finally: sock.close()
def choose_port(preferred=8765):
    for candidate in range(preferred, 65536):
        if port_available(candidate): return candidate
    raise RuntimeError("没有可用的 TCP 端口")
def projects():
    for p in sorted(PROJECTS.iterdir() if PROJECTS.exists() else []):
        meta = load(p / "project.json")
        if meta: yield p, meta

def project(slug):
    p = PROJECTS / slug; meta = load(p / "project.json")
    return (p, meta) if meta else (None, None)

def new_secret(password=None):
    SECRET.write_text(password or secrets.token_urlsafe(18)); os.chmod(SECRET, 0o600)
def secret():
    if not SECRET.exists(): new_secret()
    return SECRET.read_text().strip()

def token():
    stamp = str(int(time.time() // 86400))
    sig = hmac.new(secret().encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{stamp}:{sig}".encode()).decode()
def valid_token(value):
    try:
        stamp, sig = base64.urlsafe_b64decode(value.encode()).decode().split(":", 1)
        return abs(int(time.time() // 86400) - int(stamp)) <= 1 and hmac.compare_digest(sig, hmac.new(secret().encode(), stamp.encode(), hashlib.sha256).hexdigest())
    except Exception: return False

def backend_port(slug):
    state = load(RUNTIME / f"{slug}.json", {})
    return state.get("port")

def running(slug):
    state = load(RUNTIME / f"{slug}.json", {})
    pid = state.get("pid")
    if not pid: return False
    try: os.kill(pid, 0); return True
    except OSError: return False

def stop_backend(slug):
    statefile = RUNTIME / f"{slug}.json"; state = load(statefile, {})
    if state.get("pid"):
        try: os.kill(state["pid"], signal.SIGTERM)
        except OSError: pass
    statefile.unlink(missing_ok=True)

def start_backend(slug, directory, meta):
    if running(slug): return backend_port(slug)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    runner = "asgi_runner.py" if meta.get("type") == "asgi" else "wsgi_runner.py"
    spec = meta.get("asgi", "app:app") if meta.get("type") == "asgi" else meta.get("wsgi", "app:app")
    cmd = [sys.executable, str(ROOT / runner), str(directory), str(port), spec]
    log = open(RUNTIME / f"{slug}.log", "ab")
    proc = subprocess.Popen(cmd, cwd=directory, stdout=log, stderr=log, start_new_session=True)
    save(RUNTIME / f"{slug}.json", {"pid": proc.pid, "port": port})
    for _ in range(20):
        time.sleep(.05)
        if running(slug): return port
    stop_backend(slug); raise RuntimeError("backend failed to start; see runtime log")

PAGE_CSS = '''
:root{color-scheme:light;--bg:#fff7f0;--dot:#f6dfd3;--ink:#4b3934;--muted:#9a8079;--line:#f3ddd2;--panel:rgba(255,255,255,.84);--solid:#fffdfb;--field:#fffaf6;--accent:#ff8c7a;--accent-deep:#e46f5d;--accent-soft:#ffe6df;--danger:#e0566a;--danger-soft:#ffe8ec;--danger-deep:#b93f52;--ok:#4cbf8a;--ok-soft:#dcf5e7;--butter:#ffe7a3;--shadow:0 18px 40px -18px rgba(196,112,88,.45);--body:#ffc9a8;--body-shade:#ffb48d;--cheek:#ff8fa3}
*{box-sizing:border-box}
html{-webkit-tap-highlight-color:transparent}
body{min-height:100vh;margin:0;background:var(--bg) radial-gradient(circle,var(--dot) 1.3px,transparent 1.6px) 0 0/24px 24px;color:var(--ink);font:16px/1.6 ui-rounded,"Nunito","Varela Round","PingFang SC","HarmonyOS Sans SC","MiSans","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif}
a{color:inherit}
.ambient{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.blob{position:absolute;border-radius:50%;filter:blur(46px);opacity:.6;animation:drift 20s ease-in-out infinite alternate}
.blob.b1{width:30rem;height:30rem;left:-10rem;top:-12rem;background:#ffd2c2}
.blob.b2{width:26rem;height:26rem;right:-9rem;top:12%;background:#fff0bf;animation-delay:-6s}
.blob.b3{width:28rem;height:28rem;left:30%;bottom:-16rem;background:#d9f3e4;animation-delay:-12s}
.spark{position:absolute;font-size:1.1rem;color:#ffb3a3;animation:twinkle 4s ease-in-out infinite}
.spark.s1{top:14%;left:6%}.spark.s2{top:9%;right:18%;color:#f7c75b;animation-delay:-1.3s}.spark.s3{top:58%;right:5%;color:#9edbbd;animation-delay:-2.6s;font-size:1.4rem}.spark.s4{bottom:12%;left:9%;color:#c7b4ff;animation-delay:-.7s}
.shell{position:relative;z-index:1;width:min(100% - 2rem,1040px);margin:0 auto;padding:clamp(1rem,3vw,2rem) 0 5rem}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:clamp(1.8rem,5vw,3.2rem)}
.brand{display:inline-flex;align-items:center;gap:.6rem;font-weight:800;font-size:1.08rem;text-decoration:none;letter-spacing:-.01em}
.logo{display:block;width:2.5rem;height:2.5rem;transition:transform .35s cubic-bezier(.3,1.6,.5,1)}.logo svg{display:block;width:100%;height:100%}
.brand:hover .logo{transform:rotate(-12deg) scale(1.08)}
.nav-link{white-space:nowrap;display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1.05rem;border:2px solid var(--line);border-radius:999px;background:var(--panel);color:var(--muted);font-weight:750;text-decoration:none;transition:all .2s}
.nav-link:hover{border-color:var(--accent);color:var(--accent-deep);transform:translateY(-2px)}
.eyebrow{white-space:nowrap;display:inline-flex;align-items:center;gap:.45rem;padding:.25rem .75rem .25rem .6rem;border-radius:999px;background:var(--accent-soft);color:var(--accent-deep);font-size:.74rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
.eyebrow:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px #ff8c7a33;animation:pulse 2.4s ease-in-out infinite}
.hero{display:flex;align-items:center;justify-content:space-between;gap:2rem;margin-bottom:2.4rem}
.hero-text{max-width:38rem}
.hero h1{margin:.8rem 0 .7rem;font-size:clamp(2.3rem,7vw,4rem);font-weight:900;line-height:1.1;letter-spacing:-.03em}
.hl{background:linear-gradient(transparent 60%,var(--butter) 60%,var(--butter) 92%,transparent 92%);padding:0 .12em;border-radius:.2em}
.hero p{max-width:34rem;margin:0;color:var(--muted);font-size:clamp(1rem,2vw,1.12rem)}
.mascot{flex:none;width:clamp(6.5rem,16vw,9.5rem);height:auto;overflow:visible;animation:bob 3.2s ease-in-out infinite}
.m-body{fill:var(--body)}.m-shine{fill:#fff;opacity:.45}.m-eyes{fill:var(--ink);transform-box:fill-box;transform-origin:center;animation:blink 5s infinite}.m-glint{fill:#fff}
.m-cheek{fill:var(--cheek);opacity:.55}.m-mouth{fill:none;stroke:var(--ink);stroke-width:3;stroke-linecap:round}
.m-leaf{fill:#8fd6ae}.m-stem{fill:none;stroke:#72c295;stroke-width:3;stroke-linecap:round}.m-sprout{transform-box:fill-box;transform-origin:50% 100%;animation:sway 3.2s ease-in-out infinite}
.m-paws{fill:var(--body-shade);transition:transform .45s cubic-bezier(.3,1.5,.5,1)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,270px),1fr));gap:1.2rem}
.grid.projects{grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))}
.card,.empty{position:relative;border:2px solid var(--line);border-radius:1.7rem;background:var(--panel);box-shadow:var(--shadow);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.rise{animation:rise .6s cubic-bezier(.2,.9,.3,1.15) both;animation-delay:calc(var(--i,0) * 70ms)}
.tint-0{--tint:#ffe2d8;--tint-ink:#d8664f}.tint-1{--tint:#fff0c4;--tint-ink:#b98a0f}.tint-2{--tint:#d9f4e4;--tint-ink:#35946a}.tint-3{--tint:#dcebff;--tint-ink:#4d7fc2}.tint-4{--tint:#ece3ff;--tint-ink:#7c60c8}.tint-5{--tint:#ffdfea;--tint-ink:#cc5580}
.avatar{flex:none;display:grid;place-items:center;width:3.1rem;height:3.1rem;border-radius:1.1rem;background:var(--tint);color:var(--tint-ink);font-size:1.35rem;font-weight:900;transform:rotate(-6deg);transition:transform .4s cubic-bezier(.3,1.6,.5,1),filter .3s,opacity .3s}
a.card{display:flex;flex-direction:column;gap:.5rem;min-height:210px;padding:1.3rem 1.3rem 1.2rem;overflow:hidden;text-decoration:none;transition:transform .3s cubic-bezier(.3,1.4,.5,1),box-shadow .3s,border-color .3s}
a.card:before{content:"";position:absolute;width:9rem;height:9rem;right:-3.2rem;top:-3.2rem;border-radius:50%;background:var(--tint);opacity:.55;transition:transform .5s cubic-bezier(.3,1.4,.5,1)}
a.card:hover{transform:translateY(-6px) rotate(-.5deg);border-color:var(--tint-ink);box-shadow:0 26px 44px -20px rgba(196,112,88,.55)}
a.card:hover:before{transform:scale(1.35)}
a.card:hover .avatar{transform:rotate(6deg) scale(1.08)}
a.card:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.card-top{position:relative;display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem}
.arrow{display:grid;place-items:center;width:2.3rem;height:2.3rem;border-radius:50%;background:var(--solid);color:var(--tint-ink);font-weight:900;box-shadow:0 4px 12px -4px rgba(150,90,70,.35);transition:transform .3s cubic-bezier(.3,1.6,.5,1)}
a.card:hover .arrow{transform:translateX(4px)}
.card h2{position:relative;margin:0;font-size:1.22rem;font-weight:850;line-height:1.35}
.card p{position:relative;margin:0;color:var(--muted);font-size:.93rem}
.slug{position:relative;align-self:flex-start;max-width:100%;margin-top:auto;padding:.2rem .65rem;border-radius:999px;background:var(--tint);color:var(--tint-ink);font:700 .74rem/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere;word-break:break-all}
.empty{grid-column:1/-1;display:flex;flex-direction:column;align-items:center;gap:.4rem;padding:2.4rem 1.5rem;text-align:center;color:var(--muted)}
.empty .mascot{width:6rem;margin-bottom:.4rem}
.empty strong{color:var(--ink);font-size:1.1rem}
.empty code{padding:.1rem .45rem;border-radius:.5rem;background:var(--accent-soft);color:var(--accent-deep)}
.empty .nav-link{margin-top:1rem}
.empty pre{max-width:100%;margin:.6rem 0 0;padding:.9rem 1rem;border-radius:1rem;background:var(--accent-soft);color:var(--accent-deep);text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}
.login-wrap{max-width:420px;margin:clamp(3.5rem,12vh,7rem) auto 0}
.login-card{padding:4.2rem clamp(1.4rem,5vw,2.3rem) clamp(1.4rem,5vw,2.1rem);text-align:center}
.login-card .mascot{position:absolute;left:50%;top:0;width:7.2rem;margin:-4.6rem 0 0 -3.6rem}
.login-card:has(.pw:focus-within) .m-paws{transform:translateY(-38px)}
.login-card.reveal:has(.pw:focus-within) .m-paws{transform:translateY(-24px)}
.login-card h1{margin:.8rem 0 .4rem;font-size:1.9rem;font-weight:900;letter-spacing:-.02em}
.login-card>p{margin:0 0 1.3rem;color:var(--muted)}
.login-card form{text-align:left}
.login-card button[type=submit]{width:100%;margin-top:.4rem}
.error{margin:0 0 1rem;padding:.6rem .9rem;border-radius:1rem;background:var(--danger-soft);color:var(--danger);font-weight:750;text-align:center}
.shake{animation:shake .5s cubic-bezier(.36,.07,.19,.97) both}
.field{display:block;margin:0 0 1rem}
.label{display:block;margin:0 0 .4rem .3rem;color:var(--muted);font-size:.84rem;font-weight:800}
input,button{font:inherit;font-size:16px}
input:not([type=checkbox]):not([type=file]){width:100%;min-height:2.9rem;padding:.65rem 1rem;border:2px solid var(--line);border-radius:1rem;background:var(--field);color:var(--ink);outline:0;transition:border-color .2s,box-shadow .2s,background .2s}
input:not([type=checkbox]):not([type=file]):hover{border-color:#f0c6b7}
input:not([type=checkbox]):not([type=file]):focus{border-color:var(--accent);background:var(--solid);box-shadow:0 0 0 5px var(--accent-soft)}
input::placeholder{color:#c9b2aa}
.pw{position:relative;display:block}
.pw input{padding-right:3.2rem!important}
button.eye{position:absolute;top:50%;right:.45rem;width:2.3rem;min-height:2.3rem;height:2.3rem;padding:0;border-radius:50%;background:transparent;box-shadow:none;color:var(--muted);transform:translateY(-50%)}
button.eye:hover,button.eye:active{background:var(--accent-soft);box-shadow:none;color:var(--accent-deep);transform:translateY(-50%)}
button.eye svg{width:1.25rem;height:1.25rem}
button.eye .slash{display:none}.reveal button.eye .slash{display:inline}
button{--spin:#fff;position:relative;display:inline-flex;align-items:center;justify-content:center;gap:.45rem;min-height:2.9rem;padding:0 1.4rem;border:0;border-radius:999px;background:var(--accent);box-shadow:0 4px 0 var(--accent-deep),0 12px 20px -10px #e46f5d;color:#fff;font-weight:800;white-space:nowrap;cursor:pointer;transition:transform .12s,box-shadow .12s,background .2s,color .2s}
button:hover{transform:translateY(-2px);box-shadow:0 6px 0 var(--accent-deep),0 16px 24px -10px #e46f5d}
button:active{transform:translateY(3px);box-shadow:0 1px 0 var(--accent-deep),0 4px 8px -4px #e46f5d}
button:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
button.ghost{--spin:var(--accent-deep);background:var(--accent-soft);box-shadow:0 4px 0 #f5cabe;color:var(--accent-deep)}
button.ghost:hover{box-shadow:0 6px 0 #f5cabe}button.ghost:active{box-shadow:0 1px 0 #f5cabe}
button.danger{--spin:var(--danger);background:var(--danger-soft);box-shadow:0 4px 0 #f5c5ce;color:var(--danger)}
button.danger:hover{box-shadow:0 6px 0 #f5c5ce}button.danger:active{box-shadow:0 1px 0 #f5c5ce}
button.danger.solid{--spin:#fff;background:var(--danger);box-shadow:0 4px 0 var(--danger-deep);color:#fff}
button.danger.solid:hover{box-shadow:0 6px 0 var(--danger-deep)}button.danger.solid:active{box-shadow:0 1px 0 var(--danger-deep)}
button.busy{pointer-events:none;color:transparent!important}
button.busy:after{content:"";position:absolute;width:1.15rem;height:1.15rem;border:3px solid var(--spin);border-right-color:transparent;border-radius:50%;animation:spin .7s linear infinite}
.dashboard-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin-bottom:1.6rem}
.dashboard-head h1{margin:.6rem 0 0;font-size:clamp(2rem,5vw,2.9rem);font-weight:900;letter-spacing:-.03em}
.upload{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);align-items:center;gap:1.4rem;margin-bottom:1.6rem;padding:1.5rem;background:linear-gradient(135deg,rgba(255,236,228,.92),rgba(255,247,226,.9))}
.upload h2{margin:.7rem 0 .3rem;font-size:1.3rem;font-weight:850}
.upload p{margin:0;color:var(--muted);font-size:.92rem}
.upload form{display:flex;align-items:stretch;gap:.8rem}
.drop{position:relative;flex:1;display:flex;align-items:center;gap:.75rem;min-width:0;min-height:4.4rem;padding:.7rem 1rem;border:2.5px dashed #f4b9a8;border-radius:1.3rem;background:var(--solid);color:var(--muted);cursor:pointer;transition:border-color .2s,background .2s,transform .25s cubic-bezier(.3,1.6,.5,1)}
.drop:hover,.drop.over{border-color:var(--accent);background:#fff4ef}
.drop.over{transform:scale(1.03)}
.drop input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.drop-icon{flex:none;display:grid;place-items:center;width:2.7rem;height:2.7rem;border-radius:1rem;background:var(--accent-soft);color:var(--accent-deep);transition:transform .3s cubic-bezier(.3,1.6,.5,1)}
.drop-icon svg{width:1.45rem;height:1.45rem}
.drop:hover .drop-icon,.drop.over .drop-icon{transform:translateY(-3px) rotate(-6deg)}
.drop-name{min-width:0;overflow:hidden;font-size:.9rem;font-weight:750;text-overflow:ellipsis;white-space:nowrap}
.drop-name:empty:before{content:".html / .htm";color:#cdb3aa;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600}
.drop.has-file{border-style:solid;border-color:var(--ok);background:#f4fcf7}
.drop.has-file .drop-icon{background:var(--ok-soft);color:var(--ok)}
.drop.has-file .drop-name{color:var(--ink)}
.project{display:flex;flex-direction:column;padding:1.3rem;transition:border-color .3s,box-shadow .3s}
.project-head{display:flex;align-items:flex-start;gap:.85rem;margin-bottom:1.15rem}
.project-title{flex:1;min-width:0}
.project-name{margin:.1rem 0 .15rem;font-size:1.13rem;font-weight:850;line-height:1.35;overflow-wrap:anywhere}
.kind{display:inline-block;margin-left:.35rem;padding:0 .45rem;border-radius:.45rem;background:var(--tint);color:var(--tint-ink);font:800 .66rem/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;vertical-align:1px}
.endpoint{display:inline;max-width:100%;color:var(--muted);font:600 .76rem/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;text-decoration:none;overflow-wrap:anywhere;word-break:break-all;transition:color .2s}
a.endpoint:hover{color:var(--accent-deep);text-decoration:underline wavy;text-underline-offset:3px}
.status{flex:none;display:inline-flex;align-items:center;gap:.35rem;padding:.25rem .7rem;border-radius:999px;background:var(--ok-soft);color:#2d9464;font-size:.76rem;font-weight:850}
.status:before{content:"";width:.45rem;height:.45rem;border-radius:50%;background:currentColor;animation:pulse 2s ease-in-out infinite}
.status.off{background:#f3ebe8;color:#a8948d}.status.off:before{animation:none}
.project:has(input[name=enabled]:not(:checked)) .avatar{filter:grayscale(1);opacity:.55}
.edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 .8rem}
.edit-grid .wide{grid-column:1/-1}
.toggle{white-space:nowrap;display:flex;align-items:center;justify-content:space-between;gap:.6rem;min-height:2.9rem;padding:.4rem .5rem .4rem 1rem;border:2px solid var(--line);border-radius:1rem;background:var(--field);color:var(--ink);font-size:.92rem;font-weight:750;cursor:pointer;transition:border-color .2s}
.toggle:hover{border-color:#f0c6b7}
.toggle input{flex:none;appearance:none;-webkit-appearance:none;position:relative;width:2.9rem;height:1.7rem;margin:0;border-radius:999px;background:#ecdcd5;cursor:pointer;transition:background .25s}
.toggle input:after{content:"";position:absolute;top:.2rem;left:.2rem;width:1.3rem;height:1.3rem;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(120,60,40,.28);transition:transform .35s cubic-bezier(.3,1.6,.5,1)}
.toggle input:checked{background:var(--ok)}
.toggle input:checked:after{transform:translateX(1.2rem)}
.toggle input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.actions{display:flex;align-items:center;justify-content:space-between;gap:.75rem;margin-top:auto;padding-top:.4rem}
.inline{display:inline;margin:0}
.project.dirty{border-color:var(--accent);box-shadow:0 0 0 5px var(--accent-soft),var(--shadow)}
.project.dirty .save{animation:nudge 1.6s ease-in-out infinite}
.project.dirty .save:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:#fff}
.project.saved{animation:saved 1.4s ease-out}
.project.saved:after{content:"✓";position:absolute;top:-.9rem;right:-.6rem;display:grid;place-items:center;width:2.3rem;height:2.3rem;border-radius:50%;background:var(--ok);box-shadow:0 6px 14px -4px #4cbf8a;color:#fff;font-weight:900;animation:popout 1.8s cubic-bezier(.3,1.6,.5,1) both}
dialog.modal{width:min(92vw,370px);padding:0;border:0;background:transparent;color:var(--ink);overflow:visible}
dialog.modal::backdrop{background:rgba(92,62,54,.32);backdrop-filter:blur(5px);-webkit-backdrop-filter:blur(5px)}
.modal-card{position:relative;padding:4rem 1.6rem 1.6rem;border-radius:1.8rem;background:var(--solid);box-shadow:0 30px 60px -20px rgba(92,48,38,.5);text-align:center}
dialog[open] .modal-card{animation:pop .4s cubic-bezier(.3,1.5,.5,1)}
.modal-card .mascot{position:absolute;left:50%;top:0;width:6.4rem;margin:-3.4rem 0 0 -3.2rem;animation:tremble .5s ease-in-out infinite alternate}
.modal-card h3{margin:0 0 .3rem;font-size:1.2rem;font-weight:850}
.modal-target{margin:0 0 1.4rem;color:var(--muted);font-size:.92rem;overflow-wrap:anywhere}
.modal-actions{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}
.confetti{position:fixed;z-index:9;width:.6rem;height:.85rem;border-radius:.15rem;pointer-events:none}
@keyframes rise{from{opacity:0;transform:translateY(18px) scale(.96)}}
@keyframes drift{to{transform:translate(3rem,2rem) scale(1.12)}}
@keyframes twinkle{0%,100%{opacity:.35;transform:scale(.8) rotate(0)}50%{opacity:1;transform:scale(1.15) rotate(20deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}
@keyframes sway{0%,100%{transform:rotate(-8deg)}50%{transform:rotate(8deg)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes shake{10%,90%{transform:translateX(-2px)}20%,80%{transform:translateX(4px)}30%,50%,70%{transform:translateX(-7px)}40%,60%{transform:translateX(7px)}}
@keyframes nudge{0%,70%,100%{transform:translateY(0)}80%{transform:translateY(-4px)}90%{transform:translateY(1px)}}
@keyframes saved{0%{box-shadow:0 0 0 0 #4cbf8a88,var(--shadow);border-color:var(--ok)}100%{box-shadow:0 0 0 18px #4cbf8a00,var(--shadow)}}
@keyframes popout{0%{transform:scale(0)}15%{transform:scale(1)}80%{transform:scale(1);opacity:1}100%{transform:scale(.6);opacity:0}}
@keyframes pop{from{opacity:0;transform:scale(.85) translateY(10px)}}
@keyframes tremble{from{transform:rotate(-3deg)}to{transform:rotate(3deg)}}
@media(max-width:720px){.upload{grid-template-columns:1fr}}
@media(max-width:560px){.shell{width:min(100% - 1.25rem,1040px)}.hero{flex-direction:column-reverse;align-items:flex-start;gap:.6rem}.hero .mascot{width:5.5rem}.dashboard-head{align-items:center}.edit-grid{grid-template-columns:1fr}.edit-grid .wide{grid-column:auto}.upload form{flex-direction:column}.actions{align-items:stretch;flex-direction:column}.actions button,.upload button{width:100%}.inline{width:100%}a.card{min-height:180px}}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#241b1a;--dot:#3a2c2a;--ink:#fbece6;--muted:#c4aba3;--line:#453532;--panel:rgba(49,37,35,.84);--solid:#2f2422;--field:#2a201f;--accent:#ff9887;--accent-deep:#d86f5d;--accent-soft:#4a302b;--danger:#ff8c9b;--danger-soft:#4a2a30;--danger-deep:#b94a5b;--ok:#5ccf98;--ok-soft:#23402f;--butter:#6b5424;--shadow:0 18px 40px -18px rgba(0,0,0,.6);--body:#ffbf9c;--body-shade:#f2a47f}
.blob{opacity:.22}.blob.b1{background:#ff8f78}.blob.b2{background:#e9b84a}.blob.b3{background:#4fbf8a}
.tint-0{--tint:#4d302a;--tint-ink:#ffab96}.tint-1{--tint:#463b22;--tint-ink:#f5cf6a}.tint-2{--tint:#23402f;--tint-ink:#7fdcad}.tint-3{--tint:#26344a;--tint-ink:#9cc3ff}.tint-4{--tint:#352c4a;--tint-ink:#c3b0ff}.tint-5{--tint:#4a2a38;--tint-ink:#ff9fc1}
.m-eyes,.m-mouth{fill:#4b3934;stroke:#4b3934}.m-mouth{fill:none}
input:not([type=checkbox]):not([type=file]):hover,.toggle:hover{border-color:#6a4f49}input::placeholder{color:#7c655e}
.toggle input{background:#4a3a36}.status.off{background:#3a2f2d;color:#a8948d}.status{color:#7fdcad}
button.ghost{box-shadow:0 4px 0 #2e1e1b}button.danger{box-shadow:0 4px 0 #2e1a1e}
.upload{background:linear-gradient(135deg,rgba(74,48,43,.85),rgba(70,59,34,.7))}
.drop{border-color:#6a4a42}.drop:hover,.drop.over{background:#3a2a27}.drop.has-file{background:#1f3328}.drop-name:empty:before{color:#7c655e}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
'''
PAGE_JS = '''
(()=>{const $$=(s,r=document)=>[...r.querySelectorAll(s)];
$$('.drop').forEach(z=>{const i=z.querySelector('input'),n=z.querySelector('.drop-name'),set=()=>{const f=i.files[0];z.classList.toggle('has-file',!!f);n.textContent=f?f.name:''};
i.addEventListener('change',set);['dragenter','dragover'].forEach(e=>z.addEventListener(e,()=>z.classList.add('over')));['dragleave','drop'].forEach(e=>z.addEventListener(e,()=>z.classList.remove('over')));set()});
$$('.pw').forEach(w=>{const i=w.querySelector('input'),b=w.querySelector('.eye'),card=w.closest('.login-card');b.addEventListener('click',()=>{const show=i.type==='password';i.type=show?'text':'password';card.classList.toggle('reveal',show);b.setAttribute('aria-pressed',show);i.focus()})});
$$('form[id^="edit-"]').forEach(f=>{const card=f.closest('.project'),snap=()=>JSON.stringify([...new FormData(f)]),start=snap(),check=()=>card.classList.toggle('dirty',snap()!==start);f.addEventListener('input',check);f.addEventListener('change',check)});
const dlg=document.getElementById('confirm-delete');let pending=null;
document.addEventListener('submit',e=>{const f=e.target,b=e.submitter||f.querySelector('button[type=submit]')||document.querySelector(`button[form="${f.id}"]`);
if(f.dataset.confirm&&!f.dataset.ok){e.preventDefault();if(!dlg||!dlg.showModal){if(confirm(f.dataset.confirm)){f.dataset.ok=1;b&&b.classList.add('busy');f.submit()}return}
pending=[f,b];dlg.querySelector('.modal-target').textContent=f.dataset.name||'';dlg.showModal();return}
if(f.id.startsWith('edit-'))sessionStorage.setItem('cp-flash',f.id);if(f.action.endsWith('/admin/upload'))sessionStorage.setItem('cp-confetti','1');b&&b.classList.add('busy')});
dlg&&dlg.addEventListener('close',()=>{if(dlg.returnValue==='ok'&&pending){const[f,b]=pending;f.dataset.ok=1;b&&b.classList.add('busy');f.submit()}pending=null});
dlg&&dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close('cancel')});
const flash=sessionStorage.getItem('cp-flash');sessionStorage.removeItem('cp-flash');const card=flash&&document.getElementById(flash)?.closest('.project');
if(card){card.scrollIntoView({block:'center'});card.classList.add('saved');setTimeout(()=>card.classList.remove('saved'),1900)}
if(sessionStorage.getItem('cp-confetti')&&document.querySelector('.upload')){sessionStorage.removeItem('cp-confetti');if(!matchMedia('(prefers-reduced-motion: reduce)').matches){const r=document.querySelector('.upload').getBoundingClientRect(),c=['#ff8c7a','#ffd166','#7fdcad','#9cc3ff','#c3b0ff','#ff9fc1'];
for(let k=0;k<46;k++){const p=document.createElement('i');p.className='confetti';p.style.background=c[k%c.length];p.style.left=r.left+r.width/2+'px';p.style.top=r.top+r.height/2+'px';document.body.appendChild(p);
const a=Math.random()*Math.PI*2,d=90+Math.random()*190;p.animate([{transform:'translate(0,0) rotate(0)',opacity:1},{transform:`translate(${Math.cos(a)*d}px,${Math.sin(a)*d-60}px) rotate(${Math.random()*720}deg)`,opacity:1,offset:.7},{transform:`translate(${Math.cos(a)*d}px,${Math.sin(a)*d+80}px) rotate(${Math.random()*900}deg)`,opacity:0}],{duration:1300+Math.random()*700,easing:'cubic-bezier(.2,.7,.4,1)'}).onfinish=()=>p.remove()}}}else sessionStorage.removeItem('cp-confetti')})();
'''
LOGO_SVG = '<svg viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="12" fill="#ff8c7a"/><path d="M13 8h11l6 6v16a3 3 0 0 1-3 3H13a3 3 0 0 1-3-3V11a3 3 0 0 1 3-3z" fill="#fff"/><path d="M24 8v4a2 2 0 0 0 2 2h4z" fill="#ffc9b9"/><path d="M15.5 28.5h9" fill="none" stroke="#ffc9b9" stroke-width="2.2" stroke-linecap="round"/><path d="M20 28v-6.5" fill="none" stroke="#4fae7e" stroke-width="2.2" stroke-linecap="round"/><path d="M20 22.5c.4-3.6 3.3-5.7 7-5.3-.4 3.6-3.4 5.6-7 5.3z" fill="#6fca98"/><path d="M20 23.6c-.4-3-2.8-4.6-5.6-4.2.4 3 2.8 4.5 5.6 4.2z" fill="#6fca98"/></svg>'
LOGO_ICON_HREF = "data:image/svg+xml," + quote(LOGO_SVG.replace(' aria-hidden="true"', ' xmlns="http://www.w3.org/2000/svg"'))
def mascot(sad=False):
    mouth = "M53 80q7-7 14 0" if sad else "M53 75q7 7 14 0"
    return f'''<svg class="mascot" viewBox="0 0 120 120" aria-hidden="true"><g class="m-sprout"><path class="m-stem" d="M60 26V12"/><path class="m-leaf" d="M60 14c2-9 10-13 18-11-2 8-9 12-18 11z"/><path class="m-leaf" d="M60 16c-3-7-10-10-16-8 2 6 8 9 16 8z"/></g><path class="m-body" d="M60 24c30 0 50 22 50 50 0 27-20 40-50 40S10 101 10 74c0-28 20-50 50-50z"/><ellipse class="m-shine" cx="36" cy="46" rx="9" ry="5" transform="rotate(-30 36 46)"/><g class="m-eyes"><ellipse cx="46" cy="66" rx="5" ry="6.2"/><ellipse cx="74" cy="66" rx="5" ry="6.2"/></g><circle class="m-glint" cx="47.8" cy="63.6" r="1.7"/><circle class="m-glint" cx="75.8" cy="63.6" r="1.7"/><ellipse class="m-cheek" cx="35" cy="78" rx="7" ry="4.2"/><ellipse class="m-cheek" cx="85" cy="78" rx="7" ry="4.2"/><path class="m-mouth" d="{mouth}"/><g class="m-paws"><ellipse cx="44" cy="106" rx="10" ry="8"/><ellipse cx="76" cy="106" rx="10" ry="8"/></g></svg>'''
def page(title, content):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#fff7f0"><title>{html.escape(title)} · Codex Pages</title><link rel="icon" href="{LOGO_ICON_HREF}"><style>{PAGE_CSS}</style></head><body><div class="ambient" aria-hidden="true"><i class="blob b1"></i><i class="blob b2"></i><i class="blob b3"></i><span class="spark s1">✦</span><span class="spark s2">✿</span><span class="spark s3">✦</span><span class="spark s4">♡</span></div><main class="shell">{content}</main><script>{PAGE_JS}</script></body></html>'''
def topbar(admin=False):
    nav = "" if admin else '<a class="nav-link" href="/admin/">管理</a>'
    return f'''<header class="topbar"><a class="brand" href="/"><span class="logo">{LOGO_SVG}</span><span>Codex Pages</span></a>{nav}</header>'''
def notice(title, detail="", extra="", sad=True):
    return f'''<div class="empty rise">{mascot(sad)}<strong>{title}</strong>{detail}{extra}</div>'''
def login_page(error=False):
    err = '<p class="error" role="alert">密码不正确。</p>' if error else ""
    return page("登录", f'''{topbar()}<div class="login-wrap"><section class="card login-card rise{' shake' if error else ''}">{mascot()}<span class="eyebrow">Private area</span><h1>管理你的部署</h1><p>输入管理密码，查看和维护已发布的项目。</p>{err}<form method="post" action="/admin/login"><label class="field"><span class="label">管理密码</span><span class="pw"><input type="password" name="password" autocomplete="current-password" autofocus required><button class="eye" type="button" aria-label="显示密码" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path class="slash" d="M4 4l16 16"/></svg></button></span></label><button type="submit">进入管理台</button></form></section></div>''')
UPLOAD_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 9.5a4 4 0 0 1-.5 8.5"/><path d="M12 12v8M8.8 15.2 12 12l3.2 3.2"/></svg>'

class App(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True

class Handler(BaseHTTPRequestHandler):
    server_version = "CodexPages/1.0"
    def log_message(self, fmt, *args): print(f"[{self.log_date_time_string()}] {fmt % args}")
    def cookies(self):
        c = SimpleCookie(); c.load(self.headers.get("Cookie", "")); return c
    def authed(self): return valid_token(self.cookies().get("cp_session").value) if self.cookies().get("cp_session") else False
    def send_html(self, body, status=200, cookie=None):
        data = body.encode(); self.send_response(status); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers(); self.wfile.write(data)
    def redirect(self, target, cookie=None): self.send_response(303); self.send_header("Location", target); cookie and self.send_header("Set-Cookie", cookie); self.end_headers()
    def form(self):
        n = int(self.headers.get("Content-Length", 0)); return {k:v[-1] for k,v in parse_qs(self.rfile.read(n).decode()).items()}
    def uploaded_file(self):
        size = int(self.headers.get("Content-Length", 0))
        if size <= 0 or size > 5 * 1024 * 1024: raise ValueError("文件须为 1–5 MB 以内的 HTML 文件")
        match = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', self.headers.get("Content-Type", ""))
        if not match: raise ValueError("未收到有效的上传内容")
        boundary = (match.group(1) or match.group(2)).encode(); raw = self.rfile.read(size)
        for part in raw.split(b"--" + boundary):
            headers, sep, data = part.partition(b"\r\n\r\n")
            if not sep or b'name="file"' not in headers: continue
            found = re.search(br'filename="([^"]*)"', headers)
            if not found: continue
            filename = Path(found.group(1).decode("utf-8", "replace")).name
            return filename, data.rstrip(b"\r\n")
        raise ValueError("请选择一个 HTML 文件")
    def upload_html(self):
        filename, data = self.uploaded_file()
        if Path(filename).suffix.lower() not in (".html", ".htm"): raise ValueError("仅支持 .html 或 .htm 文件")
        if not data: raise ValueError("HTML 文件为空")
        display = Path(filename).stem.strip()[:80] or "未命名页面"
        base = re.sub(r"[^a-z0-9-]+", "-", display.lower()).strip("-") or "page"
        slug, n = base[:56], 2
        while (PROJECTS / slug).exists():
            suffix = f"-{n}"; slug = base[:63-len(suffix)] + suffix; n += 1
        directory = PROJECTS / slug; code = directory / "code"; code.mkdir(parents=True)
        (code / "index.html").write_bytes(data)
        save(directory / "project.json", {"slug":slug,"name":display,"description":"通过管理页面上传","type":"static","wsgi":"app:app","asgi":"app:app","enabled":True,"show_on_home":True,"created_at":int(time.time())})
    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def dispatch(self):
        path = urlsplit(self.path).path
        if path == "/": return self.home()
        if path.startswith("/admin"): return self.admin(path)
        if path.startswith("/p/"): return self.serve_project(path)
        self.send_error(404)
    def home(self):
        shown = [m for _,m in projects() if m.get("enabled") and m.get("show_on_home", True)]
        cards = "".join(f'''<a class="card rise tint-{i % 6}" style="--i:{i}" href="/p/{quote(m["slug"] )}/"><div class="card-top"><span class="avatar" aria-hidden="true">{html.escape(m["name"][:1].upper())}</span><span class="arrow">→</span></div><h2>{html.escape(m["name"])}</h2><p>{html.escape(m.get("description", "") or "点击打开项目")}</p><span class="slug">/{html.escape(m["slug"])}</span></a>''' for i,m in enumerate(shown))
        body=topbar()+f'''<section class="hero"><div class="hero-text rise"><span class="eyebrow">Deployment portal</span><h1><span class="hl">已部署项目</span></h1><p>集中查看和访问已发布的网页、工具与小游戏。</p></div>{mascot()}</section><section class="grid">{cards or notice("暂无已发布项目", "<small>完成项目后，可通过管理页面上传 HTML，或使用 codex-pages deploy 发布。</small>", sad=False)}</section>'''
        self.send_html(page("项目首页", body))
    def admin(self, path):
        if path == "/admin/login" and self.command == "POST":
            f=self.form()
            if hmac.compare_digest(f.get("password", ""), secret()): return self.redirect("/admin/", "cp_session="+token()+"; HttpOnly; SameSite=Strict; Path=/")
            return self.send_html(login_page(error=True), 403)
        if not self.authed(): return self.send_html(login_page())
        if path == "/admin/upload" and self.command == "POST":
            try: self.upload_html()
            except ValueError as e: return self.send_html(page("上传失败", topbar(admin=True)+notice("上传失败", f"<small>{html.escape(str(e))}</small>", '<a class="nav-link" href="/admin/">返回管理页</a>')), 400)
            return self.redirect("/admin/")
        if path == "/admin/edit" and self.command == "POST":
            f=self.form(); slug=f.get("slug", ""); p,m=project(slug)
            if not p: return self.send_error(404)
            m.update(name=f.get("name", m["name"]).strip()[:80], description=f.get("description", "").strip()[:300], enabled=f.get("enabled") == "on", show_on_home=f.get("show_on_home") == "on")
            save(p / "project.json", m); return self.redirect("/admin/")
        if path == "/admin/delete" and self.command == "POST":
            slug=self.form().get("slug", ""); p,_=project(slug)
            if p: stop_backend(slug); shutil.rmtree(p)
            return self.redirect("/admin/")
        rows=[]
        for i,(_,m) in enumerate(projects()):
            slug=html.escape(m["slug"]); checked="checked" if m.get("enabled") else ""; shown="checked" if m.get("show_on_home", True) else ""; state="在线" if m.get("enabled") else "已停用"; off="" if m.get("enabled") else " off"
            rows.append(f'''<section class="card project rise tint-{i % 6}" style="--i:{i}"><div class="project-head"><span class="avatar" aria-hidden="true">{html.escape(m['name'][:1].upper())}</span><div class="project-title"><h2 class="project-name">{html.escape(m['name'])}</h2><a class="endpoint" href="/p/{quote(m['slug'])}/" target="_blank" rel="noopener">/p/{slug}/</a><span class="kind">{html.escape(m['type']).upper()}</span></div><span class="status{off}">{state}</span></div><form id="edit-{slug}" method="post" action="/admin/edit"><input type="hidden" name="slug" value="{slug}"><div class="edit-grid"><label class="field wide"><span class="label">显示名称</span><input name="name" value="{html.escape(m['name'], quote=True)}" required></label><label class="field wide"><span class="label">简介</span><input name="description" value="{html.escape(m.get('description',''), quote=True)}" placeholder="用一句话介绍这个项目"></label><label class="field"><span class="label">状态</span><span class="toggle">对外开放<input type="checkbox" role="switch" name="enabled" {checked}></span></label><label class="field"><span class="label">主页展示</span><span class="toggle">在主页列出<input type="checkbox" role="switch" name="show_on_home" {shown}></span></label></div></form><div class="actions"><button class="save" type="submit" form="edit-{slug}">保存更改</button><form class="inline" method="post" action="/admin/delete" data-confirm="删除此项目及全部文件？" data-name="{html.escape(m['name'], quote=True)}"><input type="hidden" name="slug" value="{slug}"><button class="danger" type="submit">删除项目</button></form></div></section>''')
        upload=f'''<section class="card upload rise"><div><span class="eyebrow">Quick publish</span><h2>上传 HTML 页面</h2><p>选择一个 .html 文件，系统会为它创建独立项目目录和新端点。</p></div><form method="post" action="/admin/upload" enctype="multipart/form-data"><label class="drop"><input type="file" name="file" accept=".html,.htm,text/html" required><span class="drop-icon">{UPLOAD_ICON}</span><span class="drop-name"></span></label><button type="submit">上传并发布</button></form></section>'''
        dialog=f'''<dialog class="modal" id="confirm-delete"><form method="dialog" class="modal-card">{mascot(sad=True)}<h3>删除此项目及全部文件？</h3><p class="modal-target"></p><div class="modal-actions"><button class="ghost" value="cancel">取消</button><button class="danger solid" value="ok">删除项目</button></div></form></dialog>'''
        body=topbar(admin=True)+'''<div class="dashboard-head rise"><div><span class="eyebrow">Deployment management</span><h1>部署管理</h1></div><a class="nav-link" href="/">返回主页</a></div>'''+upload+'<section class="grid projects">'+"".join(rows or [notice("暂无项目", "<small>上传 HTML 文件，或使用 <code>codex-pages deploy</code> 发布项目。</small>", sad=False)])+"</section>"+dialog
        self.send_html(page("部署管理", body))
    def serve_project(self, path):
        rest=path[3:]; slug, _, suffix=rest.partition("/"); p,m=project(slug)
        if not p or not m.get("enabled"): return self.send_error(404)
        code=p / "code"
        if m["type"] == "static":
            target=(code / unquote(suffix or "index.html")).resolve()
            if not str(target).startswith(str(code.resolve())): return self.send_error(403)
            if target.is_dir(): target=target / "index.html"
            if not target.is_file(): return self.send_error(404)
            data=target.read_bytes(); self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        try: port=start_backend(slug, code, m)
        except RuntimeError as e: return self.send_html(page("后端启动失败", topbar()+notice("后端启动失败", f"<pre>{html.escape(str(e))}</pre>")), 502)
        # Preserve the original query string when proxying to WSGI/ASGI apps.
        # `path` is deliberately path-only for route matching, so read it from
        # self.path here rather than from the already-normalized argument.
        query = urlsplit(self.path).query
        url=f"http://127.0.0.1:{port}/"+suffix + (f"?{query}" if query else "")
        try:
            req=urllib.request.Request(url, method=self.command, headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','content-length')}, data=self.rfile.read(int(self.headers.get('Content-Length',0))) if self.command=='POST' else None)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data=resp.read(); self.send_response(resp.status)
                for k,v in resp.headers.items():
                    if k.lower() not in ('connection','transfer-encoding','content-length'): self.send_header(k,v)
                self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data=e.read(); self.send_response(e.code); self.end_headers(); self.wfile.write(data)
        except Exception as e: self.send_html(page("后端不可用", topbar()+notice("后端不可用", f"<pre>{html.escape(str(e))}</pre>")),502)

def external_url(port, slug=None):
    ip = None
    try:
        lines = subprocess.check_output(["ip", "-6", "-o", "addr", "show", "scope", "global"], text=True, stderr=subprocess.DEVNULL).splitlines()
        for line in lines:
            fields=line.split()
            if len(fields) >= 4 and fields[2] == "inet6":
                candidate=fields[3].split("/",1)[0]
                if not candidate.startswith("fe80:"):
                    ip=candidate; break
    except (OSError, subprocess.CalledProcessError): pass
    if not ip:
        try:
            ips=socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6)
            ip=next((x[4][0] for x in ips if not x[4][0].startswith('fe80') and x[4][0] != '::1'), None)
        except socket.gaierror: pass
    ip = ip or "你的IPv6地址"
    return f"http://[{ip}]:{port}/" + (f"p/{slug}/" if slug else "")

def cli():
    ap=argparse.ArgumentParser(prog="codex-pages"); sub=ap.add_subparsers(dest="cmd",required=True)
    d=sub.add_parser("deploy", help="复制一个静态站、WSGI 或 ASGI 项目并发布"); d.add_argument("source"); d.add_argument("--name",required=True); d.add_argument("--description",default=""); d.add_argument("--endpoint"); d.add_argument("--type",choices=("auto","static","wsgi","asgi"),default="auto"); d.add_argument("--wsgi",default="app:app"); d.add_argument("--asgi",default="app:app")
    sub.add_parser("list"); sub.add_parser("url"); sub.add_parser("init")
    rm=sub.add_parser("delete", help="删除已发布项目及其全部文件"); rm.add_argument("endpoint"); rm.add_argument("-y","--yes",action="store_true",help="跳过确认，直接删除")
    pwd=sub.add_parser("admin-password", help="修改管理密码（需要显式确认）"); pwd.add_argument("password"); pwd.add_argument("--confirm", action="store_true", help="确认修改管理密码")
    sub.add_parser("run"); svc=sub.add_parser("install-service"); svc.add_argument("--port",type=int,default=8765, help="首选端口；被占用时自动向上选择")
    a=ap.parse_args()
    PROJECTS.mkdir(exist_ok=True); RUNTIME.mkdir(exist_ok=True)
    if a.cmd=="init":
        if not SECRET.exists(): new_secret()
        print(f"已初始化：{ROOT}\n管理密码：{secret()}\n请立即保存或使用 codex-pages admin-password 设置新密码。\n入口：{external_url(config().get('port',8765))}"); return
    if a.cmd=="admin-password":
        if not a.confirm: raise SystemExit("为防止自动化任务覆盖密码，请使用：codex-pages admin-password <新密码> --confirm")
        new_secret(a.password); print("管理密码已更新："+secret()); return
    if a.cmd=="deploy":
        src=Path(a.source).expanduser().resolve()
        if not src.exists(): raise SystemExit("源路径不存在")
        slug=a.endpoint or re.sub(r"[^a-z0-9-]+","-",a.name.lower()).strip("-")
        if not SLUG.fullmatch(slug): raise SystemExit("端点须为 1–63 位小写字母、数字或连字符")
        dst=PROJECTS/slug
        if dst.exists(): raise SystemExit(f"端点已存在：{slug}（请换 --endpoint）")
        source_text = (src / "app.py").read_text(errors="ignore").lower() if src.is_dir() and (src / "app.py").is_file() else ""
        typ = a.type if a.type != "auto" else ("asgi" if "fastapi" in source_text else "wsgi" if source_text else "static")
        dst.mkdir(); code=dst/"code"; shutil.copytree(src,code) if src.is_dir() else (code.mkdir(), shutil.copy2(src,code/"index.html"))
        save(dst/"project.json", {"slug":slug,"name":a.name,"description":a.description,"type":typ,"wsgi":a.wsgi,"asgi":a.asgi,"enabled":True,"show_on_home":True,"created_at":int(time.time())})
        print("已发布："+external_url(config().get('port',8765),slug)); return
    if a.cmd=="delete":
        p,m=project(a.endpoint)
        if not p: raise SystemExit(f"项目不存在：{a.endpoint}")
        if not a.yes:
            reply=input(f"确定删除项目「{m['name']}」（/p/{a.endpoint}/）及其全部文件？此操作不可恢复 [y/N] ").strip().lower()
            if reply not in ("y","yes"): print("已取消"); return
        stop_backend(a.endpoint); shutil.rmtree(p)
        print(f"已删除：{a.endpoint}"); return
    if a.cmd=="list":
        for _,m in projects(): print(f"{m['slug']:20} {'on ' if m.get('enabled') else 'off'} {m['type']:6} {m['name']}")
        return
    if a.cmd=="url": print(external_url(config().get('port',8765))); return
    if a.cmd=="install-service":
        selected=choose_port(a.port)
        save(CONFIG,{"port":selected}); unit=Path.home()/".config/systemd/user/codex-pages.service"; unit.parent.mkdir(parents=True,exist_ok=True)
        unit.write_text(f"[Unit]\nDescription=Codex Pages\nAfter=network-online.target\n\n[Service]\nExecStart={sys.executable} {ROOT/'portal.py'} run\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n")
        subprocess.run(["systemctl","--user","daemon-reload"],check=True); subprocess.run(["systemctl","--user","enable","--now","codex-pages.service"],check=True)
        print("服务已启动："+external_url(selected)); return
    if a.cmd=="run":
        port=config().get("port",8765); print("Serving "+external_url(port)); App(("::",port),Handler).serve_forever()
if __name__ == "__main__": cli()
