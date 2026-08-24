"""Antigravity (Google Gemini) backend — drives the `agy` CLI as a subprocess.

The counterpart of `ralpher.backend.claude`; both are thin argv builders over
the shared driver in `ralpher.backend.base`. The `agy` CLI is close to
`claude`'s in shape, so most flags map one-to-one. Where they differ:

- The prompt is passed via ``--print`` (not positional), paired with
  ``--print-timeout 1h`` to override agy's 5-minute default timeout.
- The conversation handle is ``--conversation <id>`` (claude: ``--resume``),
  and it arrives on the result record as ``conversation_id``.
- The stream-json envelope is ``{"event": "result", "result": {...}}`` rather
  than a flat ``{"type": "result", ...}``.
- There is no per-tool flag. Read-only turns use ``--mode plan`` instead, which
  soft-denies every file write even under ``--dangerously-skip-permissions``.
- Reasoning effort is ``low|medium|high`` (claude also has ``xhigh``/``max``).
- ``extra_args`` from settings.toml is appended verbatim, same as claude.

Known gap: the `.ralpher` state directory can't be made read-only for this
backend. `agy` has no inline-settings flag (claude's ``--settings``) to carry
per-run deny rules, and its permission config is global to the user's install,
which ralpher will not edit. Read-only turns are still write-free via
``--mode plan``, and `--sandbox` restricts the terminal, but an implementation
turn can write into `.ralpher` here where claude is hard-blocked.
"""

import json
from pathlib import Path
from typing import Any, ClassVar

from ralpher.models import AgentRole

from .base import AgentResult, Backend


class AntigravityBackend(Backend):
    kind = "antigravity"
    executable = "agy"
    install_hint = (
        "Install the Antigravity CLI and sign in with `agy` — "
        "see https://antigravity.google."
    )
    context_file = "GEMINI.md"

    # ``agy models`` lists the names this backend accepts. Unlike the claude
    # defaults, these pin an effort explicitly via the ``:<level>`` suffix.
    default_models: ClassVar[dict[AgentRole, str]] = {
        "planner": "gemini-3.7-flash:high",
        "refiner": "gemini-3.7-flash:high",
        "worker": "gemini-3.7-flash:high",
        "verifier": "gemini-3.7-flash:high",
    }
    effort_levels: ClassVar[tuple[str, ...]] = ("low", "medium", "high")

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
        """Argv for one `agy` turn.

        `tools` is accepted for signature parity with the claude backend but is
        not applied: `agy` has no per-tool flag. Its sole caller pairs it with
        ``readonly=True``, and plan mode already blocks every write.
        """
        argv = [
            self.executable,
            "--print",
            prompt,
            "--print-timeout",
            "3h",
            "--output-format",
            "stream-json",
            # Unattended runs must never block on a permission prompt. In
            # read-only turns this is still safe: plan mode's write block is
            # independent of permissions.
            "--dangerously-skip-permissions",
            # Confine file access to the run's workspace.
            "--add-dir",
            str(Path.cwd().resolve()),
        ]
        if readonly:
            argv += ["--mode", "plan"]
        if self.project.sandbox:
            argv.append("--sandbox")
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if schema:
            argv += ["--json-schema", json.dumps(schema)]
        if session_id:
            argv += ["--conversation", session_id]
        argv += extra_args
        return argv

    def read_result(self, record: dict[str, Any]) -> AgentResult | None:
        if record.get("event") != "result":
            return None
        result = record.get("result")
        if not isinstance(result, dict):
            return None
        status = result.get("status")
        failed = status != "SUCCESS" and result.get("structured_output") is None
        return AgentResult(
            session_id=result.get("conversation_id"),
            structured_output=result.get("structured_output"),
            is_error=failed,
            error=(
                result.get("error")
                or f"The antigravity agent finished with status {status}."
            )
            if failed
            else None,
        )
