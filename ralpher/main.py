import datetime
from pathlib import Path

import click
import rich
import typer
from typer.core import TyperGroup

from ralpher.loop import loop as _loop
from ralpher.prd.prd import generate_prd
from ralpher.prd.extract import extract_prd_json
from ralpher.prd.refine import refine_prd
import asyncio
from slugify import slugify
from .utils.error import fail


class DefaultCommandGroup(TyperGroup):
    """Typer group that falls back to 'run' when the first arg isn't a known command."""

    default_cmd_name = "run"

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = [self.default_cmd_name] + args
        return super().parse_args(ctx, args)


app = typer.Typer(cls=DefaultCommandGroup)

DEFAULT_MAX_ITERATIONS = 15


@app.callback()
def callback() -> None:
    """
    Ralpher - autonomous agent tooling.

    [b]Example usage:[/]
        • [b]ralpher[/] "build a todo app" \\[--name todo-app] \\[--max-iterations 20]
        • [b]ralpher[/] prd "build a todo app"
        • [b]ralpher[/] refine "add user authentication" \\[--task <task_id>]
        • [b]ralpher[/] loop \\[--task <task_id>]
    """


@app.command()
def run(
    prompt: str = typer.Argument(
        ..., help="Prompt or file to generate PRD, extract, and run loop."
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
    """\\[default] Generate PRD, extract JSON, and run loop."""
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    asyncio.run(_run(prompt, name, max_iterations))


def _gen_task_id(name: str | None) -> str:
    task_id = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    if name:
        task_id += f"-{slugify(name)}"
    return task_id


async def _run(prompt: str, name: str | None, max_iterations: int) -> None:
    """Generate PRD, extract JSON, and run loop."""
    task_id = _gen_task_id(name)
    await generate_prd(task_id, prompt, name)
    rich.print(f"[green]✔ PRD generated at .ralpher/tasks/{task_id}/PRD.md[/]")

    await extract_prd_json(task_id)
    rich.print(f"[green]✔ Extracted JSON for task {task_id}[/]")

    await _loop(task_id, max_iterations)


@app.command()
def prd(
    prompt: str = typer.Argument(..., help="The PRD prompt or file to generate from."),
    name: str | None = typer.Option(
        None, "--name", "-n", help="Name for the PRD task."
    ),
) -> None:
    """Generate a PRD."""
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()

    task_id = _gen_task_id(name)
    rich.print(f"[bold blue]Generating PRD for new task: [i]{task_id}[/][/]\n")

    asyncio.run(generate_prd(task_id, prompt, name))

    rich.print(f"[green]✔ PRD generated at .ralpher/tasks/{task_id}/PRD.md[/]")


def _get_latest_task_id() -> str:
    tasks_dir = Path.cwd() / ".ralpher" / "tasks"
    if not tasks_dir.exists():
        fail("No tasks found in .ralpher/tasks.")
    task_dirs = sorted(
        [f.name for f in tasks_dir.iterdir() if f.is_dir()], reverse=True
    )
    if not task_dirs:
        fail("No tasks found in .ralpher/tasks.")
    return task_dirs[0]


@app.command()
def refine(
    prompt: str = typer.Argument(..., help="The refinement prompt or file."),
    task_id: str | None = typer.Option(
        None, "--task", "-t", help="The task ID of the PRD to refine."
    ),
) -> None:
    """Refine an existing PRD."""
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    if not task_id:
        # Default to the latest task if no task_id is provided
        task_id = _get_latest_task_id()
        rich.print(f"[bold blue]Refining the latest task: [i]{task_id}[/][/]\n")
    else:
        rich.print(f"[bold blue]Refining task: [i]{task_id}[/][/]\n")
    task_id = asyncio.run(refine_prd(task_id, prompt))
    rich.print(f"[green]✔ PRD refined at .ralpher/tasks/{task_id}/PRD.md[/]")


@app.command(hidden=True)
def extract(
    task_id: str | None = typer.Argument(
        None, help="The task ID to extract JSON from."
    ),
) -> None:
    """Extract PRD JSON for a given task ID."""
    if not task_id:
        task_id = _get_latest_task_id()
        rich.print(
            f"[bold blue]Extracting prd.json for the latest task: [i]{task_id}[/][/]\n"
        )
    else:
        rich.print(f"[bold blue]Extracting prd.json for task: [i]{task_id}[/][/]\n")
    asyncio.run(extract_prd_json(task_id))
    rich.print(f"[green]✔ Extracted to .ralpher/tasks/{task_id}/prd.json[/]")


@app.command()
def loop(
    task_id: str | None = typer.Option(
        None, "--task", "-t", help="The task ID to run the loop on."
    ),
    max_iterations: int = typer.Option(
        DEFAULT_MAX_ITERATIONS,
        "--max-iterations",
        "-n",
        help="Maximum number of iterations.",
    ),
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    if not task_id:
        task_id = _get_latest_task_id()
        rich.print(f"[bold blue]Running the latest task: [i]{task_id}[/][/]\n")
    else:
        rich.print(f"[bold blue]Running task: [i]{task_id}[/][/]\n")
    asyncio.run(_loop(task_id, max_iterations))


def main() -> None:
    app()
