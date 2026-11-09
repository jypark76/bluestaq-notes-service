import pytest

from src.errors import InvalidInputError, NotFoundError
from src.services.notes import (
    MAX_BODY_LENGTH,
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LENGTH,
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


@pytest.mark.parametrize("title", ["", "   "])
def test_create_rejects_empty_title(service, title):
    with pytest.raises(InvalidInputError, match="title"):
        service.create("team-a", "u", title, "body")


@pytest.mark.parametrize("body", ["", "\n  \t"])
def test_create_rejects_empty_body(service, body):
    with pytest.raises(InvalidInputError, match="body"):
        service.create("team-a", "u", "Title", body)


def test_blank_tag_is_rejected(service):
    with pytest.raises(InvalidInputError, match="tags"):
        service.create("team-a", "u", "T", "B", ["ok", "  "])


CASES = {
    "title": (lambda s, text: s.create("team-a", "u", text, "b"), MAX_TITLE_LENGTH),
    "body": (lambda s, text: s.create("team-a", "u", "T", text), MAX_BODY_LENGTH),
    "tag": (lambda s, text: s.create("team-a", "u", "T", "B", [text]), MAX_TAG_LENGTH),
    "search word": (lambda s, text: s.list_notes("team-a", q=text), MAX_SEARCH_LENGTH),
}


@pytest.mark.parametrize("use, limit", CASES.values(), ids=CASES.keys())
def test_length_limits_are_inclusive(service, use, limit):
    use(service, "x" * limit)  # exactly at the limit is accepted

    with pytest.raises(InvalidInputError, match="characters or fewer"):
        use(service, "x" * (limit + 1))


def test_too_many_tags_is_rejected_but_duplicates_do_not_count(service):
    many = [f"t{i}" for i in range(MAX_TAGS_PER_NOTE + 1)]
    with pytest.raises(InvalidInputError, match="at most"):
        service.create("team-a", "u", "T", "B", many)

    same_twenty_times = ["a"] * (MAX_TAGS_PER_NOTE + 5)
    assert service.create("team-a", "u", "T", "B", same_twenty_times).tags == ["a"]


# ---- get ------------------------------------------------------------


def test_get_unknown_note_raises_not_found(service):
    with pytest.raises(NotFoundError):
        service.get("team-a", "nope")


# ---- list -----------------------------------------------------------


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_SIZE + 1])
def test_list_rejects_bad_limit(service, limit):
    with pytest.raises(InvalidInputError, match="limit"):
        service.list_notes("team-a", limit=limit)


@pytest.mark.parametrize("limit", [1, MAX_PAGE_SIZE])
def test_list_accepts_the_smallest_and_largest_page_size(service, limit):
    created = service.create("team-a", "u", "T", "B")

    notes, total = service.list_notes("team-a", limit=limit)

    assert notes == [created]
    assert total == 1


@pytest.mark.parametrize("offset", [-1, MAX_OFFSET + 1, 10**20])
def test_list_rejects_offsets_outside_the_allowed_range(service, offset):
    with pytest.raises(InvalidInputError, match="offset must be between"):
        service.list_notes("team-a", offset=offset)


def test_list_accepts_the_largest_allowed_offset(service):
    service.create("team-a", "u", "T", "B")

    assert service.list_notes("team-a", offset=MAX_OFFSET) == ([], 1)


# ---- update ---------------------------------------------------------


def test_update_changes_only_what_was_sent(service):
    created = service.create("team-a", "u", "Old", "Body", ["keep"])

    updated = service.update("team-a", created.id, title="  New  ")

    assert updated.title == "New"
    assert updated.body == "Body"
    assert updated.tags == ["keep"]


def test_update_with_nothing_to_change_is_rejected(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(InvalidInputError, match="at least one"):
        service.update("team-a", created.id)


def test_update_runs_the_same_checks_as_create(service):
    created = service.create("team-a", "u", "T", "B")

    with pytest.raises(InvalidInputError, match="title"):
        service.update("team-a", created.id, title="   ")


# ---- delete ---------------------------------------------------------


# ---- search and tag filter -------------------------------------------


def test_tag_filter_ignores_letter_case_and_spaces(service):
    service.create("team-a", "u", "T", "B", ["work"])

    notes, _ = service.list_notes("team-a", tag="  WORK ")

    assert len(notes) == 1


def test_blank_search_and_blank_tag_mean_no_filter(service):
    service.create("team-a", "u", "T", "B", ["work"])

    notes, total = service.list_notes("team-a", q="   ", tag="")

    assert total == 1
    assert len(notes) == 1


# ---- characters the database cannot store -----------------------------


def test_text_with_a_lone_surrogate_is_rejected_not_crashed(service):
    bad = "\ud800"  # legal in JSON, but cannot be saved as UTF-8

    with pytest.raises(InvalidInputError, match="title contains"):
        service.create("team-a", "u", bad, "body")
    with pytest.raises(InvalidInputError, match="body contains"):
        service.create("team-a", "u", "Title", bad)
    with pytest.raises(InvalidInputError, match="tags contains"):
        service.create("team-a", "u", "Title", "body", [bad])
    with pytest.raises(InvalidInputError, match="q contains"):
        service.list_notes("team-a", q=bad)
    with pytest.raises(InvalidInputError, match="tag contains"):
        service.list_notes("team-a", tag=bad)
