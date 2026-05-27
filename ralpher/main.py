import datetime
import shutil
from pathlib import Path
from typing import Annotated

import click
import rich
import typer
from typer.core import TyperGroup

from ralpher.loop import run_ralph_loop
from ralpher.models import BackendKind, Project, Settings, ralpher_root, resolve_backend
from ralpher.plan.plan import generate_plan
from ralpher.plan.extract import extract_tasks
from ralpher.plan.refine import refine_plan
import asyncio
from slugify import slugify
from .utils.error import fail
from .utils.hooks import HooksManager
from .utils.hooks.notion import update_notion_page
from dotenv import find_dotenv, load_dotenv


def _sync_to_notion(project: Project) -> None:
    """Push the project's current state to Notion and print the URL.

    No-op (with a single info line) when Notion env vars are not configured.
    """
    import os

    if "RALPHER_NOTION_TOKEN" not in os.environ:
        return
    url = asyncio.run(update_notion_page(project, status=None))
    if url:
        rich.print(f"[green]✔ Notion page synced: [i][u]{url}[/][/][/]")
    else:
        rich.print(
            "[yellow]⚠ Notion env vars set but could not sync — check RALPHER_NOTION_PAGE_ID or RALPHER_NOTION_PARENT_PAGE_ID.[/]"
        )


def _require_backend(backend: BackendKind) -> None:
    """Exit with an error if the selected backend's prerequisites are missing."""
    if backend == "antigravity":
        import os

        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            fail(
                "GEMINI_API_KEY not set. The antigravity backend needs a Gemini API key — "
                "get one at https://aistudio.google.com/app/api-keys and set GEMINI_API_KEY "
                "(e.g. in .env)."
            )
        return
    if not shutil.which("claude"):
        fail(
            "'claude' CLI not found on PATH. Install it first: https://docs.anthropic.com/en/docs/claude-code"
        )


def _resolve_backend_or_fail(cli_backend: str | None) -> BackendKind:
    """Resolve the backend (CLI flag, else settings.json), failing on bad input."""
    try:
        return resolve_backend(cli_backend)
    except ValueError as e:
        fail(str(e))


BackendOption = Annotated[
    str | None,
    typer.Option(
        "--backend",
        "-b",
        help=(
            "Coding agent backend: claude-code (cc) or antigravity (agy). "
            "Defaults to the 'backend' key in .ralpher/settings.json, else claude-code."
        ),
    ),
]


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
    backend: BackendOption = None,
) -> None:
    """Generate a Project Plan."""
    load_dotenv(find_dotenv(usecwd=True))
    backend_kind = _resolve_backend_or_fail(backend)
    _require_backend(backend_kind)
    if Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    project_id = _gen_project_id(name)

    rich.print(f"[bold blue]Generating plan for new project: [i]{project_id}[/][/]\n")
    project = Project(id=project_id, backend=backend_kind)
    asyncio.run(
        generate_plan(
            project=project,
            prompt=prompt,
            base_branch=base_branch,
            target_branch=target_branch,
        )
    )
    rich.print(
        f"[green]✔ Project plan generated at .ralpher/projects/{project.id}/PLAN.md[/]"
    )
    _sync_to_notion(project)


def _get_latest_project_id() -> str:
    projects_dir = ralpher_root() / "projects"
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
    prompt: Annotated[
        str | None,
        typer.Argument(
            help="The refinement prompt or file. Optional when Notion is configured and has unresolved comments on the Project Plan section."
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="The project ID of the Project Plan to refine. Defaults to the latest project.",
        ),
    ] = None,
    backend: BackendOption = None,
) -> None:
    """Refine an existing Project Plan.

    When Notion env vars are configured, unresolved comments on the Project
    Plan section are fetched automatically, combined with the prompt, and
    resolved after refinement.
    """
    load_dotenv(find_dotenv(usecwd=True))
    backend_kind = _resolve_backend_or_fail(backend)
    _require_backend(backend_kind)
    if not project_id:
        # Default to the latest project if no project_id is provided
        project_id = _get_latest_project_id()
    rich.print(f"[bold blue]Refining plan for project: [i]{project_id}[/][/]\n")
    project = Project(id=project_id, backend=backend_kind)
    if prompt and Path(prompt).is_file():
        prompt = Path(prompt).read_text()
    result = asyncio.run(refine_plan(project=project, prompt=prompt))
    if result is None:
        return
    rich.print(
        f"[green]✔ Project Plan refined at .ralpher/projects/{project_id}/PLAN.md[/]"
    )
    _sync_to_notion(project)


@app.command(hidden=True)
def extract(
    project_id: Annotated[
        str | None,
        typer.Argument(
            help="The project ID to extract JSON from. Defaults to the latest project.",
        ),
    ] = None,
    backend: BackendOption = None,
) -> None:
    """Extract tasks.json for a given project ID."""
    load_dotenv(find_dotenv(usecwd=True))
    backend_kind = _resolve_backend_or_fail(backend)
    _require_backend(backend_kind)
    if not project_id:
        project_id = _get_latest_project_id()
    rich.print(f"[bold blue]Extracting tasks.json for project: [i]{project_id}[/][/]\n")
    project = Project(id=project_id, backend=backend_kind)
    asyncio.run(extract_tasks(project=project))
    rich.print(f"[green]✔ Extracted to .ralpher/projects/{project_id}/tasks.json[/]")


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
    sandbox: Annotated[
        bool | None,
        typer.Option(
            "--sandbox/--no-sandbox",
            help="Run Claude's Bash tool in an OS sandbox (claude-code agent only).",
        ),
    ] = None,
    backend: BackendOption = None,
) -> None:
    """Run the coding agent in a loop until tasks are complete or max iterations reached."""
    load_dotenv(find_dotenv(usecwd=True))

    backend_kind = _resolve_backend_or_fail(backend)
    _require_backend(backend_kind)

    if not project_id:
        project_id = _get_latest_project_id()

    # CLI flag wins when given; otherwise honor .ralpher/settings.json (default on).
    sandbox_enabled = sandbox if sandbox is not None else Settings.load().sandbox

    rich.print(f"[bold blue]Running project: [i]{project_id}[/][/]\n")

    async def run_loop_with_hooks():
        hooks = HooksManager()
        project = Project(
            id=project_id,
            backend=backend_kind,
            max_iterations=max_iterations if max_iterations > 0 else None,
            sandbox=sandbox_enabled,
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
