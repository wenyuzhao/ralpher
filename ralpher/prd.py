import asyncio
import shutil
from pathlib import Path

import frontmatter
import jinja2

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prd_prompt(user_input: str, *, interactive: bool = True) -> str:
    """Load the PRD template, strip frontmatter, and render with user input."""
    template_path = PROMPTS_DIR / "PRD.md"
    post = frontmatter.load(str(template_path))
    content = post.content
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(content)
    return template.render(prompt=user_input, interactive=interactive)


async def generate_prd(user_input: str, interactive=True) -> int:
    """Run an interactive Claude Code session with the rendered PRD prompt."""
    prompt = load_prd_prompt(user_input, interactive=interactive)

    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError("claude CLI not found on PATH")

    proc = await asyncio.create_subprocess_exec(
        claude_bin,
        "--output-format=json",
        "-p",
        prompt,
    )

    await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"claude exited with code {proc.returncode}")

    return proc.returncode
