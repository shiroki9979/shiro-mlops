"""Domain errors for Data Explorer queries and persistence access."""


class ExplorerQueryError(ValueError):
    """Raised when a list query uses an invalid bounded window or filter."""


class DatabaseUnavailableError(RuntimeError):
    """Raised when the operational store cannot be queried."""
