import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import json
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from .prd.extract import extract_prd_json
from .models import PRD

console = Console()


async def loop(task_id: str, max_iterations: int = 10) -> None:
    """Run Claude in a loop, checking for completion signal each iteration."""
    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    prd_file = task_dir / "prd.json"
    prd_doc = task_dir / "PRD.md"
    progress_file = task_dir / "progress.md"
    last_branch_file = task_dir / ".last-branch"

    if not prd_doc.exists():
        console.print(f"[red][b]Error:[/] {prd_doc} not found.[/]")
        raise SystemExit(1)

    if not prd_file.exists():
        console.print(f"[yellow]prd.json not found. Extracting from PRD.md...[/]")
        await extract_prd_json(task_id)
        if not prd_file.exists():
            console.print(
                f"[red][b]Error:[/] prd.json still not found after extraction.[/]"
            )
            raise SystemExit(1)

    prd = PRD.model_validate(json.loads(prd_file.read_text()))

    # Track current branch
    _track_branch(prd, last_branch_file)

    # Initialize progress file if it doesn't exist
    if not progress_file.exists():
        _init_progress(progress_file)

    console.print(
        Panel(
            f"[bold]Tool:[/bold] claude  |  [bold]Max iterations:[/bold] {max_iterations}",
            title="[bold cyan]Ralph Loop[/bold cyan]",
            border_style="cyan",
        )
    )

    for i in range(1, max_iterations + 1):
        console.print()
        console.print(
            Rule(
                f"[bold yellow]Iteration {i} of {max_iterations}[/bold yellow]",
                style="yellow",
            )
        )

        # Run claude
        await _run_one_iteration(task_id, prd, task_dir)

        # Check for completion
        prd = PRD.model_validate(json.loads(prd_file.read_text()))
        all_passed = all(story.passes for story in prd.user_stories)

        if all_passed:
            console.print()
            console.print(
                Panel(
                    f"[bold green]All tasks completed at iteration {i} of {max_iterations}[/bold green]",
                    title="[bold green]Done[/bold green]",
                    border_style="green",
                )
            )
            return

        console.print(
            Text(f"Iteration {i} complete. Continuing...", style="dim"),
        )
        if i < max_iterations:
            time.sleep(2)

    console.print()
    console.print(
        Panel(
            f"[bold red]Reached max iterations ({max_iterations}) without completing all tasks.[/bold red]\n"
            f"Check [bold]{progress_file}[/bold] for status.",
            title="[bold red]Incomplete[/bold red]",
            border_style="red",
        )
    )
    raise SystemExit(1)


async def _run_one_iteration(task_id: str, prd: PRD, task_dir: Path) -> None:
    """Run claude --dangerously-skip-permissions --print with CLAUDE.md as stdin."""

    # Pick user story
    user_stories = [s for s in prd.user_stories if not s.passes]
    user_stories.sort(key=lambda s: s.priority)
    assert user_stories, "No failing user stories found."
    # Always pick the highest priority failing story
    story = user_stories[-1]
    (task_dir / "current_user_story.json").write_text(
        json.dumps(story.model_dump(), indent=2)
    )

    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "dontAsk",
        "--print",
        f"/ralpher:loop {task_id}",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()

    if proc.stdout:
        stdout = (await proc.stdout.read()).decode()
    else:
        stdout = ""

    if proc.returncode != 0:
        if stdout:
            print(stdout, file=sys.stdout)
        if proc.stderr:
            stderr = await proc.stderr.read()
            print(stderr.decode(), file=sys.stderr)
        console.print(f"[bold red]Claude process exited with code {proc.returncode}[/]")
        raise SystemExit(proc.returncode)


def _checkout_branch(prd: PRD) -> None:
    """Checkout the branch or create from main/master if it's different from the current branch."""

    current_branch = (
        subprocess.check_output(["git", "rev-parse", "--abrev-ref", "HEAD"])
        .decode()
        .strip()
    )
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
