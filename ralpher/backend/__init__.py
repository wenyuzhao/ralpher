"""Coding-agent backends and the dispatcher that selects between them.

This package is the single abstraction boundary for invoking a coding agent.
Callers import `run_agent` / `run_agent_plan_mode` from here and never reach
into a specific backend; the dispatcher builds one based on ``project.backend``:

- ``claude-code`` → :class:`ralpher.backend.claude.ClaudeBackend` (the `claude` CLI)
- ``antigravity`` → :class:`ralpher.backend.antigravity.AntigravityBackend` (the `agy` CLI)

Both are subclasses of :class:`ralpher.backend.base.Backend`, which drives the
chosen CLI as a subprocess and owns everything the two have in common; each
subclass only builds its argv and recognizes its own terminal result record.
Anything shared above that layer (the plan-mode schema, the clarification
question UX) lives in :mod:`ralpher.backend.common`.
"""

from typing import overload

from pydantic import BaseModel

from ralpher.models import BackendKind, Project

from .antigravity import AntigravityBackend
from .base import AgentResult, Backend
from .claude import ClaudeBackend

__all__ = [
    "AgentResult",
    "Backend",
    "check_prerequisites",
    "get_backend",
    "run_agent",
    "run_agent_plan_mode",
]

BACKENDS: dict[BackendKind, type[Backend]] = {
    "claude-code": ClaudeBackend,
    "antigravity": AntigravityBackend,
}


def get_backend(project: Project) -> Backend:
    """The backend instance driving `project`'s run."""
    return BACKENDS[project.backend](project)


def check_prerequisites(kind: BackendKind) -> None:
    """Exit with an error if `kind`'s CLI is not available."""
    BACKENDS[kind].check_prerequisites()


@overload
async def run_agent(
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> None: ...


@overload
async def run_agent[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T: ...


async def run_agent[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T | None:
    """Run the project's selected agent to execute a prompt."""
    return await get_backend(project).run(
        kind=kind,
        prompt=prompt,
        model=model,
        schema=schema,
        readonly=readonly,
        tools=tools,
    )


async def run_agent_plan_mode(
    *, kind: str, prompt: str, project: Project, model: str | None = None
) -> None:
    """Run the project's selected agent with a Q&A loop for plan generation."""
    await get_backend(project).run_plan_mode(kind=kind, prompt=prompt, model=model)
