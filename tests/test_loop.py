import json
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.loop.prepare import _init_progress
from ralpher.loop.iterate import Result, iterate
from ralpher.loop.loop import run_ralph_loop
from ralpher.models import ProjectConfig, Tasks, Project
from ralpher.utils.hooks import HooksManager


def _make_tasks_data(tasks: list[dict] | None = None) -> dict:
    if tasks is None:
        tasks = [
            {
                "id": "T-001",
                "title": "Login",
                "description": "User can log in",
                "acceptance_criteria": ["AC1"],
                "passes": False,
            }
        ]
    return {"tasks": tasks}


_TASK_TEMPLATE = {
    "id": "T-001",
    "title": "Login",
    "description": "User can log in",
    "acceptance_criteria": ["AC1"],
}


def _make_project(task_id: str, max_iterations: int = 5) -> Project:
    project = Project(id=task_id, max_iterations=max_iterations)
    return project


def _write_config(project: Project) -> None:
    """Write a default config.json so prepare() can load it."""
    config = ProjectConfig(base_branch="main", target_branch=f"ralph/{project.id}")
    project.save_config(config)


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
    async def test_marks_task_passed_when_current_task_passes(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-task")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_json.write_text(json.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        # implement() call returns None; verify() call returns Result.
        mock_run.side_effect = [None, Result(task_passed=True)]
        await iterate(project, HooksManager([]))

        updated = Tasks.model_validate(json.loads(project.tasks_json.read_text()))
        assert updated.tasks[0].passes is True

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-fail")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_json.write_text(json.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = SystemExit("Claude process returned an error.")

        with pytest.raises(SystemExit):
            await iterate(project, HooksManager([]))

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_writes_current_task(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-logs")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_json.write_text(json.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        written_task: dict | None = None

        async def side_effect(**kwargs):
            nonlocal written_task
            if written_task is None:
                # First call is the implement() session — capture the file then.
                written_task = json.loads(project.current_task_json.read_text())
                return None
            return Result(task_passed=False)

        mock_run.side_effect = side_effect
        await iterate(project, HooksManager([]))

        assert written_task["id"] == "T-001"  # type: ignore

    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_command_uses_iterate_and_verify_skills(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "iter-flags"
        project = _make_project(task_id)
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_json.write_text(json.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [None, Result(task_passed=False)]
        await iterate(project, HooksManager([]))

        assert mock_run.call_count == 2
        implement_kwargs, verify_kwargs = (
            mock_run.call_args_list[0][1],
            mock_run.call_args_list[1][1],
        )
        # Prompts are rendered from the prompt templates; they reference the
        # project's files by path (which embed the project id) rather than a
        # slash command.
        assert "Coding Agent Instructions" in implement_kwargs["prompt"]
        assert task_id in implement_kwargs["prompt"]
        assert implement_kwargs.get("schema") is None
        assert implement_kwargs["project"] is project
        assert "Verification Agent Instructions" in verify_kwargs["prompt"]
        assert task_id in verify_kwargs["prompt"]
        assert verify_kwargs["schema"] is Result


class TestLoop:
    @patch("ralpher.loop.prepare.extract_tasks", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_plan_md_missing(
        self, mock_extract, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("no-plan")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await run_ralph_loop(project=project, hooks=HooksManager([]))

    @patch("ralpher.loop.prepare.checkout_branch")
    @patch("ralpher.loop.prepare.extract_tasks", new_callable=AsyncMock)
    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_completes_when_all_tasks_pass(
        self, mock_run, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("loop-done")
        project.project_dir.mkdir(parents=True)
        _write_config(project)

        tasks_data = _make_tasks_data()
        project.plan_md.write_text("# Plan")
        project.tasks_json.write_text(json.dumps(tasks_data))

        # Each iteration: implement() returns None, verify() returns Result.
        mock_run.side_effect = [None, Result(task_passed=True)]
        await run_ralph_loop(project=project, hooks=HooksManager([]))
        assert mock_run.call_count == 2

    @patch("ralpher.loop.prepare.checkout_branch")
    @patch("ralpher.loop.prepare.extract_tasks", new_callable=AsyncMock)
    @patch("ralpher.loop.iterate.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_exits_with_error_when_max_iterations_reached(
        self, mock_run, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("loop-fail", max_iterations=2)
        project.project_dir.mkdir(parents=True)
        _write_config(project)

        tasks_data = _make_tasks_data()
        project.plan_md.write_text("# Plan")
        project.tasks_json.write_text(json.dumps(tasks_data))

        # Two iterations × (implement + verify) == 4 run_claude calls.
        mock_run.side_effect = [
            None,
            Result(task_passed=False),
            None,
            Result(task_passed=False),
        ]
        import sys

        _loop_mod = sys.modules["ralpher.loop.loop"]
        monkeypatch.setattr(_loop_mod.time, "sleep", lambda _: None)
        with pytest.raises(SystemExit):
            await run_ralph_loop(project=project, hooks=HooksManager([]))
        assert mock_run.call_count == 4

    @patch("ralpher.loop.prepare.checkout_branch")
    @patch("ralpher.loop.prepare.extract_tasks", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_skips_loop_when_all_tasks_already_pass(
        self, mock_extract, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("loop-skip")
        project.project_dir.mkdir(parents=True)
        _write_config(project)

        tasks_data = _make_tasks_data(
            [
                {
                    "id": "T-001",
                    "title": "Done",
                    "description": "Already done",
                    "acceptance_criteria": [],
                    "passes": True,
                }
            ]
        )
        project.plan_md.write_text("# Plan")
        project.tasks_json.write_text(json.dumps(tasks_data))

        await run_ralph_loop(project=project, hooks=HooksManager([]))
