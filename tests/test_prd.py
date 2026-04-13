import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.utils.claude import _ask_user_questions
from ralpher.models import Questions, Question, QuestionOption
from ralpher.prd.prd import generate_prd
from ralpher.prd.extract import extract_prd_json


def _make_questions(raw: list[dict]) -> Questions:
    """Build a Questions model from a list of raw dicts."""
    questions = []
    for q in raw:
        options = [QuestionOption(**o) for o in q.get("options", [])]
        questions.append(
            Question(
                header=q.get("header", ""),
                question=q.get("question", ""),
                options=options,
            )
        )
    return Questions(questions=questions)


class TestQuestionsLoad:
    def test_returns_none_when_file_missing(self, tmp_path):
        assert Questions.load(tmp_path) is None

    def test_loads_valid_questions(self, tmp_path):
        data = {
            "questions": [
                {
                    "header": "Goal",
                    "question": "What is the goal?",
                    "options": [
                        {"label": "A", "description": "Option A"},
                        {"label": "B", "description": "Option B"},
                    ],
                }
            ]
        }
        (tmp_path / "questions.json").write_text(json.dumps(data))
        result = Questions.load(tmp_path)
        assert result is not None
        assert len(result.questions) == 1
        assert result.questions[0].header == "Goal"

    def test_loads_multiple_questions(self, tmp_path):
        data = {
            "questions": [
                {
                    "header": "Q1",
                    "question": "First",
                    "options": [{"label": "A", "description": "a"}],
                },
                {
                    "header": "Q2",
                    "question": "Second",
                    "options": [{"label": "B", "description": "b"}],
                },
            ]
        }
        (tmp_path / "questions.json").write_text(json.dumps(data))
        result = Questions.load(tmp_path)
        assert result is not None
        assert len(result.questions) == 2

    def test_clear_removes_file(self, tmp_path):
        (tmp_path / "questions.json").write_text("{}")
        Questions.clear(tmp_path)
        assert not (tmp_path / "questions.json").exists()

    def test_clear_noop_when_missing(self, tmp_path):
        Questions.clear(tmp_path)  # should not raise


class TestAskUserQuestions:
    @pytest.mark.asyncio
    @patch("ralpher.utils.claude.ChoiceInput")
    async def test_single_question_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="REST")
        questions = _make_questions([
            {
                "header": "API",
                "question": "API style",
                "options": [
                    {"label": "REST", "description": "RESTful API"},
                    {"label": "GraphQL", "description": "GraphQL API"},
                ],
            }
        ])
        result = await _ask_user_questions(questions)
        assert "API style: REST" in result

    @pytest.mark.asyncio
    @patch("ralpher.utils.claude.ChoiceInput")
    async def test_multiple_questions_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(side_effect=["Yes", "Mobile"])
        questions = _make_questions([
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
        ])
        result = await _ask_user_questions(questions)
        assert "Auth needed?: Yes" in result
        assert "Platform: Mobile" in result

    @pytest.mark.asyncio
    @patch("ralpher.utils.claude.ChoiceInput")
    async def test_question_with_options(self, mock_choice_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="Monolith")
        questions = _make_questions([
            {
                "header": "Architecture",
                "question": "Pick a pattern",
                "options": [
                    {"label": "Monolith", "description": "Single deployable"},
                    {"label": "Microservices", "description": "Distributed"},
                ],
            }
        ])
        result = await _ask_user_questions(questions)
        assert "Pick a pattern: Monolith" in result

    @pytest.mark.asyncio
    async def test_skips_questions_without_options(self):
        questions = _make_questions([
            {"header": "X", "question": "No options here", "options": []},
        ])
        result = await _ask_user_questions(questions)
        assert result == ""

    @pytest.mark.asyncio
    @patch("ralpher.utils.claude.PromptSession")
    @patch("ralpher.utils.claude.ChoiceInput")
    async def test_other_option_prompts_freeform(self, mock_choice_cls, mock_session_cls):
        mock_choice_cls.return_value.prompt_async = AsyncMock(return_value="__other__")
        mock_session_cls.return_value.prompt_async = AsyncMock(return_value="Custom answer")
        questions = _make_questions([
            {
                "header": "Style",
                "question": "Pick style",
                "options": [
                    {"label": "A", "description": "Option A"},
                ],
            }
        ])
        result = await _ask_user_questions(questions)
        assert "Pick style: Custom answer" in result


