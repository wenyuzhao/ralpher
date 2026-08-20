import tomllib
from unittest.mock import AsyncMock, patch

import pytest
import tomli_w

from ralpher.agents import ProgressReport, Result
from ralpher.loop.iterate import _append_progress, iterate
from ralpher.loop.loop import run_ralph_loop
from ralpher.loop.prepare import _init_progress
from ralpher.models import Project, ProjectConfig, Tasks
from ralpher.utils.hooks import HooksManager


def _make_tasks_data(tasks: list[dict] | None = None) -> dict:
    if tasks is None:
        tasks = [
            {
                "id": "T-001",
                "title": "Login",
                "description": "User can log in",
                "acceptance_criteria": ["AC1"],
                "passed": False,
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
    """Write a default config.toml so prepare() can load it."""
    config = ProjectConfig(base_branch="main", target_branch=f"ralph/{project.id}")
    project.save_config(config)


class TestInitProgress:
    def test_creates_file(self, tmp_path):
        progress_file = tmp_path / "progress.md"
        _init_progress(progress_file)
        content = progress_file.read_text()
        assert "# Ralph Progress Log" in content
        assert "Started:" in content


class TestProgressLog:
    def test_append_progress_wraps_notes_in_a_task_heading(self, tmp_path):
        progress = tmp_path / "progress.md"
        _init_progress(progress)
        _append_progress(progress, "T-001", "- Added login\n")

        content = progress.read_text()
        assert "- T-001\n" in content
        assert "- Added login" in content
        assert content.rstrip().endswith("---")

    def test_append_progress_keeps_earlier_entries(self, tmp_path):
        progress = tmp_path / "progress.md"
        _init_progress(progress)
        _append_progress(progress, "T-001", "- Added login")
        _append_progress(progress, "T-002", "- Added logout")

        content = progress.read_text()
        assert content.index("- Added login") < content.index("- Added logout")

    def test_append_progress_records_empty_notes_as_na(self, tmp_path):
        progress = tmp_path / "progress.md"
        _init_progress(progress)
        _append_progress(progress, "T-001", "   ")

        assert "N/A" in progress.read_text()


class TestIterate:
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
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
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        # implement() returns a ProgressReport; verify() returns a Result.
        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=True),
        ]
        await iterate(project, HooksManager([]))

        with project.tasks_toml.open("rb") as f:
            updated = Tasks.model_validate(tomllib.load(f))
        assert updated.tasks[0].passed is True

        # The implementer never touches progress.md; ralpher records its report.
        assert "did the thing" in project.progress_md.read_text()

    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_counts_verification_failures(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-failures")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        project.tasks_toml.write_text(tomli_w.dumps(_make_tasks_data()))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [
            ProgressReport(notes="attempt one"),
            Result(task_passed=False, notes="AC1 unmet"),
            ProgressReport(notes="attempt two"),
            Result(task_passed=False, notes="AC1 still unmet"),
        ]
        await iterate(project, HooksManager([]))
        await iterate(project, HooksManager([]))

        tasks = project.load_tasks()
        assert tasks is not None
        assert tasks.tasks[0].passed is False
        assert tasks.tasks[0].failures == 2
        assert "failures = 2" in project.tasks_toml.read_text()
        assert "**Verification failures:** 2" in project.tasks_md.read_text()

    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_passing_task_records_no_failure_count(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-clean")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        project.tasks_toml.write_text(tomli_w.dumps(_make_tasks_data()))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=True),
        ]
        await iterate(project, HooksManager([]))

        assert "failures" not in project.tasks_toml.read_text()
        assert "**Verification failures:**" not in project.tasks_md.read_text()

    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-fail")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = SystemExit("Claude process returned an error.")

        with pytest.raises(SystemExit):
            await iterate(project, HooksManager([]))

    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_writes_current_task(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("iter-logs")
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        tasks_data = _make_tasks_data()
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        written_task: dict | None = None

        async def side_effect(**kwargs):
            nonlocal written_task
            if written_task is None:
                # First call is the implement() session — capture the file then.
                with project.current_task_toml.open("rb") as f:
                    written_task = tomllib.load(f)
                return ProgressReport(notes="did the thing")
            return Result(task_passed=False)

        mock_run.side_effect = side_effect
        await iterate(project, HooksManager([]))

        assert written_task["id"] == "T-001"  # type: ignore

    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
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
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=False),
        ]
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
        assert implement_kwargs["schema"] is ProgressReport
        assert implement_kwargs["project"] is project
        assert "Verification Agent Instructions" in verify_kwargs["prompt"]
        assert task_id in verify_kwargs["prompt"]
        assert verify_kwargs["schema"] is Result

    @pytest.mark.parametrize(
        ("backend", "expected", "other"),
        [
            ("claude-code", "CLAUDE.md", "GEMINI.md"),
            ("antigravity", "GEMINI.md", "CLAUDE.md"),
        ],
    )
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_prompt_names_the_backends_context_file(
        self, mock_run, backend, expected, other, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project(f"iter-ctx-{backend}")
        project.backend = backend
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"

        project.tasks_toml.write_text(tomli_w.dumps(_make_tasks_data()))
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=False),
        ]
        await iterate(project, HooksManager([]))

        prompt = mock_run.call_args_list[0][1]["prompt"]
        assert f"## Update {expected} Files" in prompt
        assert other not in prompt


