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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, overload

from pydantic import BaseModel

from ralpher.models import BackendKind, Project, Settings
from ralpher.utils.error import fail
from ralpher.utils.spinner import Spinner

from .common import Plan, PlanOrQuestions, ask_user_questions

# A single JSONL record can carry a whole assistant message, which is routinely
# larger than asyncio's 64 KiB default line limit — hence a generous one here.
STREAM_LINE_LIMIT = 32 * 1024 * 1024

# Placeholder written to the log in place of the prompt argv element, which is
# already logged in full on the log's first line.
_PROMPT_PLACEHOLDER = "<prompt>"


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
    #: Per-kind default model specs for this CLI, keyed by the `kind` passed to
    #: `run` ("plan", "refine", "loop", "verify", "extract-tasks"). A `models`
    #: pin in settings.json overrides these. A trailing ``:<level>`` suffix on a
    #: spec sets the reasoning effort; a bare name leaves the CLI's own default.
    default_models: ClassVar[dict[str, str]]
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
    ) -> list[str]:
        """Full argv for one turn, including the executable itself."""

    @abc.abstractmethod
    def read_result(self, record: dict[str, Any]) -> AgentResult | None:
        """Return an `AgentResult` if `record` is the terminal result, else None."""

    # --- public entry points ---------------------------------------------- #

    @overload
    async def run(
        self,
        *,
        kind: str,
        prompt: str,
        model: str | None = None,
        schema: None = None,
        readonly: bool = False,
        tools: list[str] | None = None,
    ) -> None: ...

    @overload
    async def run[T: BaseModel](
        self,
        *,
        kind: str,
        prompt: str,
        model: str | None = None,
        schema: type[T],
        readonly: bool = False,
        tools: list[str] | None = None,
    ) -> T: ...

    async def run[T: BaseModel](
        self,
        *,
        kind: str,
        prompt: str,
        model: str | None = None,
        schema: type[T] | None = None,
        readonly: bool = False,
        tools: list[str] | None = None,
    ) -> T | None:
        """Run one turn of this backend's CLI to execute `prompt`."""
        log_file = self._start_log(kind, prompt)
        model_name, effort = self._resolve_model(kind, model)

        argv = self.build_command(
            prompt=prompt,
            model=model_name,
            effort=effort,
            schema=schema.model_json_schema() if schema else None,
            readonly=readonly,
            tools=tools,
            session_id=None,
        )
        result = await self._spawn(argv, prompt, log_file)

        if schema is None:
            return None
        if result.structured_output is None:
            fail(f"Failed to get structured output from {self.executable}.")
        return schema.model_validate(result.structured_output)

    async def run_plan_mode(
        self, *, kind: str, prompt: str, model: str | None = None
    ) -> None:
        """Run a Q&A loop until the agent returns a plan, then write PLAN.md.

        Each turn asks for a `PlanOrQuestions`: either the finished plan, or
        clarification questions to put to the user. Answers are fed back as the
        next turn's prompt on the same conversation (the backend's `--resume` /
        `--conversation` handle), so the agent keeps its context.
        """
        log_file = self._start_log(kind, prompt)
        model_name, effort = self._resolve_model(kind, model)
        schema = PlanOrQuestions.model_json_schema()

        session_id: str | None = None
        current_prompt = prompt

        while True:
            argv = self.build_command(
                prompt=current_prompt,
                model=model_name,
                effort=effort,
                schema=schema,
                readonly=True,
                tools=None,
                session_id=session_id,
            )
            result = await self._spawn(argv, current_prompt, log_file)

            if not session_id:
                session_id = result.session_id
            if result.structured_output is None:
                fail(f"Failed to get structured output from {self.executable}.")

            output = PlanOrQuestions.model_validate(result.structured_output)
            if isinstance(output.plan_or_questions, Plan):
                self.project.plan_md.write_text(output.plan_or_questions.markdown)
                return

            current_prompt = await ask_user_questions(output.plan_or_questions)
            _append_log(log_file, {"answers": current_prompt})

    # --- shared plumbing --------------------------------------------------- #

    def _resolve_model(
        self, kind: str, model: str | None
    ) -> tuple[str | None, str | None]:
        """Model name and reasoning effort for `kind`.

        An explicitly passed `model` wins, else a `models` pin in settings.json,
        else this backend's `default_models`. Whichever it is, a trailing
        ``:<level>`` suffix is peeled off into the effort; a spec without one
        leaves the effort unset, so the CLI applies its own default.
        """
        spec = (
            model or Settings.load().models.get(kind) or self.default_models.get(kind)
        )
        return self.split_effort(spec) if spec else (None, None)

    def _start_log(self, kind: str, prompt: str) -> Path:
        """Create this run's log file, seeded with the initial prompt."""
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
        log_file = self.project.project_dir / "logs" / f"{kind}-{timestamp}.log"
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
