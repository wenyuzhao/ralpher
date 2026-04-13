import time

import rich
from ralpher.models import RunInfo
from ralpher.utils.hooks.hooks import HooksManager

from .iterate import iterate
from .prepare import prepare


async def run_ralph_loop(*, run: RunInfo, hooks: HooksManager) -> None:
    should_continue = await prepare(run, hooks)
    if not should_continue:
        return

    await hooks.on_loop_start()

    all_passed = False
    iterations = 0

    for i in range(run.max_iterations):
        iterations += 1
        run.current_iteration = i

        # Pick user story
        prd = run.load_prd()
        user_stories = prd.failed_stories()
        user_stories.sort(key=lambda s: s.priority)
        assert user_stories, "No failing user stories found."
        story = user_stories[0]  # highest priority failing story
        run.current_user_story_id = story.id

        # Run iteration
        await iterate(run, hooks)

        # Check if all user stories pass after this iteration
        prd = run.load_prd()
        all_passed = len(prd.failed_stories()) == 0
        if all_passed:
            break

        if i < run.max_iterations - 1:
            time.sleep(3)

    await hooks.on_loop_end(iterations, all_passed)
    if all_passed:
        rich.print(f"[bold green]✔ Completed in {iterations} iterations![/bold green]")
    else:
        rich.print(
            f"[bold red]✘ Not completed after {iterations} iterations.[/bold red]"
        )
        raise SystemExit(1)
