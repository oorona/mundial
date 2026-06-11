from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from typing import Dict, Any, Optional
from pydantic import BaseModel
import structlog

from app.db.session import get_db
from app.models import User
from app.api.deps import get_current_user

router = APIRouter()
logger = structlog.get_logger()

class UserSettingsUpdate(BaseModel):
    theme: Optional[str] = None
    language: Optional[str] = None
    default_guild_id: Optional[str] = None

@router.get("/me/settings")
async def get_user_settings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get current user settings."""
    user = await db.get(User, int(current_user["user_id"]))
    if not user:
        raise HTTPException(404, "User not found")
    
    return {
        "user_id": str(user.id),
        "settings": user.preferences or {}
    }

@router.put("/me/settings")
async def update_user_settings(
    settings: UserSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update user settings."""
    user_id = int(current_user["user_id"])
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
        
    # Merge existing preferences with updates
    current_prefs = user.preferences or {}
    updates = settings.dict(exclude_unset=True)
    
    current_prefs.update(updates)
    
    # Use direct update statement to ensure persistence
    stmt = update(User).where(User.id == user_id).values(preferences=current_prefs)
    await db.execute(stmt)
    await db.commit()
    
    # Refresh to return
    await db.refresh(user)
    
    return {
        "user_id": str(user.id),
        "settings": user.preferences
    }
