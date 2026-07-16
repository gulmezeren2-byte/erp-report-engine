"""Exception taxonomy with stable process exit codes.

An unattended run is only useful if the scheduler (or CI) can tell *why* it
failed, not merely *that* it did. Every engine error carries an ``exit_code``
so a Task Scheduler "on failure" action or a CI gate can branch:

    0  success
    1  unexpected/unhandled error
    2  configuration error (bad or missing config)
    3  database/connection error
    4  contract error (profile schema wrong, or source reconciliation mismatch)
    5  data-quality gate failure (only surfaced under --strict)
"""

from __future__ import annotations


class EngineError(Exception):
    """Base for all engine errors. ``exit_code`` is the process exit status."""

    exit_code = 1


class ConfigError(EngineError):
    exit_code = 2


class DatabaseError(EngineError):
    exit_code = 3


class ContractError(EngineError):
    """A profile/schema contract was not met (missing columns, unparseable
    profile, or fetched rows not reconciling with the source count)."""

    exit_code = 4


class DataQualityError(EngineError):
    """The data-quality gate flagged an issue and the run was invoked --strict."""

    exit_code = 5
