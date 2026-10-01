#!/usr/bin/env python3
import importlib, sys
from wsgiref.simple_server import make_server
from pathlib import Path
path, port, spec = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, path)
module, name = spec.split(":", 1)
app = getattr(importlib.import_module(module), name)
make_server("127.0.0.1", port, app).serve_forever()
