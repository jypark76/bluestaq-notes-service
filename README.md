# Notes Service

A small REST API where several teams keep their own notes. Each team sees only its own notes. Built with FastAPI and SQLite.

## Run it

Needs Python 3.12 or newer.

    python -m venv .venv
    source .venv/bin/activate        # on Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn --factory src.main:create_app    # http://localhost:8000

Interactive API docs are at http://localhost:8000/docs.

The database is a SQLite file named `notes.db`, created on first run. Set `NOTES_DB_PATH` to put it somewhere else.

Try it:

    curl -X POST localhost:8000/notes \
      -H "X-Team-Id: team-a" -H "X-User-Id: user-1" \
      -H "Content-Type: application/json" \
      -d '{"title": "Plan", "body": "Ship it", "tags": ["work"]}'

    curl "localhost:8000/notes?q=ship&tag=work" \
      -H "X-Team-Id: team-a" -H "X-User-Id: user-1"

## Test it

    pytest

## What I built

Every call to `/notes` needs two headers: `X-Team-Id` (which team's notes) and `X-User-Id` (who is calling, saved as the note's author). A missing or blank header returns 400.

| Method and path | What it does |
|---|---|
| `POST /notes` | Create a note. Returns 201. Body: `title`, `body`, optional `tags`. |
| `GET /notes` | List the team's notes, newest edit first. Query: `q`, `tag`, `limit` (1 to 100, default 20), `offset`. Returns `{items, total}`. |
| `GET /notes/{id}` | Fetch one note. |
| `PATCH /notes/{id}` | Change any of `title`, `body`, `tags`. Fields you leave out stay as they are. |
| `DELETE /notes/{id}` | Delete a note. Returns 204. |
| `GET /health` | Liveness check. Needs no headers. |

Rules the service enforces:

- Title and body are trimmed and can't be empty. The title is at most 200 characters and the body at most 10,000.
- Tags are trimmed, lowercased and de-duplicated. A tag is at most 30 characters and a note has at most 20.
- `q` matches the title or body, ignoring letter case. `tag` matches one exact tag. Both can be combined with paging, and `total` counts every match.

Every error has the same shape:

    {"error": {"code": "not_found", "message": "note not found"}}

The codes are `missing_header` (400), `not_found` (404) and `invalid_input` (422). Bad input never produces a 500.

## Assumptions

- There is no real login. The two headers stand in for it, so anyone who sets a header is trusted. That is fine for this exercise and unsafe for production.
- Everyone on a team can see, edit and delete every note of that team. The author is recorded but doesn't limit who can edit.
- Timestamps are UTC in ISO 8601. Ids are opaque strings.
- A blank `q` or `tag` means "no filter" rather than an error.

## Trade-offs

These are the three choices I spent the most time on.

**1. Team isolation lives in one place, and another team's note looks like a missing one.**
Every store method takes a `team_id` and puts it in the SQL `WHERE` clause first. Search and tag filters are added after it, so a filter can't reach another team's notes. Asking for a note that belongs to another team returns the same 404 as a note that doesn't exist. A 403 would tell a caller that the id is real. The cost is that a mistyped id and a wrong team look the same when debugging.

**2. Three layers, with SQLite behind a small store class.**
Routes only translate HTTP. The service holds the rules (limits, cleanup, not-found). `NoteStore` holds all the SQL. This let me test the rules with no web server and the HTTP layer with an in-memory database, and swapping SQLite for Postgres means rewriting one class. The request models check only the shape of the input, so each limit is written once, in the service. The cost is a little more code than one file would need. SQLite also allows one writer at a time, so the store shares one connection behind a lock. That is fine at this size and would be the first thing to replace under heavy write load.

**3. Search uses plain `LIKE` and paging uses `limit` and `offset`.**
It needs no extra dependency, it is easy to read, and it is enough for notes at team scale. `%` and `_` in a search are escaped so they match themselves. The limits: SQLite's `LIKE` ignores letter case only for plain English letters (so `ünï` won't match `ÜNÏ`), a search scans the team's notes instead of using an index, and offset paging can skip or repeat a note if notes change between pages.

## What I cut (3-hour time box)

- Real authentication and team membership checks
- Per-note sharing and author-only edit rules
- Full-text search
- Database migrations
- Docker, CI and deployment
- Rate limiting and request logging

## What I would do next

1. Replace the headers with real authentication, and check team membership against a table.
2. Move search to SQLite FTS5 so it ranks results and handles non-English letter case.
3. Switch to keyset paging (continue from the last note seen) so pages stay stable.
4. Add migrations, and move to Postgres if more than one server needs to write.
5. Add optimistic concurrency on `PATCH` (reject an edit if the note changed since it was read).
6. Add structured request logging and basic metrics.

## AI usage

Built with Claude Code, which the prompt allows. I chose the scope and approved each step before the next was built. The tests were written alongside the code and all pass.
