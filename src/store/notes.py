import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

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
"""


def _utc_now() -> str:
    """Current time as a text timestamp, always in UTC."""
    return datetime.now(timezone.utc).isoformat()


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
        stamp = self._now()
        with self._lock, self._db:  # "with self._db" saves, or undoes on error
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
        self, team_id: str, limit: int = 20, offset: int = 0
    ) -> tuple[list[Note], int]:
        """Return one page of the team's notes (newest edit first) and the total."""
        with self._lock:
            total = self._db.execute(
                "SELECT COUNT(*) FROM notes WHERE team_id = ?", (team_id,)
            ).fetchone()[0]
            rows = self._db.execute(
                "SELECT * FROM notes WHERE team_id = ?"
                " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (team_id, limit, offset),
            ).fetchall()
            return [self._to_note(row) for row in rows], total

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
            if self._fetch(team_id, note_id) is None:
                return None
            if title is not None:
                self._db.execute(
                    "UPDATE notes SET title = ? WHERE id = ?", (title, note_id)
                )
            if body is not None:
                self._db.execute(
                    "UPDATE notes SET body = ? WHERE id = ?", (body, note_id)
                )
            if tags is not None:
                self._write_tags(note_id, tags)
            self._db.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?", (self._now(), note_id)
            )
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
        return self._to_note(row) if row else None

    def _to_note(self, row: sqlite3.Row) -> Note:
        tag_rows = self._db.execute(
            "SELECT tag FROM note_tags WHERE note_id = ? ORDER BY tag", (row["id"],)
        ).fetchall()
        return Note(
            id=row["id"],
            team_id=row["team_id"],
            author_id=row["author_id"],
            title=row["title"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=[t["tag"] for t in tag_rows],
        )

    def _write_tags(self, note_id: str, tags: list[str]) -> None:
        """Replace a note's tags with exactly this list."""
        self._db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        self._db.executemany(
            "INSERT OR IGNORE INTO note_tags (note_id, tag) VALUES (?, ?)",
            [(note_id, tag) for tag in tags],
        )
