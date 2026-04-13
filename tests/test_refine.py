import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.prd.refine import refine_prd


class TestRefinePrd:
    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await refine_prd("nonexistent-task", "add auth")

    @pytest.mark.asyncio
    async def test_raises_when_prd_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await refine_prd("test-task", "add auth")

    @patch("ralpher.prd.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-task"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# Original PRD")

        result = await refine_prd(task_id, "add user authentication")
        assert result == task_id

    @patch("ralpher.prd.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_prd_deleted_after_refine(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-delete"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        async def side_effect(**kwargs):
            (task_dir / "PRD.md").unlink()

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            await refine_prd(task_id, "break everything")

    @patch("ralpher.prd.refine.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_refine_skill(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-skill"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        await refine_prd(task_id, "add feature X")
        call_kwargs = mock_run.call_args[1]
        assert "/ralpher:refine-prd" in call_kwargs["prompt"]
        assert task_id in call_kwargs["prompt"]
        assert call_kwargs["interactive"] is True
