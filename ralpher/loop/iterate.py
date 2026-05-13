from datetime import datetime
from pathlib import Path

import rich
from pydantic import BaseModel, Field
import tempfile
import contextlib

from ..models import Project
from ..utils.claude import run_claude
from ..utils.hooks import HooksManager


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


def _append_verifier_notes(
    progress_md: Path, task_id: str, task_passed: bool, notes: str | None
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "PASSED" if task_passed else "FAILED"
    body = notes.strip() if notes and notes.strip() else "N/A"
    section = (
        f"\n### VERIFIER NOTES - {timestamp} - {task_id}\n\n"
        f"- **Status:** {status}\n"
        f"- **Notes:**\n\n{body}\n\n---\n"
    )
    with progress_md.open("a") as f:
        f.write(section)


@contextlib.contextmanager
def with_temp_file(original: Path):
    with tempfile.NamedTemporaryFile(
        prefix="progress-", suffix=".md", delete=False
    ) as file:
        # Copy original content to temp file
        assert original.exists()
        Path(file.name).write_text(original.read_text())
    try:
        yield file.name
    finally:
        # Copy content back to original file
        content = Path(file.name).read_text()
        if content:
            original.write_text(content)
        # Remove temp file
        Path(file.name).unlink()


async def implement(project: Project) -> None:
    assert project.current_iteration is not None

    with with_temp_file(project.progress_md) as temp_file:
        await run_claude(
            kind="iterate",
            prompt=f"/ralpher:iterate {project.id} {temp_file}",
            project=project,
            model=project.model,
        )


async def verify(project: Project) -> Result:
    """Run a fresh, non-persistent Claude session to independently verify the
    current task. The verifier has no context from the implementation session,
    so it cannot rubber-stamp its own work."""
    assert project.current_iteration is not None

    return await run_claude(
        kind="verify",
        prompt=f"/ralpher:verify {project.id}",
        project=project,
        model=project.model,
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

    # save to current_task.json for claude to read
    project.save_current_task(task)

    # Implement the task in one session, then verify in a fresh session so the
    # verifier isn't biased by the implementer's context.
    await implement(project)
    result = await verify(project)

    # Always persist the verifier verdict to the progress log so the next
    # implementation iteration can see the previous status + any diagnosis.
    _append_verifier_notes(
        project.progress_md, task.id, result.task_passed, result.notes
    )

    # Propagate changes to tasks.json if updated
    tasks = project.load_tasks()
    assert tasks is not None
    if result.task_passed:
        # Update the corresponding task in tasks.json
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
