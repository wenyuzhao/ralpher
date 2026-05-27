"""Antigravity (Google Gemini) backend for the agent helpers.

Mirrors the Claude Agent SDK backend in :mod:`ralpher.backend.claude`: the two
public entry points here (`run_antigravity`, `run_antigravity_plan_mode`) have
the same signatures and behaviour as `run_claude` / `run_claude_plan_mode`, so
the dispatcher in :mod:`ralpher.backend` can route to either based on
``project.backend`` without callers needing to know which backend is active.

Differences from the claude-code backend:
- Structured output is requested via ``LocalAgentConfig.response_schema`` and
  read back with ``ChatResponse.structured_output()`` (a plain dict, which we
  validate against the pydantic ``schema`` ourselves).
- The read-only ``.ralpher`` guarantee is enforced with deny *policies* on the
  file-writing builtins rather than Claude Code ``deny`` permission rules.
  Whole-tool restrictions (disabling ``ask_question``, the read-only tool set)
  instead go through ``CapabilitiesConfig``, which drops the tool from the
  model's context entirely.
- The OS Bash sandbox (``project.sandbox``) has no antigravity equivalent and
  is ignored; file writes are still confined to the workspace + the .ralpher
  deny policies.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, overload

from pydantic import BaseModel

from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
from google.antigravity.hooks import policy
from google.antigravity.types import (
    DEFAULT_MODEL,
    BuiltinTools,
    GeminiConfig,
    GenerationConfig,
    ModelConfig,
    ModelEntry,
    ThinkingLevel,
    ToolCall,
)

from ralpher.models import Project, Settings, ralpher_root, split_thinking_level
from ralpher.utils.error import fail

# The question prompt UX and the plan-mode output schema are backend-agnostic
# and shared via common, so this backend never depends on the claude one.
from ralpher.utils.spinner import Spinner

from .common import Plan, PlanOrQuestions, ask_user_questions

# Builtins that create or mutate files. Reads (view_file, list_directory, …)
# are always permitted so the agent can read its task/plan/progress files.
_WRITE_TOOLS = [BuiltinTools.CREATE_FILE, BuiltinTools.EDIT_FILE]


def _ralpher_readonly_policies() -> list[policy.Policy]:
    """Deny policies that make the ``.ralpher`` state directory read-only.

    The agent must read the task/plan/progress files (passed by absolute path)
    but never write into them — progress updates are mediated through a temp
    file in the loop. These are *specific deny* policies, the highest priority
    bucket, so they win even over the read-only allow-list below.
    """
    root = str(ralpher_root().resolve())

    def _in_ralpher(tc: ToolCall) -> bool:
        path = tc.canonical_path or ""
        if not path:
            return False
        target = str(Path(path).resolve())
        return target == root or target.startswith(root + os.sep)

    return [
        policy.deny(tool.value, when=_in_ralpher, name="ralpher_readonly")
        for tool in _WRITE_TOOLS
    ]


def _build_config(
    *,
    model: str | None = None,
    thinking_level: str | None = None,
    schema: type[BaseModel] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> LocalAgentConfig:
    """Build the ``LocalAgentConfig`` for one antigravity run.

    ``thinking_level`` (one of the ``ThinkingLevel`` values) sets the model's
    reasoning effort. It can only travel on the full ``gemini_config`` — the
    ``model`` shorthand carries a name only, and the SDK rejects setting both —
    so when a level is given we build the model entry ourselves and leave the
    shorthand unset.

    ``tools`` is accepted for signature parity with ``run_claude`` but is not
    applied here — its sole caller pairs it with ``readonly=True``, and the
    read-only capability set below is exactly the safe read tool set.

    Which builtins the model can even see is set via ``capabilities`` rather
    than policies: capabilities drop a tool from the model's context entirely
    (the SDK's recommended mechanism for an unconditional restriction), whereas
    a deny policy still shows the tool and rejects calls at the hook layer. The
    path-conditional ``.ralpher`` write guard can't be a capability (it gates a
    tool only for certain paths), so it stays a policy.
    """
    workspace = str(Path.cwd().resolve())

    # The .ralpher write guard is path-conditional, so it must remain a policy.
    # It also doubles as the safety policy the SDK requires whenever write
    # tools are active (it raises otherwise), which is the non-readonly case.
    policies: list[policy.Policy] = list(_ralpher_readonly_policies())

    # ask_question is always disabled: the loop/verify turns run unattended and
    # plan mode drives its own clarification UX, so an interactive question tool
    # would only stall the run. Read-only mode narrows the set further to the
    # safe read builtins (a whitelist, which already excludes ask_question);
    # enabled_tools and disabled_tools are mutually exclusive, hence either/or.
    if readonly:
        capabilities = CapabilitiesConfig(enabled_tools=BuiltinTools.read_only())
    else:
        capabilities = CapabilitiesConfig(disabled_tools=[BuiltinTools.ASK_QUESTION])

    if thinking_level is not None:
        model_kwargs: dict[str, Any] = {
            "gemini_config": GeminiConfig(
                models=ModelConfig(
                    default=ModelEntry(
                        name=model or DEFAULT_MODEL,
                        generation=GenerationConfig(
                            thinking_level=ThinkingLevel(thinking_level)
                        ),
                    )
                )
            )
        }
    else:
        model_kwargs = {"model": model}

    return LocalAgentConfig(
        response_schema=schema,
        workspaces=[workspace],
        policies=policies,
        capabilities=capabilities,
        **model_kwargs,
    )


def _log_chunk(log_file: Path, chunk: Any) -> None:
    """Append one streamed chunk to the JSONL log (best-effort)."""
    try:
        if hasattr(chunk, "model_dump"):
            payload = {"type": type(chunk).__name__, **chunk.model_dump(mode="json")}
        else:
            payload = {"type": type(chunk).__name__, "repr": repr(chunk)}
        with log_file.open("a") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


async def _run_chat(
    prompt: str, config: LocalAgentConfig, log_file: Path, *, expect_structured: bool
) -> dict[str, Any] | None:
    """Run a single antigravity turn, stream chunks to the log, return output."""
    structured: dict[str, Any] | None = None
    async with Spinner():
        try:
            async with Agent(config) as agent:
                response = await agent.chat(prompt)
                async for chunk in response.chunks:
                    _log_chunk(log_file, chunk)
                if expect_structured:
                    structured = await response.structured_output()
        except Exception as e:
            fail(f"Antigravity agent returned an error: {e}")
    return structured


@overload
async def run_antigravity(
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
async def run_antigravity[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T: ...


async def run_antigravity[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T | None:
    """Run the antigravity SDK to execute a prompt (counterpart of run_claude)."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    settings = Settings.load()
    if model is None:
        model = settings.model_for(kind, backend="antigravity")
        thinking_level = settings.thinking_for(kind, backend="antigravity")
    else:
        model, thinking_level = split_thinking_level(model)

    config = _build_config(
        model=model,
        thinking_level=thinking_level,
        schema=schema,
        readonly=readonly,
        tools=tools,
    )

    structured = await _run_chat(
        prompt, config, log_file, expect_structured=schema is not None
    )

    if schema:
        if structured is None:
            fail("Failed to get structured output from the antigravity agent.")
        return schema.model_validate(structured)
    return None


