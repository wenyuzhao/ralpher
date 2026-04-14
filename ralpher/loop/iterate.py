import rich

from ..models import RunInfo
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail
from ..utils.hooks import HooksManager


async def implement_and_review(run: RunInfo, hooks: HooksManager):
    assert run.current_iteration is not None

    i = run.current_iteration

    try:
        await run_claude(
            prompt=f"/ralpher:iterate {run.id}", task_dir=run.task_dir, model=run.model
        )
    except ClaudeError as e:
        await hooks.on_error(f"Iteration {i} failed with exit code {e.returncode}")
        fail(f"Claude process exited with code {e.returncode}")


async def iterate(run: RunInfo, hooks: HooksManager) -> None:
    i = run.current_iteration
    task = run.load_original_current_task()
    assert i is not None

    # Start iteration
    rich.print(
        f"[bold magenta]\\[#{i}] [i]{task.id}[/] - {task.title}[/bold magenta]\n"
    )
    await hooks.on_iteration_start(i, task.id)

    # save to current_task.json for claude to read
    run.save_current_task(task)

    # Implement the task using claude
    await implement_and_review(run, hooks)

    # Propagate changes to plan.json if updated
    modified_task = run.load_current_task()
    plan = run.load_plan()
    if modified_task.passes:
        # Update the corresponding task in plan.json
        for t in plan.tasks:
            if t.id == modified_task.id:
                t.passes = True
                break
        plan.save(run.plan_json_file)

    # Finish iteration
    run.remove_current_task()
    if modified_task.passes:
        rich.print(f"  [green]✔ PASSED[/green]\n")
    else:
        rich.print(f"  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, task.id)
