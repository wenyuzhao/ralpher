import json

from ralpher.models import Project, Settings
from ralpher.backend.claude import _build_options


class TestSandboxDefaults:
    def test_settings_sandbox_enabled_by_default(self):
        assert Settings().sandbox is True

    def test_project_sandbox_off_by_default(self):
        # Only the loop command opts a run into sandboxing; everything else
        # (plan/refine/extract) leaves it off.
        assert Project(id="x").sandbox is False


class TestSettingsSandboxFromFile:
    """The --sandbox flag falls back to the 'sandbox' key in settings.json."""

    def test_reads_sandbox_false_from_settings_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"sandbox": False}))
        assert Settings.load().sandbox is False

    def test_defaults_true_when_settings_json_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert Settings.load().sandbox is True

    def test_defaults_true_when_key_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(json.dumps({"models": {}}))
        assert Settings.load().sandbox is True


class TestBuildOptionsSandbox:
    def test_sandbox_enabled_sets_sandbox(self):
        opts = _build_options(sandbox=True)
        assert opts.sandbox == {"enabled": True}

    def test_sandbox_disabled_leaves_sandbox_unset(self):
        opts = _build_options(sandbox=False)
        assert opts.sandbox is None

    def test_user_settings_always_loaded(self):
        # setting_sources is independent of the sandbox toggle, so a
        # sandbox.network allowlist in .claude/settings.json always applies.
        for sb in (True, False):
            assert _build_options(sandbox=sb).setting_sources == [
                "user",
                "project",
                "local",
            ]

    def test_ralpher_is_always_read_only(self):
        # The deny rules are independent of the sandbox toggle.
        for sb in (True, False):
            opts = _build_options(sandbox=sb)
            assert opts.settings is not None
            deny = json.loads(opts.settings)["permissions"]["deny"]
            assert any(
                r.startswith("Write(//") and r.endswith("/.ralpher/**)") for r in deny
            )


class TestBuildOptionsEffort:
    def test_effort_passed_through(self):
        # The :<level> suffix becomes Claude's --effort (EffortLevel).
        assert _build_options(effort="xhigh").effort == "xhigh"

    def test_effort_defaults_to_none(self):
        # A bare model leaves effort unset, so the SDK uses its own default.
        assert _build_options().effort is None
