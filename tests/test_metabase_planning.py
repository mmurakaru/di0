"""Unit tests for the pure Metabase dashboard planner - no HTTPServer involved.

`_plan_dashboard` computes tab/card placement and reuse from plain data; these
tests exercise that logic directly, in contrast to test_dashboard_authoring.py
and test_authoring_extras.py, which prove the same rules end-to-end against a
fake Metabase.
"""

from __future__ import annotations

from di0.adapters.metabase_execution import _plan_dashboard
from di0.deliverable import ResolvedCard, ResolvedDashboard, ResolvedTab


def _card(title: str = "", text: str = "", **kwargs) -> ResolvedCard:
    return ResolvedCard(title=title, text=text, **kwargs)


def test_new_dashboard_assigns_negative_placeholder_ids():
    dashboard = ResolvedDashboard(
        name="D",
        tabs=(
            ResolvedTab(name="Overview", cards=(_card("A", sql="select 1"),)),
            ResolvedTab(name="Trend", cards=(_card("B", sql="select 2"),)),
        ),
    )

    plan = _plan_dashboard(dashboard, existing=None)

    assert [tab.id for tab in plan.tabs] == [-1, -2]
    assert all(card.reuse_card_id is None for tab in plan.tabs for card in tab.cards)
    assert plan.archive_card_ids == frozenset()


def test_replace_reuses_tab_and_card_ids_matched_by_name_and_title():
    dashboard = ResolvedDashboard(
        name="D",
        tabs=(ResolvedTab(name="T", cards=(_card("c", sql="select 1"),)),),
    )
    existing = {
        "tabs": [{"id": 77, "name": "T"}],
        "dashcards": [
            {"card_id": 901, "card": {"name": "c"}},  # same title -> reused
            {"card_id": 902, "card": {"name": "gone this run"}},  # unreferenced -> archived
        ],
    }

    plan = _plan_dashboard(dashboard, existing)

    assert plan.tabs[0].id == 77
    assert plan.tabs[0].cards[0].reuse_card_id == 901
    assert plan.archive_card_ids == frozenset({902})


def test_archive_ids_exclude_dashcards_with_no_name():
    dashboard = ResolvedDashboard(name="D", tabs=())
    existing = {
        "tabs": [],
        "dashcards": [
            {"card_id": 903, "card": {"name": "orphan"}},
            {"card_id": None},  # a text card - never archived
        ],
    }

    plan = _plan_dashboard(dashboard, existing)

    assert plan.archive_card_ids == frozenset({903})


def test_grid_auto_stacks_by_size_y_when_row_is_unset():
    dashboard = ResolvedDashboard(
        name="D",
        tabs=(
            ResolvedTab(
                name="T",
                cards=(
                    _card("a", sql="select 1", size_y=4),
                    _card("b", sql="select 2", size_y=6),
                    _card("c", sql="select 3"),
                ),
            ),
        ),
    )

    plan = _plan_dashboard(dashboard, existing=None)

    rows = [card.row for card in plan.tabs[0].cards]
    assert rows == [0, 4, 10]


def test_explicit_row_and_col_are_kept_and_do_not_advance_auto_stack():
    dashboard = ResolvedDashboard(
        name="D",
        tabs=(
            ResolvedTab(
                name="T",
                cards=(
                    _card("a", sql="select 1", row=5, col=2, size_y=3),
                    _card("b", sql="select 2"),  # auto-placed, unaffected by the explicit card
                ),
            ),
        ),
    )

    plan = _plan_dashboard(dashboard, existing=None)

    first, second = plan.tabs[0].cards
    assert (first.row, first.col) == (5, 2)
    assert second.row == 0


def test_text_card_gets_virtual_card_settings_and_no_reuse_id():
    dashboard = ResolvedDashboard(
        name="D",
        tabs=(ResolvedTab(name="T", cards=(_card(text="Section", display="heading"),)),),
    )

    plan = _plan_dashboard(dashboard, existing=None)

    card = plan.tabs[0].cards[0]
    assert card.reuse_card_id is None
    assert card.text_visualization_settings == {
        "virtual_card": {"display": "heading"},
        "text": "Section",
    }
