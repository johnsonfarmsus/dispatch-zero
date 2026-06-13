"""Badge surface — GET /badges for the current user's computed badge set."""
from dispatchzero.badges.routes import router as badges_router

__all__ = ["badges_router"]
