import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from src.types import Note

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY,
    team_id    TEXT NOT NULL,
    author_id  TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_team_updated
    ON notes (team_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);
-- The primary key starts with note_id, so a lookup by tag needs its own index.
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags (tag, note_id);
"""


def _utc_now() -> str:
    """Current time as a text timestamp, always in UTC."""
    return datetime.now(UTC).isoformat()


def _escape_like(text: str) -> str:
    """Make % and _ in a search word match themselves instead of acting as wildcards."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class NoteStore:
    """Saves and loads notes in SQLite.

    Every method needs a team_id and only ever touches that team's notes.
    The rest of the app never writes SQL, so the database can be swapped
    later by replacing just this class.
    """

    def __init__(self, path: str = ":memory:", now: Callable[[], str] = _utc_now):
        # The web server handles requests on several threads, so we allow
        # sharing one connection and take a lock around every operation.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._now = now  # swappable so tests can control the clock
        # The newest timestamp handed out so far, so a restart keeps counting up.
        self._last: str | None = self._db.execute(
            "SELECT MAX(updated_at) FROM notes"
        ).fetchone()[0]

    def _stamp(self) -> str:
        """A timestamp that is always later than the one before it.

        A coarse clock (about 16 ms on Windows) can give two writes the same
        time, and then "newest first" would fall back to the random id. If the
        clock has not moved, nudge it forward by one microsecond.
        """
        stamp = self._now()
        if self._last is not None and stamp <= self._last:
            stamp = (
                datetime.fromisoformat(self._last) + timedelta(microseconds=1)
            ).isoformat()
        self._last = stamp
        return stamp

    # ---- create ----------------------------------------------------

    def create(
        self,
        team_id: str,
        author_id: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
    ) -> Note:
        """Save a new note and return it."""
        note_id = uuid.uuid4().hex
        with self._lock, self._db:  # "with self._db" saves, or undoes on error
            stamp = self._stamp()
            self._db.execute(
                "INSERT INTO notes (id, team_id, author_id, title, body,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, team_id, author_id, title, body, stamp, stamp),
            )
            self._write_tags(note_id, tags or [])
            return self._fetch(team_id, note_id)

    # ---- read ------------------------------------------------------

    def get(self, team_id: str, note_id: str) -> Note | None:
        """Return one note, or None if it is missing or belongs to another team."""
        with self._lock:
            return self._fetch(team_id, note_id)

    def list_notes(
        self,
        team_id: str,
        limit: int = 20,
        offset: int = 0,
        q: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[Note], int]:
        """Return one page of the team's notes (newest edit first) and the total.

        q keeps notes whose title or body contains that text (any letter case).
        tag keeps notes that carry exactly that tag. The total counts every
        match, not just this page.
        """
        # The team check always comes first, so a filter can never reach
        # another team's notes.
        where = ["team_id = ?"]
        params: list[str] = [team_id]
        if q:
            pattern = f"%{_escape_like(q)}%"
            where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
            params += [pattern, pattern]
        if tag:
            where.append("id IN (SELECT note_id FROM note_tags WHERE tag = ?)")
            params.append(tag)
        condition = " AND ".join(where)

        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) FROM notes WHERE {condition}", params
            ).fetchone()[0]
            rows = self._db.execute(
                f"SELECT * FROM notes WHERE {condition}"
                " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return self._to_notes(rows), total

    # ---- update ----------------------------------------------------

    def update(
        self,
        team_id: str,
        note_id: str,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
    ) -> Note | None:
        """Change only the fields given. None means "leave it alone".

        Passing tags=[] clears all tags. Returns None if the note is missing
        or belongs to another team.
        """
        with self._lock, self._db:
            # One statement changes the fields and checks the team. COALESCE
            # keeps the old value when we pass None. If nothing matched, the
            # note is missing or another team's, and nothing else is touched.
            cursor = self._db.execute(
                "UPDATE notes SET title = COALESCE(?, title),"
                " body = COALESCE(?, body), updated_at = ?"
                " WHERE id = ? AND team_id = ?",
                (title, body, self._stamp(), note_id, team_id),
            )
            if cursor.rowcount == 0:
                return None
            if tags is not None:
                self._write_tags(note_id, tags)
            return self._fetch(team_id, note_id)

    # ---- delete ----------------------------------------------------

    def delete(self, team_id: str, note_id: str) -> bool:
        """Remove a note. Returns False if it was missing or another team's."""
        with self._lock, self._db:
            cursor = self._db.execute(
                "DELETE FROM notes WHERE id = ? AND team_id = ?", (note_id, team_id)
            )
            return cursor.rowcount > 0

    # ---- helpers (callers must already hold the lock) ----------------

    def _fetch(self, team_id: str, note_id: str) -> Note | None:
        row = self._db.execute(
            "SELECT * FROM notes WHERE id = ? AND team_id = ?", (note_id, team_id)
        ).fetchone()
        return self._to_notes([row])[0] if row else None

    def _to_notes(self, rows: list[sqlite3.Row]) -> list[Note]:
        """Turn rows into notes, loading every note's tags in one query.

        A page is at most 100 notes (the service enforces that), so the list
        of ids stays well inside SQLite's limit on query parameters.
        """
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        marks = ",".join("?" * len(ids))
        tag_rows = self._db.execute(
            f"SELECT note_id, tag FROM note_tags WHERE note_id IN ({marks})"
            " ORDER BY tag",
            ids,
        ).fetchall()
        tags_by_note: dict[str, list[str]] = {}
        for tag_row in tag_rows:
            tags_by_note.setdefault(tag_row["note_id"], []).append(tag_row["tag"])
        return [
            Note(
                id=row["id"],
                team_id=row["team_id"],
                author_id=row["author_id"],
                title=row["title"],
                body=row["body"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                tags=tags_by_note.get(row["id"], []),
            )
            for row in rows
        ]

    def _write_tags(self, note_id: str, tags: list[str]) -> None:
        """Replace a note's tags with exactly this list."""
        self._db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        self._db.executemany(
            "INSERT OR IGNORE INTO note_tags (note_id, tag) VALUES (?, ?)",
            [(note_id, tag) for tag in tags],
        )
