from datetime import datetime
from pathlib import Path

import rich

from ..agents import Verifier, Worker
from ..models import Project
from ..utils.hooks import HooksManager


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

    task_passed = False
    try:
        # The worker implements the task in one session; the verifier then runs in a
        # fresh one, so it isn't biased by the worker's context.
        report = await Worker(project).run()
        _append_progress(project.progress_md, task.id, report.notes)

        result = await Verifier(project).run()
        task_passed = result.task_passed

        # Always persist the verifier verdict to the progress log so the next
        # implementation iteration can see the previous status + any diagnosis.
        _append_verifier_notes(
            project.progress_md, task.id, result.task_passed, result.notes
        )
    except (Exception, SystemExit) as e:
        if isinstance(e, SystemExit) and (e.code == 0 or e.code is None):
            raise

    # Propagate changes to tasks.toml if updated
    tasks = project.load_tasks()
    assert tasks is not None
    # Record this verdict on the corresponding task in tasks.toml: a pass flips
    # `passed`, a failure bumps that task's running failure count.
    for t in tasks.tasks:
        if t.id == task.id:
            if task_passed:
                t.passed = True
            else:
                t.failures += 1
            break
    project.save_tasks(tasks)

    # Finish iteration
    project.remove_current_task()
    if task_passed:
        rich.print("  [green]✔ PASSED[/green]\n")
    else:
        rich.print("  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, task.id)
