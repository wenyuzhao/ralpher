import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

console = Console()

COMPLETION_SIGNAL = "<promise>COMPLETE</promise>"


def loop(max_iterations: int = 10) -> None:
    """Run Claude in a loop, checking for completion signal each iteration."""
    script_dir = Path.cwd()
    prd_file = script_dir / "prd.json"
    progress_file = script_dir / "progress.txt"
    archive_dir = script_dir / "archive"
    last_branch_file = script_dir / ".last-branch"
    claude_md = script_dir / "CLAUDE.md"

    # Archive previous run if branch changed
    _maybe_archive(prd_file, last_branch_file, progress_file, archive_dir)

    # Track current branch
    _track_branch(prd_file, last_branch_file)

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
        output = _run_claude(claude_md)

        # Check for completion signal
        if COMPLETION_SIGNAL in output:
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


def _run_claude(claude_md: Path) -> str:
    """Run claude --dangerously-skip-permissions --print with CLAUDE.md as stdin."""
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        console.print("[bold red]Error:[/bold red] claude CLI not found on PATH.")
        raise SystemExit(1)

    cmd = [claude_bin, "--dangerously-skip-permissions", "--print"]

    stdin_data = None
    if claude_md.exists():
        stdin_data = claude_md.read_text()

    proc = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
    )

    output = proc.stdout
    if output:
        console.print(output)
    if proc.stderr:
        console.print(Text(proc.stderr, style="dim red"))

    return output


def _maybe_archive(
    prd_file: Path,
    last_branch_file: Path,
    progress_file: Path,
    archive_dir: Path,
) -> None:
    """Archive previous run if the branch in prd.json changed."""
    if not prd_file.exists() or not last_branch_file.exists():
        return

    try:
        current_branch = json.loads(prd_file.read_text()).get("branchName", "")
    except (json.JSONDecodeError, OSError):
        return

    last_branch = last_branch_file.read_text().strip()

    if not current_branch or not last_branch or current_branch == last_branch:
        return

    # Archive
    date_str = datetime.now().strftime("%Y-%m-%d")
    folder_name = last_branch.removeprefix("ralph/")
    archive_folder = archive_dir / f"{date_str}-{folder_name}"
    archive_folder.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Archiving previous run:[/dim] {last_branch}")
    if prd_file.exists():
        shutil.copy2(prd_file, archive_folder)
    if progress_file.exists():
        shutil.copy2(progress_file, archive_folder)
    console.print(f"[dim]  Archived to:[/dim] {archive_folder}")

    # Reset progress
    _init_progress(progress_file)


def _track_branch(prd_file: Path, last_branch_file: Path) -> None:
    """Write current branch from prd.json to .last-branch."""
    if not prd_file.exists():
        return
    try:
        branch = json.loads(prd_file.read_text()).get("branchName", "")
    except (json.JSONDecodeError, OSError):
        return
    if branch:
        last_branch_file.write_text(branch)


def _init_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    progress_file.write_text(
        f"# Ralph Progress Log\nStarted: {datetime.now()}\n---\n"
    )
