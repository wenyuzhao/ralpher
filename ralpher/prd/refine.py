from pathlib import Path
import tempfile

from rich.console import Console
from .prd import _run_agent_with_qa

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def refine_prd(task_id: str, user_input: str) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id

    if not task_dir.exists():
        console.print(f"[bold red]Task directory {task_dir} does not exist.[/]")
        raise SystemExit(1)

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    with tempfile.NamedTemporaryFile(prefix=f"ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(user_input)

        await _run_agent_with_qa(f"/ralpher:refine-prd {task_id} {tmp_path}")

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    return task_id
