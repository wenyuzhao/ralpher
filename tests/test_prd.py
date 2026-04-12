import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.prd.prd import _ask_user_questions, _parse_result, generate_prd
from ralpher.prd.extract import extract_prd_json


class TestParseResult:
    def test_extracts_session_id(self):
        data = {"session_id": "sess-123", "result": "done"}
        questions, session_id = _parse_result(data)
        assert session_id == "sess-123"
        assert questions is None

    def test_detects_ask_user_question_in_permission_denials(self):
        data = {
            "session_id": "sess-abc",
            "permission_denials": [
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [
                            {"label": "What is the goal?", "description": "Describe the primary objective"}
                        ]
                    },
                }
            ],
        }
        questions, session_id = _parse_result(data)
        assert session_id == "sess-abc"
        assert questions is not None
        assert len(questions) == 1
        assert questions[0]["label"] == "What is the goal?"

    def test_ignores_other_tool_denials(self):
        data = {
            "session_id": "sess-x",
            "permission_denials": [
                {"tool_name": "Write", "tool_input": {"path": "foo.txt"}},
            ],
        }
        questions, _ = _parse_result(data)
        assert questions is None

    def test_handles_empty_data(self):
        questions, session_id = _parse_result({})
        assert questions is None
        assert session_id is None

    def test_multiple_questions_in_single_denial(self):
        data = {
            "session_id": "sess-multi",
            "permission_denials": [
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [
                            {"label": "Q1", "description": "First"},
                            {"label": "Q2", "description": "Second"},
                        ]
                    },
                }
            ],
        }
        questions, _session_id = _parse_result(data)
        assert questions is not None
        assert len(questions) == 2

    def test_no_permission_denials_key(self):
        data = {"session_id": "sess-no-denials"}
        questions, session_id = _parse_result(data)
        assert questions is None
        assert session_id == "sess-no-denials"


class TestAskUserQuestions:
    @pytest.mark.asyncio
    @patch("ralpher.prd.prd.ChoiceInput")
    async def test_single_question_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="REST")
        questions = [
            {
                "header": "API",
                "question": "API style",
                "options": [
                    {"label": "REST", "description": "RESTful API"},
                    {"label": "GraphQL", "description": "GraphQL API"},
                ],
            }
        ]
        result = await _ask_user_questions(questions)
        assert "API style: REST" in result

    @pytest.mark.asyncio
    @patch("ralpher.prd.prd.ChoiceInput")
    async def test_multiple_questions_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(side_effect=["Yes", "Mobile"])
        questions = [
            {
                "header": "Auth",
                "question": "Auth needed?",
                "options": [
                    {"label": "Yes", "description": "Require login"},
                    {"label": "No", "description": "No auth"},
                ],
            },
            {
                "header": "Platform",
                "question": "Platform",
                "options": [
                    {"label": "Mobile", "description": "Mobile app"},
                    {"label": "Web", "description": "Web app"},
                ],
            },
        ]
        result = await _ask_user_questions(questions)
        assert "Auth needed?: Yes" in result
        assert "Platform: Mobile" in result

    @pytest.mark.asyncio
    @patch("ralpher.prd.prd.ChoiceInput")
    async def test_question_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="Monolith")
        questions = [
            {
                "header": "Architecture",
                "question": "Pick a pattern",
                "options": [
                    {"label": "Monolith", "description": "Single deployable"},
                    {"label": "Microservices", "description": "Distributed"},
                ],
            }
        ]
        result = await _ask_user_questions(questions)
        assert "Pick a pattern: Monolith" in result

    @pytest.mark.asyncio
    async def test_skips_questions_without_options(self):
        questions = [
            {"question": "No options here", "description": "Should be skipped"},
        ]
        result = await _ask_user_questions(questions)
        assert result == ""

    @pytest.mark.asyncio
    @patch("ralpher.prd.prd.PromptSession")
    @patch("ralpher.prd.prd.ChoiceInput")
    async def test_other_option_prompts_freeform(self, mock_choice_cls, mock_session_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="__other__")
        mock_session_cls.return_value.prompt_async = AsyncMock(return_value="Custom answer")
        questions = [
            {
                "header": "Style",
                "question": "Pick style",
                "options": [
                    {"label": "A", "description": "Option A"},
                ],
            }
        ]
        result = await _ask_user_questions(questions)
        assert "Pick style: Custom answer" in result


def _make_mock_process(returncode: int, stdout_json: dict | None = None) -> AsyncMock:
    proc = AsyncMock()
    proc.wait.return_value = None
    proc.returncode = returncode

    stdout_bytes = json.dumps(stdout_json or {}).encode()
    proc.stdout.read.return_value = stdout_bytes
    proc.stderr.read.return_value = b""
    return proc


