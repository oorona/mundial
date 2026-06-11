"""LLM Configs storage API — editable structured-output schemas and
function-calling sets, managed from the dashboard (Developer / L6).

Mounted at /api/v1/gemini. Backs the LLM Configs page (api-client.ts:
listLlmSchemas / getLlmSchema / upsertLlmSchema / deleteLlmSchema and the
function-set equivalents). Shapes match that frontend contract verbatim:

  GET    /gemini/schemas              -> {"schemas":       [{id,name,description}, ...]}
  GET    /gemini/schemas/{id}         -> full object {id,name,description, schema:{...}}
  POST   /gemini/schemas/{id}         -> saved object  (body = whole posted JSON)
  DELETE /gemini/schemas/{id}         -> {"ok": true}
  GET    /gemini/function-sets        -> {"function_sets": [{id,name,description}, ...]}
  GET    /gemini/function-sets/{id}   -> full object {id,name,description, functions:[...]}
  POST   /gemini/function-sets/{id}   -> saved object
  DELETE /gemini/function-sets/{id}   -> {"ok": true}

llm_schemas / llm_function_sets are GLOBAL tables (no RLS); read/written via
get_db (RLS-bypassed). The 3 read-only built-in schema files under
backend/schemas/*.json are unioned into the schema list/read (DB rows win on id).
"""
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_platform_admin
from app.db.session import get_db
from app.models import LlmSchema, LlmFunctionSet

router = APIRouter()

# Read-only built-in structured-output schemas shipped with the backend.
_SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"


def _builtin_schemas() -> Dict[str, dict]:
    """{id: full_object} for the bundled backend/schemas/*.json files."""
    out: Dict[str, dict] = {}
    if not _SCHEMAS_DIR.exists():
        return out
    for f in sorted(_SCHEMAS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        sid = data.get("id") or f.stem
        data.setdefault("id", sid)
        out[sid] = data
    return out


def _summary(sid: str, obj: dict) -> dict:
    return {"id": sid, "name": obj.get("name") or sid, "description": obj.get("description", "")}


# ── Schemas ────────────────────────────────────────────────────────────────

@router.get("/schemas")
async def list_schemas(db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    items: Dict[str, dict] = {sid: _summary(sid, obj) for sid, obj in _builtin_schemas().items()}
    rows = (await db.execute(select(LlmSchema))).scalars().all()
    for r in rows:  # DB rows override built-ins of the same id
        items[r.id] = {"id": r.id, "name": r.name or r.id, "description": r.description or ""}
    return {"schemas": list(items.values())}


@router.get("/schemas/{schema_id}")
async def get_schema(schema_id: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    row = await db.get(LlmSchema, schema_id)
    if row:
        return row.body
    builtin = _builtin_schemas().get(schema_id)
    if builtin is not None:
        return builtin
    raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")


@router.post("/schemas/{schema_id}")
async def upsert_schema(
    schema_id: str,
    body: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    body.setdefault("id", schema_id)  # keep body.id consistent with the path
    name = body.get("name") or schema_id
    description = body.get("description") or ""
    row = await db.get(LlmSchema, schema_id)
    if row:
        row.name, row.description, row.body = name, description, body
    else:
        db.add(LlmSchema(id=schema_id, name=name, description=description, body=body))
    await db.commit()
    return body


@router.delete("/schemas/{schema_id}")
async def delete_schema(schema_id: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    row = await db.get(LlmSchema, schema_id)
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}


# ── Function sets ──────────────────────────────────────────────────────────

@router.get("/function-sets")
async def list_function_sets(db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    rows = (await db.execute(select(LlmFunctionSet))).scalars().all()
    return {"function_sets": [{"id": r.id, "name": r.name or r.id, "description": r.description or ""} for r in rows]}


@router.get("/function-sets/{set_id}")
async def get_function_set(set_id: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    row = await db.get(LlmFunctionSet, set_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Function set '{set_id}' not found")
    return row.body


@router.post("/function-sets/{set_id}")
async def upsert_function_set(
    set_id: str,
    body: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    body.setdefault("id", set_id)
    name = body.get("name") or set_id
    description = body.get("description") or ""
    row = await db.get(LlmFunctionSet, set_id)
    if row:
        row.name, row.description, row.body = name, description, body
    else:
        db.add(LlmFunctionSet(id=set_id, name=name, description=description, body=body))
    await db.commit()
    return body


@router.delete("/function-sets/{set_id}")
async def delete_function_set(set_id: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(verify_platform_admin)):
    row = await db.get(LlmFunctionSet, set_id)
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}
