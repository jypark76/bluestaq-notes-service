from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict


@dataclass
class Note:
    """One note, exactly as the store hands it back."""

    id: str
    team_id: str
    author_id: str
    title: str
    body: str
    created_at: str
    updated_at: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Identity:
    """Who is calling, taken from the request headers."""

    team_id: str
    user_id: str


# ---- what clients send and receive over HTTP --------------------------
# These only check the shape (is it text? is it a list?). The real rules
# live in the service so there is a single place to read them.


class NoteCreate(BaseModel):
    title: str
    body: str
    tags: list[str] | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    author_id: str
    title: str
    body: str
    tags: list[str]
    created_at: str
    updated_at: str


class NoteList(BaseModel):
    items: list[NoteOut]
    total: int
