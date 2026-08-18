import json

from ralpher.models import Project, Settings


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
