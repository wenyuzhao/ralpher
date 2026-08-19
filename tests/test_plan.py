import json
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.backend.common import ask_user_questions
from ralpher.models import Project, Question, QuestionOption, Questions, Tasks
from ralpher.plan.extract import extract_tasks
from ralpher.plan.plan import generate_plan


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


class TestAskUserQuestions:
    """The tabbed prompt itself is covered by tests/test_questions_ui.py."""

    @pytest.mark.asyncio
    @patch("ralpher.backend.common.QuestionsPrompt")
    async def test_serializes_answers_as_json(self, mock_prompt_cls):
        mock_prompt_cls.return_value.run = AsyncMock(
            return_value=[
                {"Q": "Auth needed?", "A": "Yes"},
                {"Q": "Platform", "A": "Mobile"},
            ]
        )
        questions = _make_questions(
            [
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
        )
        result = await ask_user_questions(questions)
        assert mock_prompt_cls.call_args.args[0] is questions
        assert json.loads(result) == [
            {"Q": "Auth needed?", "A": "Yes"},
            {"Q": "Platform", "A": "Mobile"},
        ]

    @pytest.mark.asyncio
    async def test_skips_questions_without_options(self):
        # No answerable question means nothing is prompted at all.
        questions = _make_questions(
            [
                {"header": "X", "question": "No options here", "options": []},
            ]
        )
        result = await ask_user_questions(questions)
        assert json.loads(result) == []


class TestGeneratePlan:
    @patch("ralpher.plan.plan.init_project")
    @patch("ralpher.plan.plan.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(
        self, mock_run, mock_init, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "test-task-1"
        project = Project(id=task_id)

        async def side_effect(**kwargs):
            project.project_dir.mkdir(parents=True, exist_ok=True)
            project.plan_md.write_text("# Plan")

        mock_run.side_effect = side_effect
        result = await generate_plan(project=project, prompt="Build a chat app")
        assert result == task_id

    @patch("ralpher.plan.plan.init_project")
    @patch("ralpher.plan.plan.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_claude_error(
        self, mock_run, mock_init, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_run.side_effect = SystemExit("Claude process returned an error.")
        with pytest.raises(SystemExit):
            await generate_plan(project=Project(id="task-fail"), prompt="test")

    @patch("ralpher.plan.plan.init_project")
    @patch("ralpher.plan.plan.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_creates_task_directory_and_prompt(
        self, mock_run, mock_init, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "task-dir-test"
        project = Project(id=task_id)

        def init_side_effect(proj, prompt, **kwargs):
            proj.project_dir.mkdir(parents=True, exist_ok=True)
            proj.prompt_md.write_text(prompt)

        mock_init.side_effect = init_side_effect

        async def run_side_effect(**kwargs):
            project.plan_md.write_text("# Plan")

        mock_run.side_effect = run_side_effect
        await generate_plan(project=project, prompt="My feature request")
        assert project.project_dir.exists()
        assert project.prompt_md.read_text() == "My feature request"

    @patch("ralpher.plan.plan.init_project")
    @patch("ralpher.plan.plan.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_calls_run_agent_with_correct_args(
        self, mock_run, mock_init, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        task_id = "task-flags"
        project = Project(id=task_id)

        async def side_effect(**kwargs):
            project.project_dir.mkdir(parents=True, exist_ok=True)
            project.plan_md.write_text("# Plan")

        mock_run.side_effect = side_effect
        await generate_plan(project=project, prompt="Implement SSO login")
        call_kwargs = mock_run.call_args[1]
        # The rendered prompt references the project's PROMPT.md path, which
        # embeds the project id, and carries the plan-skill instructions.
        assert task_id in call_kwargs["prompt"]
        assert "Create Project Plan" in call_kwargs["prompt"]
        assert call_kwargs["project"] is project

    @patch("ralpher.plan.plan.init_project")
    @patch("ralpher.plan.plan.run_agent_plan_mode", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_plan_not_created(
        self, mock_run, mock_init, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_run.return_value = None
        with pytest.raises(SystemExit):
            await generate_plan(project=Project(id="task-no-plan"), prompt="test")


class TestExtractTasks:
    @pytest.mark.asyncio
    async def test_raises_when_task_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            await extract_tasks(Project(id="nonexistent-task"))

    @pytest.mark.asyncio
    async def test_raises_when_plan_md_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        with pytest.raises(SystemExit):
            await extract_tasks(project)

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_returns_on_success(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# My Plan")

        mock_run.return_value = Tasks(tasks=[])
        await extract_tasks(project)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["kind"] == "extract-tasks"
        assert project.tasks_toml.exists()

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_on_all_retries_failed(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# My Plan")

        mock_run.side_effect = SystemExit("Claude process returned an error.")
        with pytest.raises(SystemExit):
            await extract_tasks(project, retries=1)

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_raises_when_tasks_toml_not_created(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="test-task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# My Plan")

        mock_run.side_effect = SystemExit("Claude process returned an error.")
        with pytest.raises(SystemExit):
            await extract_tasks(project, retries=1)

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_prompt_includes_task_id(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_id = "my-task-123"
        project = Project(id=task_id)
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")

        mock_run.return_value = Tasks(tasks=[])
        await extract_tasks(project)

        call_kwargs = mock_run.call_args[1]
        assert "my-task-123" in call_kwargs["prompt"]

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_retries_on_invalid_tasks_toml(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = Project(id="retry-task")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SystemExit("Claude process returned an error.")
            return Tasks(tasks=[])

        mock_run.side_effect = side_effect
        await extract_tasks(project, retries=3)
        assert mock_run.call_count == 2

    @patch("ralpher.plan.extract.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_retries_on_claude_error_then_succeeds(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="retry-exit")
        project.project_dir.mkdir(parents=True)
        project.plan_md.write_text("# Plan")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SystemExit("Claude process returned an error.")
            return Tasks(tasks=[])

        mock_run.side_effect = side_effect
        await extract_tasks(project, retries=3)
        assert mock_run.call_count == 2
