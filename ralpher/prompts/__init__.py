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

# Content of the Project Plan structure reference doc. It ships inside this
# package; its full text is embedded directly into the plan/refine prompts so
# the agent never has to read a file outside the run's workspace (the
# antigravity backend confines file access to that workspace).
_env.globals["plan_structure"] = (_PROMPTS_DIR / "plan-structure.md").read_text()


def render_prompt(name: str, /, **context: object) -> str:
    """Render the prompt template `name` (without extension) with `context`.

    Raises `jinja2.UndefinedError` if the template references a variable that
    was not supplied, which surfaces wiring mistakes early.
    """
    template = _env.get_template(f"{name}.md")
    return template.render(**context)
