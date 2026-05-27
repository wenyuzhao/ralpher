import json

import pytest
from pydantic import ValidationError

from ralpher.models import (
    DEFAULT_BACKEND,
    Project,
    Settings,
    normalize_backend,
    resolve_backend,
    split_thinking_level,
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

    def test_antigravity_uses_defaults(self):
        s = Settings()
        assert s.model_for("plan", backend="antigravity") == "gemini-3.1-pro-preview"
        assert s.model_for("verify", backend="antigravity") == "gemini-3.5-flash"
        assert s.model_for("extract-tasks", backend="antigravity") == "gemini-3.5-flash"

    def test_settings_override_applies_to_both_backends(self):
        s = Settings(models={"plan": "gemini-3-pro"})
        assert s.model_for("plan", backend="antigravity") == "gemini-3-pro"
        assert s.model_for("plan", backend="claude-code") == "gemini-3-pro"

    def test_thinking_for_antigravity_uses_kind_defaults(self):
        s = Settings()
        assert s.thinking_for("plan", backend="antigravity") == "high"
        assert s.thinking_for("verify", backend="antigravity") == "high"
        assert s.thinking_for("extract-tasks", backend="antigravity") == "medium"

    def test_thinking_for_claude_code_bare_defaults_is_none(self):
        # The claude-code defaults carry no :<level> suffix, so they run at the
        # SDK's own default effort (no forced level).
        assert Settings().thinking_for("plan") is None
        assert Settings().thinking_for("plan", backend="claude-code") is None

    def test_claude_code_pinned_model_can_carry_thinking_suffix(self):
        # The effort suffix works for claude-code too, with claude's level set.
        s = Settings(models={"plan": "claude-opus-4-7:xhigh"})
        assert s.model_for("plan", backend="claude-code") == "claude-opus-4-7"
        assert s.thinking_for("plan", backend="claude-code") == "xhigh"

    def test_claude_code_suffix_after_bracketed_model(self):
        # A "[1m]" context-window suffix is kept; only the :<level> is peeled.
        s = Settings(models={"plan": "claude-opus-4-7[1m]:high"})
        assert s.model_for("plan", backend="claude-code") == "claude-opus-4-7[1m]"
        assert s.thinking_for("plan", backend="claude-code") == "high"

    def test_thinking_for_unknown_kind_is_none(self):
        assert Settings().thinking_for("nope", backend="antigravity") is None
        assert Settings().thinking_for("nope", backend="claude-code") is None

    def test_pinned_bare_model_has_no_thinking_level(self):
        # A pinned name without a :<level> suffix runs at the SDK's default
        # effort; the model still applies, but no thinking level is forced.
        s = Settings(models={"plan": "gemini-3-pro"})
        assert s.model_for("plan", backend="antigravity") == "gemini-3-pro"
        assert s.thinking_for("plan", backend="antigravity") is None

    def test_pinned_model_can_carry_thinking_suffix(self):
        # The thinking level travels on the model string, so a pin can set it.
        s = Settings(models={"plan": "gemini-3-pro:low"})
        assert s.model_for("plan", backend="antigravity") == "gemini-3-pro"
        assert s.thinking_for("plan", backend="antigravity") == "low"


class TestSplitThinkingLevel:
    def test_peels_known_suffix(self):
        assert split_thinking_level("gemini-3.5-flash:high") == (
            "gemini-3.5-flash",
            "high",
        )
        assert split_thinking_level("gemini-3.1-pro-preview:medium") == (
            "gemini-3.1-pro-preview",
            "medium",
        )

    def test_no_suffix_returns_model_unchanged(self):
        assert split_thinking_level("gemini-3.5-flash") == ("gemini-3.5-flash", None)

    def test_unknown_trailing_word_is_not_a_level(self):
        # A ":" suffix that isn't a recognized level stays part of the name.
        assert split_thinking_level("gemini-3.1-pro:preview") == (
            "gemini-3.1-pro:preview",
            None,
        )

    def test_claude_levels(self):
        # claude-code accepts xhigh/max; "minimal" is not a claude level.
        assert split_thinking_level("claude-opus-4-7:xhigh", "claude-code") == (
            "claude-opus-4-7",
            "xhigh",
        )
        assert split_thinking_level("claude-opus-4-7:max", "claude-code") == (
            "claude-opus-4-7",
            "max",
        )
        assert split_thinking_level("claude-opus-4-7:minimal", "claude-code") == (
            "claude-opus-4-7:minimal",
            None,
        )

    def test_levels_are_backend_specific(self):
        # "xhigh" is a claude level only; "minimal" an antigravity level only.
        assert split_thinking_level("m:xhigh", "antigravity") == ("m:xhigh", None)
        assert split_thinking_level("m:minimal", "antigravity") == ("m", "minimal")
        assert split_thinking_level("m:minimal", "claude-code") == ("m:minimal", None)


class TestProjectBackend:
    def test_default_backend(self):
        assert Project(id="x").backend == "claude-code"

    def test_explicit_backend(self):
        assert Project(id="x", backend="antigravity").backend == "antigravity"
