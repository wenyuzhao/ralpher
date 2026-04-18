from typing import NoReturn

import rich


def fail(message: str) -> NoReturn:
    rich.print(f"[red][b]Error:[/] {message}[/]")
    raise SystemExit(message)
