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


class TestProjectBackend:
    def test_default_backend(self):
        assert Project(id="x").backend == "claude-code"

    def test_explicit_backend(self):
        assert Project(id="x", backend="antigravity").backend == "antigravity"
