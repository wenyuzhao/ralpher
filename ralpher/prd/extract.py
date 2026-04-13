import json
import sys
from pathlib import Path

import rich
from ..models import PRD
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def __try_extract_prd(task_dir: Path, task_id: str):
    """Run a Claude Code session with the rendered PRD prompt."""

    try:
        await run_claude(
            f"/ralpher:ralph {task_id}",
            mode="qa",
            model="haiku",
        )
    except ClaudeError as e:
        (task_dir / ".claude.out.log").write_bytes(e.stdout)
        (task_dir / ".claude.err.log").write_bytes(e.stderr)
        return False

    if not (task_dir / "prd.json").exists():
        return False
    prd_dict = json.loads((task_dir / "prd.json").read_text())
    try:
        PRD.model_validate(prd_dict)
    except Exception:
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
