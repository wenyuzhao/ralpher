"""Tests for the `Backend` CLI abstraction and its two implementations.

No real `claude` / `agy` invocation happens here. Argv construction and result
parsing are pure functions, so they are tested directly; the shared subprocess
driver is exercised against a stub "CLI" (a small python script that replays a
canned JSONL stream), which keeps `_spawn` honest without a network call.
"""

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel

from ralpher.backend import BACKENDS, get_backend
from ralpher.backend.antigravity import AntigravityBackend
from ralpher.backend.base import MAX_PLAN_CORRECTIONS, AgentResult, Backend
from ralpher.backend.claude import READONLY_TOOLS, ClaudeBackend
from ralpher.backend.common import MAX_TASKS, Plan, check_task_ids
from ralpher.models import AGENT_ROLES, AgentRole, PlannedTask, Project, Task, Tasks


class Out(BaseModel):
    value: int


def _project(tmp_path, monkeypatch, **kwargs) -> Project:
    monkeypatch.chdir(tmp_path)
    kwargs.setdefault("backend", "claude-code")
    return Project(id="proj", **kwargs)


def _flag(argv: list[str], name: str) -> str | None:
    """The value following `name` in `argv`, or None if the flag is absent."""
    return argv[argv.index(name) + 1] if name in argv else None


def _build(backend: Backend, **overrides) -> list[str]:
    kwargs: dict = {
        "prompt": "do the thing",
        "model": None,
        "effort": None,
        "schema": None,
        "readonly": False,
        "tools": None,
        "session_id": None,
        "extra_args": [],
    }
    kwargs.update(overrides)
    return backend.build_command(**kwargs)


# --- dispatcher ----------------------------------------------------------- #


