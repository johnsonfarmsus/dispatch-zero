"""require_admin dependency for the /admin/* router.

Sits on top of current_user (which already enforces session validity).
If the authenticated user isn't flagged is_admin, raise 404 — not 403.
The 404 posture matches how share routes and other unguessable resources
behave elsewhere in the app: rather than revealing "this surface exists
but you can't use it," we make it look like the route doesn't exist at all.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status

from dispatchzero.auth.deps import current_user
from dispatchzero.models import User


async def require_admin(
    user: Annotated[User, Depends(current_user)],
) -> User:
    if not user.is_admin:
        # 404 not 403 — see module docstring.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return user
