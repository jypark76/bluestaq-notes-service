from src.errors import InvalidInputError, NotFoundError
from src.store.notes import NoteStore
from src.types import Note

MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 10_000
MAX_TAGS_PER_NOTE = 20
MAX_TAG_LENGTH = 30
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000
MAX_SEARCH_LENGTH = 100


class NoteService:
    """The rules for notes. It knows nothing about web requests or SQL.

    It cleans up and checks whatever the caller sends, then asks the store
    to save or load. Problems are raised as InvalidInputError or NotFoundError.
    """

    def __init__(self, store: NoteStore):
        self._store = store

    def create(
        self,
        team_id: str,
        author_id: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
    ) -> Note:
        return self._store.create(
            team_id,
            author_id,
            _clean_title(title),
            _clean_body(body),
            _clean_tags(tags or []),
        )

    def get(self, team_id: str, note_id: str) -> Note:
        note = self._store.get(team_id, note_id)
        if note is None:
            raise NotFoundError(note_id)
        return note

    def list_notes(
        self,
        team_id: str,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        q: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[Note], int]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidInputError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        # The upper limit also keeps a huge number from overflowing the database.
        if not 0 <= offset <= MAX_OFFSET:
            raise InvalidInputError(f"offset must be between 0 and {MAX_OFFSET}")
        _check_text(q or "", "q")
        _check_text(tag or "", "tag")
        # A blank search word or blank tag filter is treated as "not given".
        q = (q or "").strip() or None
        tag = (tag or "").strip().lower() or None
        if q and len(q) > MAX_SEARCH_LENGTH:
            raise InvalidInputError(
                f"q must be {MAX_SEARCH_LENGTH} characters or fewer"
            )
        return self._store.list_notes(team_id, limit, offset, q=q, tag=tag)

    def update(
        self,
        team_id: str,
        note_id: str,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
    ) -> Note:
        """Change only the fields the caller sent."""
        if title is None and body is None and tags is None:
            raise InvalidInputError("send at least one of: title, body, tags")
        note = self._store.update(
            team_id,
            note_id,
            title=None if title is None else _clean_title(title),
            body=None if body is None else _clean_body(body),
            tags=None if tags is None else _clean_tags(tags),
        )
        if note is None:
            raise NotFoundError(note_id)
        return note

    def delete(self, team_id: str, note_id: str) -> None:
        if not self._store.delete(team_id, note_id):
            raise NotFoundError(note_id)


# ---- cleanup and checks --------------------------------------------


def _check_text(value: str, field: str) -> None:
    """Refuse text that cannot be stored (for example a lone surrogate).

    JSON allows such characters but the database cannot save them. Without
    this check they would crash the request instead of giving a clear error.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidInputError(f"{field} contains invalid characters") from None


def _clean_title(title: str) -> str:
    _check_text(title, "title")
    title = title.strip()
    if not title:
        raise InvalidInputError("title must not be empty")
    if len(title) > MAX_TITLE_LENGTH:
        raise InvalidInputError(f"title must be {MAX_TITLE_LENGTH} characters or fewer")
    return title


def _clean_body(body: str) -> str:
    _check_text(body, "body")
    body = body.strip()
    if not body:
        raise InvalidInputError("body must not be empty")
    if len(body) > MAX_BODY_LENGTH:
        raise InvalidInputError(f"body must be {MAX_BODY_LENGTH} characters or fewer")
    return body


def _clean_tags(tags: list[str]) -> list[str]:
    """Trim, lowercase and de-duplicate tags, keeping the order given."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        _check_text(tag, "tags")
        tag = tag.strip().lower()
        if not tag:
            raise InvalidInputError("tags must not be empty")
        if len(tag) > MAX_TAG_LENGTH:
            raise InvalidInputError(
                f"each tag must be {MAX_TAG_LENGTH} characters or fewer"
            )
        if tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
            # Stop at the first tag over the limit. Checking only at the end
            # let one huge request keep the server busy for many seconds.
            if len(cleaned) > MAX_TAGS_PER_NOTE:
                raise InvalidInputError(
                    f"a note can have at most {MAX_TAGS_PER_NOTE} tags"
                )
    return cleaned
