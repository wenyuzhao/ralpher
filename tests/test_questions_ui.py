"""Tests for the tabbed clarification-questions TUI.

Keyboard flows are driven end-to-end through a pipe input (all key presses are
queued before the app starts, so the run is deterministic). Mouse clicks are
exercised by invoking the handler attached to the rendered fragment — the
position-to-fragment mapping itself is prompt_toolkit's job.
"""

import contextlib
from collections.abc import Iterator

import pytest
from prompt_toolkit.application.current import create_app_session
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.mouse_events import (
    MouseButton,
    MouseEvent,
    MouseEventType,
    MouseModifier,
)
from prompt_toolkit.output import DummyOutput

from ralpher.models import Question, QuestionOption, Questions
from ralpher.utils.questions_ui import QuestionsPrompt

QUESTIONS = Questions(
    questions=[
        Question(
            header="Auth",
            question="Which auth?",
            options=[
                QuestionOption(label="Cookies", description="Server sessions"),
                QuestionOption(label="JWT", description="Stateless tokens"),
            ],
        ),
        Question(
            header="Client",
            question="Which HTTP client?",
            options=[
                QuestionOption(label="httpx", description="Async first"),
                QuestionOption(label="requests", description="Sync only"),
            ],
        ),
    ]
)


@contextlib.contextmanager
def _pipe() -> Iterator[PipeInput]:
    with (
        create_pipe_input() as inp,
        create_app_session(input=inp, output=DummyOutput()),
    ):
        yield inp


def _click(fragment: tuple) -> object:
    """Fire the mouse handler attached to a rendered fragment."""
    return fragment[2](
        MouseEvent(
            position=Point(x=0, y=0),
            event_type=MouseEventType.MOUSE_UP,
            button=MouseButton.LEFT,
            modifiers=frozenset[MouseModifier](),
        )
    )


def _text(prompt: QuestionsPrompt) -> str:
    return "".join(fragment[1] for fragment in prompt._fragments())


def _tab_fragments(prompt: QuestionsPrompt) -> list[tuple]:
    """Rendered tab fragments, minus the indent and the separators."""
    return [f for f in prompt._tab_fragments() if len(f) > 2]


class TestKeyboard:
    @pytest.mark.asyncio
    async def test_enter_picks_highlighted_option_of_each_tab(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            inp.send_text("\r\r\r")  # Q1, Q2, then submit on the review tab
            assert await prompt.run() == [
                {"Q": "Which auth?", "A": "Cookies"},
                {"Q": "Which HTTP client?", "A": "httpx"},
            ]

    @pytest.mark.asyncio
    async def test_digit_keys_pick_options(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            inp.send_text("21\r")
            assert await prompt.run() == [
                {"Q": "Which auth?", "A": "JWT"},
                {"Q": "Which HTTP client?", "A": "httpx"},
            ]

    @pytest.mark.asyncio
    async def test_arrow_keys_move_within_a_tab(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            inp.send_text("\x1b[B\r\r\r")  # down, enter, enter, submit
            answers = await prompt.run()
            assert answers[0] == {"Q": "Which auth?", "A": "JWT"}

    @pytest.mark.asyncio
    async def test_other_option_takes_a_free_form_answer(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            inp.send_text("3mTLS everywhere\r\r\r")
            answers = await prompt.run()
            assert answers[0] == {"Q": "Which auth?", "A": "mTLS everywhere"}

    @pytest.mark.asyncio
    async def test_review_tab_can_send_the_user_back(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            # Answer both, pick "Change an answer", re-answer Q1, then submit.
            inp.send_text("\r\r\x1b[B\r2\r")
            answers = await prompt.run()
            assert answers[0] == {"Q": "Which auth?", "A": "JWT"}

    @pytest.mark.asyncio
    async def test_ctrl_c_aborts(self):
        with _pipe() as inp:
            prompt = QuestionsPrompt(QUESTIONS)
            inp.send_text("\x03")
            with pytest.raises(KeyboardInterrupt):
                await prompt.run()

    @pytest.mark.asyncio
    async def test_questions_without_options_are_skipped(self):
        questions = Questions(
            questions=[Question(header="X", question="No options", options=[])]
        )
        prompt = QuestionsPrompt(questions)
        assert prompt.questions == []
        assert await prompt.run() == []  # returns without prompting at all


class TestMouse:
    def test_clicking_a_tab_switches_question(self):
        prompt = QuestionsPrompt(QUESTIONS)
        assert prompt.current == 0
        _click(_tab_fragments(prompt)[1])
        assert prompt.current == 1

    def test_clicking_an_option_answers_and_advances(self):
        prompt = QuestionsPrompt(QUESTIONS)
        options = [f for f in prompt._question_fragments() if len(f) > 2]
        _click(options[2])  # second option's label row (label, description, label…)
        assert prompt.answers[0] == "JWT"
        assert prompt.current == 1  # moved on to the next unanswered question

    def test_non_click_mouse_events_are_not_handled(self):
        prompt = QuestionsPrompt(QUESTIONS)
        handler = _tab_fragments(prompt)[1][2]
        result = handler(
            MouseEvent(
                position=Point(x=0, y=0),
                event_type=MouseEventType.MOUSE_MOVE,
                button=MouseButton.LEFT,
                modifiers=frozenset[MouseModifier](),
            )
        )
        assert result is NotImplemented
        assert prompt.current == 0


class TestRendering:
    def test_tabs_show_headers_and_mark_answered_ones(self):
        prompt = QuestionsPrompt(QUESTIONS)
        assert "Auth" in _text(prompt)
        assert "Client" in _text(prompt)
        assert "Submit" not in _text(prompt)  # review tab is hidden until answered

        prompt.answers = ["JWT", "httpx"]
        rendered = _text(prompt)
        assert "✓ Auth" in rendered
        assert "Submit" in rendered

    def test_current_question_lists_its_options_and_other(self):
        prompt = QuestionsPrompt(QUESTIONS)
        rendered = _text(prompt)
        assert "Question 1/2" in rendered
        assert "1. Cookies" in rendered
        assert "Stateless tokens" in rendered
        assert "3. Other" in rendered

    def test_revisiting_a_tab_highlights_the_existing_answer(self):
        prompt = QuestionsPrompt(QUESTIONS)
        prompt.answers[0] = "JWT"
        prompt._goto(0)
        assert prompt.cursors[0] == 1
        assert "❯ ● 2. JWT" in _text(prompt)

    def test_free_form_answer_is_marked_on_the_other_row(self):
        prompt = QuestionsPrompt(QUESTIONS)
        prompt.answers[0] = "mTLS everywhere"
        assert "● 3. Other" in _text(prompt)

    def test_review_tab_lists_every_answer(self):
        prompt = QuestionsPrompt(QUESTIONS)
        prompt.answers = ["JWT", "httpx"]
        prompt._goto_review()
        rendered = _text(prompt)
        assert "Review your answers" in rendered
        assert "→ JWT" in rendered
        assert "→ httpx" in rendered
        assert "Submit these answers" in rendered
