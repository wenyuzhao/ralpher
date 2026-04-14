import json
from pathlib import Path

import rich
from ..models import ProjectPlan
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def __try_extract_plan(task_dir: Path, task_id: str):
    """Run a Claude Code session to extract plan.json."""

    try:
        await run_claude(
            prompt=f"/ralpher:extract-plan {task_id}", task_dir=task_dir, model="haiku"
        )
    except ClaudeError as e:
        return False

    if not (task_dir / "plan.json").exists():
        return False
    plan_dict = json.loads((task_dir / "plan.json").read_text())
    try:
        ProjectPlan.model_validate(plan_dict)
    except Exception:
        return False
    return True


async def extract_plan_json(task_id: str, retries: int = 3) -> None:
    """Run a Claude Code session to extract structured plan.json from PLAN.md."""

    task_dir = Path.cwd() / ".ralpher" / "projects" / task_id
    if not task_dir.exists():
        fail(f"{task_dir} does not exist.")

    if not (task_dir / "PLAN.md").exists():
        fail(f"{task_dir / 'PLAN.md'} does not exist.")

    for i in range(retries):
        success = await __try_extract_plan(task_dir, task_id)
        if success:
            return
        else:
            rich.print(
                f"[red]Failed to extract plan.json. Retrying... ({i+1}/{retries})[/]"
            )

    if not (task_dir / "plan.json").exists():
        fail(f"Failed to extract plan.json after {retries} attempts.")
