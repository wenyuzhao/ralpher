"""Coding-agent backends and the dispatcher that selects between them.

This package is the single abstraction boundary for invoking a coding agent.
Callers import `run_agent` / `run_agent_plan_mode` from here and never reach
into a specific backend; the dispatcher picks one based on ``project.backend``:

- ``claude-code`` → :mod:`ralpher.backend.claude` (Claude Agent SDK)
- ``antigravity`` → :mod:`ralpher.backend.antigravity` (Google Antigravity SDK)

The two backends are independent of each other; anything they share (the
plan-mode schema, the clarification-question UX) lives in
:mod:`ralpher.backend.common`. Backends are imported lazily so a run only
loads the SDK it actually uses.
"""

from typing import overload

from pydantic import BaseModel

from ralpher.models import Project

__all__ = ["run_agent", "run_agent_plan_mode"]


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
    if project.backend == "antigravity":
        from .antigravity import run_antigravity

        return await run_antigravity(
            kind=kind,
            prompt=prompt,
            project=project,
            model=model,
            schema=schema,
            readonly=readonly,
            tools=tools,
        )

    from .claude import run_claude

    return await run_claude(
        kind=kind,
        prompt=prompt,
        project=project,
        model=model,
        schema=schema,
        readonly=readonly,
        tools=tools,
    )


async def run_agent_plan_mode(
    *, kind: str, prompt: str, project: Project, model: str | None = None
):
    """Run the project's selected agent with a Q&A loop for plan generation."""
    if project.backend == "antigravity":
        from .antigravity import run_antigravity_plan_mode

        return await run_antigravity_plan_mode(
            kind=kind, prompt=prompt, project=project, model=model
        )

    from .claude import run_claude_plan_mode

    return await run_claude_plan_mode(
        kind=kind, prompt=prompt, project=project, model=model
    )