class TestLoop:
    @pytest.mark.asyncio
    async def test_raises_when_design_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _make_project("no-plan")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await run_ralph_loop(project=project, hooks=HooksManager([]))

    @pytest.mark.asyncio
    async def test_raises_when_tasks_toml_missing(self, tmp_path, monkeypatch):
        # Both halves come out of `ralpher plan` together; the loop no longer
        # extracts tasks itself, so a missing tasks.toml is a hard stop.
        monkeypatch.chdir(tmp_path)
        project = _make_project("no-tasks")
        project.project_dir.mkdir(parents=True)
        project.design_md.write_text("# Design")
        with pytest.raises(SystemExit):
            await run_ralph_loop(project=project, hooks=HooksManager([]))

    @patch("ralpher.loop.prepare.checkout_branch")
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_completes_when_all_tasks_pass(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("loop-done")
        project.project_dir.mkdir(parents=True)
        _write_config(project)

        tasks_data = _make_tasks_data()
        project.design_md.write_text("# Design")
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))

        # Each iteration: implement() returns a ProgressReport, verify() a Result.
        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=True),
        ]
        await run_ralph_loop(project=project, hooks=HooksManager([]))
        assert mock_run.call_count == 2

    @patch("ralpher.loop.prepare.checkout_branch")
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_exits_with_error_when_max_iterations_reached(
        self, mock_run, mock_checkout, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = _make_project("loop-fail", max_iterations=2)
        project.project_dir.mkdir(parents=True)
        _write_config(project)

        tasks_data = _make_tasks_data()
        project.design_md.write_text("# Design")
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))

        # Two iterations × (implement + verify) == 4 run_agent calls.
        mock_run.side_effect = [
            ProgressReport(notes="attempt 1"),
            Result(task_passed=False),
            ProgressReport(notes="attempt 2"),
            Result(task_passed=False),
        ]
        import sys

        _loop_mod = sys.modules["ralpher.loop.loop"]
        monkeypatch.setattr(_loop_mod.asyncio, "sleep", AsyncMock())
        with pytest.raises(SystemExit):
            await run_ralph_loop(project=project, hooks=HooksManager([]))
        assert mock_run.call_count == 4

    @patch("ralpher.loop.prepare.checkout_branch")
    @pytest.mark.asyncio
    async def test_skips_loop_when_all_tasks_already_pass(
        self, mock_checkout, tmp_path, monkeypatch
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
                    "passed": True,
                }
            ]
        )
        project.design_md.write_text("# Design")
        project.tasks_toml.write_text(tomli_w.dumps(tasks_data))

        await run_ralph_loop(project=project, hooks=HooksManager([]))
