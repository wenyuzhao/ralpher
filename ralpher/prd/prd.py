from pathlib import Path

from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def generate_prd(task_id: str, user_input: str, name: str | None = None) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "PROMPT.md").write_text(user_input)
    plugin_path = Path(__file__).parent.parent / "plugin"

    try:
        await run_claude(
            prompt=f"/ralpher:prd {task_id} {plugin_path}",
            task_dir=task_dir,
            interactive=True,
        )
    except ClaudeError as e:
        fail(f"Claude process exited with code {e.returncode}")

    if not (task_dir / "PRD.md").exists():
        fail(f"{task_dir / 'PRD.md'} was not created.")

    return task_id
