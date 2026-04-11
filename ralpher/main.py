import typer

from ralpher.init import init as _init

app = typer.Typer(invoke_without_command=True)


@app.callback()
def callback() -> None:
    """Ralph - autonomous agent tooling."""


@app.command()
def init() -> None:
    """Install prd and ralph skills to .claude/skills/ in the current directory."""
    _init()


def main() -> None:
    app()