async def run_antigravity_plan_mode(
    *, kind: str, prompt: str, project: Project, model: str | None = None
):
    """Run the antigravity SDK with a Q&A loop for plan generation.

    A single ``Agent`` is held open across turns, so its conversation history
    carries the context forward — the antigravity equivalent of Claude Code's
    ``--resume <session_id>`` continuation.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    settings = Settings.load()
    if model is None:
        model = settings.model_for(kind, backend="antigravity")
        thinking_level = settings.thinking_for(kind, backend="antigravity")
    else:
        model, thinking_level = split_thinking_level(model)

    config = _build_config(
        model=model,
        thinking_level=thinking_level,
        schema=PlanOrQuestions,
        readonly=True,
    )
    current_prompt = prompt

    try:
        async with Agent(config) as agent:
            while True:
                async with Spinner():
                    response = await agent.chat(current_prompt)
                    async for chunk in response.chunks:
                        _log_chunk(log_file, chunk)
                    data = await response.structured_output()

                if data is None:
                    fail("Failed to get structured output from the antigravity agent.")

                output = PlanOrQuestions.model_validate(data)

                if isinstance(output.plan_or_questions, Plan):
                    project.plan_md.write_text(output.plan_or_questions.markdown)
                    return

                # Q&A turn: prompt the user, then continue the same conversation.
                current_prompt = await ask_user_questions(output.plan_or_questions)
                with log_file.open("a") as f:
                    f.write("\n" + json.dumps({"answers": current_prompt}) + "\n\n")
    except SystemExit:
        raise
    except Exception as e:
        fail(f"Antigravity agent returned an error: {e}")
