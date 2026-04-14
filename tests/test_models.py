from ralpher.models import ProjectPlan, Task


class TestTask:
    def test_defaults(self):
        task = Task(
            id="T-001",
            title="Login",
            description="User can log in",
            acceptance_criteria=["Can enter email"],
            priority=1,
        )
        assert task.passes is False
        assert task.notes == ""

    def test_all_fields(self):
        task = Task(
            id="T-002",
            title="Signup",
            description="User can sign up",
            acceptance_criteria=["Email", "Password"],
            priority=2,
            passes=True,
            notes="Done",
        )
        assert task.passes is True
        assert task.notes == "Done"


class TestProjectPlan:
    def _make_plan(self, tasks_pass: list[bool] | None = None) -> ProjectPlan:
        if tasks_pass is None:
            tasks_pass = [True, False, True]
        tasks = [
            Task(
                id=f"T-{i:03d}",
                title=f"Task {i}",
                description=f"Desc {i}",
                acceptance_criteria=[],
                priority=i,
                passes=p,
            )
            for i, p in enumerate(tasks_pass)
        ]
        return ProjectPlan(
            project="Test",
            description="A test plan",
            tasks=tasks,
        )

    def test_failed_tasks(self):
        plan = self._make_plan([True, False, True, False])
        failed = plan.failed_tasks()
        assert len(failed) == 2
        assert all(not t.passes for t in failed)

    def test_failed_tasks_all_pass(self):
        plan = self._make_plan([True, True, True])
        assert plan.failed_tasks() == []

    def test_failed_tasks_none_pass(self):
        plan = self._make_plan([False, False])
        assert len(plan.failed_tasks()) == 2

    def test_model_validate_from_dict(self):
        data = {
            "project": "P",
            "branch_name": "b",
            "description": "d",
            "tasks": [
                {
                    "id": "T-001",
                    "title": "T",
                    "description": "D",
                    "acceptance_criteria": ["AC1"],
                    "priority": 1,
                }
            ],
        }
        plan = ProjectPlan.model_validate(data)
        assert plan.project == "P"
        assert len(plan.tasks) == 1
        assert plan.tasks[0].passes is False
