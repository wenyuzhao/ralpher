import rich
import typer

from ralpher.init import init as _init
from ralpher.loop import loop as _loop
from ralpher.prd.prd import generate_prd
from ralpher.prd.extract import extract_prd_json
import asyncio

app = typer.Typer(invoke_without_command=True)

DEFAULT_MAX_ITERATIONS = 15


@app.callback()
def callback(
    ctx: typer.Context,
    prompt: str = typer.Option(
        None, "--prompt", "-p", help="Prompt to generate PRD, extract, and run loop."
    ),
    name: str | None = typer.Option(
        None, "--name", "-t", help="Name for the PRD task."
    ),
    max_iterations: int = typer.Option(
        DEFAULT_MAX_ITERATIONS,
        "--max-iterations",
        "-n",
        help="Maximum loop iterations.",
    ),
) -> None:
    """Ralph - autonomous agent tooling."""
    if ctx.invoked_subcommand is not None:
        return
    if prompt is None:
        return
    asyncio.run(_run(prompt, name, max_iterations))


async def _run(prompt: str, name: str | None, max_iterations: int) -> None:
    """Generate PRD, extract JSON, and run loop."""
    task_id = await generate_prd(prompt, name)
    rich.print(f"[green]PRD generated at .ralpher/tasks/{task_id}/PRD.md[/]")

    await extract_prd_json(task_id)
    rich.print(f"[green]Extracted JSON for task {task_id}[/]")

    await _loop(task_id, max_iterations)


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
        DEFAULT_MAX_ITERATIONS,
        "--max-iterations",
        "-n",
        help="Maximum number of iterations.",
    ),
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    asyncio.run(_loop(task_id, max_iterations))


def main() -> None:
    app()
