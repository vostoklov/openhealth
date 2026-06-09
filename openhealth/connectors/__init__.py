"""Data connectors — turn exports from devices/apps into canonical records.

Each connector is a pure function that reads an export and returns Observation-
shaped dicts (see openhealth.models.Observation), graded and dated, ready for the
index. Connectors meet people where they are: the lowest-friction one (Apple
Health export) needs only an iPhone.
"""

from .apple_health import import_apple_health  # noqa: F401
from .google_calendar import (  # noqa: F401
    GoogleCalendarClient,
    GoogleCalendarError,
    ensure_derived_calendar,
    list_available_calendars,
    load_google_calendar_config,
    sync_google_calendar,
)

__all__ = [
    "import_apple_health",
    "GoogleCalendarClient",
    "GoogleCalendarError",
    "ensure_derived_calendar",
    "list_available_calendars",
    "load_google_calendar_config",
    "sync_google_calendar",
]
