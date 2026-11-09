from fastapi import APIRouter, Depends, Header, Request, Response, status

from src.errors import MissingIdentityError
from src.services.notes import DEFAULT_PAGE_SIZE, NoteService
from src.types import Identity, NoteCreate, NoteList, NoteOut, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])


def get_identity(
    x_team_id: str | None = Header(default=None, description="Which team's notes"),
    x_user_id: str | None = Header(default=None, description="Who is calling"),
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
    return Identity(team_id=team_id, user_id=user_id)


def get_service(request: Request) -> NoteService:
    """Hand each endpoint the one shared NoteService."""
    return request.app.state.service


# These endpoints only translate between HTTP and the service. The rules
# (what is allowed, who can see what) all live in services/notes.py.


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteCreate,
    who: Identity = Depends(get_identity),
    service: NoteService = Depends(get_service),
):
    return service.create(
        who.team_id, who.user_id, payload.title, payload.body, payload.tags
    )


@router.get("", response_model=NoteList)
def list_notes(
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    who: Identity = Depends(get_identity),
    service: NoteService = Depends(get_service),
):
    notes, total = service.list_notes(who.team_id, limit, offset, q=q, tag=tag)
    return NoteList(items=notes, total=total)


@router.get("/{note_id}", response_model=NoteOut)
def get_note(
    note_id: str,
    who: Identity = Depends(get_identity),
    service: NoteService = Depends(get_service),
):
    return service.get(who.team_id, note_id)


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: str,
    payload: NoteUpdate,
    who: Identity = Depends(get_identity),
    service: NoteService = Depends(get_service),
):
    return service.update(
        who.team_id, note_id, payload.title, payload.body, payload.tags
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: str,
    who: Identity = Depends(get_identity),
    service: NoteService = Depends(get_service),
):
    service.delete(who.team_id, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
