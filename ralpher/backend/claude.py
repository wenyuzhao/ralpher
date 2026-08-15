import dataclasses
import json
from pathlib import Path
from datetime import datetime
from typing import Any, cast, overload

from pydantic import BaseModel

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import EffortLevel

from ralpher.models import Project, Settings, ralpher_root, split_thinking_level
from ralpher.utils.error import fail
from ralpher.utils.spinner import Spinner

from .common import Plan, PlanOrQuestions, ask_user_questions


READONLY_TOOLS = [
    "Agent",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Glob",
    "Grep",
    "ListMcpResourcesTool",
    "LSP",
    "Read",
    "ReadMcpResourceTool",
    "SendMessage",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    "TeamCreate",
    "TeamDelete",
    "TodoWrite",
    "ToolSearch",
    "WebFetch",
    "WebSearch",
]


def _readonly_ralpher_settings() -> str:
    """Settings JSON that makes the ``.ralpher`` state directory read-only.

    Claude must be able to read its task/plan/progress files (which are passed
    by absolute path) but never write into them — progress updates are mediated
    through a temp file in the loop. ``deny`` rules are a hard block that is
    enforced even under ``bypassPermissions``, so this holds for every call.

    The absolute path uses the ``//`` prefix required by Claude Code's
    gitignore-style permission patterns for filesystem-root paths.
    """
    root = ralpher_root().resolve()
    pattern = f"//{str(root).lstrip('/')}/**"
    deny = [f"Write({pattern})", f"Edit({pattern})", f"NotebookEdit({pattern})"]
    return json.dumps({"permissions": {"deny": deny}})


def _build_options(
    *,
    model: str | None = None,
    effort: str | None = None,
    session_id: str | None = None,
    schema: dict[str, Any] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
    sandbox: bool = False,
) -> ClaudeAgentOptions:
    if readonly:
        tools = tools or READONLY_TOOLS

    options = ClaudeAgentOptions(
        permission_mode="dontAsk" if readonly else "bypassPermissions",
        model=model,
        # Reasoning effort (Claude's --effort). Peeled off the model spec's
        # ":<level>" suffix; None leaves the SDK's own default (high). The value
        # is validated against EffortLevel by split_thinking_level upstream.
        effort=cast("EffortLevel | None", effort),
        resume=session_id,
        output_format={"type": "json_schema", "schema": schema} if schema else None,
        allowed_tools=tools if tools is not None else [],
        tools=(
            tools if tools is not None else {"type": "preset", "preset": "claude_code"}
        ),
        # Keep the .ralpher state directory read-only to Claude. deny rules are
        # enforced even under bypassPermissions, so this holds in the loop too.
        settings=_readonly_ralpher_settings(),
        # Run Bash in an OS sandbox so the .ralpher deny rule is enforced against
        # shell writes, not just the file tools.
        sandbox={"enabled": True, "network": {"allowedDomains": ["*"]}}
        if sandbox
        else None,
        # Load the user's Claude Code settings rather than running hermetically,
        # so e.g. a sandbox.network allowlist in .claude/settings.json applies.
        setting_sources=["user", "project", "local"],
    )
    return options


async def _run_query(
    prompt: str, options: ClaudeAgentOptions, log_file: Path
) -> ResultMessage:
    """Run a claude SDK query, stream messages to log, return the ResultMessage."""
    result: ResultMessage | None = None

    async with Spinner():
        async for message in query(prompt=prompt, options=options):
            # Log each message as JSONL
            with log_file.open("a") as f:
                try:
                    f.write(json.dumps(dataclasses.asdict(message)) + "\n")
                except Exception:
                    pass

            if isinstance(message, ResultMessage):
                result = message

    if result is None:
        fail("No result received from Claude.")

    if result.is_error:
        fail("Claude process returned an error.")

    return result


@overload
async def run_claude(
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> None: ...


@overload
async def run_claude[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T: ...


async def run_claude[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T | None:
    """Run the Claude Agent SDK to execute a prompt."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Log initial prompt
    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    schema_dict = schema.model_json_schema() if schema else None
    settings = Settings.load()
    if model is None:
        model = settings.model_for(kind)
        effort = settings.thinking_for(kind)
    else:
        model, effort = split_thinking_level(model)
    options = _build_options(
        model=model,
        effort=effort,
        schema=schema_dict,
        readonly=readonly,
        tools=tools,
        sandbox=project.sandbox,
    )

    result = await _run_query(prompt, options, log_file)

    if schema:
        if result.structured_output is None:
            fail("Failed to get structured output from Claude.")
        return schema.model_validate(result.structured_output)
    return None


async def run_claude_plan_mode(
    *, kind: str, prompt: str, project: Project, model: str | None = None
):
    """Run the Claude Agent SDK with a Q&A loop for plan generation."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Log initial prompt
    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    settings = Settings.load()
    if model is None:
        model = settings.model_for(kind)
        effort = settings.thinking_for(kind)
    else:
        model, effort = split_thinking_level(model)
    session_id: str | None = None
    current_prompt = prompt

    while True:
        schema = PlanOrQuestions.model_json_schema()
        options = _build_options(
            model=model,
            effort=effort,
            session_id=session_id,
            schema=schema,
            readonly=True,
            sandbox=project.sandbox,
        )

        result = await _run_query(current_prompt, options, log_file)

        # Capture session_id for resumption
        if not session_id:
            session_id = result.session_id

        # Parse structured output
        if result.structured_output is None:
            fail("Failed to get structured output from Claude.")

        output = PlanOrQuestions.model_validate(result.structured_output)

        if isinstance(output.plan_or_questions, Plan):
            project.plan_md.write_text(output.plan_or_questions.markdown)
            return
        else:
            current_prompt = await ask_user_questions(output.plan_or_questions)
            with log_file.open("a") as f:
                f.write("\n" + json.dumps({"answers": current_prompt}) + "\n\n")
            continue
