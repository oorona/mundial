"""
Tests for app/services/prompt_files.py — PromptFileService (context/file layout)

Layout under test:
  {tmp_path}/
    {plugin_name}/
      manifest.json
      {context_name}/
        {file_name}.txt

All I/O is redirected to tmp_path via monkeypatching PROMPTS_BASE.
"""
import json
import pytest
from pathlib import Path


# ── Patch PROMPTS_BASE before importing the service ───────────────────────────

@pytest.fixture(autouse=True)
def patch_prompts_base(tmp_path, monkeypatch):
    import app.services.prompt_files as svc_mod
    monkeypatch.setattr(svc_mod, "PROMPTS_BASE", tmp_path)
    return tmp_path


@pytest.fixture
def svc():
    from app.services.prompt_files import PromptFileService
    return PromptFileService()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_plugin(base: Path, plugin_name: str, contexts: list) -> Path:
    """Write a manifest.json and return the plugin directory."""
    plugin_dir = base / plugin_name
    plugin_dir.mkdir(parents=True)
    manifest = {
        "plugin_name": plugin_name,
        "display_name": plugin_name.replace("_", " ").title(),
        "contexts": contexts,
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def _write_file(base: Path, plugin: str, context: str, file_name: str, content: str):
    path = base / plugin / context / f"{file_name}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ── list_plugins ──────────────────────────────────────────────────────────────

class TestListPlugins:
    def test_empty_returns_empty(self, svc):
        assert svc.list_plugins() == []

    def test_directory_without_manifest_skipped(self, svc, tmp_path):
        (tmp_path / "no_manifest").mkdir()
        assert svc.list_plugins() == []

    def test_single_plugin_with_one_context(self, svc, tmp_path):
        _make_plugin(tmp_path, "ticketnode", [
            {"name": "ticket_intake", "label": "Ticket Intake", "files": [
                {"name": "system_prompt", "label": "System", "default": ""},
            ]},
        ])
        groups = svc.list_plugins()
        assert len(groups) == 1
        assert groups[0].plugin_name == "ticketnode"
        assert len(groups[0].contexts) == 1
        assert groups[0].contexts[0].name == "ticket_intake"
        assert len(groups[0].contexts[0].files) == 1

    def test_multiple_contexts_per_plugin(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx_a", "label": "A", "files": [{"name": "system_prompt", "default": ""}]},
            {"name": "ctx_b", "label": "B", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        groups = svc.list_plugins()
        assert len(groups[0].contexts) == 2

    def test_plugins_sorted_alphabetically(self, svc, tmp_path):
        _make_plugin(tmp_path, "zzz", [{"name": "c", "files": []}])
        _make_plugin(tmp_path, "aaa", [{"name": "c", "files": []}])
        names = [g.plugin_name for g in svc.list_plugins()]
        assert names == sorted(names)

    def test_corrupted_manifest_skipped(self, svc, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "manifest.json").write_text("{not valid json")
        assert svc.list_plugins() == []


# ── get_file (content) ────────────────────────────────────────────────────────

class TestGetFile:
    def test_reads_existing_txt(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ticket_intake", "label": "T", "files": [
                {"name": "system_prompt", "default": "fallback"},
            ]},
        ])
        _write_file(tmp_path, "myplugin", "ticket_intake", "system_prompt", "Live content")
        assert svc.get_file("myplugin", "ticket_intake", "system_prompt") == "Live content"

    def test_falls_back_to_manifest_default(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ticket_intake", "label": "T", "files": [
                {"name": "system_prompt", "default": "Default from manifest"},
            ]},
        ])
        # No .txt written — should return the manifest default
        assert svc.get_file("myplugin", "ticket_intake", "system_prompt") == "Default from manifest"

    def test_raises_plugin_not_found(self, svc):
        from app.services.prompt_files import PluginNotFoundError
        with pytest.raises(PluginNotFoundError):
            svc.get_file("ghost_plugin", "ctx", "system_prompt")

    def test_raises_context_not_found(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "real_ctx", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        from app.services.prompt_files import ContextNotFoundError
        with pytest.raises(ContextNotFoundError):
            svc.get_file("myplugin", "missing_ctx", "system_prompt")

    def test_raises_prompt_not_found(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        from app.services.prompt_files import PromptNotFoundError
        with pytest.raises(PromptNotFoundError):
            svc.get_file("myplugin", "ctx", "nonexistent_file")


# ── save_file ─────────────────────────────────────────────────────────────────

class TestSaveFile:
    def test_creates_file_and_directories(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ticket_intake", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        svc.save_file("myplugin", "ticket_intake", "system_prompt", "New content")
        assert (tmp_path / "myplugin" / "ticket_intake" / "system_prompt.txt").read_text() == "New content"

    def test_overwrites_existing_content(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "user_prompt", "default": ""}]},
        ])
        _write_file(tmp_path, "myplugin", "ctx", "user_prompt", "Old")
        svc.save_file("myplugin", "ctx", "user_prompt", "New")
        assert (tmp_path / "myplugin" / "ctx" / "user_prompt.txt").read_text() == "New"

    def test_raises_if_context_not_declared(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "real_ctx", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        from app.services.prompt_files import ContextNotFoundError
        with pytest.raises(ContextNotFoundError):
            svc.save_file("myplugin", "ghost_ctx", "system_prompt", "x")

    def test_raises_if_file_not_declared(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "system_prompt", "default": ""}]},
        ])
        from app.services.prompt_files import PromptNotFoundError
        with pytest.raises(PromptNotFoundError):
            svc.save_file("myplugin", "ctx", "ghost_file", "x")


