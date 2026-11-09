import itertools
from datetime import UTC, datetime, timedelta

import pytest

from src.store.notes import NoteStore


@pytest.fixture
def store():
    """A fresh empty database for each test, with a clock that ticks 1 second."""
    ticks = itertools.count(1)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return NoteStore(
        ":memory:", now=lambda: (start + timedelta(seconds=next(ticks))).isoformat()
    )


def test_writes_in_the_same_clock_tick_still_sort_newest_first():
    frozen = NoteStore(":memory:", now=lambda: "2026-01-01T00:00:00+00:00")
    old = frozen.create("team-a", "u", "old", "b")
    frozen.create("team-a", "u", "middle", "b")
    frozen.create("team-a", "u", "newest", "b")

    created_order = [n.title for n in frozen.list_notes("team-a")[0]]
    frozen.update("team-a", old.id, body="edited")
    after_edit = [n.title for n in frozen.list_notes("team-a")[0]]

    assert created_order == ["newest", "middle", "old"]
    assert after_edit == ["old", "newest", "middle"]


def test_timestamps_keep_counting_up_after_a_restart(tmp_path):
    db_file = str(tmp_path / "notes.db")
    first = NoteStore(db_file, now=lambda: "2026-01-01T00:00:00+00:00")
    for i in range(6):
        first.create("team-a", "u", f"before {i}", "b")

    second = NoteStore(db_file, now=lambda: "2026-01-01T00:00:00+00:00")
    for i in range(6):
        second.create("team-a", "u", f"after {i}", "b")

    # Six of each: a random order of ties would almost never come out right.
    titles = [n.title.split()[0] for n in second.list_notes("team-a")[0]]
    assert titles == ["after"] * 6 + ["before"] * 6


def test_create_then_get_returns_the_same_note(store):
    created = store.create("team-a", "user-1", "Plan", "Ship it", ["work", "q4"])

    found = store.get("team-a", created.id)

    assert found == created
    assert found.tags == ["q4", "work"]  # tags come back sorted
    assert found.created_at == found.updated_at


def test_get_from_another_team_returns_none(store):
    created = store.create("team-a", "user-1", "Secret", "Only team A")

    assert store.get("team-b", created.id) is None


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
    created = store.create("team-a", "u", "Mine", "B", ["keep"])

    result = store.update("team-b", created.id, title="Hacked", tags=["hacked"])

    assert result is None
    owners_note = store.get("team-a", created.id)
    assert owners_note.title == "Mine"
    assert owners_note.tags == ["keep"]  # the tag write must not slip through


def test_delete_removes_the_note(store):
    created = store.create("team-a", "u", "T", "B")

    assert store.delete("team-a", created.id) is True
    assert store.get("team-a", created.id) is None


def test_delete_from_another_team_leaves_the_note(store):
    created = store.create("team-a", "u", "T", "B")

    assert store.delete("team-b", created.id) is False
    assert store.get("team-a", created.id) is not None


def test_a_deleted_note_no_longer_shows_up_in_search_or_tag_filter(store):
    created = store.create("team-a", "u", "Budget", "numbers", ["finance"])

    store.delete("team-a", created.id)

    assert store.list_notes("team-a", q="budget") == ([], 0)
    assert store.list_notes("team-a", tag="finance") == ([], 0)


def test_each_note_in_a_page_gets_its_own_tags(store):
    store.create("team-a", "u", "one", "b", ["x"])
    store.create("team-a", "u", "two", "b", ["y", "z"])
    store.create("team-a", "u", "none", "b")

    notes, _ = store.list_notes("team-a")

    assert {n.title: n.tags for n in notes} == {
        "one": ["x"],
        "two": ["y", "z"],
        "none": [],
    }


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


def test_search_treats_percent_underscore_and_backslash_as_plain_characters(store):
    store.create("team-a", "u", "Goal", "reach 100% by June")
    store.create("team-a", "u", "Names", "use snake_case here")
    store.create("team-a", "u", "Path", r"open C:\temp\file")
    store.create("team-a", "u", "Word", "a temporary note")
    store.create("team-a", "u", "Plain", "nothing special")

    def titles(word):
        notes, _ = store.list_notes("team-a", q=word)
        return [n.title for n in notes]

    assert titles("%") == ["Goal"]
    assert titles("_") == ["Names"]
    assert titles("\\") == ["Path"]
    assert titles("\\temp") == ["Path"]  # not "temporary"


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


# ---- edge cases ------------------------------------------------------


def test_notes_survive_a_restart(tmp_path):
    db_file = str(tmp_path / "notes.db")
    first = NoteStore(db_file)
    created = first.create("team-a", "u", "Keep me", "body", ["x"])

    second = NoteStore(db_file)  # same file, like restarting the server

    assert second.get("team-a", created.id) == created


def test_editing_an_old_note_moves_it_to_the_top(store):
    old = store.create("team-a", "u", "old", "b")
    store.create("team-a", "u", "newer", "b")

    store.update("team-a", old.id, body="edited")
    notes, _ = store.list_notes("team-a")

    assert [n.title for n in notes] == ["old", "newer"]


def test_unicode_text_round_trips_and_is_searchable(store):
    store.create("team-a", "u", "Café ☕ 日本語", "naïve résumé 🎉")

    notes, total = store.list_notes("team-a", q="résumé")
    emoji, _ = store.list_notes("team-a", q="🎉")

    assert total == 1
    assert notes[0].title == "Café ☕ 日本語"
    assert len(emoji) == 1


def test_many_threads_writing_at_once_lose_nothing(store):
    from concurrent.futures import ThreadPoolExecutor

    def add(i):
        store.create("team-a", "u", f"note {i}", "b", [f"t{i % 3}"])

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(add, range(100)))

    _, total = store.list_notes("team-a", limit=1)
    assert total == 100


def test_sql_in_search_and_tag_is_treated_as_plain_text(store):
    store.create("team-a", "u", "Safe", "b", ["x"])
    attack = "' OR 1=1 --"

    by_word = store.list_notes("team-a", q=attack)
    by_tag = store.list_notes("team-a", tag=attack)
    by_id = store.get("team-a", attack)

    assert by_word == ([], 0)
    assert by_tag == ([], 0)
    assert by_id is None
    assert store.list_notes("team-a")[1] == 1  # table is intact
