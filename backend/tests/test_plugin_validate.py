"""
Tests for scripts/plugin_validate.py

These tests call the validator's internal functions directly rather than
through the CLI, resetting the ERRORS/WARNINGS lists before each test.

Covers:
  - _validate_settings_schema_in_cog() — valid types, invalid types, missing keys
  - validate_frontend() — apiClient double /api/ prefix detection, raw fetch/axios
  - validate_cog() — app_commands description, forbidden patterns
"""

import ast
import sys
import importlib
from pathlib import Path
import pytest

# ── Load the validator module from scripts/ ───────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

@pytest.fixture(autouse=True)
def load_and_reset_validator(tmp_path):
    """
    Import plugin_validate fresh for each test so ERRORS/WARNINGS are empty.
    The module uses module-level lists; we reset them directly.
    """
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))

    import plugin_validate as pv
    pv.ERRORS.clear()
    pv.WARNINGS.clear()
    yield pv
    pv.ERRORS.clear()
    pv.WARNINGS.clear()


# ─────────────────────────────────────────────────────────────────────────────
# _validate_settings_schema_in_cog — field type validation
# ─────────────────────────────────────────────────────────────────────────────

def _parse(src: str) -> ast.AST:
    return ast.parse(src)


class TestValidateSettingsSchema:
    def test_valid_types_no_errors(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "my_cog",
    "label": "My Cog",
    "fields": [
        {"key": "enabled",    "type": "boolean",        "label": "Enabled",  "default": True},
        {"key": "channel",    "type": "channel_select", "label": "Channel",  "default": None},
        {"key": "role",       "type": "role_select",    "label": "Role",     "default": None},
        {"key": "tags",       "type": "multiselect",    "label": "Tags",     "default": []},
        {"key": "prefix",     "type": "text",           "label": "Prefix",   "default": "!"},
        {"key": "limit",      "type": "number",         "label": "Limit",    "default": 5},
    ],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert pv.ERRORS == []

    def test_channel_select_valid(self, load_and_reset_validator):
        """channel_select must be accepted — populated from API, no manual choices needed."""
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "ch", "type": "channel_select", "label": "Channel", "default": None}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert pv.ERRORS == []

    def test_role_select_valid(self, load_and_reset_validator):
        """role_select must be accepted — populated from API, no manual choices needed."""
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "r", "type": "role_select", "label": "Role", "default": None}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert pv.ERRORS == []

    def test_invalid_type_integer(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "n", "type": "integer", "label": "N", "default": 0}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("integer" in e for e in pv.ERRORS)

    def test_invalid_type_string(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "s", "type": "string", "label": "S", "default": ""}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("string" in e for e in pv.ERRORS)

    def test_invalid_type_bool(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "b", "type": "bool", "label": "B", "default": False}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("bool" in e for e in pv.ERRORS)

    def test_select_valid(self, load_and_reset_validator):
        """'select' (single-choice enum) is a valid rich-settings type (Gap E)."""
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [{"key": "s", "type": "select", "label": "S",
                "choices": [{"value": "a", "label": "A"}], "default": "a"}],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert pv.ERRORS == []

    def test_color_types_valid(self, load_and_reset_validator):
        """color / color_list / bounded number are valid rich-settings types (Gap E)."""
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [
        {"key": "accent", "type": "color", "label": "Accent", "default": "#3690ea"},
        {"key": "palette", "type": "color_list", "label": "Palette", "count": 4, "default": []},
        {"key": "cooldown", "type": "number", "label": "Cooldown", "default": 5, "min": 1, "max": 60, "step": 1},
    ],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert pv.ERRORS == []

    def test_missing_id_key(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "label": "X",
    "fields": [],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("'id'" in e for e in pv.ERRORS)

    def test_missing_label_key(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x",
    "fields": [],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("'label'" in e for e in pv.ERRORS)

    def test_missing_fields_key(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x",
    "label": "X",
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        assert any("'fields'" in e for e in pv.ERRORS)

    def test_multiple_invalid_types_each_reported(self, load_and_reset_validator):
        pv = load_and_reset_validator
        src = """
SETTINGS_SCHEMA = {
    "id": "x", "label": "X",
    "fields": [
        {"key": "a", "type": "integer", "label": "A"},
        {"key": "b", "type": "string",  "label": "B"},
    ],
}
"""
        pv._validate_settings_schema_in_cog(_parse(src))
        error_text = " ".join(pv.ERRORS)
        assert "integer" in error_text
        assert "string" in error_text


# ─────────────────────────────────────────────────────────────────────────────
# validate_frontend — apiClient double /api/ prefix
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateFrontend:
    def _make_page(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "page.tsx"
        p.write_text(
            "'use client'\n"
            "import { withPermission, PermissionLevel } from '@/lib/auth'\n"
            "import { useTranslation } from '@/lib/i18n'\n"
            f"{body}\n"
            "export default withPermission(Page, PermissionLevel.AUTHORIZED)\n"
        )
        return p

    def test_double_api_prefix_get(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        page = self._make_page(
            tmp_path,
            "const r = apiClient.get<{}>('/api/v1/guilds/1/items')"
        )
        pv.validate_frontend(page)
        assert any("/api/" in e for e in pv.ERRORS)

    def test_double_api_prefix_post(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        page = self._make_page(
            tmp_path,
            "const r = apiClient.post<{}>('/api/guilds/1/items', data)"
        )
        pv.validate_frontend(page)
        assert any("/api/" in e for e in pv.ERRORS)

    def test_correct_path_no_error(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        page = self._make_page(
            tmp_path,
            "const r = apiClient.get<{ items: Item[] }>(`/guilds/${guildId}/items`)"
        )
        pv.validate_frontend(page)
        assert not any("/api/" in e for e in pv.ERRORS)

    def test_raw_fetch_rejected(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        page = self._make_page(
            tmp_path,
            "const r = await fetch('/api/v1/guilds/1/items')"
        )
        pv.validate_frontend(page)
        assert any("fetch" in e.lower() for e in pv.ERRORS)

    def test_untyped_apiclient_rejected(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        page = self._make_page(
            tmp_path,
            "const r = await apiClient.get('/guilds/1/items')"
        )
        pv.validate_frontend(page)
        assert any("Untyped" in e or "unknown" in e.lower() for e in pv.ERRORS)

    def test_missing_with_permission_error(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        p = tmp_path / "page.tsx"
        p.write_text(
            "'use client'\n"
            "import { useTranslation } from '@/lib/i18n'\n"
            "export default function Page() { return <div /> }\n"
        )
        pv.validate_frontend(p)
        assert any("withPermission" in e for e in pv.ERRORS)

    def test_missing_use_translation_error(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        p = tmp_path / "page.tsx"
        p.write_text(
            "'use client'\n"
            "export default withPermission(Page, PermissionLevel.AUTHORIZED)\n"
        )
        pv.validate_frontend(p)
        assert any("useTranslation" in e for e in pv.ERRORS)


# ─────────────────────────────────────────────────────────────────────────────
# validate_cog — description=, forbidden patterns, LLM access
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateCog:
    def _make_cog(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "cog.py"
        p.write_text(
            "from discord.ext import commands\n"
            "import discord\n"
            f"{body}\n"
            "async def setup(bot): await bot.add_cog(MyCog(bot))\n"
        )
        return p

    def test_missing_description_error(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "class MyCog(commands.Cog):\n"
            "    @app_commands.command(name='test')\n"
            "    async def test(self, i): pass\n"
        )
        pv.validate_cog(cog)
        assert any("description=" in e for e in pv.ERRORS)

    def test_description_present_no_error(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "class MyCog(commands.Cog):\n"
            "    @app_commands.command(name='test', description='Does a thing')\n"
            "    async def test(self, i): pass\n"
        )
        pv.validate_cog(cog)
        assert not any("description=" in e for e in pv.ERRORS)

    def test_forbidden_direct_llm(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "import openai\n"
            "class MyCog(commands.Cog):\n"
            "    def __init__(self, bot):\n"
            "        self.client = openai.OpenAI()\n"
        )
        pv.validate_cog(cog)
        assert any("openai.OpenAI" in e for e in pv.ERRORS)

    def test_forbidden_bot_llm_attribute(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "class MyCog(commands.Cog):\n"
            "    async def run(self):\n"
            "        return self.bot.llm_service.generate()\n"
        )
        pv.validate_cog(cog)
        assert any("llm_service" in e or "bot.llm" in e for e in pv.ERRORS)

    def test_forbidden_aiohttp_session(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "import aiohttp\n"
            "class MyCog(commands.Cog):\n"
            "    async def run(self):\n"
            "        async with aiohttp.ClientSession() as s: pass\n"
        )
        pv.validate_cog(cog)
        assert any("ClientSession" in e for e in pv.ERRORS)

    def test_settings_schema_invalid_type_propagated(self, load_and_reset_validator, tmp_path):
        pv = load_and_reset_validator
        cog = self._make_cog(
            tmp_path,
            "class MyCog(commands.Cog):\n"
            "    SETTINGS_SCHEMA = {\n"
            '        "id": "my_cog", "label": "My Cog",\n'
            '        "fields": [{"key": "n", "type": "integer", "label": "N"}],\n'
            "    }\n"
        )
        pv.validate_cog(cog)
        assert any("integer" in e for e in pv.ERRORS)
