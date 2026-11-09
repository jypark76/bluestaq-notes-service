import pytest

from src.errors import InvalidInputError, NotFoundError
from src.services.notes import (
    MAX_BODY_LENGTH,
    MAX_PAGE_SIZE,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_NOTE,
    MAX_TITLE_LENGTH,
    NoteService,
)
from src.store.notes import NoteStore


@pytest.fixture
def service():
    """A service on top of a fresh empty database."""
    return NoteService(NoteStore(":memory:"))


# ---- create ---------------------------------------------------------


def test_create_trims_text_and_cleans_tags(service):
    note = service.create(
        "team-a", "user-1", "  Plan  ", "  Ship it  ", [" Work ", "WORK", "q4"]
    )

    assert note.title == "Plan"
    assert note.body == "Ship it"
    assert note.tags == ["q4", "work"]  # lowercased, de-duplicated, sorted by store
    assert note.author_id == "user-1"


def test_create_without_tags_gives_empty_list(service):
    assert service.create("team-a", "u", "T", "B").tags == []


@pytest.mark.parametrize("title", ["", "   "])
def test_create_rejects_empty_title(service, title):
    with pytest.raises(InvalidInputError, match="title"):
        service.create("team-a", "u", title, "body")


@pytest.mark.parametrize("body", ["", "\n  \t"])
def test_create_rejects_empty_body(service, body):
    with pytest.raises(InvalidInputError, match="body"):
        service.create("team-a", "u", "Title", body)


def test_title_length_limit_is_inclusive(service):
    ok = service.create("team-a", "u", "x" * MAX_TITLE_LENGTH, "b")
    assert len(ok.title) == MAX_TITLE_LENGTH

    with pytest.raises(InvalidInputError, match="title"):
        service.create("team-a", "u", "x" * (MAX_TITLE_LENGTH + 1), "b")


def test_body_too_long_is_rejected(service):
    with pytest.raises(InvalidInputError, match="body"):
        service.create("team-a", "u", "T", "x" * (MAX_BODY_LENGTH + 1))


def test_blank_tag_is_rejected(service):
    with pytest.raises(InvalidInputError, match="tags"):
        service.create("team-a", "u", "T", "B", ["ok", "  "])


def test_tag_length_limit(service):
    with pytest.raises(InvalidInputError, match="tag"):
        service.create("team-a", "u", "T", "B", ["x" * (MAX_TAG_LENGTH + 1)])


def test_too_many_tags_is_rejected_but_duplicates_do_not_count(service):
    many = [f"t{i}" for i in range(MAX_TAGS_PER_NOTE + 1)]
    with pytest.raises(InvalidInputError, match="at most"):
        service.create("team-a", "u", "T", "B", many)

    same_twenty_times = ["a"] * (MAX_TAGS_PER_NOTE + 5)
    assert service.create("team-a", "u", "T", "B", same_twenty_times).tags == ["a"]


# ---- get ------------------------------------------------------------


def test_get_returns_the_note(service):
    created = service.create("team-a", "u", "T", "B")

    assert service.get("team-a", created.id) == created


def test_get_unknown_note_raises_not_found(service):
    with pytest.raises(NotFoundError):
        service.get("team-a", "nope")


def test_get_other_teams_note_raises_not_found(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(NotFoundError):
        service.get("team-b", created.id)


# ---- list -----------------------------------------------------------


def test_list_returns_own_team_notes_and_total(service):
    service.create("team-a", "u", "A", "b")
    service.create("team-b", "u", "B", "b")

    notes, total = service.list_notes("team-a")

    assert total == 1
    assert notes[0].title == "A"


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_SIZE + 1])
def test_list_rejects_bad_limit(service, limit):
    with pytest.raises(InvalidInputError, match="limit"):
        service.list_notes("team-a", limit=limit)


def test_list_accepts_the_largest_allowed_limit(service):
    service.list_notes("team-a", limit=MAX_PAGE_SIZE)


def test_list_rejects_negative_offset(service):
    with pytest.raises(InvalidInputError, match="offset"):
        service.list_notes("team-a", offset=-1)


# ---- update ---------------------------------------------------------


def test_update_changes_only_what_was_sent(service):
    created = service.create("team-a", "u", "Old", "Body", ["keep"])

    updated = service.update("team-a", created.id, title="  New  ")

    assert updated.title == "New"
    assert updated.body == "Body"
    assert updated.tags == ["keep"]


def test_update_can_clear_tags(service):
    created = service.create("team-a", "u", "T", "B", ["a"])

    assert service.update("team-a", created.id, tags=[]).tags == []


def test_update_with_nothing_to_change_is_rejected(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(InvalidInputError, match="at least one"):
        service.update("team-a", created.id)


def test_update_runs_the_same_checks_as_create(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(InvalidInputError, match="title"):
        service.update("team-a", created.id, title="   ")


def test_update_other_teams_note_raises_not_found_and_changes_nothing(service):
    created = service.create("team-a", "u", "Mine", "B")

    with pytest.raises(NotFoundError):
        service.update("team-b", created.id, title="Hacked")

    assert service.get("team-a", created.id).title == "Mine"


# ---- delete ---------------------------------------------------------


def test_delete_removes_the_note(service):
    created = service.create("team-a", "u", "T", "B")

    service.delete("team-a", created.id)

    with pytest.raises(NotFoundError):
        service.get("team-a", created.id)


def test_delete_other_teams_note_raises_not_found_and_keeps_it(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(NotFoundError):
        service.delete("team-b", created.id)

    assert service.get("team-a", created.id) == created
