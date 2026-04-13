import json
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.loop.prepare import _init_progress
from ralpher.loop.iterate import iterate
from ralpher.loop.loop import run_ralph_loop
from ralpher.models import PRD, RunInfo
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
        "description": "Test PRD",
        "user_stories": stories,
    }


_STORY_TEMPLATE = {
    "id": "us-1",
    "title": "Login",
    "description": "User can log in",
    "acceptance_criteria": ["AC1"],
    "priority": 1,
    "notes": "",
}


def _make_run(
    task_id: str, max_iterations: int = 5, model: str | None = None
) -> RunInfo:
    return RunInfo(id=task_id, max_iterations=max_iterations, model=model)


class TestInitProgress:
    def test_creates_file(self, tmp_path):
        progress_file = tmp_path / "progress.md"
        _init_progress(progress_file)
        content = progress_file.read_text()
        assert "# Ralph Progress Log" in content
        assert "Started:" in content


class TestIterate:
    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_marks_story_passed_when_current_story_passes(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        run = _make_run("iter-task")
        run.task_dir.mkdir(parents=True)
        run.current_iteration = 0
        run.current_user_story_id = "us-1"

        prd_data = _make_prd()
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            (run.task_dir / "current_user_story.json").write_text(
                json.dumps({**_STORY_TEMPLATE, "passes": True})
            )

        mock_run.side_effect = side_effect
        await iterate(run, HooksManager([]))

        updated = PRD.load(run.task_dir / "prd.json")
        assert updated.user_stories[0].passes is True

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(self, mock_run, tmp_path, monkeypatch):
        from ralpher.utils.claude import ClaudeError

        monkeypatch.chdir(tmp_path)
        run = _make_run("iter-fail")
        run.task_dir.mkdir(parents=True)
        run.current_iteration = 0
        run.current_user_story_id = "us-1"

        prd_data = _make_prd()
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        mock_run.side_effect = ClaudeError(1)

        with pytest.raises(SystemExit):
            await iterate(run, HooksManager([]))

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_writes_current_user_story(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = _make_run("iter-logs")
        run.task_dir.mkdir(parents=True)
        run.current_iteration = 0
        run.current_user_story_id = "us-1"

        prd_data = _make_prd()
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        written_story: dict | None = None

        async def side_effect(**kwargs):
            nonlocal written_story
            # Read what iterate() wrote before claude runs
            written_story = json.loads(
                (run.task_dir / "current_user_story.json").read_text()
            )
            # Simulate claude leaving the story file as-is
            (run.task_dir / "current_user_story.json").write_text(
                json.dumps({**_STORY_TEMPLATE, "passes": False})
            )

        mock_run.side_effect = side_effect
        await iterate(run, HooksManager([]))

        assert written_story["id"] == "us-1"  # type: ignore

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_iterate_skill(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "iter-flags"
        run = _make_run(task_id)
        run.task_dir.mkdir(parents=True)
        run.current_iteration = 0
        run.current_user_story_id = "us-1"

        prd_data = _make_prd()
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            (run.task_dir / "current_user_story.json").write_text(
                json.dumps({**_STORY_TEMPLATE, "passes": False})
            )

        mock_run.side_effect = side_effect
        await iterate(run, HooksManager([]))

        call_kwargs = mock_run.call_args[1]
        assert f"/ralpher:iterate {task_id}" in call_kwargs["prompt"]
        assert call_kwargs["task_dir"] == run.task_dir


class TestLoop:
    @patch("ralpher.loop.prepare.extract_prd_json", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_prd_md_missing(
        self, mock_extract, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        run = _make_run("no-prd")
        run.task_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await run_ralph_loop(run=run, hooks=HooksManager([]))

    @patch("ralpher.loop.prepare._checkout_branch")
    @patch("ralpher.loop.prepare.extract_prd_json", new_callable=AsyncMock)
    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_completes_when_all_stories_pass(
        self, mock_run, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        run = _make_run("loop-done")
        run.task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (run.task_dir / "PRD.md").write_text("# PRD")
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            (run.task_dir / "current_user_story.json").write_text(
                json.dumps({**_STORY_TEMPLATE, "passes": True})
            )

        mock_run.side_effect = side_effect
        await run_ralph_loop(run=run, hooks=HooksManager([]))
        assert mock_run.call_count == 1

    @patch("ralpher.loop.prepare._checkout_branch")
    @patch("ralpher.loop.prepare.extract_prd_json", new_callable=AsyncMock)
    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_exits_with_error_when_max_iterations_reached(
        self, mock_run, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        run = _make_run("loop-fail", max_iterations=2)
        run.task_dir.mkdir(parents=True)

        prd_data = _make_prd()
        (run.task_dir / "PRD.md").write_text("# PRD")
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        async def side_effect(**kwargs):
            (run.task_dir / "current_user_story.json").write_text(
                json.dumps({**_STORY_TEMPLATE, "passes": False})
            )

        mock_run.side_effect = side_effect
        import sys

        _loop_mod = sys.modules["ralpher.loop.loop"]
        monkeypatch.setattr(_loop_mod.time, "sleep", lambda _: None)
        with pytest.raises(SystemExit):
            await run_ralph_loop(run=run, hooks=HooksManager([]))
        assert mock_run.call_count == 2

    @patch("ralpher.loop.prepare._checkout_branch")
    @patch("ralpher.loop.prepare.extract_prd_json", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_loop_when_all_stories_already_pass(
        self, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        run = _make_run("loop-skip")
        run.task_dir.mkdir(parents=True)

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
        (run.task_dir / "PRD.md").write_text("# PRD")
        (run.task_dir / "prd.json").write_text(json.dumps(prd_data))

        await run_ralph_loop(run=run, hooks=HooksManager([]))
