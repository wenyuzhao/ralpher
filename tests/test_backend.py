import json
import shutil

import pytest
from pydantic import ValidationError

from ralpher.models import (
    Project,
    Settings,
    detect_default_backend,
    normalize_backend,
    resolve_backend,
)


@pytest.fixture
def installed(monkeypatch):
    """Pretend exactly the named CLIs are on PATH, for backend auto-detection."""

    def _installed(*executables: str):
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name, *a, **kw: f"/usr/bin/{name}" if name in executables else None,
        )

    return _installed


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


class TestDetectDefaultBackend:
    def test_prefers_claude_code_when_both_installed(self, installed):
        installed("claude", "agy")
        assert detect_default_backend() == "claude-code"

    def test_antigravity_when_only_agy_installed(self, installed):
        installed("agy")
        assert detect_default_backend() == "antigravity"

    def test_claude_code_when_only_claude_installed(self, installed):
        installed("claude")
        assert detect_default_backend() == "claude-code"

    def test_falls_back_to_claude_code_when_neither_installed(self, installed):
        installed()
        assert detect_default_backend() == "claude-code"


class TestSettingsBackend:
    def test_default_is_the_detected_backend(self, installed):
        installed("agy")
        assert Settings().backend == "antigravity"
        installed("claude", "agy")
        assert Settings().backend == "claude-code"

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

    def test_defaults_when_key_missing(self, tmp_path, monkeypatch, installed):
        installed("claude", "agy")
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

    def test_defaults_to_detected_backend(self, tmp_path, monkeypatch, installed):
        monkeypatch.chdir(tmp_path)
        installed("claude", "agy")
        assert resolve_backend(None) == "claude-code"
        installed("agy")
        assert resolve_backend(None) == "antigravity"

    def test_cli_alias_normalized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_backend("agy") == "antigravity"

    def test_invalid_cli_value_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            resolve_backend("bogus")


class TestProjectBackend:
    def test_default_backend(self, installed):
        installed("claude", "agy")
        assert Project(id="x").backend == "claude-code"

    def test_explicit_backend(self):
        assert Project(id="x", backend="antigravity").backend == "antigravity"
