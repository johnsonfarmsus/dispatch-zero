"""Admin surface — community-submission review queue.

Routes live under /admin/* and are gated by the `is_admin` flag on the
authenticated user. Non-admins get a 404 (NOT 403) so the surface area
doesn't reveal itself to randos who happen to know the route name.
Promote a user via:

    python -m dispatchzero.tools.user_admin promote <callsign>

The review surface is intentionally bare — list pending, approve, return.
Heavy moderation features (notes per category, batch actions, audit log)
can be layered on top later if the queue ever gets big enough to warrant
them. Today it's a one-admin game.
"""
from dispatchzero.admin.routes import router as admin_router

__all__ = ["admin_router"]