class TestGeneratePrd:
    @patch("ralpher.prd.prd.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "test-task-1"

        async def side_effect(**kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")

        mock_run.side_effect = side_effect
        result = await generate_prd(task_id, "Build a chat app")
        assert result == task_id

    @patch("ralpher.prd.prd.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(self, mock_run, tmp_path, monkeypatch):
        from ralpher.utils.claude import ClaudeError
        monkeypatch.chdir(tmp_path)
        mock_run.side_effect = ClaudeError(1)
        with pytest.raises(SystemExit):
            await generate_prd("task-fail", "test")

    @patch("ralpher.prd.prd.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_creates_task_directory_and_prompt(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "task-dir-test"

        async def side_effect(**kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")

        mock_run.side_effect = side_effect
        result = await generate_prd(task_id, "My feature request")
        task_dir = tmp_path / ".ralpher" / "tasks" / task_id
        assert task_dir.exists()
        assert (task_dir / "PROMPT.md").read_text() == "My feature request"

    @patch("ralpher.prd.prd.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_calls_run_claude_with_correct_args(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "task-flags"

        async def side_effect(**kwargs):
            (tmp_path / ".ralpher" / "tasks" / task_id / "PRD.md").write_text("# PRD")

        mock_run.side_effect = side_effect
        await generate_prd(task_id, "Implement SSO login")
        call_kwargs = mock_run.call_args[1]
        assert task_id in call_kwargs["prompt"]
        assert "/ralpher:prd" in call_kwargs["prompt"]
        assert call_kwargs["interactive"] is True

    @patch("ralpher.prd.prd.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_prd_not_created(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_run.return_value = None
        with pytest.raises(SystemExit):
            await generate_prd("task-no-prd", "test")


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

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_on_success(self, mock_run, tmp_path, monkeypatch):
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

        async def side_effect(**kwargs):
            (task_dir / "prd.json").write_text(valid_prd)

        mock_run.side_effect = side_effect
        await extract_prd_json("test-task")
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "haiku"

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_all_retries_failed(self, mock_run, tmp_path, monkeypatch):
        from ralpher.utils.claude import ClaudeError
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_run.side_effect = ClaudeError(1)
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task", retries=1)

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_prd_json_not_created(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / ".ralpher" / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "PRD.md").write_text("# My PRD")

        mock_run.return_value = None
        with pytest.raises(SystemExit):
            await extract_prd_json("test-task", retries=1)

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_prompt_includes_task_id(self, mock_run, tmp_path, monkeypatch):
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

        async def side_effect(**kwargs):
            (task_dir / "prd.json").write_text(valid_prd)

        mock_run.side_effect = side_effect
        await extract_prd_json("my-task-123")

        call_kwargs = mock_run.call_args[1]
        assert "my-task-123" in call_kwargs["prompt"]

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_retries_on_invalid_prd_json(self, mock_run, tmp_path, monkeypatch):
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

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                (task_dir / "prd.json").write_text('{"invalid": true}')
            else:
                (task_dir / "prd.json").write_text(valid_prd)

        mock_run.side_effect = side_effect
        await extract_prd_json("retry-task", retries=3)
        assert mock_run.call_count == 2

    @patch("ralpher.prd.extract.run_claude", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_retries_on_claude_error_then_succeeds(self, mock_run, tmp_path, monkeypatch):
        from ralpher.utils.claude import ClaudeError
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

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClaudeError(1)
            else:
                (task_dir / "prd.json").write_text(valid_prd)

        mock_run.side_effect = side_effect
        await extract_prd_json("retry-exit", retries=3)
        assert mock_run.call_count == 2