class TestDispatcher:
    def test_registry_covers_both_backends(self):
        assert BACKENDS == {
            "claude-code": ClaudeBackend,
            "antigravity": AntigravityBackend,
        }

    def test_get_backend_selects_on_project(self, tmp_path, monkeypatch):
        assert isinstance(get_backend(_project(tmp_path, monkeypatch)), ClaudeBackend)
        assert isinstance(
            get_backend(_project(tmp_path, monkeypatch, backend="antigravity")),
            AntigravityBackend,
        )

    def test_backend_carries_its_project(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        assert get_backend(project).project is project

    def test_missing_executable_fails(self, monkeypatch):
        monkeypatch.setattr("ralpher.backend.base.shutil.which", lambda _: None)
        with pytest.raises(SystemExit):
            ClaudeBackend.check_prerequisites()

    def test_present_executable_passes(self, monkeypatch):
        monkeypatch.setattr("ralpher.backend.base.shutil.which", lambda _: "/bin/agy")
        AntigravityBackend.check_prerequisites()


# --- per-backend model defaults -------------------------------------------- #


class TestDefaultModels:
    """Each backend owns its own per-role defaults and effort vocabulary."""

    def test_claude_defaults(self, tmp_path, monkeypatch):
        backend = get_backend(_project(tmp_path, monkeypatch))
        assert backend._resolve_model("planner", None) == ("opus", None)
        assert backend._resolve_model("verifier", None) == ("sonnet", None)
        assert backend._resolve_model("worker", None) == ("opus", None)

    def test_antigravity_defaults(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        backend = get_backend(project)
        assert backend._resolve_model("planner", None) == ("gemini-3.7-flash", "high")
        assert backend._resolve_model("verifier", None) == ("gemini-3.7-flash", "high")

    def test_every_role_has_a_default_on_both_backends(self):
        for cls in BACKENDS.values():
            assert set(AGENT_ROLES) == set(cls.default_models)

    def test_defaults_do_not_leak_across_backends(self):
        assert ClaudeBackend.default_models != AntigravityBackend.default_models

    def test_explicit_model_wins(self, tmp_path, monkeypatch):
        # The agent passes its `[agents.<role>].model` in this argument.
        backend = get_backend(_project(tmp_path, monkeypatch))
        assert backend._resolve_model("planner", "haiku:low") == ("haiku", "low")

    def test_settings_pin_beats_the_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text('model = "some-model:medium"\n')
        # The pin applies whichever backend is active.
        for kind in ("claude-code", "antigravity"):
            backend = get_backend(Project(id="proj", backend=kind))
            assert backend._resolve_model("planner", None) == ("some-model", "medium")

    def test_bare_pin_leaves_effort_to_the_cli(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text('model = "some-model"\n')
        backend = get_backend(Project(id="proj", backend="claude-code"))
        assert backend._resolve_model("planner", None) == ("some-model", None)

    def test_settings_pin_applies_to_every_role(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text('model = "universal-model:low"\n')
        for kind in ("claude-code", "antigravity"):
            backend = get_backend(Project(id="proj", backend=kind))
            for role in AGENT_ROLES:
                assert backend._resolve_model(role, None) == ("universal-model", "low")


class TestResolveExtraArgs:
    """The global `extra_args` and the role's own are merged, in that order."""

    def _backend(self, tmp_path, monkeypatch, settings: str = "") -> Backend:
        monkeypatch.chdir(tmp_path)
        if settings:
            ralpher = tmp_path / ".ralpher"
            ralpher.mkdir()
            (ralpher / "settings.toml").write_text(settings)
        return get_backend(Project(id="proj", backend="claude-code"))

    def test_global_only(self, tmp_path, monkeypatch):
        backend = self._backend(tmp_path, monkeypatch, 'extra_args = ["--foo"]\n')
        assert backend._resolve_extra_args(None) == ["--foo"]

    def test_role_args_follow_the_global_ones(self, tmp_path, monkeypatch):
        backend = self._backend(tmp_path, monkeypatch, 'extra_args = ["--foo"]\n')
        assert backend._resolve_extra_args(["--bar"]) == ["--foo", "--bar"]

    def test_role_args_without_any_global_ones(self, tmp_path, monkeypatch):
        backend = self._backend(tmp_path, monkeypatch)
        assert backend._resolve_extra_args(["--bar"]) == ["--bar"]


class TestSplitEffort:
    def test_peels_a_known_suffix(self):
        assert AntigravityBackend.split_effort("gemini-3.5-flash:high") == (
            "gemini-3.5-flash",
            "high",
        )

    def test_no_suffix_returns_the_spec_unchanged(self):
        assert ClaudeBackend.split_effort("haiku") == ("haiku", None)

    def test_unknown_trailing_word_is_not_a_level(self):
        assert AntigravityBackend.split_effort("gemini-3.1-pro:preview") == (
            "gemini-3.1-pro:preview",
            None,
        )

    def test_bracketed_context_window_is_kept(self):
        # Only a recognized ":<level>" is peeled; "[1m]" is part of the name.
        assert ClaudeBackend.split_effort("claude-opus-5[1m]:high") == (
            "claude-opus-5[1m]",
            "high",
        )
        assert ClaudeBackend.split_effort("claude-opus-5[1m]") == (
            "claude-opus-5[1m]",
            None,
        )

    def test_levels_are_per_backend(self):
        # agy takes only low/medium/high; xhigh and max are claude-only.
        assert ClaudeBackend.split_effort("m:xhigh") == ("m", "xhigh")
        assert ClaudeBackend.split_effort("m:max") == ("m", "max")
        assert AntigravityBackend.split_effort("m:xhigh") == ("m:xhigh", None)
        assert AntigravityBackend.split_effort("m:max") == ("m:max", None)
        assert AntigravityBackend.split_effort("m:high") == ("m", "high")


# --- claude argv ----------------------------------------------------------- #


class TestClaudeCommand:
    def test_streams_json_with_prompt_last(self, tmp_path, monkeypatch):
        argv = _build(get_backend(_project(tmp_path, monkeypatch)))
        assert argv[0] == "claude"
        # The prompt is positional, so it must not be swallowed by an option.
        assert argv[-1] == "do the thing"
        assert _flag(argv, "--output-format") == "stream-json"
        assert "--verbose" in argv

    def test_model_and_effort(self, tmp_path, monkeypatch):
        argv = _build(
            get_backend(_project(tmp_path, monkeypatch)),
            model="claude-opus-5",
            effort="xhigh",
        )
        assert _flag(argv, "--model") == "claude-opus-5"
        assert _flag(argv, "--effort") == "xhigh"

    def test_bare_model_omits_effort(self, tmp_path, monkeypatch):
        argv = _build(get_backend(_project(tmp_path, monkeypatch)), model="haiku")
        assert "--effort" not in argv

    def test_schema_is_serialized(self, tmp_path, monkeypatch):
        argv = _build(
            get_backend(_project(tmp_path, monkeypatch)),
            schema=Out.model_json_schema(),
        )
        raw = _flag(argv, "--json-schema")
        assert raw is not None
        assert json.loads(raw) == Out.model_json_schema()

    def test_write_turn_skips_permissions(self, tmp_path, monkeypatch):
        argv = _build(get_backend(_project(tmp_path, monkeypatch)))
        assert _flag(argv, "--permission-mode") == "bypassPermissions"
        assert "--dangerously-skip-permissions" in argv
        assert not any(a.startswith("--tools") for a in argv)

    def test_readonly_turn_restricts_tools(self, tmp_path, monkeypatch):
        argv = _build(get_backend(_project(tmp_path, monkeypatch)), readonly=True)
        assert _flag(argv, "--permission-mode") == "dontAsk"
        assert "--dangerously-skip-permissions" not in argv
        joined = ",".join(READONLY_TOOLS)
        # The "=" form is required: these options are variadic and would
        # otherwise swallow the positional prompt.
        assert f"--tools={joined}" in argv
        assert f"--allowed-tools={joined}" in argv

    def test_explicit_tools_win_over_the_readonly_set(self, tmp_path, monkeypatch):
        argv = _build(
            get_backend(_project(tmp_path, monkeypatch)),
            readonly=True,
            tools=["Read"],
        )
        assert "--tools=Read" in argv

    def test_session_id_resumes(self, tmp_path, monkeypatch):
        argv = _build(get_backend(_project(tmp_path, monkeypatch)), session_id="sess-1")
        assert _flag(argv, "--resume") == "sess-1"

    def test_extra_args_precede_the_prompt(self, tmp_path, monkeypatch):
        backend = get_backend(_project(tmp_path, monkeypatch))
        argv = _build(backend, extra_args=["--foo", "bar"])
        assert "--foo" in argv
        assert argv[argv.index("--foo") + 1] == "bar"
        # The prompt is positional, so extra args must not land after it.
        assert argv[-1] == "do the thing"

    def test_user_settings_are_loaded(self, tmp_path, monkeypatch):
        # Not hermetic: a sandbox.network allowlist in .claude/settings.json
        # must still apply on top of the inline settings.
        argv = _build(get_backend(_project(tmp_path, monkeypatch)))
        assert _flag(argv, "--setting-sources") == "user,project,local"

    def test_ralpher_is_always_read_only(self, tmp_path, monkeypatch):
        for sandbox in (True, False):
            project = _project(tmp_path, monkeypatch, sandbox=sandbox)
            argv = _build(get_backend(project))
            raw = _flag(argv, "--settings")
            assert raw is not None
            deny = json.loads(raw)["permissions"]["deny"]
            assert any(
                r.startswith("Write(//") and r.endswith("/.ralpher/**)") for r in deny
            )

    def test_sandbox_enabled_in_settings(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, sandbox=True)
        raw = _flag(_build(get_backend(project)), "--settings")
        assert raw is not None
        assert json.loads(raw)["sandbox"] == {
            "enabled": True,
            "network": {"allowedDomains": ["*"]},
        }

    def test_sandbox_disabled_leaves_key_out(self, tmp_path, monkeypatch):
        raw = _flag(_build(get_backend(_project(tmp_path, monkeypatch))), "--settings")
        assert raw is not None
        assert "sandbox" not in json.loads(raw)


# --- antigravity argv ------------------------------------------------------ #


class TestAntigravityCommand:
    def test_prompt_rides_on_the_print_flag(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project))
        assert argv[0] == "agy"
        assert _flag(argv, "--print") == "do the thing"
        assert _flag(argv, "--print-timeout") == "3h"
        assert _flag(argv, "--output-format") == "stream-json"

    def test_workspace_is_cwd(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project))
        assert _flag(argv, "--add-dir") == str(tmp_path.resolve())

    def test_model_and_effort(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), model="gemini-3.1-pro", effort="high")
        assert _flag(argv, "--model") == "gemini-3.1-pro"
        assert _flag(argv, "--effort") == "high"

    def test_schema_is_serialized(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), schema=Out.model_json_schema())
        raw = _flag(argv, "--json-schema")
        assert raw is not None
        assert json.loads(raw) == Out.model_json_schema()

    def test_write_turn_has_no_plan_mode(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project))
        assert "--mode" not in argv
        # Unattended runs must never block on a permission prompt.
        assert "--dangerously-skip-permissions" in argv

    def test_readonly_turn_uses_plan_mode(self, tmp_path, monkeypatch):
        # agy has no per-tool flag; plan mode is what blocks writes, and it does
        # so even under --dangerously-skip-permissions.
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), readonly=True)
        assert _flag(argv, "--mode") == "plan"

    def test_tools_are_ignored(self, tmp_path, monkeypatch):
        # Accepted for signature parity with claude, but agy has no equivalent.
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), readonly=True, tools=["Read"])
        assert not any(a.startswith("--tools") for a in argv)

    def test_session_id_resumes_the_conversation(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), session_id="conv-1")
        assert _flag(argv, "--conversation") == "conv-1"

    def test_sandbox_flag(self, tmp_path, monkeypatch):
        off = _project(tmp_path, monkeypatch, backend="antigravity")
        on = _project(tmp_path, monkeypatch, backend="antigravity", sandbox=True)
        assert "--sandbox" not in _build(get_backend(off))
        assert "--sandbox" in _build(get_backend(on))

    def test_extra_args_are_appended(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        argv = _build(get_backend(project), extra_args=["--foo", "bar"])
        assert "--foo" in argv
        assert argv[argv.index("--foo") + 1] == "bar"


# --- result parsing -------------------------------------------------------- #


class TestClaudeReadResult:
    def _backend(self, tmp_path, monkeypatch) -> Backend:
        return get_backend(_project(tmp_path, monkeypatch))

    def test_ignores_non_result_records(self, tmp_path, monkeypatch):
        backend = self._backend(tmp_path, monkeypatch)
        assert backend.read_result({"type": "assistant"}) is None

    def test_success(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "sess-1",
                "structured_output": {"value": 3},
            }
        )
        assert result == AgentResult(
            session_id="sess-1", structured_output={"value": 3}
        )

    def test_error_flag(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {"type": "result", "subtype": "success", "is_error": True}
        )
        assert result is not None
        assert result.is_error

    def test_non_success_subtype_is_an_error(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {"type": "result", "subtype": "error_max_turns", "is_error": False}
        )
        assert result is not None
        assert result.is_error


