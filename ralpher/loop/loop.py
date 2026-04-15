import time

import rich
from ralpher.models import Project
from ralpher.utils.hooks.hooks import HooksManager

from .iterate import iterate
from .prepare import finalize_progress, prepare


async def run_ralph_loop(*, project: Project, hooks: HooksManager) -> None:
    should_continue = await prepare(project, hooks)
    if not should_continue:
        return

    await hooks.on_loop_start()

    all_passed = False
    iterations = 0

    def next_iteration() -> bool:
        nonlocal iterations, all_passed
        if project.max_iterations is not None and iterations >= project.max_iterations:
            return False
        project.current_iteration = iterations
        iterations += 1
        return True

    while next_iteration():
        # Pick next failing task
        tasks = project.load_tasks()
        assert tasks is not None
        failed_tasks = tasks.failed_tasks()
        assert failed_tasks, "No failing tasks found."
        task = failed_tasks[0]  # highest priority failing task
        project.current_task_id = task.id

        # Run iteration
        await iterate(project, hooks)

        # Check if all tasks pass after this iteration
        tasks = project.load_tasks()
        assert tasks is not None
        all_passed = len(tasks.failed_tasks()) == 0
        if all_passed:
            break

        if project.max_iterations is None or iterations < project.max_iterations - 1:
            time.sleep(3)

    if all_passed:
        finalize_progress(project.progress_md)
    await hooks.on_loop_end(iterations, all_passed)
    if all_passed:
        rich.print(f"[bold green]✔ Completed in {iterations} iterations![/bold green]")
    else:
        rich.print(
            f"[bold red]✘ Not completed after {iterations} iterations.[/bold red]"
        )
        raise SystemExit(1)
