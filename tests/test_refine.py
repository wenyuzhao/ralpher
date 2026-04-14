import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.models import Project
from ralpher.plan.refine import refine_plan


class TestRefinePlan:
    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await refine_plan(project=Project(id="nonexistent-task"), prompt="add auth", model=None)

    @pytest.mark.asyncio
    async def test_raises_when_plan_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="add auth", model=None)

    @patch("ralpher.plan.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-task"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Original Plan")

        result = await refine_plan(
            project=project, prompt="add user authentication", model=None
        )
        assert result == task_id

    @patch("ralpher.plan.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_plan_deleted_after_refine(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-delete"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")

        async def side_effect(**kwargs):
            project.plan_md.unlink()

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            await refine_plan(project=project, prompt="break everything", model=None)

    @patch("ralpher.plan.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_refine_skill(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-skill"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")

        await refine_plan(project=project, prompt="add feature X", model=None)
        call_kwargs = mock_run.call_args[1]
        assert "/ralpher:refine-plan" in call_kwargs["prompt"]
        assert task_id in call_kwargs["prompt"]
        assert call_kwargs["interactive"] is True
