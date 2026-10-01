#!/usr/bin/env python3
"""Run an ASGI project (FastAPI, Starlette, etc.) on the private loopback port."""
import importlib, sys

path, port, spec = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, path)
module, name = spec.split(":", 1)
try:
    import uvicorn
except ImportError:
    print("ASGI requires uvicorn. Install it with: uv pip install uvicorn fastapi", file=sys.stderr)
    raise SystemExit(1)
app = getattr(importlib.import_module(module), name)
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
