"""Tests for the `Agent` abstraction — the four roles and their configuration.

What each agent *does* end to end is covered where it is used (tests/test_plan.py,
tests/test_refine.py, tests/test_loop.py). Here the backend is patched out, so
what is asserted is the wiring: which prompt, which schema, which flags, and how
an `[agents.<role>]` table in settings.toml overrides them.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.agents import (
    AGENTS,
    Agent,
    OutputAgent,
    Planner,
    PlanningAgent,
    ProgressReport,
    Refiner,
    Result,
    Verifier,
    Worker,
)
from ralpher.backend import Plan
from ralpher.models import AGENT_ROLES, PlannedTask, Project, Task


def _project(tmp_path, monkeypatch, **kwargs) -> Project:
    monkeypatch.chdir(tmp_path)
    project = Project(id="proj", **kwargs)
    project.project_dir.mkdir(parents=True, exist_ok=True)
    return project


def _write_settings(tmp_path, content: str) -> None:
    ralpher = tmp_path / ".ralpher"
    ralpher.mkdir(exist_ok=True)
    (ralpher / "settings.toml").write_text(content)


def _task(task_id: str, *, passed: bool = False) -> Task:
    return Task(
        id=task_id,
        title="Login",
        description=f"Do {task_id}",
        acceptance_criteria=["Tests pass"],
        passed=passed,
    )


def _agent(cls: type[Agent], project: Project) -> Agent:
    """Build `cls` for `project`, supplying the refiner's extra inputs."""
    if cls is Refiner:
        return Refiner(project, input_path=Path("/tmp/in.md"), completed=[])
    return cls(project)


# --- the registry ---------------------------------------------------------- #


class TestRegistry:
    def test_covers_every_role(self):
        assert set(AGENTS) == set(AGENT_ROLES)

    def test_each_agent_is_filed_under_its_own_role(self):
        for role, cls in AGENTS.items():
            assert cls.role == role

    def test_roles_map_to_the_expected_agents(self):
        assert AGENTS == {
            "planner": Planner,
            "refiner": Refiner,
            "worker": Worker,
            "verifier": Verifier,
        }

    def test_planning_agents_plan_and_output_agents_report(self):
        assert issubclass(Planner, PlanningAgent)
        assert issubclass(Refiner, PlanningAgent)
        assert issubclass(Worker, OutputAgent)
        assert issubclass(Verifier, OutputAgent)


# --- prompts --------------------------------------------------------------- #


