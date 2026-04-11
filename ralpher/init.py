import urllib.request
from pathlib import Path

import typer

SKILL_BASE_URL = (
    "https://raw.githubusercontent.com/snarktank/ralph/main/skills"
)
SKILLS = {
    "prd": f"{SKILL_BASE_URL}/prd/SKILL.md",
    "ralph": f"{SKILL_BASE_URL}/ralph/SKILL.md",
}


def init() -> None:
    """Install prd and ralph skills to .claude/skills/ in the current directory."""
    skills_dir = Path.cwd() / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    for name, url in SKILLS.items():
        dest = skills_dir / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)

        typer.echo(f"Downloading {name} skill...")
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                content = resp.read()
            dest.write_bytes(content)
            typer.echo(f"  Installed to {dest.relative_to(Path.cwd())}")
        except Exception as e:
            typer.echo(f"  Failed to download {name}: {e}", err=True)
            raise typer.Exit(1)

    typer.echo("Done! Skills installed.")
