"""Claude Code backend — drives the `claude` CLI as a subprocess.

Only the two backend-specific pieces live here (see `ralpher.backend.base` for
everything shared): the argv for one turn, and how to spot the terminal
`{"type": "result", ...}` record in the CLI's stream-json output.

Flags this backend relies on:
- ``--print <prompt> --output-format stream-json --verbose`` — one turn, JSONL out
- ``--json-schema <schema>`` — structured output, echoed back on the result
  record's ``structured_output`` field
- ``--permission-mode`` + ``--dangerously-skip-permissions`` — unattended runs
- ``--tools`` / ``--allowed-tools`` — the read-only tool set
- ``--effort <level>`` — reasoning effort, from the model spec's ``:<level>``
  suffix; omitted for a bare model so the CLI's own default (``high``) applies
- ``--settings <json>`` — inline settings keeping ``.ralpher`` read-only, plus
  the optional Bash sandbox
- ``--resume <session_id>`` — plan-mode Q&A continuation
- ``extra_args`` from settings.toml — appended verbatim, before the prompt
"""

import json
from pathlib import Path
from typing import Any, ClassVar

from ralpher.models import AgentRole, ralpher_root

from .base import AgentResult, Backend

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


class ClaudeBackend(Backend):
    kind = "claude-code"
    executable = "claude"
    install_hint = "Install it first: https://docs.anthropic.com/en/docs/claude-code"
    context_file = "CLAUDE.md"

    # None of these carry a ``:<level>`` suffix, so they run at the CLI's own
    # default effort (``high``). Pin a model per role in settings.toml to
    # override, with or without a suffix.
    default_models: ClassVar[dict[AgentRole, str]] = {
        "planner": "opus",
        "refiner": "opus",
        "worker": "opus",
        "verifier": "sonnet",
    }
    effort_levels: ClassVar[tuple[str, ...]] = ("low", "medium", "high", "xhigh", "max")

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
        if readonly:
            tools = tools or READONLY_TOOLS

        argv = [
            self.executable,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk" if readonly else "bypassPermissions",
            # Load the user's Claude Code settings rather than running
            # hermetically, so e.g. a sandbox.network allowlist in
            # .claude/settings.json applies on top of the inline settings.
            "--setting-sources",
            "user,project,local",
            "--settings",
            self._settings_json(),
        ]
        if not readonly:
            argv.append("--dangerously-skip-permissions")
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if schema:
            argv += ["--json-schema", json.dumps(schema)]
        if tools is not None:
            # These options are variadic, so they would otherwise swallow every
            # following argv element (the prompt included). The "--opt=value"
            # form binds exactly one value.
            joined = ",".join(tools)
            argv += [f"--tools={joined}", f"--allowed-tools={joined}"]
        if session_id:
            argv += ["--resume", session_id]
        argv += extra_args

        # The prompt is positional, so it goes last.
        argv.append(prompt)
        return argv

    def read_result(self, record: dict[str, Any]) -> AgentResult | None:
        if record.get("type") != "result":
            return None
        failed = bool(record.get("is_error")) or record.get("subtype") != "success"
        return AgentResult(
            session_id=record.get("session_id"),
            structured_output=record.get("structured_output"),
            is_error=failed,
            error=f"Claude returned an error: {record.get('subtype')}."
            if failed
            else None,
        )

    def _settings_json(self) -> str:
        """Inline settings JSON for the `claude` subprocess.

        Keeps the ``.ralpher`` state directory read-only: Claude must be able to
        read its task/plan/progress files (which are passed by absolute path)
        but never write into them — progress updates are mediated through a temp
        file in the loop. ``deny`` rules are a hard block that is enforced even
        under ``bypassPermissions``, so this holds for every call.

        The absolute path uses the ``//`` prefix required by Claude Code's
        gitignore-style permission patterns for filesystem-root paths.

        When the run is sandboxed, the OS Bash sandbox is enabled here too, so
        the deny rule is enforced against shell writes and not just the file
        tools (a tool-path deny alone doesn't cover arbitrary Bash).
        """
        root = Path(ralpher_root()).resolve()
        pattern = f"//{str(root).lstrip('/')}/**"
        settings: dict[str, Any] = {
            "permissions": {
                "deny": [
                    f"Write({pattern})",
                    f"Edit({pattern})",
                    f"NotebookEdit({pattern})",
                ]
            }
        }
        if self.project.sandbox:
            settings["sandbox"] = {
                "enabled": True,
                "network": {"allowedDomains": ["*"]},
            }
        return json.dumps(settings)