class TestGeneratePrd:
    @pytest.fixture(autouse=True)
    def _patch_spinner(self, monkeypatch):
        """Mock Spinner so tests don't need yaspin."""
        mock_spinner = MagicMock()
        mock_spinner.__aenter__ = AsyncMock(return_value=mock_spinner)
        mock_spinner.__aexit__ = AsyncMock(return_value=False)
        mock_spinner.run = AsyncMock()
        monkeypatch.setattr(
            "ralpher.prd.prd.Spinner", lambda: mock_spinner,
        )

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "test-task-1"

        def create_prd_side_effect(*args, **kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1", "result": "done"})

        mock_exec.side_effect = create_prd_side_effect
        result = await generate_prd(task_id, "Build a chat app")
        assert result == task_id

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_exec.return_value = _make_mock_process(1)
        with pytest.raises(SystemExit):
            await generate_prd("task-fail", "test")

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_command_flags(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "task-flags"

        def side_effect(*args, **kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1"})

        mock_exec.side_effect = side_effect
        await generate_prd(task_id, "Implement SSO login")
        call_args = mock_exec.call_args[0]
        assert "--output-format" in call_args
        assert "json" in call_args
        assert "--dangerously-skip-permissions" in call_args
        assert "--permission-mode" in call_args
        assert "dontAsk" in call_args
        assert "--plugin-dir" in call_args
        assert "--print" in call_args

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_creates_task_directory_and_prompt(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "task-dir-test"

        def side_effect(*args, **kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1"})

        mock_exec.side_effect = side_effect
        result = await generate_prd(task_id, "My feature request")
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        assert task_dir.exists()
        assert (task_dir / "PROMPT.md").read_text() == "My feature request"

    @patch("ralpher.prd.prd._ask_user_questions", return_value="Q1: A")
    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_intercepts_ask_user_question_and_resumes(
        self, mock_exec, mock_ask, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "task-interactive"
        ask_result = {
            "session_id": "sess-interactive",
            "permission_denials": [
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [{"label": "Goal?", "description": "What is the primary goal?"}]
                    },
                }
            ],
        }

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_process(0, ask_result)
            else:
                (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")
                return _make_mock_process(0, {"session_id": "sess-interactive"})

        mock_exec.side_effect = side_effect
        result = await generate_prd(task_id, "Build feature")
        assert result == task_id
        assert mock_exec.call_count == 2

        second_call_args = mock_exec.call_args_list[1][0]
        assert "--resume" in second_call_args
        assert "sess-interactive" in second_call_args
        assert "--print" in second_call_args

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_when_prd_not_created(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_exec.return_value = _make_mock_process(0, {"session_id": "s1"})
        with pytest.raises(SystemExit):
            await generate_prd("task-no-prd", "test")

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_prompt_uses_prd_skill_with_task_id(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "task-skill-check"

        def side_effect(*args, **kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1"})

        mock_exec.side_effect = side_effect
        await generate_prd(task_id, "Some feature")
        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[-1]
        assert f"/ralpher:prd {task_id}" == prompt_arg


class TestExtractPrdJson:
    @pytest.fixture(autouse=True)
    def _patch_spinner(self, monkeypatch):
        """Mock Spinner so tests don't need yaspin."""
        mock_spinner = MagicMock()
        mock_spinner.__aenter__ = AsyncMock(return_value=mock_spinner)
        mock_spinner.__aexit__ = AsyncMock(return_value=False)
        mock_spinner.run = AsyncMock()
        monkeypatch.setattr(
            "ralpher.prd.extract.Spinner", lambda: mock_spinner,
        )

    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await extract_prd_json("nonexistent-task")

    @pytest.mark.asyncio
    async def test_raises_when_prd_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task")

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_returns_on_success(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        valid_prd = json.dumps({
            "project": "Test",
            "branch_name": "test-branch",
            "description": "A test",
            "user_stories": [],
        })

        def side_effect(*args, **kwargs):
            (task_dir / "prd.json").write_text(valid_prd)
            return _make_mock_process(0, {})

        mock_exec.side_effect = side_effect
        await extract_prd_json("test-task")

        call_args = mock_exec.call_args[0]
        assert "--output-format" in call_args
        assert "json" in call_args
        assert "--dangerously-skip-permissions" in call_args
        assert "--permission-mode" in call_args
        assert "dontAsk" in call_args
        assert "--model" in call_args
        assert "haiku" in call_args
        assert "--print" in call_args

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_on_all_retries_failed(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_exec.return_value = _make_mock_process(1)
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task", retries=1)

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_when_prd_json_not_created(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_exec.return_value = _make_mock_process(0, {})
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task", retries=1)

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_prompt_includes_task_id(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "my-task-123"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        valid_prd = json.dumps({
            "project": "Test",
            "branch_name": "test-branch",
            "description": "A test",
            "user_stories": [],
        })

        def side_effect(*args, **kwargs):
            (task_dir / "prd.json").write_text(valid_prd)
            return _make_mock_process(0, {})

        mock_exec.side_effect = side_effect
        await extract_prd_json("my-task-123")

        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[-1]
        assert "my-task-123" in prompt_arg

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_retries_on_invalid_prd_json(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "retry-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        valid_prd = json.dumps({
            "project": "Test",
            "branch_name": "test-branch",
            "description": "A test",
            "user_stories": [],
        })

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt: write invalid JSON
                (task_dir / "prd.json").write_text('{"invalid": true}')
            else:
                # Second attempt: write valid PRD JSON
                (task_dir / "prd.json").write_text(valid_prd)
            return _make_mock_process(0, {})

        mock_exec.side_effect = side_effect
        await extract_prd_json("retry-task", retries=3)
        assert mock_exec.call_count == 2

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_retries_on_nonzero_exit_then_succeeds(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "retry-exit"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")

        valid_prd = json.dumps({
            "project": "Test",
            "branch_name": "test-branch",
            "description": "A test",
            "user_stories": [],
        })

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_process(1)
            else:
                (task_dir / "prd.json").write_text(valid_prd)
                return _make_mock_process(0, {})

        mock_exec.side_effect = side_effect
        await extract_prd_json("retry-exit", retries=3)
        assert mock_exec.call_count == 2
