import typer

from ralpher.init import init as _init
from ralpher.loop import loop as _loop

app = typer.Typer(invoke_without_command=True)


@app.callback()
def callback() -> None:
    """Ralph - autonomous agent tooling."""


@app.command()
def init() -> None:
    """Install prd and ralph skills to .claude/skills/ in the current directory."""
    _init()


@app.command()
def loop(
    max_iterations: int = typer.Option(10, "--max-iterations", "-n", help="Maximum number of iterations."),
) -> None:
    """Run Claude in a loop until tasks are complete or max iterations reached."""
    _loop(max_iterations)


def main() -> None:
    app()
