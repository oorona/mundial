# Adding Backend API Endpoints

This guide explains how to add new REST API endpoints to the FastAPI backend.

## Overview

The backend uses FastAPI with:
- **PostgreSQL** for data storage
- **Redis** for sessions and caching
- **SQLAlchemy** for ORM (async)
- **Alembic** for migrations
- **Pydantic** for validation

---

## Security Level — Decide First

**Before writing a single line of code**, decide the security level of your endpoint. See `docs/SECURITY.md` for the full model. Every endpoint must be explicitly assigned one of these levels:

| Level | Dependency to use | When |
|-------|-------------------|------|
| **L0/L1 Public** | No auth dependency | Read-only public data (no PII, no guild data) |
| **L2 User** | `Depends(get_current_user)` | Any authenticated user; still check guild membership |
| **L3 Authorized** | `Depends(get_current_user)` + guild auth check | Write operations, bot settings |
| **L4 Administrator** | `Depends(get_current_user)` + admin check | Add/remove authorized users and roles |
| **L5 Owner** | `Depends(get_current_user)` + owner check | Destructive / billing / permission management |
| **L6 Developer** | `Depends(verify_platform_admin)` | Cross-guild platform operations |

> **Default to L3 when unsure.** It is easier to relax security than to tighten it after data has been exposed.

---

## Step 1: Define Your Data Model

Create or update models in `backend/app/models.py`:

```python
from sqlalchemy import Column, String, BigInteger, DateTime, JSON
from sqlalchemy.sql import func
from app.db.base import Base                  # ← always use this path
from app.db.mixins import GuildScopedMixin    # ← adds guild_id + RLS marker

class CustomFeature(GuildScopedMixin, Base):  # ← GuildScopedMixin first
    __tablename__ = "custom_features"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    config = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

> Use `GuildScopedMixin` (from `app.db.mixins`) instead of manually adding `guild_id` and `__guild_scoped__ = True`. The mixin adds both the column and the RLS marker in one step, ensuring consistent guild isolation across all models. Never import `Base` from `.db.session` — the correct path is `app.db.base`.

## Step 2: Create Database Migration

```bash
# Auto-generate migration
docker compose exec backend alembic revision --autogenerate -m "add_custom_feature"

# Apply migration
docker compose exec backend alembic upgrade head
```

## Step 3: Define Pydantic Schemas

Create schemas in `backend/app/schemas.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class CustomFeatureCreate(BaseModel):
    name: str = Field(..., max_length=100)
    config: dict = {}

class CustomFeature(CustomFeatureCreate):
    id: int
    guild_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

## Step 4: Create API Router

Create a new router file in `backend/app/api/`:

```python
# backend/app/api/custom_features.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..db.guild_session import get_guild_db      # use for guild-scoped endpoints
from ..models import CustomFeature as CustomFeatureModel, Guild, AuditLog
from ..schemas import CustomFeature, CustomFeatureCreate
from .deps import get_current_user

router = APIRouter()

@router.get("/{guild_id}/features")
async def list_features(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),       # RLS active
    current_user: dict = Depends(get_current_user)  # L2: must be logged in
):
    """List all custom features for a guild."""
    user_id = int(current_user["user_id"])

    # L3: verify the user is authorized for this guild
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    if guild.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(CustomFeatureModel).where(CustomFeatureModel.guild_id == guild_id)
    )
    return result.scalars().all()


@router.post("/{guild_id}/features", status_code=201)
async def create_feature(
    guild_id: int,
    feature: CustomFeatureCreate,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new custom feature."""
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild or guild.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    new_feature = CustomFeatureModel(guild_id=guild_id, **feature.model_dump())
    db.add(new_feature)

    # Audit log — required for all write operations (see Security Rules)
    db.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        action="CREATE_CUSTOM_FEATURE",
        details={"name": feature.name}
    ))

    await db.commit()

    # ✅ CORRECT: re-query after commit to get server-generated fields (id, created_at)
    # ❌ WRONG:  await db.refresh(new_feature)  ← raises InvalidRequestError in async SQLAlchemy
    result = await db.execute(
        select(CustomFeatureModel).where(CustomFeatureModel.id == new_feature.id)
    )
    return result.scalar_one()


@router.delete("/{guild_id}/features/{feature_id}")
async def delete_feature(
    guild_id: int,
    feature_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a custom feature."""
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild or guild.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    feature = await db.get(CustomFeatureModel, feature_id)
    if not feature or feature.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Feature not found")

    await db.delete(feature)
    db.add(AuditLog(
        guild_id=guild_id,
        user_id=user_id,
        action="DELETE_CUSTOM_FEATURE",
        details={"feature_id": feature_id}
    ))
    await db.commit()

    return {"message": "Feature deleted"}
```

