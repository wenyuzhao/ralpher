import datetime
import shutil
from pathlib import Path
from typing import Annotated

import click
import rich
import typer
from typer.core import TyperGroup

from ralpher.loop import run_ralph_loop
from ralpher.models import Project
from ralpher.plan.plan import generate_plan
from ralpher.plan.extract import extract_tasks
from ralpher.plan.refine import refine_plan
import asyncio
from slugify import slugify
from .utils.error import fail
from .utils.hooks import HooksManager
from dotenv import find_dotenv, load_dotenv


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


def _gen_project_id(name: str) -> str:
    project_id = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    project_id += f"-{slugify(name)}"
    return project_id


@app.command()
def plan(
    prompt: Annotated[str, typer.Argument(help="The prompt or file to generate from.")],
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name for the project, in kebab-case."),
    ],
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Claude model to use")
    ] = None,
    base_branch: Annotated[
        str | None,
        typer.Option(
            "--base-branch",
            help="Base branch to fork from when creating the target branch. Must exist. Defaults to main or master.",
        ),
    ] = None,
    target_branch: Annotated[
        str | None,
        typer.Option(
            "--target-branch",
            help="Target branch to work on. Created from base-branch if it doesn't exist.",
        ),
    ] = None,
) -> None:
    """Generate a Project Plan."""
    _require_claude()
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    project_id = _gen_project_id(name)

    rich.print(f"[bold blue]Generating plan for new project: [i]{project_id}[/][/]\n")
    project = Project(id=project_id, model=model)
    asyncio.run(
        generate_plan(
            project=project,
            prompt=prompt,
            model=model,
            base_branch=base_branch,
            target_branch=target_branch,
        )
    )
    rich.print(
        f"[green]✔ Project plan generated at .ralpher/projects/{project.id}/PLAN.md[/]"
    )


def _get_latest_project_id() -> str:
    projects_dir = Path.cwd() / ".ralpher" / "projects"
    if not projects_dir.exists():
        fail("No projects found in .ralpher/projects.")
    project_dirs = sorted(
        [f.name for f in projects_dir.iterdir() if f.is_dir()], reverse=True
    )
    if not project_dirs:
        fail("No projects found in .ralpher/projects.")
    return project_dirs[0]


@app.command()
def refine(
    prompt: Annotated[str, typer.Argument(help="The refinement prompt or file.")],
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="The project ID of the Project Plan to refine. Defaults to the latest project.",
        ),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Claude model to use")
    ] = None,
) -> None:
    """Refine an existing Project Plan."""
    _require_claude()
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    if not project_id:
        # Default to the latest project if no project_id is provided
        project_id = _get_latest_project_id()
    rich.print(f"[bold blue]Refining plan for project:[i]{project_id}[/][/]\n")
    project = Project(id=project_id, model=model)
    asyncio.run(refine_plan(project=project, prompt=prompt, model=model))
    rich.print(
        f"[green]✔ Project Plan refined at .ralpher/projects/{project_id}/PLAN.md[/]"
    )


@app.command(hidden=True)
def extract(
    project_id: Annotated[
        str | None,
        typer.Argument(
            help="The project ID to extract JSON from. Defaults to the latest project.",
        ),
    ] = None,
) -> None:
    """Extract plan.json for a given project ID."""
    _require_claude()
    if not project_id:
        project_id = _get_latest_project_id()
    rich.print(f"[bold blue]Extracting plan.json for project: [i]{project_id}[/][/]\n")
    project = Project(id=project_id)
    asyncio.run(extract_tasks(project=project))
    rich.print(f"[green]✔ Extracted to .ralpher/projects/{project_id}/plan.json[/]")


@app.command()
def loop(
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="The project ID to run the loop on. Defaults to the latest project.",
        ),
    ] = None,
    max_iterations: Annotated[
        int,
        typer.Option("--max-iterations", "-n", help="Maximum number of iterations."),
    ] = DEFAULT_MAX_ITERATIONS,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Claude model to use")
    ] = None,
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    _require_claude()

    load_dotenv(find_dotenv(usecwd=True))

    if not project_id:
        project_id = _get_latest_project_id()

    rich.print(f"[bold blue]Running project: [i]{project_id}[/][/]\n")

    async def run_loop_with_hooks():
        hooks = HooksManager()
        project = Project(
            id=project_id,
            max_iterations=max_iterations if max_iterations > 0 else None,
            model=model,
        )
        await hooks.init(project)
        try:
            await run_ralph_loop(project=project, hooks=hooks)
        except BaseException as e:
            await hooks.on_error(str(e))
            raise e

    asyncio.run(run_loop_with_hooks())


def main() -> None:
    app()
