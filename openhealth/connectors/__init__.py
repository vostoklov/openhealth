"""Data connectors — turn exports from devices/apps into canonical records.

Each connector is a pure function that reads an export and returns Observation-
shaped dicts (see openhealth.models.Observation), graded and dated, ready for the
index. Connectors meet people where they are: the lowest-friction one (Apple
Health export) needs only an iPhone.
"""

from .apple_health import import_apple_health  # noqa: F401

__all__ = ["import_apple_health"]
