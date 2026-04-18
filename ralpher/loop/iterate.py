import rich
from pydantic import BaseModel, Field

from ..models import Project
from ..utils.claude import run_claude
from ..utils.hooks import HooksManager


class Result(BaseModel):
    task_passed: bool = Field(
        description="Whether the task is fully implemented and passes all checks."
    )


async def implement_and_review(project: Project) -> Result:
    assert project.current_iteration is not None

    return await run_claude(
        prompt=f"/ralpher:iterate {project.id}",
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

    # Implement the task using claude
    result = await implement_and_review(project)

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
