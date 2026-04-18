from unittest.mock import AsyncMock, patch

import pytest

from ralpher.models import Project, ProjectConfig
from ralpher.plan.refine import refine_plan


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
