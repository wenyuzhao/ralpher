"""The `Backend` abstraction: one coding-agent CLI, driven as a subprocess.

Every backend is a CLI that ralpher spawns, feeds a prompt, and reads a JSONL
event stream back from. The two supported ones — `claude` and `agy` — are close
enough in shape that only two things actually differ:

- **the argv** for a turn (`build_command`), and
- **which streamed record is the terminal result** (`read_result`).

Everything else — resolving the model/effort for a kind, creating the log file,
spawning the process, tee'ing its stdout to that log, turning a non-zero exit or
an error result into `fail()`, validating structured output against a pydantic
schema, and the plan-mode Q&A loop — is shared here so the two backends stay
thin argv builders. Neither imports a vendor SDK; the CLI *is* the interface.
"""

import abc
import asyncio
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, overload

import rich
from pydantic import BaseModel

from ralpher.models import AgentRole, BackendKind, Project, Settings
from ralpher.utils.error import fail
from ralpher.utils.spinner import Spinner

from .common import (
    Plan,
    PlanOnly,
    PlanOrQuestions,
    ask_user_questions,
    check_task_ids,
)

# A single JSONL record can carry a whole assistant message, which is routinely
# larger than asyncio's 64 KiB default line limit — hence a generous one here.
STREAM_LINE_LIMIT = 32 * 1024 * 1024

# Placeholder written to the log in place of the prompt argv element, which is
# already logged in full on the log's first line.
_PROMPT_PLACEHOLDER = "<prompt>"

# How many times a plan rejected by the caller's `validate` hook is handed back
# to the agent to fix before the run gives up. Each retry costs a full turn, so
# keep this small.
MAX_PLAN_CORRECTIONS = 4


@dataclass(frozen=True)
class AgentResult:
    """The terminal record of one CLI turn, normalized across backends.

    ``session_id`` is whatever the backend calls its conversation handle
    (claude's ``session_id``, agy's ``conversation_id``); it is fed back to
    `build_command` to continue a plan-mode conversation.
    """

    session_id: str | None = None
    structured_output: dict[str, Any] | None = None
    is_error: bool = False
    error: str | None = None


