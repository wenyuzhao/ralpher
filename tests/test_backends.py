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
from ralpher.backend.base import AgentResult, Backend
from ralpher.backend.claude import READONLY_TOOLS, ClaudeBackend
from ralpher.models import Project


class Out(BaseModel):
    value: int


def _project(tmp_path, monkeypatch, **kwargs) -> Project:
    monkeypatch.chdir(tmp_path)
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
    """Each backend owns its own per-kind defaults and effort vocabulary."""

    def test_claude_defaults(self, tmp_path, monkeypatch):
        backend = get_backend(_project(tmp_path, monkeypatch))
        assert backend._resolve_model("plan", None) == ("opus", None)
        assert backend._resolve_model("verify", None) == ("sonnet", None)
        assert backend._resolve_model("extract-tasks", None) == ("sonnet", None)

    def test_antigravity_defaults(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch, backend="antigravity")
        backend = get_backend(project)
        assert backend._resolve_model("plan", None) == ("gemini-3.7-flash", "high")
        assert backend._resolve_model("verify", None) == ("gemini-3.7-flash", "high")
        assert backend._resolve_model("extract-tasks", None) == (
            "gemini-3.7-flash",
            "medium",
        )

    def test_every_kind_has_a_default_on_both_backends(self):
        kinds = {"plan", "refine", "loop", "verify", "extract-tasks"}
        for cls in BACKENDS.values():
            assert kinds <= set(cls.default_models)

    def test_defaults_do_not_leak_across_backends(self):
        assert ClaudeBackend.default_models != AntigravityBackend.default_models

    def test_unknown_kind_has_no_default(self, tmp_path, monkeypatch):
        backend = get_backend(_project(tmp_path, monkeypatch))
        assert backend._resolve_model("nope", None) == (None, None)

    def test_explicit_model_wins(self, tmp_path, monkeypatch):
        backend = get_backend(_project(tmp_path, monkeypatch))
        assert backend._resolve_model("plan", "haiku:low") == ("haiku", "low")

    def test_settings_pin_beats_the_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(
            json.dumps({"models": {"plan": "some-model:medium"}})
        )
        # The pin applies whichever backend is active.
        for kind in ("claude-code", "antigravity"):
            backend = get_backend(Project(id="proj", backend=kind))
            assert backend._resolve_model("plan", None) == ("some-model", "medium")

    def test_bare_pin_leaves_effort_to_the_cli(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.json").write_text(
            json.dumps({"models": {"plan": "some-model"}})
        )
        backend = get_backend(Project(id="proj"))
        assert backend._resolve_model("plan", None) == ("some-model", None)


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


# --- the shared subprocess driver ------------------------------------------ #


class _StubBackend(Backend):
    """Backend whose "CLI" replays a canned JSONL stream (see `_stub_cli`)."""

    kind = "claude-code"
    executable = sys.executable
    install_hint = ""
    default_models: ClassVar[dict[str, str]] = {}
    effort_levels: ClassVar[tuple[str, ...]] = ()

    script: str = ""

    def build_command(
        self, *, prompt, model, effort, schema, readonly, tools, session_id
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
    tmp_path: Path, *, lines: list[str], code: int = 0, stderr: str = ""
) -> str:
    """Write a stub CLI that prints `lines` to stdout and exits with `code`."""
    script = tmp_path / "stub_cli.py"
    script.write_text(
        "import sys\n"
        f"for line in {lines!r}:\n"
        "    print(line, flush=True)\n"
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
        assert await backend.run(kind="verify", prompt="go", schema=Out) == Out(value=7)

    @pytest.mark.asyncio
    async def test_returns_none_without_a_schema(self, stub):
        assert await stub(lines=[_RESULT]).run(kind="loop", prompt="go") is None

    @pytest.mark.asyncio
    async def test_tees_the_stream_to_the_log(self, stub):
        backend = stub(lines=[_RESULT])
        await backend.run(kind="loop", prompt="go")
        logs = list((backend.project.project_dir / "logs").glob("loop-*.log"))
        assert len(logs) == 1
        body = logs[0].read_text()
        # The initial prompt heads the log, the raw CLI stream follows.
        assert json.loads(body.splitlines()[0]) == {"initial_prompt": "go"}
        assert _RESULT in body

    @pytest.mark.asyncio
    async def test_log_records_the_command_without_the_prompt(self, stub):
        backend = stub(lines=[_RESULT])
        await backend.run(kind="loop", prompt="go")
        log = next((backend.project.project_dir / "logs").glob("loop-*.log"))
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
        assert await backend.run(kind="verify", prompt="go", schema=Out) == Out(value=7)

    @pytest.mark.asyncio
    async def test_non_zero_exit_fails(self, stub):
        backend = stub(lines=[_RESULT], code=2, stderr="boom")
        with pytest.raises(SystemExit, match="boom"):
            await backend.run(kind="loop", prompt="go")

    @pytest.mark.asyncio
    async def test_missing_result_fails(self, stub):
        with pytest.raises(SystemExit, match="No result"):
            await stub(lines=[json.dumps({"type": "assistant"})]).run(
                kind="loop", prompt="go"
            )

    @pytest.mark.asyncio
    async def test_error_result_fails(self, stub):
        line = json.dumps({"type": "result", "is_error": True, "error": "nope"})
        with pytest.raises(SystemExit, match="nope"):
            await stub(lines=[line]).run(kind="loop", prompt="go")

    @pytest.mark.asyncio
    async def test_missing_structured_output_fails(self, stub):
        line = json.dumps({"type": "result", "session_id": "s1"})
        with pytest.raises(SystemExit, match="structured output"):
            await stub(lines=[line]).run(kind="verify", prompt="go", schema=Out)


class TestRunPlanMode:
    @pytest.mark.asyncio
    async def test_writes_plan_md(self, stub):
        plan = {"plan_or_questions": {"markdown": "# Plan"}}
        backend = stub(
            lines=[json.dumps({"type": "result", "structured_output": plan})]
        )
        backend.project.project_dir.mkdir(parents=True, exist_ok=True)
        await backend.run_plan_mode(kind="plan", prompt="go")
        assert backend.project.plan_md.read_text() == "# Plan"

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
        plan = {"plan_or_questions": {"markdown": "# Plan"}}
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
        await backend.run_plan_mode(kind="plan", prompt="go")

        assert turns == ["go", "answers"]
        assert backend.project.plan_md.read_text() == "# Plan"