class TestAntigravityReadResult:
    def _backend(self, tmp_path, monkeypatch) -> Backend:
        return get_backend(_project(tmp_path, monkeypatch, backend="antigravity"))

    def test_ignores_non_result_events(self, tmp_path, monkeypatch):
        backend = self._backend(tmp_path, monkeypatch)
        assert backend.read_result({"event": "step_update"}) is None

    def test_success(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {
                "event": "result",
                "result": {
                    "conversation_id": "conv-1",
                    "status": "SUCCESS",
                    "structured_output": {"value": 3},
                },
            }
        )
        assert result == AgentResult(
            session_id="conv-1", structured_output={"value": 3}
        )

    def test_non_success_status_is_an_error(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {"event": "result", "result": {"status": "ERROR"}}
        )
        assert result is not None
        assert result.is_error

    def test_error_status_with_response_is_an_error(self, tmp_path, monkeypatch):
        result = self._backend(tmp_path, monkeypatch).read_result(
            {
                "event": "result",
                "result": {
                    "conversation_id": "conv-1",
                    "status": "ERROR",
                    "response": "An error occurred",
                    "error": "search path does not exist",
                },
            }
        )
        assert result is not None
        assert result.is_error
        assert result.error == "search path does not exist"


# --- the shared subprocess driver ------------------------------------------ #