class Backend(abc.ABC):
    """One coding-agent CLI, bound to the `Project` it is running for."""

    #: Canonical backend name; selects this class in the dispatcher.
    kind: ClassVar[BackendKind]
    #: Executable to spawn. Must be on PATH.
    executable: ClassVar[str]
    #: Appended to the "not found on PATH" error, telling the user how to fix it.
    install_hint: ClassVar[str]
    #: Name of the per-directory context file this CLI reads for project
    #: conventions ("CLAUDE.md", "GEMINI.md", …). Prompts refer to it by this
    #: name so the agent updates the file its own CLI will pick up later.
    context_file: ClassVar[str]
    #: Per-role default model specs for this CLI, keyed by the `role` passed to
    #: `run` (see `AgentRole`). A model pinned in settings.toml — globally or
    #: under ``[agents.<role>]`` — overrides these. A trailing ``:<level>``
    #: suffix on a spec sets the reasoning effort; a bare name leaves the CLI's
    #: own default.
    default_models: ClassVar[dict[AgentRole, str]]
    #: Reasoning-effort levels this CLI accepts as ``--effort``. Only these are
    #: recognized as a ``:<level>`` model suffix.
    effort_levels: ClassVar[tuple[str, ...]]

    def __init__(self, project: Project) -> None:
        self.project = project

    @classmethod
    def split_effort(cls, spec: str) -> tuple[str, str | None]:
        """Peel a trailing ``:<level>`` reasoning-effort suffix off a model spec.

        ``"claude-opus-5:high"`` → ``("claude-opus-5", "high")``. The level must
        be one this CLI accepts (`effort_levels`), so an unrecognized suffix
        stays part of the name — as does the bracketed ``[1m]`` context-window
        suffix on a Claude model, which is never a level.
        """
        name, sep, level = spec.rpartition(":")
        if sep and name and level in cls.effort_levels:
            return name, level
        return spec, None

    @classmethod
    def check_prerequisites(cls) -> None:
        """Exit with an error unless this backend's CLI is available."""
        if not shutil.which(cls.executable):
            fail(f"'{cls.executable}' CLI not found on PATH. {cls.install_hint}")

    # --- subclass hooks --------------------------------------------------- #

    @abc.abstractmethod
    def build_command(
        self,
        *,
        prompt: str,
        model: str | None,
        effort: str | None,
        schema: dict[str, Any] | None,
        readonly: bool,
        tools: list[str] | None,
        session_id: str | None,
        extra_args: list[str],
    ) -> list[str]:
        """Full argv for one turn, including the executable itself.

        `extra_args` is already merged (global settings first, then this role's)
        and must be appended verbatim, before any positional prompt.
        """

    @abc.abstractmethod
    def read_result(self, record: dict[str, Any]) -> AgentResult | None:
        """Return an `AgentResult` if `record` is the terminal result, else None."""

    # --- public entry points ---------------------------------------------- #

    @overload
    async def run(
        self,
        *,
        role: AgentRole,
        prompt: str,
        model: str | None = None,
        schema: None = None,
        readonly: bool = False,
        tools: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> None: ...

    @overload
    async def run[T: BaseModel](
        self,
        *,
        role: AgentRole,
        prompt: str,
        model: str | None = None,
        schema: type[T],
        readonly: bool = False,
        tools: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> T: ...

    async def run[T: BaseModel](
        self,
        *,
        role: AgentRole,
        prompt: str,
        model: str | None = None,
        schema: type[T] | None = None,
        readonly: bool = False,
        tools: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> T | None:
        """Run one turn of this backend's CLI to execute `prompt`."""
        log_file = self._start_log(role, prompt)
        model_name, effort = self._resolve_model(role, model)

        argv = self.build_command(
            prompt=prompt,
            model=model_name,
            effort=effort,
            schema=schema.model_json_schema() if schema else None,
            readonly=readonly,
            tools=tools,
            session_id=None,
            extra_args=self._resolve_extra_args(extra_args),
        )
        result = await self._spawn(argv, prompt, log_file)

        if schema is None:
            return None
        if result.structured_output is None:
            fail(f"Failed to get structured output from {self.executable}.")
        return schema.model_validate(result.structured_output)

    async def run_plan_mode(
        self,
        *,
        role: AgentRole,
        prompt: str,
        model: str | None = None,
        validate: Callable[[Plan], str | None] | None = None,
        readonly: bool = True,
        tools: list[str] | None = None,
        extra_args: list[str] | None = None,
        max_corrections: int | None = None,
    ) -> None:
        """Run a Q&A loop until the agent returns a plan, then write it out.

        The plan arrives in two halves — the design document, written to
        design.md, and the structured task list, written to tasks.toml — so no
        separate extraction pass is needed to turn prose back into tasks.

        Each turn asks for a `PlanOrQuestions`: either the finished plan, or
        clarification questions to put to the user. Answers are fed back as the
        next turn's prompt on the same conversation (the backend's `--resume` /
        `--conversation` handle), so the agent keeps its context.

        Two checks stand between a returned plan and the files. `check_task_ids`
        always runs: a plan's ids must be `T-001`, `T-002`, … in list order, and
        there may be at most `MAX_TASKS` of them. `validate` is the caller's own
        check on top of that (refine uses it to freeze the tasks that already
        passed). Either one returning a message rejects the plan, and that
        message becomes the next turn's prompt so the agent can correct itself
        with its context intact — both messages together when both fire. After
        `max_corrections` rejections (`MAX_PLAN_CORRECTIONS` unless the role
        pins its own) the run fails with it instead — nothing is written for a
        plan that never validated. A correction turn is given the narrower
        `PlanOnly` schema: it is answering a rejection of its own output, so its
        only move is to return a fixed plan, never to put a question to the user.
        """
        log_file = self._start_log(role, prompt)
        model_name, effort = self._resolve_model(role, model)
        schema = PlanOrQuestions.model_json_schema()
        correction_schema = PlanOnly.model_json_schema()
        limit = MAX_PLAN_CORRECTIONS if max_corrections is None else max_corrections
        merged_extra_args = self._resolve_extra_args(extra_args)

        session_id: str | None = None
        current_prompt = prompt
        corrections = 0

        while True:
            argv = self.build_command(
                prompt=current_prompt,
                model=model_name,
                effort=effort,
                schema=correction_schema if corrections else schema,
                readonly=readonly,
                tools=tools,
                session_id=session_id,
                extra_args=merged_extra_args,
            )
            result = await self._spawn(argv, current_prompt, log_file)

            if not session_id:
                session_id = result.session_id
            if result.structured_output is None:
                fail(f"Failed to get structured output from {self.executable}.")

            output = PlanOrQuestions.model_validate(result.structured_output)
            if isinstance(output.plan_or_questions, Plan):
                plan = output.plan_or_questions
                # Both checks run on every plan, and their complaints are sent
                # back together: fixing one can break the other (renumbering vs.
                # refine's frozen ids), so the agent needs to see both at once.
                problems = [
                    message
                    for message in (
                        check_task_ids(plan),
                        validate(plan) if validate else None,
                    )
                    if message
                ]
                if not problems:
                    self.project.design_md.write_text(plan.markdown)
                    self.project.save_planned_tasks(plan.tasks)
                    return
                problem = "\n\n".join(problems)
                _append_log(log_file, {"rejected_plan": problem})
                corrections += 1
                if corrections > limit:
                    fail(problem)
                rich.print(
                    f"[yellow]The returned plan was rejected; asking the agent to fix it "
                    f"({corrections}/{limit}).[/]"
                )
                current_prompt = problem
                continue

            current_prompt = await ask_user_questions(output.plan_or_questions)
            _append_log(log_file, {"answers": current_prompt})

    # --- shared plumbing --------------------------------------------------- #

    def _resolve_model(
        self, role: AgentRole, model: str | None
    ) -> tuple[str | None, str | None]:
        """Model name and reasoning effort for `role`.

        An explicitly passed `model` wins (the agent supplies its
        ``[agents.<role>].model`` there), else the global ``model`` pin in
        settings.toml, else this backend's `default_models`. Whichever it is, a
        trailing ``:<level>`` suffix is peeled off into the effort; a spec
        without one leaves the effort unset, so the CLI applies its own default.
        """
        spec = model or Settings.load().get_model(role) or self.default_models.get(role)
        return self.split_effort(spec) if spec else (None, None)

    def _resolve_extra_args(self, extra: list[str] | None) -> list[str]:
        """Extra CLI args for one turn: the global ones, then this role's.

        The global list is the ``extra_args`` key in settings.toml; the per-role
        one comes from ``[agents.<role>]``. There is no CLI flag for either, so
        they always come from settings.toml.
        """
        return [*Settings.load().extra_args, *(extra or [])]

    def _start_log(self, role: AgentRole, prompt: str) -> Path:
        """Create this run's log file, seeded with the initial prompt."""
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
        log_file = self.project.project_dir / "logs" / f"{role}-{timestamp}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(json.dumps({"initial_prompt": prompt}) + "\n\n")
        return log_file

    async def _spawn(self, argv: list[str], prompt: str, log_file: Path) -> AgentResult:
        """Run one CLI turn, tee'ing its JSONL stdout to `log_file`.

        stdout and stderr are drained concurrently (a full stderr pipe would
        otherwise deadlock the child), and every stdout line is written through
        to the log as it arrives so the file is tail-able mid-run.
        """
        _append_log(log_file, {"command": _redact(argv, prompt)})

        result: AgentResult | None = None
        async with Spinner():
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LINE_LIMIT,
            )
            assert proc.stdout is not None
            assert proc.stderr is not None
            drain_stderr = asyncio.create_task(proc.stderr.read())

            with log_file.open("a") as log:
                try:
                    async for raw in proc.stdout:
                        line = raw.decode("utf-8", errors="replace").rstrip("\n")
                        log.write(line + "\n")
                        log.flush()
                        record = _parse_record(line)
                        if record is None:
                            continue
                        parsed = self.read_result(record)
                        if parsed is not None:
                            result = parsed
                except ValueError:
                    # A single JSONL record longer than STREAM_LINE_LIMIT.
                    proc.kill()
                    await proc.wait()
                    drain_stderr.cancel()
                    fail(f"{self.executable} emitted an oversized output record.")

            stderr = (await drain_stderr).decode("utf-8", errors="replace").strip()
            code = await proc.wait()

        if stderr:
            _append_log(log_file, {"stderr": stderr})

        if code != 0:
            detail = f"\n{stderr}" if stderr else ""
            fail(f"{self.executable} exited with code {code}.{detail}")
        if result is None:
            fail(f"No result received from {self.executable}.")
        if result.is_error:
            fail(result.error or f"{self.executable} returned an error.")
        return result


def _parse_record(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line, ignoring anything that isn't a JSON object."""
    if not line.strip():
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _redact(argv: list[str], prompt: str) -> list[str]:
    """The argv with the prompt elided — it is already logged in full."""
    return [_PROMPT_PLACEHOLDER if arg == prompt else arg for arg in argv]


def _append_log(log_file: Path, payload: dict[str, Any]) -> None:
    """Append one JSONL record to the log (best-effort)."""
    try:
        with log_file.open("a") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:  # noqa: S110, BLE001 - logging is best-effort; never break a run
        pass
