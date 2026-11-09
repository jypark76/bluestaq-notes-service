class NotFoundError(Exception):
    """The note does not exist, or it belongs to a different team.

    We use one error for both cases on purpose, so a caller can never
    learn that another team's note exists.
    """


class InvalidInputError(Exception):
    """The caller sent something we refuse to save. The message says why."""
