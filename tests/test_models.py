import pytest
from pydantic import ValidationError

from ralpher.models import (
    AGENT_ROLES,
    AgentSettings,
    PlannedTask,
    Project,
    ProjectConfig,
    Settings,
    Task,
    Tasks,
)


class TestTask:
    def test_defaults(self):
        task = Task(
            id="T-001",
            title="Login",
            description="User can log in",
            acceptance_criteria=["Can enter email"],
        )
        assert task.passed is False

    def test_all_fields(self):
        task = Task(
            id="T-002",
            title="Signup",
            description="User can sign up",
            acceptance_criteria=["Email", "Password"],
            passed=True,
        )
        assert task.passed is True

    def test_reads_the_legacy_passes_field(self):
        """A tasks.toml written before `passes` was renamed still loads."""
        task = Task.model_validate(
            {
                "id": "T-003",
                "title": "Logout",
                "description": "User can log out",
                "acceptance_criteria": [],
                "passes": True,
            }
        )
        assert task.passed is True
        # It is written back out under the new name only.
        assert task.model_dump() == {
            "id": "T-003",
            "title": "Logout",
            "description": "User can log out",
            "acceptance_criteria": [],
            "passed": True,
        }


class TestTasks:
    def _make_tasks(self, tasks_pass: list[bool] | None = None) -> Tasks:
        if tasks_pass is None:
            tasks_pass = [True, False, True]
        tasks = [
            Task(
                id=f"T-{i:03d}",
                title=f"Task {i}",
                description=f"Desc {i}",
                acceptance_criteria=[],
                passed=p,
            )
            for i, p in enumerate(tasks_pass)
        ]
        return Tasks(tasks=tasks)

    def test_failed_tasks(self):
        tasks = self._make_tasks([True, False, True, False])
        failed = tasks.failed_tasks()
        assert len(failed) == 2
        assert all(not t.passed for t in failed)

    def test_failed_tasks_all_pass(self):
        tasks = self._make_tasks([True, True, True])
        assert tasks.failed_tasks() == []

    def test_failed_tasks_none_pass(self):
        tasks = self._make_tasks([False, False])
        assert len(tasks.failed_tasks()) == 2

    def test_model_validate_from_dict(self):
        data = {
            "tasks": [
                {
                    "id": "T-001",
                    "title": "T",
                    "description": "D",
                    "acceptance_criteria": ["AC1"],
                }
            ],
        }
        tasks = Tasks.model_validate(data)
        assert len(tasks.tasks) == 1
        assert tasks.tasks[0].passed is False


class TestTasksMarkdown:
    def _tasks(self) -> Tasks:
        return Tasks(
            tasks=[
                Task(
                    id="T-001",
                    title="Login",
                    description="User can log in",
                    acceptance_criteria=["Can enter email", "Session persists"],
                    passed=True,
                ),
                Task(
                    id="T-002",
                    title="Signup",
                    description="User can sign up",
                    acceptance_criteria=["Email is validated"],
                ),
            ]
        )

    def test_renders_checklist_and_details(self):
        md = self._tasks().to_markdown()
        assert "1 of 2 complete." in md
        assert "- [x] **T-001** — Login" in md
        assert "- [ ] **T-002** — Signup" in md
        assert "## T-001 — Login" in md
        assert "**Status:** ✅ passed" in md
        assert "**Status:** ⬜ pending" in md
        assert "- Session persists" in md
        assert md.endswith("\n")

    def test_renders_empty_task_list(self):
        md = Tasks(tasks=[]).to_markdown()
        assert "0 of 0 complete." in md

    def test_save_tasks_writes_markdown_mirror(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")
        project.project_dir.mkdir(parents=True, exist_ok=True)
        tasks = self._tasks()
        project.save_tasks(tasks)

        assert project.tasks_md == project.project_dir / "tasks.md"
        assert project.tasks_md.read_text() == tasks.to_markdown()

    def test_save_tasks_rewrites_markdown_mirror(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")
        project.project_dir.mkdir(parents=True, exist_ok=True)
        project.save_tasks(self._tasks())

        tasks = self._tasks()
        tasks.tasks[1].passed = True
        project.save_tasks(tasks)

        md = project.tasks_md.read_text()
        assert "2 of 2 complete." in md
        assert "- [ ]" not in md

    def test_save_planned_tasks_writes_markdown_mirror(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")
        project.project_dir.mkdir(parents=True, exist_ok=True)
        project.save_planned_tasks(
            [
                PlannedTask(
                    id="T-001",
                    title="Login",
                    description="User can log in",
                    acceptance_criteria=["Can enter email"],
                )
            ]
        )
        assert "- [ ] **T-001** — Login" in project.tasks_md.read_text()


class TestSettingsModels:
    """`model` pins one model for every role; `[agents.<role>].model` beats it."""

    def test_unset_by_default(self):
        settings = Settings()
        assert settings.model is None
        assert settings.get_model("planner") is None

    def test_global_pin_applies_to_every_role(self):
        settings = Settings(model="haiku:low")
        for role in AGENT_ROLES:
            assert settings.get_model(role) == "haiku:low"

    def test_role_pin_beats_the_global_one(self):
        settings = Settings(
            model="haiku:low", agents={"verifier": AgentSettings(model="sonnet")}
        )
        assert settings.get_model("verifier") == "sonnet"
        assert settings.get_model("worker") == "haiku:low"

    def test_role_pin_without_a_global_one(self):
        settings = Settings(agents={"planner": AgentSettings(model="opus")})
        assert settings.get_model("planner") == "opus"
        assert settings.get_model("worker") is None

    def test_load_from_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text(
            'model = "universal-model:medium"\n\n[agents.verifier]\nmodel = "cheap"\n'
        )
        settings = Settings.load()
        assert settings.get_model("worker") == "universal-model:medium"
        assert settings.get_model("verifier") == "cheap"


class TestAgentSettings:
    """Per-role overrides beyond the model pin, from `[agents.<role>]`."""

    def test_unset_roles_get_an_empty_table(self):
        config = Settings().for_agent("worker")
        assert config.model is None
        assert config.readonly is None
        assert config.tools is None
        assert config.extra_args == []
        assert config.max_corrections is None

    def test_load_from_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text(
            "[agents.worker]\n"
            'model = "opus:max"\n'
            "readonly = false\n"
            'tools = ["Read", "Bash"]\n'
            'extra_args = ["--add-dir", "/extra"]\n'
            "\n[agents.planner]\n"
            "max_corrections = 1\n"
        )
        settings = Settings.load()
        worker = settings.for_agent("worker")
        assert worker.model == "opus:max"
        assert worker.readonly is False
        assert worker.tools == ["Read", "Bash"]
        assert worker.extra_args == ["--add-dir", "/extra"]
        assert settings.for_agent("planner").max_corrections == 1

    def test_unknown_role_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        # A typo in a table name is an error, not a silently ignored table.
        (ralpher / "settings.toml").write_text('[agents.loop]\nmodel = "opus"\n')
        with pytest.raises(ValidationError):
            Settings.load()


class TestProjectConfig:
    def test_config_toml_path(self):
        project = Project(id="proj")
        assert project.config_toml == project.project_dir / "config.toml"

    def test_load_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")
        assert project.load_config() is None

    def test_save_and_load_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")
        project.project_dir.mkdir(parents=True, exist_ok=True)
        config = ProjectConfig(base_branch="main", target_branch="ralph/proj")
        project.save_config(config)

        assert project.config_toml.exists()
        loaded = project.load_config()
        assert loaded is not None
        assert loaded == config
        assert loaded.base_branch == "main"
        assert loaded.target_branch == "ralph/proj"
