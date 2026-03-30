"""Tests for the templates/audit script."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

# ── Import audit script as module ────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_audit():
    filepath = str(ROOT / "templates" / "audit")
    loader = importlib.machinery.SourceFileLoader("vendored_audit", filepath)
    spec = importlib.util.spec_from_loader("vendored_audit", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    sys.modules["vendored_audit"] = module
    spec.loader.exec_module(module)
    return module


audit = _import_audit()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored").mkdir()
    return tmp_path


@pytest.fixture
def make_schema(tmp_repo):
    """Write a schema file to manifests/."""
    def _make(vendor_name, schema):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        (manifests_dir / f"{vendor_name}.schema").write_text(
            json.dumps(schema, indent=2) + "\n"
        )
    return _make


@pytest.fixture
def make_config(tmp_repo):
    """Write a vendor config file to configs/."""
    def _make(vendor_name, config):
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
        (configs_dir / f"{vendor_name}.json").write_text(
            json.dumps(config, indent=2) + "\n"
        )
    return _make


SAMPLE_SCHEMA = {
    "vendor": "tool",
    "fields": {
        "prefix": {
            "required": True,
            "type": "string",
            "description": "Command prefix"
        },
        "debug": {
            "required": False,
            "type": "boolean",
            "description": "Enable debug mode"
        }
    }
}


# ── Tests: load_schemas ──────────────────────────────────────────────────

class TestLoadSchemas:
    def test_loads_schema_files(self, make_schema):
        make_schema("tool", SAMPLE_SCHEMA)
        schemas = audit.load_schemas()
        assert "tool" in schemas
        assert schemas["tool"]["vendor"] == "tool"

    def test_no_manifests_dir(self, tmp_repo):
        schemas = audit.load_schemas()
        assert schemas == {}

    def test_no_schema_files(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        schemas = audit.load_schemas()
        assert schemas == {}


# ── Tests: load_configs ──────────────────────────────────────────────────

class TestLoadConfigs:
    def test_loads_config_files(self, make_config):
        make_config("tool", {"_vendor": {"repo": "owner/tool"}, "prefix": "gv"})
        configs = audit.load_configs()
        assert "tool" in configs

    def test_no_configs_dir(self, tmp_repo):
        configs = audit.load_configs()
        assert configs == {}


# ── Tests: get_user_fields ───────────────────────────────────────────────

class TestGetUserFields:
    def test_excludes_vendor_key(self):
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv", "debug": True}
        fields = audit.get_user_fields(config)
        assert "_vendor" not in fields
        assert fields == {"prefix": "gv", "debug": True}

    def test_empty_config(self):
        assert audit.get_user_fields({}) == {}


# ── Tests: check_type ────────────────────────────────────────────────────

class TestCheckType:
    def test_string(self):
        assert audit.check_type("hello", "string") is True
        assert audit.check_type(42, "string") is False

    def test_number(self):
        assert audit.check_type(42, "number") is True
        assert audit.check_type(3.14, "number") is True
        assert audit.check_type("42", "number") is False

    def test_boolean(self):
        assert audit.check_type(True, "boolean") is True
        assert audit.check_type(False, "boolean") is True
        assert audit.check_type(1, "boolean") is False

    def test_boolean_not_number(self):
        """Booleans should not pass as numbers."""
        assert audit.check_type(True, "number") is False

    def test_array(self):
        assert audit.check_type([1, 2], "array") is True
        assert audit.check_type("list", "array") is False

    def test_object(self):
        assert audit.check_type({"a": 1}, "object") is True
        assert audit.check_type([1], "object") is False

    def test_unknown_type(self):
        assert audit.check_type("anything", "unknown_type") is True


# ── Tests: audit_config ─────────────────────────────────────────────────

class TestAuditConfig:
    def test_all_pass(self):
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv", "debug": True}
        schema = SAMPLE_SCHEMA
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        levels = [r[0] for r in results]
        assert "error" not in levels

    def test_missing_required_field(self):
        config = {"_vendor": {"repo": "owner/tool"}}  # no prefix
        schema = SAMPLE_SCHEMA
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        errors = [r for r in results if r[0] == "error"]
        assert len(errors) == 1
        assert "prefix" in errors[0][1]
        assert "required field missing" in errors[0][1]

    def test_unknown_field_warning(self):
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv", "mystery": 42}
        schema = SAMPLE_SCHEMA
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        warnings = [r for r in results if r[0] == "warning"]
        assert len(warnings) == 1
        assert "mystery" in warnings[0][1]
        assert "unknown field" in warnings[0][1]

    def test_cross_vendor_misplacement(self):
        other_schema = {
            "vendor": "other",
            "fields": {
                "prefix": {"required": True, "type": "string"},
                "special_key": {"required": False, "type": "string"}
            }
        }
        schemas = {"tool": SAMPLE_SCHEMA, "other": other_schema}
        field_index = audit.build_field_index(schemas)

        # tool config has "special_key" which belongs to "other"
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv", "special_key": "val"}
        results = audit.audit_config("tool", config, SAMPLE_SCHEMA, field_index)
        warnings = [r for r in results if r[0] == "warning"]
        assert len(warnings) == 1
        assert "other" in warnings[0][1]

    def test_type_mismatch_error(self):
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": 42}  # should be string
        schema = SAMPLE_SCHEMA
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        errors = [r for r in results if r[0] == "error"]
        assert len(errors) == 1
        assert "prefix" in errors[0][1]
        assert "expected string" in errors[0][1]

    def test_vendor_key_ignored(self):
        """_vendor key is ignored during audit (framework metadata)."""
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv"}
        schema = SAMPLE_SCHEMA
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        messages = [r[1] for r in results]
        assert not any("_vendor" in m for m in messages)

    def test_optional_field_not_present_ok(self):
        """Optional fields that aren't present don't generate any result."""
        config = {"_vendor": {"repo": "owner/tool"}, "prefix": "gv"}
        schema = SAMPLE_SCHEMA  # debug is optional
        field_index = audit.build_field_index({"tool": schema})
        results = audit.audit_config("tool", config, schema, field_index)
        messages = [r[1] for r in results]
        assert not any("debug" in m for m in messages)


# ── Tests: main ──────────────────────────────────────────────────────────

class TestMain:
    def test_no_schemas_exits_clean(self, tmp_repo, capsys):
        with pytest.raises(SystemExit) as exc_info:
            audit.main()
        assert exc_info.value.code == 0
        assert "No vendor schemas installed" in capsys.readouterr().out

    def test_all_pass_exit_zero(self, make_schema, make_config, capsys):
        make_schema("tool", SAMPLE_SCHEMA)
        make_config("tool", {"_vendor": {"repo": "owner/tool"}, "prefix": "gv"})
        with pytest.raises(SystemExit) as exc_info:
            audit.main()
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "[PASS]" in output

    def test_missing_required_exits_nonzero(self, make_schema, make_config, capsys):
        make_schema("tool", SAMPLE_SCHEMA)
        make_config("tool", {"_vendor": {"repo": "owner/tool"}})  # no prefix
        with pytest.raises(SystemExit) as exc_info:
            audit.main()
        assert exc_info.value.code == 1
        output = capsys.readouterr().out
        assert "[FAIL]" in output
        assert "1 error" in output

    def test_warnings_only_exit_zero(self, make_schema, make_config, capsys):
        make_schema("tool", SAMPLE_SCHEMA)
        make_config("tool", {
            "_vendor": {"repo": "owner/tool"},
            "prefix": "gv",
            "extra": "unknown"
        })
        with pytest.raises(SystemExit) as exc_info:
            audit.main()
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "[WARN]" in output
        assert "1 warning" in output

    def test_schema_without_matching_config(self, make_schema, capsys):
        """Schema exists but no config — required fields are missing."""
        make_schema("tool", SAMPLE_SCHEMA)
        # No config file for "tool"
        (Path(".vendored/configs")).mkdir(parents=True, exist_ok=True)
        with pytest.raises(SystemExit) as exc_info:
            audit.main()
        assert exc_info.value.code == 1
