import itertools

import pytest

from src.store.notes import NoteStore


@pytest.fixture
def store():
    """A fresh empty database for each test, with a clock that ticks 1 second."""
    ticks = itertools.count(1)
    return NoteStore(":memory:", now=lambda: f"2026-01-01T00:00:{next(ticks):02d}")


def test_create_then_get_returns_the_same_note(store):
    created = store.create("team-a", "user-1", "Plan", "Ship it", ["work", "q4"])

    found = store.get("team-a", created.id)

    assert found == created
    assert found.tags == ["q4", "work"]  # tags come back sorted
    assert found.created_at == found.updated_at


def test_get_from_another_team_returns_none(store):
    created = store.create("team-a", "user-1", "Secret", "Only team A")

    assert store.get("team-b", created.id) is None


def test_get_unknown_id_returns_none(store):
    assert store.get("team-a", "nope") is None


def test_duplicate_tags_are_saved_once(store):
    created = store.create("team-a", "user-1", "T", "B", ["x", "x"])

    assert created.tags == ["x"]


def test_list_only_returns_own_team_and_counts_total(store):
    store.create("team-a", "u", "A1", "b")
    store.create("team-a", "u", "A2", "b")
    store.create("team-b", "u", "B1", "b")

    notes, total = store.list_notes("team-a")

    assert total == 2
    assert {n.title for n in notes} == {"A1", "A2"}


def test_list_is_newest_edit_first_and_paginates(store):
    for title in ["one", "two", "three"]:
        store.create("team-a", "u", title, "b")

    page1, total = store.list_notes("team-a", limit=2, offset=0)
    page2, _ = store.list_notes("team-a", limit=2, offset=2)

    assert total == 3
    assert [n.title for n in page1] == ["three", "two"]
    assert [n.title for n in page2] == ["one"]


def test_list_offset_past_the_end_is_empty(store):
    store.create("team-a", "u", "one", "b")

    notes, total = store.list_notes("team-a", offset=10)

    assert notes == []
    assert total == 1


def test_update_changes_given_fields_and_bumps_updated_at(store):
    created = store.create("team-a", "u", "Old", "Old body", ["keep"])

    updated = store.update("team-a", created.id, title="New")

    assert updated.title == "New"
    assert updated.body == "Old body"  # untouched
    assert updated.tags == ["keep"]  # untouched
    assert updated.created_at == created.created_at
    assert updated.updated_at > created.updated_at


def test_update_tags_replaces_them_and_empty_list_clears(store):
    created = store.create("team-a", "u", "T", "B", ["a", "b"])

    replaced = store.update("team-a", created.id, tags=["c"])
    cleared = store.update("team-a", created.id, tags=[])

    assert replaced.tags == ["c"]
    assert cleared.tags == []


def test_update_from_another_team_changes_nothing(store):
    created = store.create("team-a", "u", "Mine", "B")

    result = store.update("team-b", created.id, title="Hacked")

    assert result is None
    assert store.get("team-a", created.id).title == "Mine"


def test_delete_removes_the_note(store):
    created = store.create("team-a", "u", "T", "B")

    assert store.delete("team-a", created.id) is True
    assert store.get("team-a", created.id) is None


def test_delete_from_another_team_leaves_the_note(store):
    created = store.create("team-a", "u", "T", "B")

    assert store.delete("team-b", created.id) is False
    assert store.get("team-a", created.id) is not None


def test_deleting_a_note_also_deletes_its_tags(store):
    created = store.create("team-a", "u", "T", "B", ["x"])

    store.delete("team-a", created.id)
    leftover = store._db.execute("SELECT COUNT(*) FROM note_tags").fetchone()[0]

    assert leftover == 0


# ---- search and tag filter -------------------------------------------


def test_search_matches_title_or_body_ignoring_letter_case(store):
    store.create("team-a", "u", "Budget Review", "numbers")
    store.create("team-a", "u", "Lunch", "talk about the BUDGET")
    store.create("team-a", "u", "Unrelated", "nothing here")

    notes, total = store.list_notes("team-a", q="budget")

    assert total == 2
    assert {n.title for n in notes} == {"Budget Review", "Lunch"}


def test_search_never_returns_another_teams_notes(store):
    store.create("team-a", "u", "Mine", "budget")
    store.create("team-b", "u", "Theirs", "budget")

    notes, total = store.list_notes("team-a", q="budget")

    assert total == 1
    assert notes[0].title == "Mine"


def test_search_treats_percent_and_underscore_as_plain_characters(store):
    store.create("team-a", "u", "Goal", "reach 100% by June")
    store.create("team-a", "u", "Names", "use snake_case here")
    store.create("team-a", "u", "Plain", "nothing special")

    percent, _ = store.list_notes("team-a", q="%")
    underscore, _ = store.list_notes("team-a", q="_")

    assert [n.title for n in percent] == ["Goal"]
    assert [n.title for n in underscore] == ["Names"]


def test_search_with_no_match_is_empty(store):
    store.create("team-a", "u", "T", "B")

    assert store.list_notes("team-a", q="zzz") == ([], 0)


def test_tag_filter_matches_the_exact_tag_only(store):
    store.create("team-a", "u", "Has", "b", ["work"])
    store.create("team-a", "u", "Close", "b", ["workout"])
    store.create("team-a", "u", "None", "b")

    notes, total = store.list_notes("team-a", tag="work")

    assert total == 1
    assert notes[0].title == "Has"


def test_tag_filter_never_returns_another_teams_notes(store):
    store.create("team-a", "u", "Mine", "b", ["work"])
    store.create("team-b", "u", "Theirs", "b", ["work"])

    notes, total = store.list_notes("team-a", tag="work")

    assert [n.title for n in notes] == ["Mine"]
    assert total == 1


def test_search_and_tag_combine_and_total_ignores_paging(store):
    for i in range(3):
        store.create("team-a", "u", f"Plan {i}", "budget", ["work"])
    store.create("team-a", "u", "Other", "budget", ["home"])

    notes, total = store.list_notes("team-a", limit=2, q="budget", tag="work")

    assert total == 3  # all three matches, even though the page holds two
    assert len(notes) == 2
