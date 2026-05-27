import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from google.antigravity.hooks.policy import Decision
from google.antigravity.types import BuiltinTools, ThinkingLevel, ToolCall

from ralpher.models import Project
from ralpher.backend import antigravity
from ralpher.backend.antigravity import (
    _build_config,
    run_antigravity,
    run_antigravity_plan_mode,
)


class Out(BaseModel):
    value: int


# --- Test doubles for the antigravity SDK --------------------------------- #


class _FakeResponse:
    def __init__(self, *, chunks=None, structured=None):
        self._chunks = chunks or []
        self._structured = structured

    @property
    def chunks(self):
        chunks = self._chunks

        async def _gen():
            for c in chunks:
                yield c

        return _gen()

    async def structured_output(self):
        return self._structured


class _NoSpinner:
    """Stand-in for Spinner so tests don't touch the terminal."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install_fake_agent(responses):
    """Patch ``antigravity.Agent`` with a fake that hands out ``responses`` in
    order, recording the configs it was built with and the prompts it saw."""
    record = {"configs": [], "prompts": []}
    queue = list(responses)

    class _FakeAgent:
        def __init__(self, config):
            record["configs"].append(config)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def chat(self, prompt):
            record["prompts"].append(prompt)
            return queue.pop(0)

    return _FakeAgent, record


def _project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Project(id="proj", backend="antigravity")


# --- _build_config -------------------------------------------------------- #


class TestBuildConfig:
    def test_model_and_schema_passed_through(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config(model="gemini-3-pro", schema=Out)
        # Without a thinking level the simple `model` shorthand carries the name.
        assert cfg.model == "gemini-3-pro"
        # The SDK normalizes a pydantic class into its JSON-schema string.
        assert json.loads(cfg.response_schema) == Out.model_json_schema()

    def test_thinking_level_rides_on_gemini_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config(model="gemini-3.1-pro-preview", thinking_level="high")
        # The shorthand is left unset; the model rides on gemini_config so the
        # thinking level travels with it (the SDK forbids setting both).
        assert cfg.model is None
        entry = cfg.gemini_config.models.default
        assert entry.name == "gemini-3.1-pro-preview"
        assert entry.generation.thinking_level == ThinkingLevel.HIGH

    def test_workspace_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config()
        assert cfg.workspaces == [str(tmp_path.resolve())]

    def test_ralpher_write_tools_denied_by_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config()
        ralpher_policies = [p for p in cfg.policies if p.name == "ralpher_readonly"]
        tools = {p.tool for p in ralpher_policies}
        assert tools == {BuiltinTools.CREATE_FILE.value, BuiltinTools.EDIT_FILE.value}
        assert all(p.decision == Decision.DENY for p in ralpher_policies)
        # Not read-only: no blanket deny_all.
        assert not any(p.tool == "*" for p in cfg.policies)

    def test_ralpher_predicate_denies_inside_allows_outside(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config()
        deny = next(p for p in cfg.policies if p.name == "ralpher_readonly")
        inside = ToolCall(
            name="edit_file",
            canonical_path=str(tmp_path / ".ralpher" / "projects" / "p" / "tasks.json"),
        )
        outside = ToolCall(name="edit_file", canonical_path=str(tmp_path / "src.py"))
        no_path = ToolCall(name="edit_file")
        assert deny.when(inside) is True
        assert deny.when(outside) is False
        assert deny.when(no_path) is False

    def test_readonly_adds_deny_all_and_read_only_allows(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _build_config(readonly=True)
        assert any(p.tool == "*" and p.decision == Decision.DENY for p in cfg.policies)
        allowed = {p.tool for p in cfg.policies if p.decision == Decision.APPROVE}
        assert allowed == {t.value for t in BuiltinTools.read_only()}
        # The .ralpher write guard is still present alongside the read-only set.
        assert any(p.name == "ralpher_readonly" for p in cfg.policies)


# --- run_antigravity ------------------------------------------------------ #


class TestRunAntigravity:
    @pytest.mark.asyncio
    async def test_returns_validated_schema(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, record = _install_fake_agent(
            [_FakeResponse(structured={"value": 7})]
        )
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            result = await run_antigravity(
                kind="verify", prompt="check it", project=project, schema=Out
            )
        assert result == Out(value=7)
        assert record["prompts"] == ["check it"]

    @pytest.mark.asyncio
    async def test_fails_when_structured_missing(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, _ = _install_fake_agent([_FakeResponse(structured=None)])
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            with pytest.raises(SystemExit):
                await run_antigravity(
                    kind="verify", prompt="x", project=project, schema=Out
                )

    @pytest.mark.asyncio
    async def test_returns_none_without_schema(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, _ = _install_fake_agent([_FakeResponse()])
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            result = await run_antigravity(kind="loop", prompt="do it", project=project)
        assert result is None

    @pytest.mark.asyncio
    async def test_writes_log_file(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, _ = _install_fake_agent([_FakeResponse(structured={"value": 1})])
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            await run_antigravity(
                kind="verify", prompt="hello", project=project, schema=Out
            )
        logs = list((project.project_dir / "logs").glob("verify-*.log"))
        assert logs and "hello" in logs[0].read_text()

    @pytest.mark.asyncio
    async def test_applies_kind_default_model_and_thinking(self, tmp_path, monkeypatch):
        # End to end: with no settings.json, the kind's defaults from
        # ANTIGRAVITY_DEFAULT_MODELS reach the LocalAgentConfig the Agent sees.
        project = _project(tmp_path, monkeypatch)
        FakeAgent, record = _install_fake_agent(
            [_FakeResponse(structured={"value": 1})]
        )
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            await run_antigravity(
                kind="verify", prompt="x", project=project, schema=Out
            )
        entry = record["configs"][0].gemini_config.models.default
        assert entry.name == "gemini-3.5-flash"
        assert entry.generation.thinking_level == ThinkingLevel.HIGH


# --- dispatch: run_agent selects the backend by project.backend ----------- #


class TestDispatch:
    @pytest.mark.asyncio
    async def test_run_agent_dispatches_to_antigravity(self, tmp_path, monkeypatch):
        from ralpher.backend import run_agent

        project = _project(tmp_path, monkeypatch)  # backend = antigravity
        with patch.object(
            antigravity, "run_antigravity", new_callable=AsyncMock
        ) as mock_ag:
            mock_ag.return_value = Out(value=3)
            result = await run_agent(
                kind="verify", prompt="p", project=project, schema=Out
            )
        assert result == Out(value=3)
        mock_ag.assert_awaited_once()
        kwargs = mock_ag.call_args.kwargs
        assert kwargs["kind"] == "verify"
        assert kwargs["prompt"] == "p"
        assert kwargs["schema"] is Out
        assert kwargs["project"] is project

    @pytest.mark.asyncio
    async def test_run_agent_dispatches_to_claude_by_default(
        self, tmp_path, monkeypatch
    ):
        from ralpher.backend import claude as claude_mod
        from ralpher.backend import run_agent

        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")  # default backend = claude-code

        with (
            patch.object(antigravity, "run_antigravity", new_callable=AsyncMock) as mag,
            patch.object(claude_mod, "run_claude", new_callable=AsyncMock) as mcc,
        ):
            mcc.return_value = None
            result = await run_agent(kind="loop", prompt="p", project=project)
        assert result is None
        mag.assert_not_awaited()
        mcc.assert_awaited_once()
        assert mcc.call_args.kwargs["project"] is project

    @pytest.mark.asyncio
    async def test_plan_mode_dispatches_to_antigravity(self, tmp_path, monkeypatch):
        from ralpher.backend import run_agent_plan_mode

        project = _project(tmp_path, monkeypatch)
        with patch.object(
            antigravity, "run_antigravity_plan_mode", new_callable=AsyncMock
        ) as mock_ag:
            await run_agent_plan_mode(kind="plan", prompt="p", project=project)
        mock_ag.assert_awaited_once()
        assert mock_ag.call_args.kwargs["project"] is project

    @pytest.mark.asyncio
    async def test_plan_mode_dispatches_to_claude_by_default(
        self, tmp_path, monkeypatch
    ):
        from ralpher.backend import claude as claude_mod
        from ralpher.backend import run_agent_plan_mode

        monkeypatch.chdir(tmp_path)
        project = Project(id="proj")  # default backend = claude-code
        with patch.object(
            claude_mod, "run_claude_plan_mode", new_callable=AsyncMock
        ) as mcc:
            await run_agent_plan_mode(kind="plan", prompt="p", project=project)
        mcc.assert_awaited_once()
        assert mcc.call_args.kwargs["project"] is project


# --- run_antigravity_plan_mode -------------------------------------------- #


def _plan_response(markdown: str) -> _FakeResponse:
    return _FakeResponse(structured={"plan_or_questions": {"markdown": markdown}})


def _questions_response() -> _FakeResponse:
    return _FakeResponse(
        structured={
            "plan_or_questions": {
                "questions": [
                    {
                        "header": "Auth",
                        "question": "Need auth?",
                        "options": [{"label": "Yes", "description": "require login"}],
                    }
                ]
            }
        }
    )


class TestPlanMode:
    @pytest.mark.asyncio
    async def test_writes_plan_when_plan_returned(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, record = _install_fake_agent([_plan_response("# The Plan")])
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            await run_antigravity_plan_mode(
                kind="plan", prompt="build", project=project
            )
        assert project.plan_md.read_text() == "# The Plan"
        assert record["prompts"] == ["build"]

    @pytest.mark.asyncio
    async def test_loops_on_questions_then_plan(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, record = _install_fake_agent(
            [_questions_response(), _plan_response("# Final")]
        )
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
            patch.object(
                antigravity,
                "ask_user_questions",
                new_callable=AsyncMock,
            ) as mock_ask,
        ):
            mock_ask.return_value = '[{"Q": "Need auth?", "A": "Yes"}]'
            await run_antigravity_plan_mode(
                kind="plan", prompt="build", project=project
            )
        assert project.plan_md.read_text() == "# Final"
        mock_ask.assert_awaited_once()
        # Two model turns: the first asked questions, the second produced the plan.
        assert len(record["prompts"]) == 2
        assert record["prompts"][1] == '[{"Q": "Need auth?", "A": "Yes"}]'

    @pytest.mark.asyncio
    async def test_fails_when_structured_missing(self, tmp_path, monkeypatch):
        project = _project(tmp_path, monkeypatch)
        FakeAgent, _ = _install_fake_agent([_FakeResponse(structured=None)])
        with (
            patch.object(antigravity, "Agent", FakeAgent),
            patch.object(antigravity, "Spinner", _NoSpinner),
        ):
            with pytest.raises(SystemExit):
                await run_antigravity_plan_mode(
                    kind="plan", prompt="build", project=project
                )
