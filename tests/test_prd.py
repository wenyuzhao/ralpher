import json
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.prd.prd import _ask_user_questions, _parse_result, generate_prd, load_prd_prompt


class TestLoadPrdPrompt:
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
    @patch("ralpher.prd.Prompt.ask", return_value="REST")
    def test_single_question(self, mock_ask):
        questions = [{"label": "API style", "description": "What kind of API do you want?"}]
        result = _ask_user_questions(questions)
        assert "API style: REST" in result
        mock_ask.assert_called_once()

    @patch("ralpher.prd.Prompt.ask", side_effect=["Yes", "Mobile"])
    def test_multiple_questions(self, mock_ask):
        questions = [
            {"label": "Auth needed?", "description": "Should the app require login?"},
            {"label": "Platform", "description": ""},
        ]
        result = _ask_user_questions(questions)
        assert "Auth needed?: Yes" in result
        assert "Platform: Mobile" in result


def _make_mock_process(returncode: int, stdout_json: dict | None = None) -> AsyncMock:
    proc = AsyncMock()
    proc.wait.return_value = None
    proc.returncode = returncode

    stdout_bytes = json.dumps(stdout_json or {}).encode()
    proc.stdout.read.return_value = stdout_bytes
    proc.stderr.read.return_value = b""
    return proc


class TestGeneratePrd:
    @patch("ralpher.prd.shutil.which", return_value=None)
    @pytest.mark.asyncio
    async def test_raises_when_claude_not_found(self, mock_which):
        with pytest.raises(RuntimeError, match="claude CLI not found"):
            await generate_prd("test")

    @patch("ralpher.prd.asyncio.create_subprocess_exec")
    @patch("ralpher.prd.shutil.which", return_value="/usr/bin/claude")
    @pytest.mark.asyncio
    async def test_returns_zero_on_success(self, mock_which, mock_exec):
        mock_exec.return_value = _make_mock_process(
            0, {"session_id": "s1", "result": "done"},
        )
        result = await generate_prd("Build a chat app")
        assert result == 0
        call_args = mock_exec.call_args[0]
        assert "--output-format" in call_args
        assert "json" in call_args
        assert "--dangerously-skip-permissions" in call_args
        assert "--print" in call_args

    @patch("ralpher.prd.asyncio.create_subprocess_exec")
    @patch("ralpher.prd.shutil.which", return_value="/usr/bin/claude")
    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit(self, mock_which, mock_exec):
        mock_exec.return_value = _make_mock_process(1)
        with pytest.raises(RuntimeError, match="exited with code 1"):
            await generate_prd("test")

    @patch("ralpher.prd.asyncio.create_subprocess_exec")
    @patch("ralpher.prd.shutil.which", return_value="/usr/bin/claude")
    @pytest.mark.asyncio
    async def test_prompt_contains_user_input(self, mock_which, mock_exec):
        mock_exec.return_value = _make_mock_process(
            0, {"session_id": "s1"},
        )
        await generate_prd("Implement SSO login")
        call_args = mock_exec.call_args[0]
        # Prompt is the last positional arg after --print
        print_idx = list(call_args).index("--print")
        prompt_text = call_args[print_idx + 1]
        assert "Implement SSO login" in prompt_text

    @patch("ralpher.prd._ask_user_questions", return_value="Q1: A")
    @patch("ralpher.prd.asyncio.create_subprocess_exec")
    @patch("ralpher.prd.shutil.which", return_value="/usr/bin/claude")
    @pytest.mark.asyncio
    async def test_intercepts_ask_user_question_and_resumes(
        self, mock_which, mock_exec, mock_ask
    ):
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
        final_result = {"session_id": "sess-interactive"}

        mock_exec.side_effect = [
            _make_mock_process(0, ask_result),
            _make_mock_process(0, final_result),
        ]

        result = await generate_prd("Build feature", interactive=True)
        assert result == 0
        assert mock_exec.call_count == 2

        second_call_args = mock_exec.call_args_list[1][0]
        assert "--resume" in second_call_args
        assert "sess-interactive" in second_call_args
        print_idx = list(second_call_args).index("--print")
        assert second_call_args[print_idx + 1] == "Q1: A"

    @patch("ralpher.prd.asyncio.create_subprocess_exec")
    @patch("ralpher.prd.shutil.which", return_value="/usr/bin/claude")
    @pytest.mark.asyncio
    async def test_non_interactive_skips_questions(self, mock_which, mock_exec):
        ask_result = {
            "session_id": "sess-ni",
            "permission_denials": [
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [{"label": "Q?", "description": "Some question"}]
                    },
                }
            ],
        }
        mock_exec.return_value = _make_mock_process(0, ask_result)
        result = await generate_prd("test", interactive=False)
        assert result == 0
        assert mock_exec.call_count == 1
