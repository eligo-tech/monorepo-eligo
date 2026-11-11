"""Importing this module registers every application action on `REGISTRY`, then checks the catalog."""

from app.actions import candidates, contacts, jobs, market, matching, pipeline, proposals, reporting  # noqa: F401
from app.actions.core import REGISTRY

REGISTRY.check()