class TestPrompts:
    """Each agent renders its own template, with every variable it references."""

    @pytest.mark.parametrize("cls", list(AGENTS.values()))
    def test_prompt_renders(self, cls, tmp_path, monkeypatch):
        # StrictUndefined means a variable the agent forgot raises here.
        assert _agent(cls, _project(tmp_path, monkeypatch)).prompt()

    def test_planner_points_at_the_prompt_file(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        assert str(project.prompt_md) in Planner(project).prompt()

    def test_refiner_points_at_both_halves_and_the_input(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        prompt = Refiner(
            project, input_path=Path("/tmp/refine-in.md"), completed=[]
        ).prompt()
        assert str(project.design_md) in prompt
        assert str(project.tasks_toml) in prompt
        assert "/tmp/refine-in.md" in prompt

    def test_refiner_lists_the_frozen_tasks(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        prompt = Refiner(
            project, input_path=Path("/tmp/in.md"), completed=[_task("T-001")]
        ).prompt()
        assert "Already-Completed Tasks" in prompt

    def test_worker_points_at_the_current_task_and_progress_log(
        self, tmp_path, monkeypatch
    ):
        project = _project(tmp_path, monkeypatch)
        prompt = Worker(project).prompt()
        assert str(project.current_task_toml) in prompt
        assert str(project.progress_md) in prompt

    @pytest.mark.parametrize(
        ("backend", "expected"),
        [("claude-code", "CLAUDE.md"), ("antigravity", "GEMINI.md")],
    )
    def test_worker_names_the_backends_context_file(
        self, backend, expected, tmp_path, monkeypatch
    ):
        project = _project(tmp_path, monkeypatch, backend=backend)
        assert expected in Worker(project).prompt()

    def test_verifier_does_not_see_the_progress_log(self, tmp_path, monkeypatch):
        # The verifier judges the repo, not the worker's own account of it.
        project = _project(tmp_path, monkeypatch)
        assert str(project.progress_md) not in Verifier(project).prompt()

    @pytest.mark.parametrize("cls", list(AGENTS.values()))
    def test_project_jj_reaches_every_prompt(self, cls, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, jj=True)
        assert "Jujutsu" in _agent(cls, project).prompt()

    def test_worker_prompt_requires_timeout(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        prompt = Worker(project).prompt()
        assert "timeout" in prompt.lower()

    def test_verifier_prompt_requires_timeout(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        prompt = Verifier(project).prompt()
        assert "timeout" in prompt.lower()


# --- declared configuration ------------------------------------------------ #


class TestDeclaredConfig:
    def test_planning_agents_are_read_only(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        assert Planner(project).resolved_readonly is True
        assert _agent(Refiner, project).resolved_readonly is True

    def test_worker_and_verifier_may_write(self, tmp_path, monkeypatch):
        # The verifier runs the project's checks, which need a writable tree.
        project = _project(tmp_path, monkeypatch)
        assert Worker(project).resolved_readonly is False
        assert Verifier(project).resolved_readonly is False

    def test_output_schemas(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        assert Worker(project).output is ProgressReport
        assert Verifier(project).output is Result

    @pytest.mark.parametrize("cls", list(AGENTS.values()))
    def test_no_tools_are_pinned_by_default(self, cls, tmp_path, monkeypatch):
        # None leaves the choice to the backend (READONLY_TOOLS on a read-only
        # claude turn), rather than pinning a list here.
        assert _agent(cls, _project(tmp_path, monkeypatch)).resolved_tools is None


# --- per-role settings ------------------------------------------------------ #


class TestPerRoleSettings:
    def test_readonly_override(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, "[agents.worker]\nreadonly = true\n")
        assert Worker(_project(tmp_path, monkeypatch)).resolved_readonly is True

    def test_tools_override(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, '[agents.worker]\ntools = ["Read", "Bash"]\n')
        assert Worker(_project(tmp_path, monkeypatch)).resolved_tools == [
            "Read",
            "Bash",
        ]

    def test_extra_args_override(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, '[agents.verifier]\nextra_args = ["--foo"]\n')
        project = _project(tmp_path, monkeypatch)
        assert Verifier(project).extra_args == ["--foo"]
        # Set for one role only, so the others stay empty.
        assert Worker(project).extra_args == []

    def test_settings_of_another_role_do_not_leak(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, "[agents.worker]\nreadonly = true\n")
        assert Verifier(_project(tmp_path, monkeypatch)).resolved_readonly is False


# --- what reaches the backend ----------------------------------------------- #


class TestOutputAgentRun:
    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    async def test_passes_role_prompt_and_schema(self, mock_run, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        mock_run.return_value = ProgressReport(notes="done")

        assert await Worker(project).run() == ProgressReport(notes="done")
        kwargs = mock_run.call_args[1]
        assert kwargs["role"] == "worker"
        assert kwargs["schema"] is ProgressReport
        assert kwargs["project"] is project
        assert "Coding Agent Instructions" in kwargs["prompt"]

    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    async def test_unset_settings_pass_through_as_none(
        self, mock_run, tmp_path, monkeypatch
    ):
        mock_run.return_value = Result(task_passed=True)
        await Verifier(_project(tmp_path, monkeypatch)).run()
        kwargs = mock_run.call_args[1]
        assert kwargs["model"] is None
        assert kwargs["tools"] is None
        assert kwargs["readonly"] is False
        assert kwargs["extra_args"] == []

    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent", new_callable=AsyncMock)
    async def test_per_role_settings_reach_the_backend(
        self, mock_run, tmp_path, monkeypatch
    ):
        _write_settings(
            tmp_path,
            "[agents.verifier]\n"
            'model = "cheap:low"\n'
            "readonly = true\n"
            'tools = ["Read"]\n'
            'extra_args = ["--foo"]\n',
        )
        mock_run.return_value = Result(task_passed=True)
        await Verifier(_project(tmp_path, monkeypatch)).run()
        kwargs = mock_run.call_args[1]
        assert kwargs["model"] == "cheap:low"
        assert kwargs["readonly"] is True
        assert kwargs["tools"] == ["Read"]
        assert kwargs["extra_args"] == ["--foo"]


class TestPlanningAgentRun:
    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    async def test_passes_role_and_prompt(self, mock_run, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        await Planner(project).run()
        kwargs = mock_run.call_args[1]
        assert kwargs["role"] == "planner"
        assert kwargs["project"] is project
        assert kwargs["readonly"] is True
        assert kwargs["max_corrections"] is None

    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    async def test_max_corrections_override(self, mock_run, tmp_path, monkeypatch):
        _write_settings(tmp_path, "[agents.planner]\nmax_corrections = 1\n")
        await Planner(_project(tmp_path, monkeypatch)).run()
        assert mock_run.call_args[1]["max_corrections"] == 1

    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    async def test_planner_accepts_any_plan(self, mock_run, tmp_path, monkeypatch):
        # Only the refiner has something to freeze; the planner starts fresh.
        await Planner(_project(tmp_path, monkeypatch)).run()
        validate = mock_run.call_args[1]["validate"]
        assert validate(Plan(markdown="# Design", tasks=[])) is None

    @pytest.mark.asyncio
    @patch("ralpher.agents.base.run_agent_plan_mode", new_callable=AsyncMock)
    async def test_refiner_validate_freezes_completed_tasks(
        self, mock_run, tmp_path, monkeypatch
    ):
        project = _project(tmp_path, monkeypatch)
        done = _task("T-001", passed=True)
        await Refiner(project, input_path=Path("/tmp/in.md"), completed=[done]).run()
        validate = mock_run.call_args[1]["validate"]

        kept = PlannedTask(**done.model_dump(exclude={"passed"}))
        assert validate(Plan(markdown="# Design", tasks=[kept])) is None
        assert validate(Plan(markdown="# Design", tasks=[])) is not None
