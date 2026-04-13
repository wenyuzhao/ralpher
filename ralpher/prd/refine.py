import tempfile
from pathlib import Path

from rich.console import Console

from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def refine_prd(task_id: str, user_input: str) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id

    if not task_dir.exists():
        fail(f"{task_dir} does not exist.")

    if not (task_dir / "PRD.md").exists():
        fail(f"{task_dir / 'PRD.md'} does not exist.")

    with tempfile.NamedTemporaryFile(prefix=f"ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(user_input)

        try:
            await run_claude(f"/ralpher:refine-prd {task_id} {tmp_path}", mode="qa")
        except ClaudeError as e:
            fail(f"Claude process exited with code {e.returncode}")

    if not (task_dir / "PRD.md").exists():
        fail(f"{task_dir / 'PRD.md'} was not created after refinement.")

    return task_id
