from ralpher.models import Project, ProjectConfig, Settings, Task, Tasks


class TestTask:
    def test_defaults(self):
        task = Task(
            id="T-001",
            title="Login",
            description="User can log in",
            acceptance_criteria=["Can enter email"],
        )
        assert task.passes is False

    def test_all_fields(self):
        task = Task(
            id="T-002",
            title="Signup",
            description="User can sign up",
            acceptance_criteria=["Email", "Password"],
            passes=True,
        )
        assert task.passes is True


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
                passes=p,
            )
            for i, p in enumerate(tasks_pass)
        ]
        return Tasks(tasks=tasks)

    def test_failed_tasks(self):
        tasks = self._make_tasks([True, False, True, False])
        failed = tasks.failed_tasks()
        assert len(failed) == 2
        assert all(not t.passes for t in failed)

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
        assert tasks.tasks[0].passes is False


class TestSettingsModels:
    def test_default_empty_dict(self):
        settings = Settings()
        assert settings.models == {}
        assert settings.get_model("plan") is None

    def test_dict_models(self):
        settings = Settings(models={"plan": "opus", "verify": "sonnet"})
        assert settings.get_model("plan") == "opus"
        assert settings.get_model("verify") == "sonnet"
        assert settings.get_model("loop") is None

    def test_string_models(self):
        settings = Settings(models="haiku:low")
        assert settings.get_model("plan") == "haiku:low"
        assert settings.get_model("verify") == "haiku:low"
        assert settings.get_model("extract-tasks") == "haiku:low"

    def test_load_string_models_from_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text('models = "universal-model:medium"\n')
        settings = Settings.load()
        assert settings.models == "universal-model:medium"
        assert settings.get_model("plan") == "universal-model:medium"
        assert settings.get_model("loop") == "universal-model:medium"


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
