from unittest.mock import AsyncMock, patch

import pytest

from ralpher.models import Project, ProjectConfig
from ralpher.plan.refine import refine_plan, refine_plan_from_notion
from ralpher.utils.notion_comments import NotionComment


def _write_config(project: Project) -> None:
    config = ProjectConfig(base_branch="main", target_branch=f"ralph/{project.id}")
    project.save_config(config)


class TestRefinePlan:
    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await refine_plan(
                project=Project(id="nonexistent-task"), prompt="add auth", model=None
            )

    @pytest.mark.asyncio
    async def test_raises_when_plan_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="add auth", model=None)

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-task"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Original Plan")
        _write_config(project)

        result = await refine_plan(
            project=project, prompt="add user authentication", model=None
        )
        assert result == task_id

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_plan_deleted_after_refine(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-delete"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")
        _write_config(project)

        async def side_effect(**kwargs):
            project.plan_md.unlink()

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="break everything", model=None)

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_refine_skill(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-skill"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")
        _write_config(project)

        await refine_plan(project=project, prompt="add feature X", model=None)
        call_kwargs = mock_run.call_args[1]
        assert "/ralpher:refine" in call_kwargs["prompt"]
        assert task_id in call_kwargs["prompt"]
        assert call_kwargs["project"] is project


class TestRefinePlanFromNotion:
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_project_plan_comments", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_fails_when_no_comments(
        self, mock_fetch, mock_resolve, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_fetch.return_value = []
        project = Project(id="task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")
        _write_config(project)
        with pytest.raises(SystemExit):
            await refine_plan_from_notion(project=project, model=None)
        mock_resolve.assert_not_awaited()

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_project_plan_comments", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_runs_refine_and_resolves(
        self,
        mock_fetch,
        mock_resolve,
        mock_run,
        mock_checkout,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
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
        project.plan_md.write_text("# Plan")
        _write_config(project)

        result = await refine_plan_from_notion(project=project, model=None)
        assert result == "task-notion"
        mock_run.assert_awaited_once()
        # The prompt passed to refine_plan should be derived from the comments.
        # refine_plan writes it to a temp file then injects the path into the
        # Claude prompt — so the Claude prompt won't contain the comment text
        # directly. We just confirm the refine subprocess was invoked once
        # and that comments were resolved afterward.
        mock_resolve.assert_awaited_once_with(comments)
