"""Tabbed terminal UI for clarification questions.

Renders every question as a tab (mouse-clickable) with its options listed
below, in the style of Claude Code's own question prompt. The user moves
between tabs with the arrow keys, `tab`/`shift-tab`, or the mouse, picks an
option with the arrow keys / a digit / a click, and lands on a final review
tab where the answers are submitted.

The whole prompt is one `prompt_toolkit` `Application`; `QuestionsPrompt.run`
returns the collected answers as `[{"Q": ..., "A": ...}, ...]`.
"""

import shutil
import textwrap
from collections.abc import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from ralpher.models import Question, Questions

QUESTIONS_STYLE = Style.from_dict(
    {
        "title": "bold ansiblue",
        "tab": "fg:ansibrightblack",
        "tab.done": "fg:ansigreen",
        "tab.active": "bold bg:ansimagenta fg:ansiblack",
        "counter": "fg:ansibrightblack",
        "question": "bold",
        "option": "",
        "option.active": "bold ansimagenta",
        "description": "fg:ansibrightblack",
        "description.active": "ansimagenta",
        "answer": "ansigreen",
        "hint": "fg:ansibrightblack",
        "other-prompt": "bold ansimagenta",
    }
)

OTHER_LABEL = "Other"
"""Pseudo-option that opens a free-form text input."""

_INDENT = "  "


def _terminal_width() -> int:
    app = get_app_or_none()
    if app is not None:
        columns = app.output.get_size().columns
        if columns > 0:
            return columns
    return shutil.get_terminal_size((80, 24)).columns


def _wrap(text: str, indent: str) -> str:
    """Wrap `text` to the terminal width, indenting every line."""
    width = max(_terminal_width() - len(indent) - 1, 20)
    lines = textwrap.wrap(text, width=width) or [""]
    return "\n".join(indent + line for line in lines)


