from pathlib import Path

from ralpher.utils.project import init_project

from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def generate_prd(*, task_id: str, prompt: str, model: str | None) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    init_project(task_dir, prompt)

    try:
        await run_claude(
            prompt=f"/ralpher:prd {task_id}",
            task_dir=task_dir,
            interactive=True,
            model=model,
        )
    except ClaudeError as e:
        fail(f"Claude process exited with code {e.returncode}")

    if not (task_dir / "PRD.md").exists():
        fail(f"{task_dir / 'PRD.md'} was not created.")

    return task_id
