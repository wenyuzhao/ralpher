import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.prd.refine import refine_prd


class TestRefinePrd:
    @pytest.fixture(autouse=True)
    def _patch_spinner(self, monkeypatch):
        mock_spinner = MagicMock()
        mock_spinner.__aenter__ = AsyncMock(return_value=mock_spinner)
        mock_spinner.__aexit__ = AsyncMock(return_value=False)
        mock_spinner.run = AsyncMock()
        monkeypatch.setattr(
            "ralpher.prd.prd.Spinner", lambda: mock_spinner,
        )

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

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-task"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# Original PRD")

        stdout_bytes = json.dumps({"session_id": "s1"}).encode()
        proc = AsyncMock()
        proc.wait.return_value = None
        proc.returncode = 0
        proc.stdout.read.return_value = stdout_bytes
        proc.stderr.read.return_value = b""
        mock_exec.return_value = proc

        result = await refine_prd(task_id, "add user authentication")
        assert result == task_id

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_when_prd_deleted_after_refine(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-delete"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        def side_effect(*args, **kwargs):
            # Simulate claude deleting PRD.md during refine
            (task_dir / "PRD.md").unlink()
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            proc.stdout.read.return_value = json.dumps({"session_id": "s1"}).encode()
            proc.stderr.read.return_value = b""
            return proc

        mock_exec.side_effect = side_effect
        with pytest.raises(SystemExit):
            await refine_prd(task_id, "break everything")

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_command_uses_refine_skill(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "refine-skill"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        proc = AsyncMock()
        proc.wait.return_value = None
        proc.returncode = 0
        proc.stdout.read.return_value = json.dumps({"session_id": "s1"}).encode()
        proc.stderr.read.return_value = b""
        mock_exec.return_value = proc

        await refine_prd(task_id, "add feature X")
        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[-1]
        assert "/ralpher:refine-prd" in prompt_arg
        assert task_id in prompt_arg
