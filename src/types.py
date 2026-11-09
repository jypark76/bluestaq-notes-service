from dataclasses import dataclass, field


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