class QuestionsPrompt:
    """A tabbed, mouse-clickable prompt for a list of clarification questions."""

    def __init__(self, questions: Questions) -> None:
        # Questions without options can't be answered as multiple choice.
        self.questions: list[Question] = [q for q in questions.questions if q.options]
        self.answers: list[str | None] = [None] * len(self.questions)
        # Highlighted row per question; `len(options)` is the "Other" row.
        self.cursors: list[int] = [0] * len(self.questions)
        self.current = 0
        self.reviewing = False
        self.review_cursor = 0
        self.editing = False
        self.other_input = TextArea(
            multiline=False,
            prompt=[("class:other-prompt", f"{_INDENT}› ")],
            accept_handler=self._accept_other,
        )
        self.app = self._build_app()

    # -- state transitions ------------------------------------------------

    @property
    def _rows(self) -> int:
        """Number of selectable rows on the current question (options + Other)."""
        return len(self.questions[self.current].options) + 1

    @property
    def _answered(self) -> bool:
        return all(answer is not None for answer in self.answers)

    def _goto(self, index: int) -> None:
        self.editing = False
        self.reviewing = False
        self.current = max(0, min(index, len(self.questions) - 1))
        # Start on the answer already given, so revisiting a tab shows the pick.
        answered_row = self._answer_row(self.current)
        if answered_row is not None:
            self.cursors[self.current] = answered_row
        self.app.layout.focus(self.window)

    def _goto_review(self) -> None:
        if not self._answered:
            return
        self.editing = False
        self.reviewing = True
        self.review_cursor = 0
        self.app.layout.focus(self.window)

    def _advance(self) -> None:
        """Move to the next unanswered question, or to the review tab."""
        order = list(range(self.current + 1, len(self.questions))) + list(
            range(self.current + 1)
        )
        for index in order:
            if self.answers[index] is None:
                self._goto(index)
                return
        self._goto_review()

    def _tabs(self) -> int:
        """Total number of tabs, including the review tab when it is shown."""
        return len(self.questions) + (1 if self._answered else 0)

    def _move_tab(self, delta: int) -> None:
        index = (
            len(self.questions) if self.reviewing else self.current
        ) + delta  # review tab sits after the questions
        index %= self._tabs()
        if index == len(self.questions):
            self._goto_review()
        else:
            self._goto(index)

    def _move_row(self, delta: int) -> None:
        if self.reviewing:
            self.review_cursor = (self.review_cursor + delta) % 2
        else:
            self.cursors[self.current] = (
                self.cursors[self.current] + delta
            ) % self._rows

    def _answer_row(self, index: int) -> int | None:
        """Row holding question `index`'s answer; a free-form one is "Other"."""
        answer = self.answers[index]
        if answer is None:
            return None
        for row, option in enumerate(self.questions[index].options):
            if option.label == answer:
                return row
        return len(self.questions[index].options)

    def _select_row(self, row: int) -> None:
        """Pick the row at `row` (a digit key or a click) and confirm it."""
        if self.reviewing:
            if row < 2:
                self._pick_review(row)
            return
        if not 0 <= row < self._rows:
            return
        self.cursors[self.current] = row
        self._confirm()

    def _confirm(self) -> None:
        if self.reviewing:
            if self.review_cursor == 0:
                self._submit()
            else:
                self._goto(0)
            return

        question = self.questions[self.current]
        row = self.cursors[self.current]
        if row == len(question.options):
            self._start_editing()
            return
        self.answers[self.current] = question.options[row].label
        self._advance()

    def _start_editing(self) -> None:
        self.editing = True
        answer = self.answers[self.current]
        free_form = self._answer_row(self.current) == len(
            self.questions[self.current].options
        )
        text = answer if answer is not None and free_form else ""
        self.other_input.text = text
        self.other_input.buffer.cursor_position = len(text)
        self.app.layout.focus(self.other_input)

    def _accept_other(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        if not text:
            return True  # keep the input open until something is typed
        self.answers[self.current] = text
        self.editing = False
        self.app.layout.focus(self.window)
        self._advance()
        return False

    def _cancel_editing(self) -> None:
        self.editing = False
        self.app.layout.focus(self.window)

    def _submit(self) -> None:
        self.app.exit(
            result=[
                {"Q": question.question, "A": answer}
                for question, answer in zip(self.questions, self.answers, strict=True)
                if answer is not None
            ]
        )

    # -- rendering --------------------------------------------------------

    def _pick_review(self, index: int) -> None:
        self.review_cursor = index
        self._confirm()

    def _click(self, action: Callable[[], None]) -> Callable[[MouseEvent], object]:
        def handler(mouse_event: MouseEvent) -> object:
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            action()
            return None

        return handler

    def _tab_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = [("", _INDENT)]
        for index, question in enumerate(self.questions):
            answered = self.answers[index] is not None
            active = not self.reviewing and index == self.current
            style = (
                "class:tab.active"
                if active
                else ("class:tab.done" if answered else "class:tab")
            )
            mark = "✓ " if answered else ""
            label = question.header or f"Q{index + 1}"
            fragments.append(
                (style, f" {mark}{label} ", self._click(lambda i=index: self._goto(i)))
            )
            fragments.append(("", " "))
        if self._answered:
            style = "class:tab.active" if self.reviewing else "class:tab.done"
            fragments.append((style, " Submit ", self._click(self._goto_review)))
        return fragments

    def _question_fragments(self) -> StyleAndTextTuples:
        question = self.questions[self.current]
        cursor = self.cursors[self.current]
        fragments: StyleAndTextTuples = [
            (
                "class:counter",
                f"{_INDENT}Question {self.current + 1}/{len(self.questions)}\n",
            ),
            ("class:question", f"{_wrap(question.question, _INDENT)}\n\n"),
        ]

        rows: list[tuple[str, str]] = [
            (opt.label, opt.description) for opt in question.options
        ]
        rows.append((OTHER_LABEL, "type your own answer"))
        picked = self._answer_row(self.current)

        for index, (label, description) in enumerate(rows):
            active = index == cursor
            marker = "❯" if active else " "
            radio = "●" if index == picked else "○"
            fragments.append(
                (
                    "class:option.active" if active else "class:option",
                    f"{_INDENT}{marker} {radio} {index + 1}. {label}\n",
                    self._click(lambda i=index: self._select_row(i)),
                )
            )
            fragments.append(
                (
                    "class:description.active" if active else "class:description",
                    f"{_wrap(description, _INDENT + ' ' * 7)}\n",
                    self._click(lambda i=index: self._select_row(i)),
                )
            )
        return fragments

    def _review_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = [
            ("class:counter", f"{_INDENT}Review your answers\n\n"),
        ]
        for index, question in enumerate(self.questions):
            fragments.append(
                (
                    "class:question",
                    f"{_wrap(question.question, _INDENT)}\n",
                    self._click(lambda i=index: self._goto(i)),
                )
            )
            fragments.append(
                (
                    "class:answer",
                    f"{_wrap(str(self.answers[index]), _INDENT + '  → ')}\n\n",
                    self._click(lambda i=index: self._goto(i)),
                )
            )
        for index, label in enumerate(["Submit these answers", "Change an answer"]):
            active = index == self.review_cursor
            marker = "❯" if active else " "
            fragments.append(
                (
                    "class:option.active" if active else "class:option",
                    f"{_INDENT}{marker} {label}\n",
                    self._click(lambda i=index: self._pick_review(i)),
                )
            )
        return fragments

    def _hint(self) -> str:
        if self.editing:
            return f"\n{_INDENT}enter submit · esc cancel"
        return (
            f"\n{_INDENT}↑↓ move · ←→ switch tab · 1-9 pick · "
            "enter confirm · ctrl-c cancel"
        )

    def _fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = [
            ("class:title", f"{_INDENT}Please answer the following questions\n\n"),
        ]
        fragments += self._tab_fragments()
        fragments.append(("", "\n\n"))
        fragments += (
            self._review_fragments() if self.reviewing else self._question_fragments()
        )
        fragments.append(("class:hint", f"{self._hint()}\n"))
        return fragments

    # -- application ------------------------------------------------------

    def _key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()
        navigating = Condition(lambda: not self.editing)

        @bindings.add("up", filter=navigating)
        @bindings.add("k", filter=navigating)
        def _(event: KeyPressEvent) -> None:
            self._move_row(-1)

        @bindings.add("down", filter=navigating)
        @bindings.add("j", filter=navigating)
        def _(event: KeyPressEvent) -> None:
            self._move_row(1)

        @bindings.add("left", filter=navigating)
        @bindings.add("s-tab", filter=navigating)
        def _(event: KeyPressEvent) -> None:
            self._move_tab(-1)

        @bindings.add("right", filter=navigating)
        @bindings.add("tab", filter=navigating)
        def _(event: KeyPressEvent) -> None:
            self._move_tab(1)

        @bindings.add("enter", filter=navigating)
        @bindings.add(" ", filter=navigating)
        def _(event: KeyPressEvent) -> None:
            self._confirm()

        for digit in range(1, 10):

            @bindings.add(str(digit), filter=navigating)
            def _(event: KeyPressEvent, row: int = digit - 1) -> None:
                self._select_row(row)

        @bindings.add("escape", filter=Condition(lambda: self.editing))
        def _(event: KeyPressEvent) -> None:
            self._cancel_editing()

        @bindings.add("c-c")
        @bindings.add("c-d")
        def _(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

        return bindings

    def _build_app(self) -> Application:
        self.window = Window(
            FormattedTextControl(self._fragments, focusable=True, show_cursor=False),
            dont_extend_height=True,
            wrap_lines=True,
        )
        layout = Layout(
            HSplit(
                [
                    self.window,
                    ConditionalContainer(
                        self.other_input, filter=Condition(lambda: self.editing)
                    ),
                ]
            ),
            focused_element=self.window,
        )
        return Application(
            layout=layout,
            key_bindings=self._key_bindings(),
            style=QUESTIONS_STYLE,
            mouse_support=True,
            erase_when_done=True,
        )

    async def run(self) -> list[dict[str, str]]:
        """Run the prompt and return the collected answers."""
        if not self.questions:
            return []
        return await self.app.run_async()