## Step 5: Register the Router

Add your router to `backend/main.py`:

```python
from app.api.custom_features import router as custom_features_router

app.include_router(
    custom_features_router,
    prefix=f"{settings.API_V1_STR}/guilds",
    tags=["custom_features"]
)
```

## Step 6: Restart Backend

```bash
docker compose restart backend
```

---

## Security Rules for Every New Endpoint

These rules are non-negotiable. See `docs/SECURITY.md` for the full model. Use this as a checklist before merging.

### Rule 1 — Assign a level and document it at the top of the file

Every router file must declare the security level of each route in its module docstring or inline comments:

```python
"""
GET  /guilds/{guild_id}/features    L2 — User: read-only, any authenticated user
POST /guilds/{guild_id}/features    L3 — Authorized: guild owner or admin
DELETE /guilds/{guild_id}/features  L5 — Owner: guild owner only
"""
```

### Rule 2 — Backend auth is mandatory; frontend is UX only

A user can call your API with `curl` and bypass the frontend entirely. The backend must enforce all permission checks independently.

```python
# WRONG — trusts the frontend to have blocked non-owners
@router.delete("/{guild_id}/features/{feature_id}")
async def delete_feature(guild_id: int, feature_id: int):
    await db.delete(...)  # anyone can call this!

# CORRECT — backend enforces ownership
@router.delete("/{guild_id}/features/{feature_id}")
async def delete_feature(
    guild_id: int,
    feature_id: int,
    current_user: dict = Depends(get_current_user)
):
    guild = await db.get(Guild, guild_id)
    if guild.owner_id != int(current_user["user_id"]):
        raise HTTPException(status_code=403, detail="Guild owner only")
    ...
```

### Rule 3 — Always validate guild membership

Never trust the `guild_id` in the URL. Any authenticated user can send any `guild_id` value.

```python
# WRONG — any logged-in user reads any guild's data
@router.get("/{guild_id}/secret")
async def get_secret(guild_id: int, current_user: dict = Depends(get_current_user)):
    return await db.get(Secret, guild_id)

# CORRECT
@router.get("/{guild_id}/secret")
async def get_secret(
    guild_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_guild_db)   # RLS enforced at DB level
):
    user_id = int(current_user["user_id"])
    auth = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id
        )
    )
    if not auth.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized for this guild")
    ...
```

### Rule 4 — Use `get_guild_db` (not `get_db`) for guild-scoped data

`get_guild_db` activates PostgreSQL Row-Level Security. Even a query bug cannot leak data between guilds.

```python
# WRONG — no RLS, a bug could return any guild's rows
db: AsyncSession = Depends(get_db)

# CORRECT — RLS enforced at the database layer
db: AsyncSession = Depends(get_guild_db)
```

### Rule 5 — Write an audit log entry for every mutation

Any endpoint that creates, updates, or deletes data must produce an audit log row. This is the only way guild owners can track what changed and when.

```python
db.add(AuditLog(
    guild_id=guild_id,
    user_id=int(current_user["user_id"]),
    action="UPDATE_FEATURE",           # SCREAMING_SNAKE_CASE, descriptive verb
    details={"before": old, "after": new.model_dump()}
))
await db.commit()
```

### Rule 6 — Never use `db.refresh()` after commit

`Session.refresh()` raises `InvalidRequestError` in async SQLAlchemy when called on a newly-inserted instance after commit, because the instance's attributes are expired and the session state is unreliable. Always re-query instead:

```python
# WRONG — crashes with InvalidRequestError on new instances
await db.commit()
await db.refresh(obj)
return obj

# CORRECT — fresh SELECT after commit
await db.commit()
result = await db.execute(select(Model).where(Model.id == obj.id))
return result.scalar_one()
```

### Rule 7 — Use strict Pydantic schemas

Avoid accepting raw `dict` or `Any` types for sensitive inputs. Define explicit fields with type constraints.

```python
# WRONG — accepts any payload
class Settings(BaseModel):
    config: Dict[str, Any]

# CORRECT — typed and bounded
class FeatureSettings(BaseModel):
    enabled: bool
    channel_id: Optional[int] = None
    label: str = Field(default="", max_length=64, pattern=r"^[\w\s-]*$")
```

### Rule 8 — L1 endpoints must return only public, non-sensitive data