class _StubBackend(Backend):
    """Backend whose "CLI" replays a canned JSONL stream (see `_stub_cli`)."""

    kind = "claude-code"
    executable = sys.executable
    install_hint = ""
    default_models: ClassVar[dict[AgentRole, str]] = {}
    effort_levels: ClassVar[tuple[str, ...]] = ()

    script: str = ""

    def build_command(
        self, *, prompt, model, effort, schema, readonly, tools, session_id, extra_args
    ):
        return [self.executable, self.script, prompt]

    def read_result(self, record):
        if record.get("type") != "result":
            return None
        return AgentResult(
            session_id=record.get("session_id"),
            structured_output=record.get("structured_output"),
            is_error=bool(record.get("is_error")),
            error=record.get("error"),
        )


def _stub_cli(
    tmp_path: Path,
    *,
    lines: list[str],
    code: int = 0,
    stderr: str = "",
    sleep_after: float = 0.0,
) -> str:
    """Write a stub CLI that prints `lines` to stdout and exits with `code`."""
    script = tmp_path / "stub_cli.py"
    script.write_text(
        "import sys, time\n"
        f"for line in {lines!r}:\n"
        "    print(line, flush=True)\n"
        f"if {sleep_after} > 0:\n"
        f"    time.sleep({sleep_after})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({code})\n"
    )
    return str(script)


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """A `_StubBackend` bound to a project rooted at a fresh tmp_path."""

    def _make(**kwargs) -> _StubBackend:
        backend = _StubBackend(_project(tmp_path, monkeypatch))
        backend.script = _stub_cli(tmp_path, **kwargs)
        return backend

    monkeypatch.setattr("ralpher.backend.base.Spinner", _NoSpinner)
    return _make


