import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
import json
import subprocess

import rich
from .prd.extract import extract_prd_json
from .models import PRD
from .utils.spinner import Spinner
from .utils.error import fail
from rich.prompt import Confirm
from .utils.hooks import HooksManager


async def loop(task_dir: Path, max_iterations: int, hooks: HooksManager) -> None:
    """Run Claude in a loop, checking for completion signal each iteration."""
    task_id = task_dir.name
    prd_file = task_dir / "prd.json"
    prd_doc = task_dir / "PRD.md"
    progress_file = task_dir / "progress.md"

    if not prd_doc.exists():
        await hooks.on_error("PRD.md not found")
        fail(f"{prd_doc} not found.")

    if not prd_file.exists():
        rich.print(f"[bold blue]Extracting prd.json from PRD.md[/]\n")
        await hooks.on_extract_start()
        await extract_prd_json(task_id)
        if not prd_file.exists():
            await hooks.on_error("Failed to extract prd.json")
            fail(f"{prd_file} still not found after extraction.")
        await hooks.on_extract_end()

    await hooks.on_loop_start()

    prd = PRD.model_validate(json.loads(prd_file.read_text()))

    num_stories = len(prd.user_stories)
    num_failed_stories = len(prd.failed_stories())

    if num_failed_stories == 0:
        rich.print(f"[bold green]✔ All {num_stories} user stories already pass![/]")
        await hooks.on_loop_end(0, True)
        return

    rich.print(f" • Incomplete user stories: {num_failed_stories} / {num_stories}")
    rich.print(f" • Branch: [i]{prd.branch_name}[/]\n")
    rich.print(f" • Max iterations: {max_iterations}\n")

    # Track current branch
    _checkout_branch(prd)

    # Initialize progress file if it doesn't exist
    if not progress_file.exists():
        _init_progress(progress_file)

    if max_iterations < len(prd.user_stories):
        rich.print(
            f"[yellow][b]Warning:[/] Max iterations ({max_iterations}) is less than the number of user stories ({len(prd.user_stories)}). Some stories may not be attempted.[/]\n"
        )
        if not Confirm.ask("Do you want to continue?", default=False):
            await hooks.on_cancel(
                "User aborted due to max_iterations < number of user stories."
            )
            raise SystemExit(0)

    all_passed = False
    iterations = 0

    for i in range(max_iterations):
        iterations += 1

        # Run claude
        await _run_one_iteration(task_id, prd, task_dir, i, hooks)

        # Check for completion
        prd = PRD.model_validate(json.loads(prd_file.read_text()))
        all_passed = len(prd.failed_stories()) == 0
        if all_passed:
            break

        if i < max_iterations - 1:
            time.sleep(3)

    await hooks.on_loop_end(iterations, all_passed)
    if all_passed:
        rich.print(f"[bold green]✔ Completed in {iterations} iterations![/bold green]")
    else:
        rich.print(
            f"[bold red]✘ Not completed after {iterations} iterations.[/bold red]"
        )
        raise SystemExit(1)


async def _run_one_iteration(
    task_id: str, prd: PRD, task_dir: Path, i: int, hooks: HooksManager
) -> None:
    """Run claude --dangerously-skip-permissions --print with CLAUDE.md as stdin."""

    # Pick user story
    user_stories = prd.failed_stories()
    user_stories.sort(key=lambda s: s.priority)
    assert user_stories, "No failing user stories found."
    story = user_stories[0]  # highest priority failing story
    (task_dir / "current_user_story.json").write_text(
        json.dumps(story.model_dump(), indent=2)
    )
    logs_dir = task_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Print banner
    rich.print(
        f"[bold magenta]\\[#{i}] [i]{story.id}[/] - {story.title}[/bold magenta]\n",
    )
    await hooks.on_iteration_start(i, story.id)

    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "dontAsk",
        "--plugin-dir",
        str(Path(__file__).resolve().parent / "plugin"),
        "--print",
        f"/ralpher:loop {task_id}",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async with Spinner() as spinner:
        await spinner.run(proc)

    # Save stdout and stderr to log files for debugging
    stdout = (await proc.stdout.read()).decode() if proc.stdout else ""
    stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
    (logs_dir / f"{i}.out.log").write_text(stdout)
    (logs_dir / f"{i}.err.log").write_text(stderr)

    if proc.returncode != 0:
        await hooks.on_error(f"Iteration {i} failed with exit code {proc.returncode}")
        fail(f"Claude process exited with code {proc.returncode}")

    # Propagate changes to prd.json if updated
    prd_file = task_dir / "prd.json"
    current_user_story_file = task_dir / "current_user_story.json"
    assert prd_file.exists(), "prd.json not found after iteration."
    assert (
        current_user_story_file.exists()
    ), "current_user_story.json not found after iteration."
    cus = json.loads(current_user_story_file.read_text())
    success = cus.get("passes", False)
    if success:
        # Update the corresponding user story in prd.json
        prd = PRD.model_validate(json.loads(prd_file.read_text()))
        for s in prd.user_stories:
            if s.id == cus["id"]:
                s.passes = True
                break
        prd_file.write_text(json.dumps(prd.model_dump(), indent=2))
        rich.print(f"  [green]✔ PASSED[/green]\n")
    else:
        rich.print(f"  [red]✘ FAILED[/red]\n")
    await hooks.on_iteration_end(i, story.id)


def _checkout_branch(prd: PRD) -> None:
    """Checkout the branch or create from main/master if it's different from the current branch."""

    try:
        current_branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError:
        # No commits yet — HEAD doesn't exist; create main first, then the target branch
        subprocess.check_call(["git", "checkout", "-b", "main"])
        subprocess.check_call(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"]
        )
        subprocess.check_call(["git", "checkout", "-b", prd.branch_name])
        return

    if prd.branch_name != current_branch:
        # Check if branch exists
        branches = (
            subprocess.check_output(["git", "branch", "--list", prd.branch_name])
            .decode()
            .strip()
        )
        if not branches:
            # Create branch from main or master
            base_branch = "main"
            try:
                subprocess.check_call(["git", "rev-parse", "--verify", base_branch])
            except subprocess.CalledProcessError:
                base_branch = "master"
            subprocess.check_call(
                ["git", "checkout", "-b", prd.branch_name, base_branch]
            )
        else:
            subprocess.check_call(["git", "checkout", prd.branch_name])


def _init_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    progress_file.write_text(f"# Ralph Progress Log\nStarted: {datetime.now()}\n---\n")
