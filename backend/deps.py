from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .auth import get_user_id_from_session
from .database import get_db
from .models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = get_user_id_from_session(request)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user session")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def require_health_professional(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "health_professional":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Health Professional access required")
    return current_user
