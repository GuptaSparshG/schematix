"""Draft Studio — STL → 2D engineering drawing service.

Self-contained submodule: rendering pipeline + history store + FastAPI routes.
Import `router` and include it in the main FastAPI app.
"""

from server.draft_studio.routes import router

__all__ = ["router"]
