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
    story = run.load_original_current_user_story()
    assert i is not None

    # Start iteration
    rich.print(
        f"[bold magenta]\\[#{i}] [i]{story.id}[/] - {story.title}[/bold magenta]\n"
    )
    await hooks.on_iteration_start(i, story.id)

    # save to current_user_story.json for claude to read
    run.save_current_user_story(story)

    # Implement the user story using claude
    await implement_and_review(run, hooks)

    # Propagate changes to prd.json if updated
    modified_story = run.load_current_user_story()
    prd = run.load_prd()
    if modified_story.passes:
        # Update the corresponding user story in prd.json
        for s in prd.user_stories:
            if s.id == modified_story.id:
                s.passes = True
                break
        prd.save(run.prd_json_file)

    # Finish iteration
    run.remove_current_user_story()
    if modified_story.passes:
        rich.print(f"  [green]✔ PASSED[/green]\n")
    else:
        rich.print(f"  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, story.id)