L0/L1 endpoints have no authentication. They must never return:
- User IDs, Discord IDs, or tokens
- Guild owner information
- Internal configuration values
- Stack traces or internal error details

```python
# WRONG — leaks owner ID in a public endpoint
@router.get("/guilds/{guild_id}/public")
async def public_info(guild_id: int):
    guild = await db.get(Guild, guild_id)
    return guild  # exposes owner_id, internal fields

# CORRECT — return only what is safe to be public
@router.get("/guilds/{guild_id}/public")
async def public_info(guild_id: int):
    guild = await db.get(Guild, guild_id)
    return {"name": guild.name, "member_count": guild.member_count}
```

---

## Session / Database Reference

| Dependency | When to use |
|-----------|-------------|
| `get_db` | Non-guild tables: users, shards, platform config |
| `get_guild_db` | Any endpoint with a `guild_id` parameter |
| `get_admin_db` | Cross-guild platform admin endpoints (L6 only) |
| `get_redis` | Caching, session lookup, pub/sub |

---

## Advanced Patterns

### Pagination

```python
from fastapi import Query

@router.get("/items")
async def list_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=100),
    db: AsyncSession = Depends(get_guild_db)
):
    result = await db.execute(
        select(Item).offset(skip).limit(limit)
    )
    return result.scalars().all()
```

### Caching with Redis

```python
from app.db.redis import get_redis
from redis.asyncio import Redis
import json

CACHE_KEY = "my:data:{guild_id}"
CACHE_TTL = 300  # seconds

@router.get("/{guild_id}/data")
async def get_data(
    guild_id: int,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    key = CACHE_KEY.format(guild_id=guild_id)
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    data = await db.execute(select(MyModel).where(MyModel.guild_id == guild_id))
    result = [row.to_dict() for row in data.scalars().all()]
    await redis.setex(key, CACHE_TTL, json.dumps(result))
    return result
```

### Structured Logging

```python
import structlog
logger = structlog.get_logger()

@router.post("/{guild_id}/features")
async def create_feature(guild_id: int, feature: FeatureCreate, ...):
    ...
    logger.info("feature_created", guild_id=guild_id, feature_id=new_feature.id, user_id=user_id)
```

---

## Testing Your Endpoint

### Using curl

```bash
# List features
curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:8000/api/v1/guilds/123/features

# Create feature
curl -X POST \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name": "test", "config": {}}' \
     http://localhost:8000/api/v1/guilds/123/features
```

### Using Interactive Docs

Visit http://localhost:8000/docs to test your endpoints interactively.

### Writing Unit Tests

Follow the pattern in `backend/tests/test_commands.py` and `backend/tests/test_guild_details.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_list_features_success():
    from app.api.custom_features import list_features
    from app.models import Guild, CustomFeature

    mock_db = AsyncMock()
    mock_db.get.return_value = Guild(id=1, owner_id=42)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [
        CustomFeature(id=1, guild_id=1, name="feat-a", config={})
    ]

    result = await list_features(
        guild_id=1,
        db=mock_db,
        current_user={"user_id": "42"}
    )

    assert len(result) == 1
    assert result[0].name == "feat-a"


@pytest.mark.asyncio
async def test_list_features_wrong_user_raises_403():
    from app.api.custom_features import list_features
    from app.models import Guild
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_db.get.return_value = Guild(id=1, owner_id=99)  # different owner

    with pytest.raises(HTTPException) as exc:
        await list_features(guild_id=1, db=mock_db, current_user={"user_id": "42"})

    assert exc.value.status_code == 403
```

---

## Security Checklist

Before submitting a new endpoint for review:

- [ ] Security level is documented in the module docstring
- [ ] `get_current_user` or `verify_platform_admin` dependency is present (unless truly L0/L1)
- [ ] Guild membership is validated (not just assumed from the URL)
- [ ] `get_guild_db` is used instead of `get_db` for guild data
- [ ] An `AuditLog` entry is written for every mutation
- [ ] Pydantic schema has typed fields and max lengths on strings
- [ ] `db.refresh()` is not used — re-query after commit instead
- [ ] L1/L0 endpoints return no PII, IDs, or internal values
- [ ] Unit tests cover at least: success path, wrong user (403), not found (404)

## Next Steps

- See `docs/integration/05-frontend-pages.md` to consume your API
- See `docs/SECURITY.md` for the complete security model
- Review existing routers in `backend/app/api/`
- Read [FastAPI documentation](https://fastapi.tiangolo.com/)
