from datetime import datetime
from pathlib import Path

import rich
from pydantic import BaseModel, Field

from ..backend import context_file, run_agent
from ..models import Project
from ..prompts import render_prompt
from ..utils.hooks import HooksManager


class ProgressReport(BaseModel):
    """What the implementation session reports back about its iteration.

    The agent never writes the progress log itself — `.ralpher` is read-only to
    it — so it returns the entry it wants recorded and ralpher appends it.
    """

    notes: str = Field(
        description=(
            "Markdown body of this iteration's progress log entry: what was "
            "implemented, which files changed, which quality checks were run "
            "and their outcome (with the exact error output of any that still "
            "fail), and learnings for future iterations. Do not include a "
            "date/task heading or a trailing '---' separator — those are added "
            "for you."
        )
    )


class Result(BaseModel):
    task_passed: bool = Field(
        description="Whether the task is fully implemented and passes all checks."
    )
    notes: str | None = Field(
        default=None,
        description=(
            "When task_passed is false, a markdown-formatted note describing "
            "what is still incomplete, which acceptance criteria are unmet, "
            "which checks failed and their error messages, and any hints for "
            "the next attempt. Null or empty when task_passed is true."
        ),
    )


def _append_progress(progress_md: Path, task_id: str, notes: str) -> None:
    """Append the implementation session's reported entry to the progress log."""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    body = notes.strip() if notes.strip() else "N/A"
    with progress_md.open("a") as f:
        f.write(f"\n## {timestamp} - {task_id}\n\n{body}\n\n---\n")


def _append_verifier_notes(
    progress_md: Path, task_id: str, task_passed: bool, notes: str | None
) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    status = "PASSED" if task_passed else "FAILED"
    body = notes.strip() if notes and notes.strip() else "N/A"
    section = (
        f"\n### VERIFIER NOTES - {timestamp} - {task_id}\n\n"
        f"- **Status:** {status}\n"
        f"- **Notes:**\n\n{body}\n\n---\n"
    )
    with progress_md.open("a") as f:
        f.write(section)


async def implement(project: Project) -> ProgressReport:
    """Implement the current task, returning the progress entry to record.

    The session reads the progress log but never writes it: it hands its entry
    back as structured output, which the caller appends.
    """
    assert project.current_iteration is not None

    return await run_agent(
        kind="loop",
        prompt=render_prompt(
            "iterate",
            current_task_path=str(project.current_task_toml),
            plan_path=str(project.plan_md),
            progress_path=str(project.progress_md),
            jj=project.jj,
            context_file=context_file(project.backend),
        ),
        project=project,
        schema=ProgressReport,
    )


async def verify(project: Project) -> Result:
    """Run a fresh, non-persistent Claude session to independently verify the
    current task. The verifier has no context from the implementation session,
    so it cannot rubber-stamp its own work."""
    assert project.current_iteration is not None

    return await run_agent(
        kind="verify",
        prompt=render_prompt(
            "verify",
            current_task_path=str(project.current_task_toml),
            plan_path=str(project.plan_md),
            jj=project.jj,
        ),
        project=project,
        schema=Result,
    )


async def iterate(project: Project, hooks: HooksManager) -> None:
    i = project.current_iteration
    tasks = project.load_tasks()
    assert tasks is not None
    assert project.current_task_id is not None
    task = tasks.get_task_by_id(project.current_task_id)
    assert task is not None
    assert i is not None

    # Start iteration
    rich.print(
        f"[bold magenta]\\[#{i}] [i]{task.id}[/] - {task.title}[/bold magenta]\n"
    )
    await hooks.on_iteration_start(i, task.id)

    # save to current_task.toml for claude to read
    project.save_current_task(task)

    # Implement the task in one session, then verify in a fresh session so the
    # verifier isn't biased by the implementer's context.
    report = await implement(project)
    _append_progress(project.progress_md, task.id, report.notes)

    result = await verify(project)

    # Always persist the verifier verdict to the progress log so the next
    # implementation iteration can see the previous status + any diagnosis.
    _append_verifier_notes(
        project.progress_md, task.id, result.task_passed, result.notes
    )

    # Propagate changes to tasks.toml if updated
    tasks = project.load_tasks()
    assert tasks is not None
    if result.task_passed:
        # Update the corresponding task in tasks.toml
        for t in tasks.tasks:
            if t.id == task.id:
                t.passes = True
                break
        project.save_tasks(tasks)

    # Finish iteration
    project.remove_current_task()
    if result.task_passed:
        rich.print("  [green]✔ PASSED[/green]\n")
    else:
        rich.print("  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, task.id)
