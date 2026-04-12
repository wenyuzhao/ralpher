import rich


def fail(message: str):
    rich.print(f"[red][b]Error:[/] {message}[/]")
    raise SystemExit(1)
