import json
from pathlib import Path
from unittest.mock import AsyncMock, patch


import pytest

from ralpher.prd.prd import _ask_user_questions, _parse_result, generate_prd, load_prd_prompt
from ralpher.prd.extract import extract_prd_json


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "ralpher" / "prompts" / "prd.md"


class TestLoadPrdPrompt:
    @pytest.fixture(autouse=True)
    def _patch_prompts_dir(self, monkeypatch):
        monkeypatch.setattr(
            "ralpher.prd.prd.PROMPTS_DIR", TEMPLATE_PATH.parent,
        )

    def test_renders_user_input(self):
        result = load_prd_prompt("Build a todo app")
        assert "Build a todo app" in result

    def test_strips_frontmatter(self):
        result = load_prd_prompt("anything")
        assert "Copied from" not in result

    def test_preserves_template_structure(self):
        result = load_prd_prompt("my feature")
        assert "## The Job" in result
        assert "## Step 1: Clarifying Questions" in result
        assert "## Step 2: PRD Structure" in result

    def test_user_input_in_correct_section(self):
        result = load_prd_prompt("Add dark mode support")
        lines = result.split("\n")
        feature_idx = next(i for i, l in enumerate(lines) if "User Provided Feature Description" in l)
        input_idx = next(i for i, l in enumerate(lines) if "Add dark mode support" in l)
        assert input_idx > feature_idx

    def test_interactive_passed_to_template(self):
        result_interactive = load_prd_prompt("test", interactive=True)
        result_non_interactive = load_prd_prompt("test", interactive=False)
        assert isinstance(result_interactive, str)
        assert isinstance(result_non_interactive, str)


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


class TestAskUserQuestions:
    @patch("ralpher.prd.prd.Prompt.ask", return_value="REST")
    def test_single_question(self, mock_ask):
        questions = [{"question": "API style", "description": "What kind of API do you want?"}]
        result = _ask_user_questions(questions)
        assert "API style: REST" in result
        mock_ask.assert_called_once()

    @patch("ralpher.prd.prd.Prompt.ask", side_effect=["Yes", "Mobile"])
    def test_multiple_questions(self, mock_ask):
        questions = [
            {"question": "Auth needed?", "description": "Should the app require login?"},
            {"question": "Platform", "description": ""},
        ]
        result = _ask_user_questions(questions)
        assert "Auth needed?: Yes" in result
        assert "Platform: Mobile" in result

    @patch("ralpher.prd.prd.Prompt.ask", return_value="B")
    def test_question_with_options(self, mock_ask):
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
        result = _ask_user_questions(questions)
        assert "Pick a pattern: B" in result


def _make_mock_process(returncode: int, stdout_json: dict | None = None) -> AsyncMock:
    proc = AsyncMock()
    proc.wait.return_value = None
    proc.returncode = returncode

    stdout_bytes = json.dumps(stdout_json or {}).encode()
    proc.stdout.read.return_value = stdout_bytes
    proc.stderr.read.return_value = b""
    return proc


class TestGeneratePrd:
    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_exec.return_value = _make_mock_process(
            0, {"session_id": "s1", "result": "done"},
        )
        # Pre-create PRD.md so generate_prd doesn't raise
        def create_prd_side_effect(*args, **kwargs):
            import glob as _g
            tasks = list((tmp_path / ".ralpher" / "tasks").iterdir())
            if tasks:
                (tasks[0] / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1", "result": "done"})

        mock_exec.side_effect = create_prd_side_effect
        result = await generate_prd("Build a chat app")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_exec.return_value = _make_mock_process(1)
        with pytest.raises(SystemExit):
            await generate_prd("test")

    @patch("ralpher.prd.prd.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_command_flags(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def side_effect(*args, **kwargs):
            tasks = list((tmp_path / ".ralpher" / "tasks").iterdir())
            if tasks:
                (tasks[0] / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1"})

        mock_exec.side_effect = side_effect
        await generate_prd("Implement SSO login")
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

        def side_effect(*args, **kwargs):
            tasks = list((tmp_path / ".ralpher" / "tasks").iterdir())
            if tasks:
                (tasks[0] / "PRD.md").write_text("# PRD")
            return _make_mock_process(0, {"session_id": "s1"})

        mock_exec.side_effect = side_effect
        task_id = await generate_prd("My feature request")
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
                tasks = list((tmp_path / ".ralpher" / "tasks").iterdir())
                if tasks:
                    (tasks[0] / "PRD.md").write_text("# PRD")
                return _make_mock_process(0, {"session_id": "sess-interactive"})

        mock_exec.side_effect = side_effect
        result = await generate_prd("Build feature")
        assert isinstance(result, str)
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
            await generate_prd("test")


class TestExtractPrdJson:
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
        (task_dir / "prd.json").write_text('{"title": "Test"}')

        mock_exec.return_value = _make_mock_process(0, {})
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
    async def test_raises_on_nonzero_exit(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_exec.return_value = _make_mock_process(1)
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task")

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_raises_when_prd_json_not_created(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_exec.return_value = _make_mock_process(0, {})
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task")

    @patch("ralpher.prd.extract.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_prompt_includes_task_id(self, mock_exec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "my-task-123"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# PRD")
        (task_dir / "prd.json").write_text("{}")

        mock_exec.return_value = _make_mock_process(0, {})
        await extract_prd_json("my-task-123")

        call_args = mock_exec.call_args[0]
        prompt_arg = call_args[-1]
        assert "my-task-123" in prompt_arg
