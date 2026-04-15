import rich

from ..models import Project
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail
from ..utils.hooks import HooksManager


async def implement_and_review(project: Project, hooks: HooksManager):
    assert project.current_iteration is not None

    i = project.current_iteration

    try:
        await run_claude(
            prompt=f"/ralpher:iterate {project.id}",
            project_dir=project.project_dir,
            model=project.model,
        )
    except ClaudeError as e:
        await hooks.on_error(f"Iteration {i} failed with exit code {e.returncode}")
        fail(f"Claude process exited with code {e.returncode}")


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

    # Implement the task using claude
    await implement_and_review(project, hooks)

    # Propagate changes to tasks.json if updated
    modified_task = project.load_current_task()
    assert modified_task is not None
    tasks = project.load_tasks()
    assert tasks is not None
    if modified_task.passes:
        # Update the corresponding task in tasks.json
        for t in tasks.tasks:
            if t.id == modified_task.id:
                t.passes = True
                break
        project.save_tasks(tasks)

    # Finish iteration
    project.remove_current_task()
    if modified_task.passes:
        rich.print("  [green]✔ PASSED[/green]\n")
    else:
        rich.print("  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, task.id)
