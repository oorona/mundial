"""
PromptFileService — manages plugin prompt files on the shared data volume.

Directory layout
────────────────
  /data/prompts/
    {plugin_name}/
      manifest.json                          ← written at install time, never by this service
      {context_name}/                        ← PURPOSE goes in the folder name
        system_prompt.txt                    ← ROLE goes in the file name
        user_prompt.txt

Naming rules (enforced by the validator):
  • The context folder name encodes PURPOSE  — e.g. "ticket_intake", "faq_answers"
  • The file name encodes ROLE in the LLM call — must be one of VALID_FILE_NAMES
  • Do NOT encode purpose in the file name (wrong: "agent_system.txt", "welcome.txt")
  • Do NOT use a flat layout with descriptive names instead of context subfolders

The "context" is a purpose identifier chosen by the plugin: "ticket_intake",
"faq_answers", "dm_support", etc. Each context groups the prompts that belong
to one LLM interaction pattern so it is clear what they are used for.

manifest.json schema
────────────────────
  {
    "plugin_name":  "ticketnode",
    "display_name": "Ticket Node",
    "contexts": [
      {
        "name":        "ticket_intake",
        "label":       "Ticket Intake",
        "description": "Handles DM messages when a user opens a ticket.",
        "files": [
          {
            "name":        "system_prompt",
            "label":       "System Prompt",
            "description": "Controls the AI assistant's persona for this context.",
            "default":     "You are a helpful ticket assistant..."
          },
          {
            "name":        "user_prompt",
            "label":       "User Prompt Template",
            "description": "Template applied to each user message. Use {message} and {username}.",
            "default":     "{message}"
          }
        ]
      }
    ]
  }

Required file names — the validator rejects any name not in this set:
  system_prompt  → system-level instruction for the LLM
  user_prompt    → template applied to each incoming user message
  assistant_prompt → pre-seeded assistant turn (for few-shot examples)
  injection      → content injected mid-conversation (RAG snippets, tool results)
  context        → background context prepended to the conversation
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

PROMPTS_BASE = Path("/data/prompts")

VALID_FILE_NAMES = {"system_prompt", "user_prompt", "assistant_prompt", "injection", "context"}


class PromptNotFoundError(Exception):
    pass


class ContextNotFoundError(Exception):
    pass


class PluginNotFoundError(Exception):
    pass


# ── Public data shapes ────────────────────────────────────────────────────────

class PromptFileMeta:
    """Metadata for one file within a context (e.g. system_prompt inside ticket_intake)."""

    def __init__(self, plugin_name: str, context_name: str, entry: dict):
        self.plugin_name = plugin_name
        self.context_name = context_name
        self.name: str = entry["name"]               # filename stem, no extension
        self.label: str = entry.get("label", self.name)
        self.description: str = entry.get("description", "")
        self.default: str = entry.get("default", "")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
        }


class PromptContext:
    """One named purpose within a plugin — groups its related prompt files."""

    def __init__(self, plugin_name: str, entry: dict):
        self.plugin_name = plugin_name
        # Context entries are keyed "context" (plugin.json convention, copied verbatim
        # into manifest.json by the installer). Fall back to "name" for older shapes.
        self.name: str = entry.get("context") or entry["name"]
        self.label: str = entry.get("label", self.name)
        self.description: str = entry.get("description", "")
        self.files: List[PromptFileMeta] = [
            PromptFileMeta(plugin_name, self.name, f) for f in entry.get("files", [])
        ]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "files": [f.to_dict() for f in self.files],
        }


class PluginPromptGroup:
    """All contexts and files for one plugin."""

    def __init__(self, plugin_name: str, display_name: str, contexts: List[PromptContext]):
        self.plugin_name = plugin_name
        self.display_name = display_name
        self.contexts = contexts

    def to_dict(self) -> dict:
        return {
            "plugin_name": self.plugin_name,
            "display_name": self.display_name,
            "contexts": [c.to_dict() for c in self.contexts],
        }


# ── Service ───────────────────────────────────────────────────────────────────

class PromptFileService:

    def _plugin_dir(self, plugin_name: str) -> Path:
        return PROMPTS_BASE / plugin_name

    def _manifest_path(self, plugin_name: str) -> Path:
        return self._plugin_dir(plugin_name) / "manifest.json"

    def _context_dir(self, plugin_name: str, context_name: str) -> Path:
        return self._plugin_dir(plugin_name) / context_name

    def _file_path(self, plugin_name: str, context_name: str, file_name: str) -> Path:
        return self._context_dir(plugin_name, context_name) / f"{file_name}.txt"

    # ── Read manifest helpers ─────────────────────────────────────────────────

    def _read_manifest(self, plugin_name: str) -> dict:
        path = self._manifest_path(plugin_name)
        if not path.exists():
            raise PluginNotFoundError(f"No prompt manifest for plugin '{plugin_name}'")
        return json.loads(path.read_text())

    def _get_context_entry(self, manifest: dict, context_name: str) -> dict:
        for ctx in manifest.get("contexts", []):
            if (ctx.get("context") or ctx.get("name")) == context_name:
                return ctx
        raise ContextNotFoundError(
            f"Context '{context_name}' not declared in plugin '{manifest.get('plugin_name', '?')}'"
        )

    def _get_file_entry(self, ctx_entry: dict, file_name: str) -> dict:
        for f in ctx_entry.get("files", []):
            if f["name"] == file_name:
                return f
        raise PromptNotFoundError(
            f"File '{file_name}' not declared in context '{ctx_entry.get('name', '?')}'"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def list_plugins(self) -> List[PluginPromptGroup]:
        """Return all plugins that have a manifest.json under PROMPTS_BASE."""
        groups: List[PluginPromptGroup] = []
        if not PROMPTS_BASE.exists():
            return groups
        for child in sorted(PROMPTS_BASE.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                # Build contexts inside the try so one malformed manifest can't 500
                # the whole list endpoint.
                contexts = [PromptContext(child.name, c) for c in manifest.get("contexts", [])]
            except (json.JSONDecodeError, OSError, KeyError):
                continue
            groups.append(PluginPromptGroup(
                plugin_name=child.name,
                display_name=manifest.get("display_name", child.name),
                contexts=contexts,
            ))
        return groups

    def get_manifest(self, plugin_name: str) -> dict:
        return self._read_manifest(plugin_name)

    def get_file_meta(self, plugin_name: str, context_name: str, file_name: str) -> PromptFileMeta:
        manifest = self._read_manifest(plugin_name)
        ctx_entry = self._get_context_entry(manifest, context_name)
        file_entry = self._get_file_entry(ctx_entry, file_name)
        return PromptFileMeta(plugin_name, context_name, file_entry)

    def get_file(self, plugin_name: str, context_name: str, file_name: str) -> str:
        """Return current content of a prompt file. Falls back to manifest default."""
        meta = self.get_file_meta(plugin_name, context_name, file_name)
        path = self._file_path(plugin_name, context_name, file_name)
        if path.exists():
            return path.read_text()
        return meta.default

    def save_file(self, plugin_name: str, context_name: str, file_name: str, content: str) -> None:
        """Write new content. Plugin, context, and file_name must all be declared."""
        self.get_file_meta(plugin_name, context_name, file_name)  # validate
        path = self._file_path(plugin_name, context_name, file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def reset_file(self, plugin_name: str, context_name: str, file_name: str) -> str:
        """Reset to the default from the manifest. Returns the default text."""
        meta = self.get_file_meta(plugin_name, context_name, file_name)
        path = self._file_path(plugin_name, context_name, file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(meta.default)
        return meta.default