class _NoSpinner:
    """Stand-in for Spinner so tests don't touch the terminal."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


_RESULT = json.dumps(
    {"type": "result", "session_id": "s1", "structured_output": {"value": 7}}
)


class TestSpawn:
    @pytest.mark.asyncio
    async def test_returns_validated_structured_output(self, stub):
        backend = stub(lines=[json.dumps({"type": "assistant"}), _RESULT])
        assert await backend.run(role="verifier", prompt="go", schema=Out) == Out(
            value=7
        )

    @pytest.mark.asyncio
    async def test_returns_none_without_a_schema(self, stub):
        assert await stub(lines=[_RESULT]).run(role="worker", prompt="go") is None

    @pytest.mark.asyncio
    async def test_tees_the_stream_to_the_log(self, stub):
        backend = stub(lines=[_RESULT])
        await backend.run(role="worker", prompt="go")
        logs = list((backend.project.project_dir / "logs").glob("worker-*.log"))
        assert len(logs) == 1
        body = logs[0].read_text()
        # The initial prompt heads the log, the raw CLI stream follows.
        assert json.loads(body.splitlines()[0]) == {"initial_prompt": "go"}
        assert _RESULT in body

    @pytest.mark.asyncio
    async def test_log_records_the_command_without_the_prompt(self, stub):
        backend = stub(lines=[_RESULT])
        await backend.run(role="worker", prompt="go")
        log = next((backend.project.project_dir / "logs").glob("worker-*.log"))
        command = next(
            json.loads(line)["command"]
            for line in log.read_text().splitlines()
            if line.startswith('{"command"')
        )
        assert "go" not in command
        assert "<prompt>" in command

    @pytest.mark.asyncio
    async def test_ignores_non_json_output(self, stub):
        backend = stub(lines=["not json at all", _RESULT])
        assert await backend.run(role="verifier", prompt="go", schema=Out) == Out(
            value=7
        )

    @pytest.mark.asyncio
    async def test_non_zero_exit_fails(self, stub):
        backend = stub(lines=[_RESULT], code=2, stderr="boom")
        with pytest.raises(SystemExit, match="boom"):
            await backend.run(role="worker", prompt="go")

    @pytest.mark.asyncio
    async def test_missing_result_fails(self, stub):
        with pytest.raises(SystemExit, match="No result"):
            await stub(lines=[json.dumps({"type": "assistant"})]).run(
                role="worker", prompt="go"
            )

    @pytest.mark.asyncio
    async def test_error_result_fails(self, stub):
        line = json.dumps({"type": "result", "is_error": True, "error": "nope"})
        with pytest.raises(SystemExit, match="nope"):
            await stub(lines=[line]).run(role="worker", prompt="go")

    @pytest.mark.asyncio
    async def test_missing_structured_output_fails(self, stub):
        line = json.dumps({"type": "result", "session_id": "s1"})
        with pytest.raises(SystemExit, match="structured output"):
            await stub(lines=[line]).run(role="verifier", prompt="go", schema=Out)

    @pytest.mark.asyncio
    async def test_does_not_block_when_process_hangs_after_result(
        self, stub, monkeypatch
    ):
        monkeypatch.setattr("ralpher.backend.base.PROCESS_EXIT_TIMEOUT", 0.1)
        backend = stub(lines=[_RESULT], sleep_after=10.0)
        assert await backend.run(role="verifier", prompt="go", schema=Out) == Out(
            value=7
        )


_PLANNED_TASK = {
    "id": "T-001",
    "title": "Login",
    "description": "User can log in",
    "acceptance_criteria": ["AC1"],
}


def _plan_with_ids(*ids: str) -> Plan:
    return Plan(
        markdown="# Design",
        tasks=[
            PlannedTask(
                id=task_id,
                title="Login",
                description="User can log in",
                acceptance_criteria=["AC1"],
            )
            for task_id in ids
        ],
    )


class TestCheckTaskIds:
    def test_accepts_a_sequentially_numbered_list(self):
        assert check_task_ids(_plan_with_ids("T-001", "T-002", "T-003")) is None

    def test_accepts_an_empty_list(self):
        assert check_task_ids(_plan_with_ids()) is None

    def test_accepts_the_maximum_number_of_tasks(self):
        ids = [f"T-{n:03d}" for n in range(1, MAX_TASKS + 1)]
        assert check_task_ids(_plan_with_ids(*ids)) is None

    def test_rejects_ids_out_of_order(self):
        problem = check_task_ids(_plan_with_ids("T-002", "T-001"))
        assert problem is not None
        assert "task #1 has id `T-002`; it must be `T-001`." in problem
        assert "task #2 has id `T-001`; it must be `T-002`." in problem

    def test_rejects_a_gap_in_the_numbering(self):
        problem = check_task_ids(_plan_with_ids("T-001", "T-003"))
        assert problem is not None
        assert "task #2 has id `T-003`; it must be `T-002`." in problem

    def test_rejects_numbering_that_does_not_start_at_one(self):
        problem = check_task_ids(_plan_with_ids("T-002", "T-003"))
        assert problem is not None
        assert "task #1 has id `T-002`; it must be `T-001`." in problem

    @pytest.mark.parametrize("bad_id", ["T-1", "T-01", "T-0001", "1", "task-001"])
    def test_rejects_a_malformed_id(self, bad_id):
        assert check_task_ids(_plan_with_ids(bad_id)) is not None

    def test_rejects_more_than_the_maximum_number_of_tasks(self):
        ids = [f"T-{n:03d}" for n in range(1, MAX_TASKS + 2)]
        problem = check_task_ids(_plan_with_ids(*ids))
        assert problem is not None
        assert f"at most {MAX_TASKS}" in problem


class TestRunPlanMode:
    @pytest.mark.asyncio
    async def test_writes_design_md_and_tasks_toml(self, stub):
        plan = {"plan_or_questions": {"markdown": "# Design", "tasks": [_PLANNED_TASK]}}
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": plan})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)
        await backend.run_plan_mode(role="planner", prompt="go")
        assert backend.project.design_md.read_text() == "# Design"
        tasks = backend.project.load_tasks()
        assert tasks is not None
        assert [t.id for t in tasks.tasks] == ["T-001"]
        assert tasks.tasks[0].passed is False

    @pytest.mark.asyncio
    async def test_keeps_pass_state_of_surviving_tasks(self, stub):
        plan = {
            "plan_or_questions": {
                "markdown": "# Design",
                "tasks": [_PLANNED_TASK, {**_PLANNED_TASK, "id": "T-002"}],
            }
        }
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": plan})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)
        # A previous run already finished T-001; a refine must not undo that.
        backend.project.save_tasks(
            Tasks(
                tasks=[
                    Task(
                        id="T-001",
                        title="Login",
                        description="User can log in",
                        acceptance_criteria=["AC1"],
                        passed=True,
                    )
                ]
            )
        )
        await backend.run_plan_mode(role="planner", prompt="go")
        tasks = backend.project.load_tasks()
        assert tasks is not None
        assert [(t.id, t.passed) for t in tasks.tasks] == [
            ("T-001", True),
            ("T-002", False),
        ]

    @pytest.mark.asyncio
    async def test_rejected_plan_is_handed_back_for_correction(self, stub, monkeypatch):
        bad = {"plan_or_questions": {"markdown": "# Bad", "tasks": []}}
        good = {
            "plan_or_questions": {"markdown": "# Good", "tasks": [_PLANNED_TASK]},
        }
        backend = stub(lines=[json.dumps({"type": "result", "structured_output": bad})])
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        turns: list[str] = []
        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            turns.append(prompt)
            if len(turns) == 1:
                return await original(argv, prompt, log_file)
            return AgentResult(session_id="s1", structured_output=good)

        monkeypatch.setattr(backend, "_spawn", _spawn)
        await backend.run_plan_mode(
            role="refiner",
            prompt="go",
            validate=lambda plan: "restore the tasks" if not plan.tasks else None,
        )

        # The rejection message is the next turn's prompt, and only the plan
        # that finally validated is written out.
        assert turns == ["go", "restore the tasks"]
        assert backend.project.design_md.read_text() == "# Good"

    @pytest.mark.asyncio
    async def test_misnumbered_tasks_are_handed_back_without_a_validator(
        self, stub, monkeypatch
    ):
        misnumbered = {
            "plan_or_questions": {
                "markdown": "# Bad",
                "tasks": [{**_PLANNED_TASK, "id": "T-007"}],
            }
        }
        good = {"plan_or_questions": {"markdown": "# Good", "tasks": [_PLANNED_TASK]}}
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": misnumbered})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        turns: list[str] = []
        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            turns.append(prompt)
            if len(turns) == 1:
                return await original(argv, prompt, log_file)
            return AgentResult(session_id="s1", structured_output=good)

        monkeypatch.setattr(backend, "_spawn", _spawn)
        # The id invariant holds for every plan, so no `validate` is needed.
        await backend.run_plan_mode(role="planner", prompt="go")

        assert len(turns) == 2
        assert "must be `T-001`" in turns[1]
        assert backend.project.design_md.read_text() == "# Good"

    @pytest.mark.asyncio
    async def test_both_rejections_are_sent_together(self, stub, monkeypatch):
        misnumbered = {
            "plan_or_questions": {
                "markdown": "# Bad",
                "tasks": [{**_PLANNED_TASK, "id": "T-002"}],
            }
        }
        good = {"plan_or_questions": {"markdown": "# Good", "tasks": [_PLANNED_TASK]}}
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": misnumbered})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        turns: list[str] = []
        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            turns.append(prompt)
            if len(turns) == 1:
                return await original(argv, prompt, log_file)
            return AgentResult(session_id="s1", structured_output=good)

        monkeypatch.setattr(backend, "_spawn", _spawn)
        await backend.run_plan_mode(
            role="refiner",
            prompt="go",
            validate=lambda plan: (
                None
                if any(t.id == "T-001" for t in plan.tasks)
                else "and restore T-001"
            ),
        )

        # Fixing one complaint can break the other, so the agent sees both.
        assert "must be `T-001`" in turns[1]
        assert "and restore T-001" in turns[1]

    @pytest.mark.asyncio
    async def test_correction_turn_cannot_ask_questions(self, stub, monkeypatch):
        bad = {"plan_or_questions": {"markdown": "# Bad", "tasks": []}}
        good = {"plan_or_questions": {"markdown": "# Good", "tasks": [_PLANNED_TASK]}}
        backend = stub(lines=[json.dumps({"type": "result", "structured_output": bad})])
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        schemas: list[dict] = []
        build = backend.build_command

        def _build(**kwargs):
            schemas.append(kwargs["schema"])
            return build(**kwargs)

        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            if not schemas[:-1]:
                return await original(argv, prompt, log_file)
            return AgentResult(session_id="s1", structured_output=good)

        monkeypatch.setattr(backend, "build_command", _build)
        monkeypatch.setattr(backend, "_spawn", _spawn)
        await backend.run_plan_mode(
            role="refiner",
            prompt="go",
            validate=lambda plan: "restore the tasks" if not plan.tasks else None,
        )

        # The opening turn may ask the user; the correction turn may only
        # return a fixed plan.
        assert len(schemas) == 2
        assert {"Plan", "Questions"} <= set(schemas[0]["$defs"])
        assert "Plan" in schemas[1]["$defs"]
        assert "Questions" not in schemas[1]["$defs"]

    @pytest.mark.asyncio
    async def test_persistently_rejected_plan_fails(self, stub, monkeypatch):
        bad = {"plan_or_questions": {"markdown": "# Bad", "tasks": []}}
        backend = stub(lines=[json.dumps({"type": "result", "structured_output": bad})])
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        turns: list[str] = []
        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            turns.append(prompt)
            return await original(argv, prompt, log_file)

        monkeypatch.setattr(backend, "_spawn", _spawn)
        with pytest.raises(SystemExit, match="restore the tasks"):
            await backend.run_plan_mode(
                role="refiner", prompt="go", validate=lambda plan: "restore the tasks"
            )

        # The first turn plus MAX_PLAN_CORRECTIONS retries, and nothing written.
        assert len(turns) == 1 + MAX_PLAN_CORRECTIONS
        assert not backend.project.design_md.exists()

    @pytest.mark.asyncio
    async def test_asks_questions_then_resumes(self, stub, monkeypatch):
        questions = {
            "plan_or_questions": {
                "questions": [
                    {
                        "header": "Scope",
                        "question": "How big?",
                        "options": [{"label": "small", "description": "a little"}],
                    }
                ]
            }
        }
        plan = {"plan_or_questions": {"markdown": "# Design", "tasks": [_PLANNED_TASK]}}
        # Turn 1 asks, turn 2 (after answers) returns the plan.
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": questions})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)

        turns: list[str] = []

        async def _answer(qs):
            return "answers"

        monkeypatch.setattr("ralpher.backend.base.ask_user_questions", _answer)

        original = backend._spawn

        async def _spawn(argv, prompt, log_file):
            turns.append(prompt)
            if len(turns) == 1:
                return await original(argv, prompt, log_file)
            return AgentResult(session_id="s1", structured_output=plan)

        monkeypatch.setattr(backend, "_spawn", _spawn)
        await backend.run_plan_mode(role="planner", prompt="go")

        assert turns == ["go", "answers"]
        assert backend.project.design_md.read_text() == "# Design"
