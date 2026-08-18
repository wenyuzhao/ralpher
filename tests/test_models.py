from ralpher.models import Task, Tasks


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
