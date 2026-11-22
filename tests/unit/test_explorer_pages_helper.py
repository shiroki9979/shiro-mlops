"""Behaviour of the shared ``explorer_pages`` test helper against fake readers."""

from dataclasses import dataclass

import pytest

from tests.helpers import explorer_pages


@dataclass(frozen=True)
class _Page:
    has_more: bool
    next_cursor: str | None


class _ScriptedReader:
    """Return the next scripted page per call, recording the cursor each call carried."""

    def __init__(self, pages: list[_Page]) -> None:
        self._pages = iter(pages)
        self.cursors: list[str | None] = []

    def list(self, params: dict) -> _Page:
        self.cursors.append(params.get("cursor"))
        return next(self._pages)


def test_follows_each_cursor_to_the_last_page():
    reader = _ScriptedReader([_Page(True, "first"), _Page(True, "second"), _Page(False, None)])

    pages = explorer_pages(reader, {"limit": 1})

    assert len(pages) == 3
    assert reader.cursors == [None, "first", "second"]


def test_a_cursor_handed_out_twice_fails_before_the_page_cap():
    reader = _ScriptedReader([_Page(True, "first"), _Page(True, "second"), _Page(True, "first")])

    with pytest.raises(AssertionError, match="repeated cursor"):
        explorer_pages(reader, {"limit": 1}, max_pages=20)

    assert reader.cursors == [None, "first", "second"]


def test_paging_that_never_ends_fails_at_the_page_cap():
    reader = _ScriptedReader([_Page(True, f"cursor-{index}") for index in range(10)])

    with pytest.raises(AssertionError, match="within 3 pages"):
        explorer_pages(reader, {"limit": 1}, max_pages=3)
