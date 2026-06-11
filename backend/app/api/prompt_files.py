"""
Prompt Files API — CRUD for plugin prompt files on the shared data volume.

All routes require DEVELOPER permission (Level 5).

Route structure mirrors the on-disk layout:
  /data/prompts/{plugin_name}/{context_name}/{file_name}.txt

Endpoints
─────────
  GET  /prompts/                                          list all plugins
  GET  /prompts/{plugin}                                  list contexts for a plugin
  GET  /prompts/{plugin}/{context}                        list files in a context
  GET  /prompts/{plugin}/{context}/{file}                 get file content + meta
  PUT  /prompts/{plugin}/{context}/{file}                 save new content
  POST /prompts/{plugin}/{context}/{file}/reset           reset to manifest default
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import verify_platform_admin
from app.services.prompt_files import (
    PromptFileService,
    PromptFileMeta,
    PluginNotFoundError,
    ContextNotFoundError,
    PromptNotFoundError,
)

router = APIRouter()
_svc = PromptFileService()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PromptSaveRequest(BaseModel):
    content: str


class PromptFileResponse(BaseModel):
    plugin_name: str
    context_name: str
    name: str
    label: str
    description: str
    content: str


# ── Error helpers ─────────────────────────────────────────────────────────────

def _404(detail: str) -> HTTPException:
    return HTTPException(404, detail)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_all_plugins(_: dict = Depends(verify_platform_admin)):
    """List every plugin that has registered prompt files, with all their contexts."""
    return {"plugins": [g.to_dict() for g in _svc.list_plugins()]}


@router.get("/{plugin_name}")
async def list_plugin_contexts(
    plugin_name: str,
    _: dict = Depends(verify_platform_admin),
):
    """List all contexts (purpose folders) for a plugin."""
    try:
        manifest = _svc.get_manifest(plugin_name)
    except PluginNotFoundError as e:
        raise _404(str(e))

    from app.services.prompt_files import PromptContext
    contexts = [PromptContext(plugin_name, c).to_dict() for c in manifest.get("contexts", [])]
    return {
        "plugin_name": plugin_name,
        "display_name": manifest.get("display_name", plugin_name),
        "contexts": contexts,
    }


@router.get("/{plugin_name}/{context_name}")
async def list_context_files(
    plugin_name: str,
    context_name: str,
    _: dict = Depends(verify_platform_admin),
):
    """List all prompt files declared for a context, without their content."""
    try:
        manifest = _svc.get_manifest(plugin_name)
    except PluginNotFoundError as e:
        raise _404(str(e))

    from app.services.prompt_files import ContextNotFoundError as CNF, PromptContext
    try:
        ctx_entry = next(c for c in manifest.get("contexts", []) if (c.get("context") or c.get("name")) == context_name)
    except StopIteration:
        raise _404(f"Context '{context_name}' not found in plugin '{plugin_name}'")

    ctx = PromptContext(plugin_name, ctx_entry)
    return {
        "plugin_name": plugin_name,
        "context_name": context_name,
        "label": ctx.label,
        "description": ctx.description,
        "files": [f.to_dict() for f in ctx.files],
    }


@router.get("/{plugin_name}/{context_name}/{file_name}")
async def get_prompt_file(
    plugin_name: str,
    context_name: str,
    file_name: str,
    _: dict = Depends(verify_platform_admin),
):
    """Return the current content and metadata of a single prompt file."""
    try:
        meta = _svc.get_file_meta(plugin_name, context_name, file_name)
        content = _svc.get_file(plugin_name, context_name, file_name)
    except PluginNotFoundError as e:
        raise _404(str(e))
    except ContextNotFoundError as e:
        raise _404(str(e))
    except PromptNotFoundError as e:
        raise _404(str(e))

    return PromptFileResponse(
        plugin_name=plugin_name,
        context_name=context_name,
        name=meta.name,
        label=meta.label,
        description=meta.description,
        content=content,
    )


@router.put("/{plugin_name}/{context_name}/{file_name}")
async def save_prompt_file(
    plugin_name: str,
    context_name: str,
    file_name: str,
    body: PromptSaveRequest,
    _: dict = Depends(verify_platform_admin),
):
    """Overwrite a prompt file with new content."""
    try:
        _svc.save_file(plugin_name, context_name, file_name, body.content)
    except PluginNotFoundError as e:
        raise _404(str(e))
    except ContextNotFoundError as e:
        raise _404(str(e))
    except PromptNotFoundError as e:
        raise _404(str(e))
    return {"ok": True, "plugin_name": plugin_name, "context_name": context_name, "name": file_name}


@router.post("/{plugin_name}/{context_name}/{file_name}/reset")
async def reset_prompt_file(
    plugin_name: str,
    context_name: str,
    file_name: str,
    _: dict = Depends(verify_platform_admin),
):
    """Reset a prompt file to the default stored in its manifest."""
    try:
        default = _svc.reset_file(plugin_name, context_name, file_name)
    except PluginNotFoundError as e:
        raise _404(str(e))
    except ContextNotFoundError as e:
        raise _404(str(e))
    except PromptNotFoundError as e:
        raise _404(str(e))
    return {"ok": True, "plugin_name": plugin_name, "context_name": context_name, "name": file_name, "content": default}
