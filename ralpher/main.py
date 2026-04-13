import datetime
import shutil
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
from .utils.hooks import HooksManager
from dotenv import load_dotenv


def _require_claude() -> None:
    """Exit with an error if the claude CLI is not on PATH."""
    if not shutil.which("claude"):
        fail(
            "'claude' CLI not found on PATH. Install it first: https://docs.anthropic.com/en/docs/claude-code"
        )


class DefaultCommandGroup(TyperGroup):
    """Typer group that falls back to 'run' when the first arg isn't a known command."""

    default_cmd_name = "run"

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = [self.default_cmd_name] + args
        return super().parse_args(ctx, args)


app = typer.Typer(cls=DefaultCommandGroup)

DEFAULT_MAX_ITERATIONS = 30


def _gen_task_id(name: str | None) -> str:
    task_id = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    if name:
        task_id += f"-{slugify(name)}"
    return task_id


@app.command()
def prd(
    prompt: str = typer.Argument(..., help="The PRD prompt or file to generate from."),
    name: str | None = typer.Option(
        None, "--name", "-n", help="Name for the PRD task."
    ),
    model: str | None = typer.Option(None, "--model", "-m", help="Claude model to use"),
) -> None:
    """Generate a PRD."""
    _require_claude()
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    task_id = _gen_task_id(name)

    rich.print(f"[bold blue]Generating PRD for new task: [i]{task_id}[/][/]\n")
    asyncio.run(generate_prd(task_id=task_id, prompt=prompt, model=model))
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
    model: str | None = typer.Option(None, "--model", "-m", help="Claude model to use"),
) -> None:
    """Refine an existing PRD."""
    _require_claude()
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    if not task_id:
        # Default to the latest task if no task_id is provided
        task_id = _get_latest_task_id()
        rich.print(f"[bold blue]Refining the latest task: [i]{task_id}[/][/]\n")
    else:
        rich.print(f"[bold blue]Refining task: [i]{task_id}[/][/]\n")
    task_id = asyncio.run(refine_prd(task_id=task_id, prompt=prompt, model=model))
    rich.print(f"[green]✔ PRD refined at .ralpher/tasks/{task_id}/PRD.md[/]")


@app.command(hidden=True)
def extract(
    task_id: str | None = typer.Argument(
        None, help="The task ID to extract JSON from."
    ),
) -> None:
    """Extract PRD JSON for a given task ID."""
    _require_claude()
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
    model: str | None = typer.Option(None, "--model", "-m", help="Claude model to use"),
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    _require_claude()
    load_dotenv()

    if not task_id:
        task_id = _get_latest_task_id()
        rich.print(f"[bold blue]Running the latest task: [i]{task_id}[/][/]\n")
    else:
        rich.print(f"[bold blue]Running task: [i]{task_id}[/][/]\n")

    async def run_loop_with_hooks():
        hooks = HooksManager()
        task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
        await hooks.init(task_dir, max_iterations)
        try:
            await _loop(
                task_dir=task_dir,
                max_iterations=max_iterations,
                hooks=hooks,
                model=model,
            )
        except BaseException as e:
            await hooks.on_error(str(e))
            raise e

    asyncio.run(run_loop_with_hooks())


def main() -> None:
    app()
