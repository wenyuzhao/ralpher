"""Raw prompts that drive Claude.

These replace the former `ralpher` plugin and its `/ralpher:*` skills. Each
`.md` file in this package is the body of a skill with its positional `$0`/`$1`
arguments turned into Jinja2 variables. The rendered string is passed directly
to the agent as the initial prompt (see `ralpher.backend.claude.run_claude`).
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
)

# Absolute path to the Project Plan structure reference doc. It ships inside
# this package; templates reference it by path and ask the agent to read it.
_env.globals["plan_structure_path"] = str(_PROMPTS_DIR / "plan-structure.md")


def render_prompt(name: str, /, **context: object) -> str:
    """Render the prompt template `name` (without extension) with `context`.

    Raises `jinja2.UndefinedError` if the template references a variable that
    was not supplied, which surfaces wiring mistakes early.
    """
    template = _env.get_template(f"{name}.md")
    return template.render(**context)
