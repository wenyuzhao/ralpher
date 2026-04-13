import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.loop import loop, _run_one_iteration, _init_progress
from ralpher.models import PRD, UserStory
from ralpher.utils.hooks import HooksManager


def _make_prd(stories: list[dict] | None = None) -> dict:
    if stories is None:
        stories = [
            {
                "id": "us-1",
                "title": "Login",
                "description": "User can log in",
                "acceptance_criteria": ["AC1"],
                "priority": 1,
                "passes": False,
                "notes": "",
            }
        ]
    return {
        "project": "Test",
        "branch_name": "feat/test",
        "description": "Test PRD",
        "user_stories": stories,
    }


class TestInitProgress:
    def test_creates_file(self, tmp_path):
        progress_file = tmp_path / "progress.md"
        _init_progress(progress_file)
        content = progress_file.read_text()
        assert "# Ralph Progress Log" in content
        assert "Started:" in content


class TestRunOneIteration:
    @pytest.fixture(autouse=True)
    def _patch_spinner(self, monkeypatch):
        mock_spinner = MagicMock()
        mock_spinner.__aenter__ = AsyncMock(return_value=mock_spinner)
        mock_spinner.__aexit__ = AsyncMock(return_value=False)
        mock_spinner.run = AsyncMock()
        monkeypatch.setattr(
            "ralpher.utils.claude.Spinner",
            lambda: mock_spinner,
        )

    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_marks_story_passed_when_current_story_passes(
        self, mock_exec, tmp_path
    ):
        task_id = "iter-task"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        prd = PRD.model_validate(prd_data)

        def side_effect(*args, **kwargs):
            # Simulate claude marking story as passed
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": True})
            )
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            proc.stdout.read.return_value = b""
            proc.stderr.read.return_value = b""
            return proc

        mock_exec.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        updated = json.loads((task_dir / "prd.json").read_text())
        assert updated["user_stories"][0]["passes"] is True

    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit(self, mock_exec, tmp_path):
        task_id = "iter-fail"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "logs").mkdir()

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.model_validate(prd_data)

        proc = AsyncMock()
        proc.wait.return_value = None
        proc.returncode = 1
        proc.stdout.read.return_value = b""
        proc.stderr.read.return_value = b""
        mock_exec.return_value = proc

        with pytest.raises(SystemExit):
            await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_writes_log_files(self, mock_exec, tmp_path):
        task_id = "iter-logs"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.model_validate(prd_data)

        def side_effect(*args, **kwargs):
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )
            # Write to the file objects passed as stdout/stderr
            stdout_file = kwargs.get("stdout")
            stderr_file = kwargs.get("stderr")
            if stdout_file:
                stdout_file.write(b"some output")
            if stderr_file:
                stderr_file.write(b"some error")
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            return proc

        mock_exec.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        logs_dir = task_dir / "logs"
        assert (logs_dir / "0.out.log").read_text() == "some output"
        assert (logs_dir / "0.err.log").read_text() == "some error"

    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_command_flags(self, mock_exec, tmp_path):
        task_id = "iter-flags"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.model_validate(prd_data)

        def side_effect(*args, **kwargs):
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            proc.stdout.read.return_value = b""
            proc.stderr.read.return_value = b""
            return proc

        mock_exec.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        call_args = mock_exec.call_args[0]
        assert "--dangerously-skip-permissions" in call_args
        assert "--permission-mode" in call_args
        assert "dontAsk" in call_args
        assert "--plugin-dir" in call_args
        assert "--print" in call_args
        assert f"/ralpher:loop {task_id}" in call_args


class TestLoop:
    @pytest.fixture(autouse=True)
    def _patch_spinner(self, monkeypatch):
        mock_spinner = MagicMock()
        mock_spinner.__aenter__ = AsyncMock(return_value=mock_spinner)
        mock_spinner.__aexit__ = AsyncMock(return_value=False)
        mock_spinner.run = AsyncMock()
        monkeypatch.setattr(
            "ralpher.utils.claude.Spinner",
            lambda: mock_spinner,
        )

    @pytest.mark.asyncio
    async def test_raises_when_prd_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "no-prd"
        task_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await loop(task_dir, max_iterations=5, hooks=HooksManager([]))

    @patch("ralpher.loop._checkout_branch")
    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_completes_when_all_stories_pass(
        self, mock_exec, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "loop-done"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        def side_effect(*args, **kwargs):
            # Mark the story as passed
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": True})
            )
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            proc.stdout.read.return_value = b""
            proc.stderr.read.return_value = b""
            return proc

        mock_exec.side_effect = side_effect
        await loop(task_dir, max_iterations=5, hooks=HooksManager([]))
        # Should complete without raising
        assert mock_exec.call_count == 1

    @patch("ralpher.loop._checkout_branch")
    @patch("ralpher.utils.claude.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_exits_with_error_when_max_iterations_reached(
        self, mock_exec, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "loop-fail"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        def side_effect(*args, **kwargs):
            # Story never passes
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )
            proc = AsyncMock()
            proc.wait.return_value = None
            proc.returncode = 0
            proc.stdout.read.return_value = b""
            proc.stderr.read.return_value = b""
            return proc

        mock_exec.side_effect = side_effect
        monkeypatch.setattr("ralpher.loop.time.sleep", lambda _: None)
        with pytest.raises(SystemExit):
            await loop(task_dir, max_iterations=2, hooks=HooksManager([]))
        assert mock_exec.call_count == 2

    @patch("ralpher.loop._checkout_branch")
    @pytest.mark.asyncio
    async def test_skips_loop_when_all_stories_already_pass(
        self, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "loop-skip"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd(
            [
                {
                    "id": "us-1",
                    "title": "Done",
                    "description": "Already done",
                    "acceptance_criteria": [],
                    "priority": 1,
                    "passes": True,
                    "notes": "",
                }
            ]
        )
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        await loop(task_dir, max_iterations=5, hooks=HooksManager([]))
        # Should return immediately without running any iterations
