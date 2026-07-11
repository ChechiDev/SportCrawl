"""Work server package.

Public API:
- create_app: build a configured aiohttp Application (for testing and composition root)
- serve: async composition root (AppRunner + JobLoop, drives the event loop)
"""

from infrastructure.work_server.runtime import serve
from infrastructure.work_server.server import create_app

__all__ = ["create_app", "serve"]
