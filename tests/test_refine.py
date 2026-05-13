from unittest.mock import AsyncMock, patch

import pytest

from ralpher.models import Project, ProjectConfig
from ralpher.plan.refine import refine_plan
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


class TestRefinePlanWithNotion:
    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_when_no_prompt_and_notion_unconfigured(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RALPHER_NOTION_TOKEN", raising=False)
        project = Project(id="task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")
        _write_config(project)
        result = await refine_plan(project=project, prompt=None, model=None)
        assert result is None
        mock_run.assert_not_awaited()

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_project_plan_comments", new_callable=AsyncMock)
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
        project.plan_md.write_text("# Plan")
        _write_config(project)
        result = await refine_plan(project=project, prompt=None, model=None)
        assert result is None
        mock_run.assert_not_awaited()
        mock_resolve.assert_not_awaited()

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_project_plan_comments", new_callable=AsyncMock)
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
        project.plan_md.write_text("# Plan")
        _write_config(project)

        result = await refine_plan(project=project, prompt=None, model=None)
        assert result == "task-notion"
        mock_run.assert_awaited_once()
        mock_resolve.assert_awaited_once_with(comments)

    @patch("ralpher.plan.refine.checkout_existing_branch")
    @patch("ralpher.plan.refine.run_claude_plan_mode", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.resolve_comments", new_callable=AsyncMock)
    @patch("ralpher.plan.refine.fetch_project_plan_comments", new_callable=AsyncMock)
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
        project.plan_md.write_text("# Plan")
        _write_config(project)

        result = await refine_plan(
            project=project, prompt="add feature X", model=None
        )
        assert result == "task-no-comments"
        mock_run.assert_awaited_once()
        mock_resolve.assert_not_awaited()
