"""Verification domain.

The trust boundary between agents and the system-of-record. Agents never write
directly: they *propose*, and ``verify_and_commit`` checks postconditions and
records a tamper-evident ``Receipt`` before any change is persisted.
"""