"""HTTP Adapter：REST + SSE 接入。"""

from __future__ import annotations

from .app import create_app
from .server import start

__all__ = ["create_app", "start"]
