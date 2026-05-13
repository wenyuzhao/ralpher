from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ralpher.models import Project
from ralpher.utils.notion_comments import (
    NotionComment,
    fetch_project_plan_comments,
    render_comments_as_prompt,
    resolve_comments,
)


def _heading_1(id_: str, text: str):
    block = SimpleNamespace(
        id=id_,
        type="heading_1",
        heading_1={"rich_text": [{"plain_text": text}]},
        has_children=False,
    )
    # _iter_section_blocks discriminates with isinstance(Heading1Block); we
    # patch that check via the duck-typed Heading1Block import in the tests
    # that need it.
    return block


def _paragraph(id_: str, text: str, children=None):
    return SimpleNamespace(
        id=id_,
        type="paragraph",
        paragraph={"rich_text": [{"plain_text": text}]},
        has_children=bool(children),
        _children=children or [],
    )


def _comment(id_: str, discussion_id: str, text: str, author: str | None = None):
    created_by = SimpleNamespace(name=author) if author else None
    return SimpleNamespace(
        id=id_,
        discussion_id=discussion_id,
        rich_text=[SimpleNamespace(plain_text=text)],
        created_by=created_by,
    )


def _async_iter(items):
    async def gen():
        for it in items:
            yield it

    return gen()


def _make_client(*, top_blocks, comments_by_block, child_blocks=None):
    """Build a fake NotionClient with paginated iterators."""
    child_blocks = child_blocks or {}
    client = MagicMock()

    def children_for(block_id, page_size=None):
        if block_id == "page-id":
            return _async_iter(top_blocks)
        return _async_iter(child_blocks.get(block_id, []))

    client.blocks.children = MagicMock(side_effect=children_for)

    def comments_for(block_id, page_size=None):
        return _async_iter(comments_by_block.get(block_id, []))

    client.comments.list = MagicMock(side_effect=comments_for)
    client.comments.create = AsyncMock()
    client._transport = SimpleNamespace(patch=AsyncMock())
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestFetchProjectPlanComments:
    @pytest.mark.asyncio
    async def test_returns_empty_when_token_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RALPHER_NOTION_TOKEN", raising=False)
        result = await fetch_project_plan_comments(Project(id="proj"))
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_page_unresolved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.delenv("RALPHER_NOTION_PAGE_ID", raising=False)
        monkeypatch.delenv("RALPHER_NOTION_PARENT_PAGE_ID", raising=False)

        client = _make_client(top_blocks=[], comments_by_block={})
        with patch(
            "ralpher.utils.notion_comments.NotionClient", return_value=client
        ):
            result = await fetch_project_plan_comments(Project(id="proj"))
        assert result == []

    @pytest.mark.asyncio
    async def test_collects_only_comments_in_project_plan_section(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.setenv("RALPHER_NOTION_PAGE_ID", "page-id")

        from znotion.models.blocks import Heading1Block, ParagraphBlock

        before = ParagraphBlock(id="b-before", paragraph={"rich_text": []})
        h1_plan = Heading1Block(
            id="h-plan",
            heading_1={"rich_text": [{"plain_text": "📜 Project Plan"}]},
        )
        in_section = ParagraphBlock(
            id="b-in",
            paragraph={"rich_text": [{"plain_text": "Use Postgres for storage."}]},
        )
        h1_after = Heading1Block(
            id="h-after",
            heading_1={"rich_text": [{"plain_text": "💬 User Prompt"}]},
        )
        after = ParagraphBlock(
            id="b-after",
            paragraph={"rich_text": [{"plain_text": "after"}]},
        )

        client = _make_client(
            top_blocks=[before, h1_plan, in_section, h1_after, after],
            comments_by_block={
                "b-before": [_comment("c0", "d0", "should be ignored")],
                "b-in": [_comment("c1", "d1", "Switch to MySQL", author="Alice")],
                "b-after": [_comment("c2", "d2", "also ignored")],
            },
        )
        with patch(
            "ralpher.utils.notion_comments.NotionClient", return_value=client
        ):
            result = await fetch_project_plan_comments(Project(id="proj"))

        assert len(result) == 1
        c = result[0]
        assert c.id == "c1"
        assert c.text == "Switch to MySQL"
        assert c.context == "Use Postgres for storage."
        assert c.author == "Alice"

    @pytest.mark.asyncio
    async def test_recurses_into_block_children(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        monkeypatch.setenv("RALPHER_NOTION_PAGE_ID", "page-id")

        from znotion.models.blocks import Heading1Block, ParagraphBlock

        h1 = Heading1Block(
            id="h-plan",
            heading_1={"rich_text": [{"plain_text": "Project Plan"}]},
        )
        parent = ParagraphBlock(
            id="b-parent",
            paragraph={"rich_text": [{"plain_text": "parent text"}]},
            has_children=True,
        )
        child = ParagraphBlock(
            id="b-child",
            paragraph={"rich_text": [{"plain_text": "child text"}]},
        )

        client = _make_client(
            top_blocks=[h1, parent],
            comments_by_block={
                "b-child": [_comment("c-child", "d", "nested comment")],
            },
            child_blocks={"b-parent": [child]},
        )
        with patch(
            "ralpher.utils.notion_comments.NotionClient", return_value=client
        ):
            result = await fetch_project_plan_comments(Project(id="proj"))

        assert len(result) == 1
        assert result[0].context == "child text"


class TestResolveComments:
    @pytest.mark.asyncio
    async def test_no_op_on_empty(self, monkeypatch):
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        await resolve_comments([])  # should not raise

    @pytest.mark.asyncio
    async def test_uses_patch_when_supported(self, monkeypatch):
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        client = _make_client(top_blocks=[], comments_by_block={})
        with patch(
            "ralpher.utils.notion_comments.NotionClient", return_value=client
        ):
            await resolve_comments(
                [NotionComment(id="c1", discussion_id="d1", text="x", context="y", author=None)]
            )
        client._transport.patch.assert_awaited_once()
        client.comments.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_reply_when_patch_fails(self, monkeypatch):
        monkeypatch.setenv("RALPHER_NOTION_TOKEN", "t")
        client = _make_client(top_blocks=[], comments_by_block={})
        client._transport.patch = AsyncMock(side_effect=Exception("404"))
        with patch(
            "ralpher.utils.notion_comments.NotionClient", return_value=client
        ):
            await resolve_comments(
                [NotionComment(id="c1", discussion_id="d1", text="x", context="y", author=None)]
            )
        client.comments.create.assert_awaited_once()
        kwargs = client.comments.create.call_args.kwargs
        assert kwargs["discussion_id"] == "d1"


class TestRenderCommentsAsPrompt:
    def test_includes_context_text_and_author(self):
        comments = [
            NotionComment(
                id="c1",
                discussion_id="d1",
                text="Switch to MySQL",
                context="Use Postgres for storage.",
                author="Alice",
            ),
            NotionComment(
                id="c2",
                discussion_id="d2",
                text="Add a CI task",
                context="",
                author=None,
            ),
        ]
        rendered = render_comments_as_prompt(comments)
        assert "Use Postgres for storage." in rendered
        assert "Switch to MySQL" in rendered
        assert "by Alice" in rendered
        assert "Add a CI task" in rendered
        assert "## Comment 1" in rendered
        assert "## Comment 2" in rendered
