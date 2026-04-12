import asyncio
from pathlib import Path

from rich.console import Console


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def extract_prd_json(task_id: str):
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    if not task_dir.exists():
        console.print(f"[bold red]Task directory {task_dir} does not exist.[/]")
        raise SystemExit(1)

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    prompt = f"/ralpher:ralph {task_id}"
    cmd = [
        "claude",
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "dontAsk",
        "--plugin-dir",
        str(Path(__file__).resolve().parent.parent / "plugin"),
        "--print",
        "--model",
        "haiku",
        prompt,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    # stdout_bytes = await proc.stdout.read()
    # print(stdout_bytes.decode())

    if proc.returncode != 0:
        console.print(f"[bold red]Claude process exited with code {proc.returncode}[/]")
        raise SystemExit(proc.returncode)

    if not (task_dir / "prd.json").exists():
        console.print(f"[bold red]prd.json not found in {task_dir}[/]")
        raise SystemExit(1)
