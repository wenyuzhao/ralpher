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
    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_marks_story_passed_when_current_story_passes(
        self, mock_run, tmp_path
    ):
        task_id = "iter-task"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        prd = PRD.model_validate(prd_data)

        async def side_effect(**kwargs):
            # Simulate claude marking story as passed
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": True})
            )

        mock_run.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        updated = PRD.load(task_dir / "prd.json")
        assert updated.user_stories[0].passes is True

    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(self, mock_run, tmp_path):
        from ralpher.utils.claude import ClaudeError

        task_id = "iter-fail"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.load(task_dir / "prd.json")

        mock_run.side_effect = ClaudeError(1)

        with pytest.raises(SystemExit):
            await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_writes_current_user_story(self, mock_run, tmp_path):
        task_id = "iter-logs"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.load(task_dir / "prd.json")

        async def side_effect(**kwargs):
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )

        mock_run.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        cus = json.loads((task_dir / "current_user_story.json").read_text())
        assert cus["id"] == "us-1"

    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_loop_skill(self, mock_run, tmp_path):
        task_id = "iter-flags"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "prd.json").write_text(json.dumps(prd_data))
        prd = PRD.load(task_dir / "prd.json")

        async def side_effect(**kwargs):
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )

        mock_run.side_effect = side_effect
        await _run_one_iteration(task_id, prd, task_dir, 0, HooksManager([]))

        call_kwargs = mock_run.call_args[1]
        assert f"/ralpher:loop {task_id}" in call_kwargs["prompt"]
        assert call_kwargs["task_dir"] == task_dir


class TestLoop:
    @pytest.mark.asyncio
    async def test_raises_when_prd_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "no-prd"
        task_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await loop(task_dir, max_iterations=5, hooks=HooksManager([]))

    @patch("ralpher.loop._checkout_branch")
    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_completes_when_all_stories_pass(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "loop-done"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            # Mark the story as passed
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": True})
            )

        mock_run.side_effect = side_effect
        await loop(task_dir, max_iterations=5, hooks=HooksManager([]))
        assert mock_run.call_count == 1

    @patch("ralpher.loop._checkout_branch")
    @patch("ralpher.loop.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_exits_with_error_when_max_iterations_reached(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "loop-fail"
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            (task_dir / "current_user_story.json").write_text(
                json.dumps({"id": "us-1", "passes": False})
            )

        mock_run.side_effect = side_effect
        monkeypatch.setattr("ralpher.loop.time.sleep", lambda _: None)
        with pytest.raises(SystemExit):
            await loop(task_dir, max_iterations=2, hooks=HooksManager([]))
        assert mock_run.call_count == 2

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
