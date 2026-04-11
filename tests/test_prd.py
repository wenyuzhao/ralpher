from unittest.mock import AsyncMock, patch

import pytest

from ralpher.prd import generate_prd, load_prd_prompt


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
        # Both should render without error; content may differ if template uses it
        assert isinstance(result_interactive, str)
        assert isinstance(result_non_interactive, str)


def _make_mock_process(returncode: int) -> AsyncMock:
    proc = AsyncMock()
    proc.wait.return_value = None
    proc.returncode = returncode
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
        mock_exec.return_value = _make_mock_process(0)
        result = await generate_prd("Build a chat app")
        assert result == 0
        call_args = mock_exec.call_args[0]
        assert "--permission-mode" in call_args
        assert "dontAsk" in call_args
        assert "-p" in call_args

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
        mock_exec.return_value = _make_mock_process(0)
        await generate_prd("Implement SSO login")
        call_args = mock_exec.call_args[0]
        p_idx = list(call_args).index("-p")
        prompt_text = call_args[p_idx + 1]
        assert "Implement SSO login" in prompt_text
