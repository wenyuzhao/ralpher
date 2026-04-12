import asyncio
import json
from pathlib import Path
import sys

from rich.console import Console
from ..models import PRD


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def __try_extract_prd(task_dir: Path, task_id: str):
    """Run a Claude Code session with the rendered PRD prompt."""

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

    if proc.returncode != 0:
        if proc.stdout:
            stdout = await proc.stdout.read()
            print(stdout.decode(), file=sys.stdout)
            (task_dir / ".claude.out.log").write_bytes(stdout)
        if proc.stderr:
            stderr = await proc.stderr.read()
            (task_dir / ".claude.err.log").write_bytes(stderr)
        return False

    if not (task_dir / "prd.json").exists():
        return False
    prd_dict = json.loads((task_dir / "prd.json").read_text())
    try:
        prd = PRD.model_validate(prd_dict)
    except Exception as e:
        return False
    return True


async def extract_prd_json(task_id: str, retries: int = 3) -> None:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    if not task_dir.exists():
        console.print(f"[bold red]Task directory {task_dir} does not exist.[/]")
        raise SystemExit(1)

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    for i in range(retries):
        success = await __try_extract_prd(task_dir, task_id)
        if success:
            console.print(f"[green]Successfully extracted prd.json[/]")
            return
        else:
            console.print(
                f"[red]Failed to extract prd.json. Retrying... ({i+1}/{retries})[/]"
            )

    if not (task_dir / "prd.json").exists():
        console.print(f"[bold red]Failed to extract prd.json.[/]")
        raise SystemExit(1)
