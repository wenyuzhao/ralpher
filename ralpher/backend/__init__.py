"""Coding-agent backends and the dispatcher that selects between them.

This package is the single abstraction boundary for invoking a coding-agent
CLI. Its callers are the agents in :mod:`ralpher.agents` — a backend is *which
CLI runs*, an agent is *what it is asked to do* — which reach it through
`run_agent` / `run_agent_plan_mode` and never touch a specific backend; the
dispatcher builds one based on ``project.backend``:

- ``claude-code`` → :class:`ralpher.backend.claude.ClaudeBackend` (the `claude` CLI)
- ``antigravity`` → :class:`ralpher.backend.antigravity.AntigravityBackend` (the `agy` CLI)

Both are subclasses of :class:`ralpher.backend.base.Backend`, which drives the
chosen CLI as a subprocess and owns everything the two have in common; each
subclass only builds its argv and recognizes its own terminal result record.
Anything shared above that layer (the plan-mode schema, the clarification
question UX) lives in :mod:`ralpher.backend.common`.
"""

from collections.abc import Callable
from typing import overload

from pydantic import BaseModel

from ralpher.models import AgentRole, BackendKind, Project

from .antigravity import AntigravityBackend
from .base import AgentResult, Backend
from .claude import ClaudeBackend
from .common import Plan

__all__ = [
    "AgentResult",
    "Backend",
    "Plan",
    "check_prerequisites",
    "context_file",
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


def context_file(kind: BackendKind) -> str:
    """Name of the context file `kind`'s CLI reads (`CLAUDE.md`, `GEMINI.md`, …)."""
    return BACKENDS[kind].context_file


def check_prerequisites(kind: BackendKind) -> None:
    """Exit with an error if `kind`'s CLI is not available."""
    BACKENDS[kind].check_prerequisites()


@overload
async def run_agent(
    *,
    role: AgentRole,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> None: ...


@overload
async def run_agent[T: BaseModel](
    *,
    role: AgentRole,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> T: ...


async def run_agent[T: BaseModel](
    *,
    role: AgentRole,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> T | None:
    """Run the project's selected backend for one turn, as `role`."""
    return await get_backend(project).run(
        role=role,
        prompt=prompt,
        model=model,
        schema=schema,
        readonly=readonly,
        tools=tools,
        extra_args=extra_args,
    )


async def run_agent_plan_mode(
    *,
    role: AgentRole,
    prompt: str,
    project: Project,
    model: str | None = None,
    validate: Callable[[Plan], str | None] | None = None,
    readonly: bool = True,
    tools: list[str] | None = None,
    extra_args: list[str] | None = None,
    max_corrections: int | None = None,
) -> None:
    """Run the project's selected backend with a Q&A loop for plan generation.

    `validate` (see `Backend.run_plan_mode`) vets the returned plan before it is
    written; returning a message sends the agent back to fix it.
    """
    await get_backend(project).run_plan_mode(
        role=role,
        prompt=prompt,
        model=model,
        validate=validate,
        readonly=readonly,
        tools=tools,
        extra_args=extra_args,
        max_corrections=max_corrections,
    )
