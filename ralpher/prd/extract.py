import asyncio
import json
from pathlib import Path
import sys

import rich
from ..models import PRD
from ..utils.spinner import Spinner
from ..utils.error import fail

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


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

    async with Spinner() as spinner:
        await spinner.run(proc)

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
        fail(f"{task_dir} does not exist.")

    if not (task_dir / "PRD.md").exists():
        fail(f"{task_dir / 'PRD.md'} does not exist.")

    for i in range(retries):
        success = await __try_extract_prd(task_dir, task_id)
        if success:
            return
        else:
            rich.print(
                f"[red]Failed to extract prd.json. Retrying... ({i+1}/{retries})[/]"
            )

    if not (task_dir / "prd.json").exists():
        fail(f"Failed to extract prd.json after {retries} attempts.")