# ── reset_file ────────────────────────────────────────────────────────────────

class TestResetFile:
    def test_writes_manifest_default(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "system_prompt", "default": "Factory default"}]},
        ])
        _write_file(tmp_path, "myplugin", "ctx", "system_prompt", "Custom")
        returned = svc.reset_file("myplugin", "ctx", "system_prompt")
        assert returned == "Factory default"
        assert (tmp_path / "myplugin" / "ctx" / "system_prompt.txt").read_text() == "Factory default"

    def test_creates_file_if_missing(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "system_prompt", "default": "Default"}]},
        ])
        svc.reset_file("myplugin", "ctx", "system_prompt")
        assert (tmp_path / "myplugin" / "ctx" / "system_prompt.txt").exists()

    def test_returns_empty_string_when_no_default(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "system_prompt"}]},  # no "default" key
        ])
        returned = svc.reset_file("myplugin", "ctx", "system_prompt")
        assert returned == ""


# ── to_dict shapes ────────────────────────────────────────────────────────────

class TestToDictShapes:
    def test_plugin_group_to_dict(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ticket_intake", "label": "Ticket Intake", "description": "For tickets", "files": [
                {"name": "system_prompt", "label": "Sys", "description": "Persona", "default": ""},
                {"name": "user_prompt",   "label": "Usr", "description": "Template", "default": ""},
            ]},
        ])
        groups = svc.list_plugins()
        d = groups[0].to_dict()
        assert d["plugin_name"] == "myplugin"
        assert len(d["contexts"]) == 1

        ctx = d["contexts"][0]
        assert ctx["name"] == "ticket_intake"
        assert ctx["label"] == "Ticket Intake"
        assert len(ctx["files"]) == 2
        assert ctx["files"][0]["name"] == "system_prompt"
        assert "default" not in ctx["files"][0]   # default is internal only

    def test_meta_defaults_when_optional_fields_absent(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [{"name": "f"}]},  # no label/description/default
        ])
        meta = svc.get_file_meta("myplugin", "ctx", "f")
        assert meta.label == "f"        # falls back to name
        assert meta.description == ""
        assert meta.default == ""

    def test_multiple_files_per_context(self, svc, tmp_path):
        _make_plugin(tmp_path, "myplugin", [
            {"name": "ctx", "files": [
                {"name": "system_prompt", "default": "sys"},
                {"name": "user_prompt",   "default": "usr"},
                {"name": "injection",     "default": "inj"},
            ]},
        ])
        groups = svc.list_plugins()
        assert len(groups[0].contexts[0].files) == 3
