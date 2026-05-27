import json

import pytest
from pydantic import ValidationError

from ralpher.models import (
    DEFAULT_BACKEND,
    Project,
    Settings,
    normalize_backend,
    resolve_backend,
)


class TestNormalizeBackend:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("claude-code", "claude-code"),
            ("claude", "claude-code"),
            ("cc", "claude-code"),
            ("CC", "claude-code"),
            ("  Claude-Code  ", "claude-code"),
            ("antigravity", "antigravity"),
            ("agy", "antigravity"),
            ("AGY", "antigravity"),
        ],
    )
    def test_aliases(self, value, expected):
        assert normalize_backend(value) == expected

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_backend("gemini")


class TestSettingsBackend:
    def test_default_is_claude_code(self):
        assert Settings().backend == "claude-code"
        assert DEFAULT_BACKEND == "claude-code"

    def test_reads_backend_from_settings_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"backend": "agy"}))
        # Alias is normalized at load time.
        assert Settings.load().backend == "antigravity"

    def test_canonical_value_in_settings_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"backend": "antigravity"}))
        assert Settings.load().backend == "antigravity"

    def test_invalid_backend_in_settings_rejected(self):
        with pytest.raises(ValidationError):
            Settings.model_validate({"backend": "nope"})

    def test_defaults_when_key_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"models": {}}))
        assert Settings.load().backend == "claude-code"


class TestResolveBackend:
    def test_cli_value_wins_over_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"backend": "antigravity"}))
        # CLI flag overrides the settings default.
        assert resolve_backend("cc") == "claude-code"

    def test_falls_back_to_settings_when_cli_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"backend": "agy"}))
        assert resolve_backend(None) == "antigravity"

    def test_defaults_to_claude_code(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_backend(None) == "claude-code"

    def test_cli_alias_normalized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_backend("agy") == "antigravity"

    def test_invalid_cli_value_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            resolve_backend("bogus")


class TestModelForBackendAware:
    def test_claude_code_uses_defaults(self):
        s = Settings()
        assert s.model_for("plan") == "claude-opus-4-7[1m]"
        assert s.model_for("plan", backend="claude-code") == "claude-opus-4-7[1m]"

    def test_antigravity_has_no_hardcoded_default(self):
        # No Gemini model is forced — the SDK picks its own default.
        assert Settings().model_for("plan", backend="antigravity") is None
        assert Settings().model_for("verify", backend="antigravity") is None

    def test_settings_override_applies_to_both_backends(self):
        s = Settings(models={"plan": "gemini-3-pro"})
        assert s.model_for("plan", backend="antigravity") == "gemini-3-pro"
        assert s.model_for("plan", backend="claude-code") == "gemini-3-pro"


class TestProjectBackend:
    def test_default_backend(self):
        assert Project(id="x").backend == "claude-code"

    def test_explicit_backend(self):
        assert Project(id="x", backend="antigravity").backend == "antigravity"
