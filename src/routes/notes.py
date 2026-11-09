from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from src.errors import InvalidIdentityError, MissingIdentityError
from src.services.notes import DEFAULT_PAGE_SIZE, NoteService
from src.types import Identity, NoteCreate, NoteList, NoteOut, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])

MAX_IDENTITY_LENGTH = 100


def get_identity(
    x_team_id: Annotated[str | None, Header(description="Which team's notes")] = None,
    x_user_id: Annotated[str | None, Header(description="Who is calling")] = None,
) -> Identity:
    """Read who is calling from the X-Team-Id and X-User-Id headers.

    There is no real login in this project. The headers stand in for it.
    Declaring them here makes them show up as fields on the /docs page.
    A missing header is checked by hand so it gives our own 400 error.
    """
    team_id = (x_team_id or "").strip()
    user_id = (x_user_id or "").strip()
    if not team_id:
        raise MissingIdentityError("X-Team-Id header is required")
    if not user_id:
        raise MissingIdentityError("X-User-Id header is required")
    for name, value in (("X-Team-Id", team_id), ("X-User-Id", user_id)):
        if len(value) > MAX_IDENTITY_LENGTH:
            raise InvalidIdentityError(
                f"{name} header must be {MAX_IDENTITY_LENGTH} characters or fewer"
            )
    return Identity(team_id=team_id, user_id=user_id)


def get_service(request: Request) -> NoteService:
    """Hand each endpoint the one shared NoteService."""
    return request.app.state.service


# Short names for the two things every endpoint needs.
Caller = Annotated[Identity, Depends(get_identity)]
Notes = Annotated[NoteService, Depends(get_service)]


# These endpoints only translate between HTTP and the service. The rules
# (what is allowed, who can see what) all live in services/notes.py.


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, who: Caller, service: Notes):
    return service.create(
        who.team_id, who.user_id, payload.title, payload.body, payload.tags
    )


@router.get("", response_model=NoteList)
def list_notes(
    who: Caller,
    service: Notes,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
):
    notes, total = service.list_notes(who.team_id, limit, offset, q=q, tag=tag)
    return NoteList(items=notes, total=total)


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: str, who: Caller, service: Notes):
    return service.get(who.team_id, note_id)


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(note_id: str, payload: NoteUpdate, who: Caller, service: Notes):
    return service.update(
        who.team_id, note_id, payload.title, payload.body, payload.tags
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: str, who: Caller, service: Notes):
    service.delete(who.team_id, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
