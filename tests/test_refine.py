from unittest.mock import AsyncMock, patch

import pytest

from ralpher.agents.refiner import check_completed_tasks
from ralpher.backend import Plan
from ralpher.models import PlannedTask, Project, ProjectConfig, Task, Tasks
from ralpher.plan.refine import refine_plan
from ralpher.utils.notion_comments import NotionComment


def _write_config(project: Project) -> None:
    config = ProjectConfig(base_branch="main", target_branch=f"ralph/{project.id}")
    project.save_config(config)


def _task(task_id: str, *, passed: bool = False, title: str = "Login") -> Task:
    return Task(
        id=task_id,
        title=title,
        description=f"Do {task_id}",
        acceptance_criteria=["Tests pass"],
        passed=passed,
    )


def _plan(*tasks: Task) -> Plan:
    """The plan an agent would return for `tasks` (no `passed` in plan output)."""
    return Plan(
        markdown="# Design",
        tasks=[PlannedTask(**t.model_dump(exclude={"passed"})) for t in tasks],
    )


class TestRefinePlan:
    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await refine_plan(project=Project(id="nonexistent-task"), prompt="add auth")

    @pytest.mark.asyncio
    async def test_raises_when_design_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="add auth")

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-task"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Original Design")
        _write_config(project)

        result = await refine_plan(project=project, prompt="add user authentication")
        assert result == task_id

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_design_deleted_after_refine(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-delete"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)

        async def side_effect(**kwargs):
            project.design_md.unlink()

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="break everything")

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_refine_skill(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-skill"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)

        await refine_plan(project=project, prompt="add feature X")
        call_kwargs = mock_run.call_args[1]
        # The rendered prompt references the project's design.md path (which
        # embeds the project id) and carries the refine-skill instructions.
        assert "Refine the Project Plan" in call_kwargs["prompt"]
        assert task_id in call_kwargs["prompt"]
        assert call_kwargs["project"] is project


class TestCheckCompletedTasks:
    def test_accepts_completed_tasks_returned_verbatim(self):
        done = _task("T-001", passed=True)
        plan = _plan(done, _task("T-002"), _task("T-003"))
        assert check_completed_tasks([done], plan) is None

    def test_accepts_when_nothing_has_passed_yet(self):
        assert check_completed_tasks([], _plan(_task("T-009"))) is None

    def test_accepts_reordered_and_rewritten_pending_tasks(self):
        done = _task("T-001", passed=True)
        rewritten = Task(
            id="T-002",
            title="Totally different",
            description="Rewritten by the refinement",
            acceptance_criteria=["Something else"],
        )
        assert check_completed_tasks([done], _plan(rewritten, done)) is None

    def test_rejects_a_dropped_completed_task(self):
        done = _task("T-001", passed=True)
        problem = check_completed_tasks([done], _plan(_task("T-002")))
        assert problem is not None
        assert "T-001" in problem
        assert "missing" in problem

    def test_rejects_a_renumbered_completed_task(self):
        done = _task("T-001", passed=True)
        renumbered = _task("T-007", title=done.title)
        problem = check_completed_tasks([done], _plan(renumbered))
        assert problem is not None
        assert "T-001" in problem

    @pytest.mark.parametrize(
        "field,value",
        [
            ("title", "Log in, but better"),
            ("description", "Rewritten description"),
            ("acceptance_criteria", ["Tests pass", "And more"]),
        ],
    )
    def test_rejects_an_edited_completed_task(self, field, value):
        done = _task("T-001", passed=True)
        edited = done.model_copy(update={field: value})
        problem = check_completed_tasks([done], _plan(edited))
        assert problem is not None
        assert field in problem

    def test_reports_every_offending_task(self):
        first = _task("T-001", passed=True)
        second = _task("T-002", passed=True, title="Signup")
        problem = check_completed_tasks([first, second], _plan())
        assert problem is not None
        assert "T-001" in problem
        assert "T-002" in problem


class TestRefinePlanWithCompletedTasks:
    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_prompt_lists_the_completed_tasks(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="refine-partial")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        project.save_tasks(
            Tasks(
                tasks=[
                    _task("T-001", passed=True),
                    _task("T-002", passed=True, title="Signup"),
                    _task("T-003"),
                ]
            )
        )
        _write_config(project)

        await refine_plan(project=project, prompt="switch to OAuth")
        prompt = mock_run.call_args[1]["prompt"]
        assert "Already-Completed Tasks" in prompt
        # The frozen section lists exactly the tasks that already passed; the
        # pending one stays re-plannable. (Sliced out of the prompt because the
        # embedded plan-structure example mentions T-001…T-004 too.)
        frozen = prompt[
            prompt.index("Already-Completed Tasks") : prompt.index(
                "User Provided Input"
            )
        ]
        assert "`T-001` — Login" in frozen
        assert "`T-002` — Signup" in frozen
        assert "T-003" not in frozen

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_validate_hook_guards_the_completed_tasks(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="refine-validate")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        done = _task("T-001", passed=True)
        project.save_tasks(Tasks(tasks=[done, _task("T-002")]))
        _write_config(project)

        await refine_plan(project=project, prompt="switch to OAuth")
        validate = mock_run.call_args[1]["validate"]
        assert validate(_plan(done, _task("T-005"))) is None
        assert validate(_plan(_task("T-005"))) is not None

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_no_frozen_section_without_completed_tasks(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="refine-fresh")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        project.save_tasks(Tasks(tasks=[_task("T-001"), _task("T-002")]))
        _write_config(project)

        await refine_plan(project=project, prompt="switch to OAuth")
        call_kwargs = mock_run.call_args[1]
        assert "Already-Completed Tasks" not in call_kwargs["prompt"]
        # The hook is still passed, and accepts anything when nothing has passed.
        assert call_kwargs["validate"](_plan(_task("T-009"))) is None


class TestRefinePlanWithNotion:
    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_when_no_prompt_and_notion_unconfigured(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RALPHER_NOTION_TOKEN", raising=False)
        project = Project(id="task")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)
        result = await refine_plan(project=project, prompt=None)
        assert result is None
        mock_run.assert_not_awaited()

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_plan_comments", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_when_notion_configured_but_no_comments_and_no_prompt(
        self, mock_fetch, mock_resolve, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.setenv("RALPHER_NOTION_PAGE_ID", "pid")
        mock_fetch.return_value = []
        project = Project(id="task")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)
        result = await refine_plan(project=project, prompt=None)
        assert result is None
        mock_run.assert_not_awaited()
        mock_resolve.assert_not_awaited()

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_plan_comments", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_fetches_and_resolves_when_notion_configured(
        self, mock_fetch, mock_resolve, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.setenv("RALPHER_NOTION_PAGE_ID", "pid")
        comments = [
            NotionComment(
                id="c1",
                discussion_id="d1",
                text="Switch to MySQL",
                context="Use Postgres",
                author=None,
            )
        ]
        mock_fetch.return_value = comments
        project = Project(id="task-notion")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)

        result = await refine_plan(project=project, prompt=None)
        assert result == "task-notion"
        mock_run.assert_awaited_once()
        mock_resolve.assert_awaited_once_with(comments)

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_plan_comments", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_resolve_when_no_comments_but_prompt_given(
        self, mock_fetch, mock_resolve, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.setenv("RALPHER_NOTION_PAGE_ID", "pid")
        mock_fetch.return_value = []
        project = Project(id="task-no-comments")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        _write_config(project)

        result = await refine_plan(project=project, prompt="add feature X")
        assert result == "task-no-comments"
        mock_run.assert_awaited_once()
        mock_resolve.assert_not_awaited()
