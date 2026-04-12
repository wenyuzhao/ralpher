import rich
import typer

from ralpher.init import init as _init
from ralpher.loop import loop as _loop
from ralpher.prd.prd import generate_prd
from ralpher.prd.extract import extract_prd_json
import asyncio

app = typer.Typer(invoke_without_command=True)


@app.callback()
def callback() -> None:
    """Ralph - autonomous agent tooling."""


@app.command()
def init() -> None:
    """Install prd and ralph skills to .claude/skills/ in the current directory."""
    _init()


@app.command()
def prd(
    prompt: str = typer.Argument(..., help="The PRD prompt to generate from."),
    name: str | None = typer.Option(
        None, "--name", "-n", help="Name for the PRD task."
    ),
) -> None:
    """Generate a PRD."""
    task_id = asyncio.run(generate_prd(prompt, name))
    rich.print(f"[green]PRD generated at .ralpher/tasks/{task_id}/PRD.md[/]")


@app.command()
def extract(
    task_id: str = typer.Argument(..., help="The task ID to extract JSON from."),
) -> None:
    """Generate a PRD."""
    asyncio.run(extract_prd_json(task_id))
    rich.print(f"[green]Extracted JSON for task {task_id}[/]")


@app.command()
def loop(
    task_id: str = typer.Argument(..., help="The task ID to run the loop on."),
    max_iterations: int = typer.Option(
        10, "--max-iterations", "-n", help="Maximum number of iterations."
    ),
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    asyncio.run(_loop(task_id, max_iterations))


def main() -> None:
    app()
