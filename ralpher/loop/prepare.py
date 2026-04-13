from datetime import datetime
from pathlib import Path
import subprocess
import sys

import rich
from rich.prompt import Confirm

from ralpher.models import RunInfo
from ralpher.utils.error import fail
from ralpher.utils.hooks.hooks import HooksManager
from ..prd.extract import extract_prd_json


async def prepare(run: RunInfo, hooks: HooksManager) -> bool:
    # Check if PRD.md exists
    if not run.prd_doc_file.exists():
        await hooks.on_error("PRD.md not found")
        fail(f"{run.prd_doc_file } not found.")

    # Extract prd.json from PRD.md if it doesn't exist
    if not run.prd_json_file.exists():
        rich.print(f"[bold blue]Extracting prd.json from PRD.md[/]\n")
        await hooks.on_extract_start()
        try:
            await extract_prd_json(run.id)
        except Exception as e:
            await hooks.on_error(f"Failed to extract prd.json: {str(e)}")
            fail(f"Failed to extract prd.json: {str(e)}")
        if not run.prd_json_file.exists():
            await hooks.on_error("Failed to extract prd.json")
            fail(f"{run.prd_json_file } still not found after extraction.")
        await hooks.on_extract_end()

    # Create logs directory
    logs_dir = run.task_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Load PRD and check user stories
    prd = run.load_prd()

    # Check if all user stories already pass
    num_stories = len(prd.user_stories)
    num_failed_stories = len(prd.failed_stories())
    if num_failed_stories == 0:
        rich.print(f"[bold green]✔ All {num_stories} user stories already pass![/]")
        await hooks.on_loop_end(0, True)
        return False

    # Check if max_iterations is less than number of user stories
    if run.max_iterations < len(prd.user_stories):
        rich.print(
            f"[yellow][b]Warning:[/] Max iterations ({run.max_iterations}) is less than the number of user stories ({len(prd.user_stories)}). Some stories may not be attempted.[/]\n"
        )
        if not Confirm.ask("Do you want to continue?", default=False):
            await hooks.on_cancel(
                "User aborted due to max_iterations < number of user stories."
            )
            sys.exit(0)

    # Report important info before starting the loop
    rich.print(f" • Incomplete user stories: {num_failed_stories} / {num_stories}")
    rich.print(f" • Branch: [i]{run.branch}[/]")
    rich.print(f" • Max iterations: {run.max_iterations}")
    hooks.report_status()
    print()

    # Initialize progress file if it doesn't exist
    if not run.progress_file.exists():
        _init_progress(run.progress_file)

    # Track current branch
    _checkout_branch(run.branch)

    return True


def _checkout_branch(branch: str) -> None:
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
        subprocess.check_call(["git", "checkout", "-b", branch])
        return

    if branch != current_branch:
        # Check if branch exists
        branches = (
            subprocess.check_output(
                ["git", "branch", "--list", branch], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        if not branches:
            # Create branch from main or master
            base_branch = "main"
            try:
                subprocess.check_call(
                    ["git", "rev-parse", "--verify", base_branch],
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                base_branch = "master"
            subprocess.check_call(
                ["git", "checkout", "-b", branch, base_branch],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
        else:
            subprocess.check_call(
                ["git", "checkout", branch],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )


def _init_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    progress_file.write_text(f"# Ralph Progress Log\nStarted: {datetime.now()}\n---\n")
