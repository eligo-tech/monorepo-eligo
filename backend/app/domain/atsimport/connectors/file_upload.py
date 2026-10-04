"""CSV / Excel — the source every ATS has, including the ones with no API.

A recruiter changing tools has an export long before they have an
integration, and the first question in an onboarding call is "can you take
our spreadsheet?". It was answerable before this file existed — `domain/imports`
has done the work since the file-import panel shipped: header detection,
column mapping with synonyms, identity-based upsert, preview before commit.
What it was not, was an OPTION. The settings screen offered "a connected
system" (one, named) and, somewhere else, an upload box.

So this registers the file path as what it is: one source among the others,
differing only in how it is read. `mode="file"` says a human brings the data
rather than the product fetching it — which is why it stores no credential,
the scheduled runner never picks it up, and it is not ingestion under
ARCHITECTURE.md RULE 1 (nothing is crawled; the bytes arrive with the
request).

The key is `datei-import`, which is what the importer has always written to
`source` on every row it creates. Keeping it means existing rows stay
recognisable and a re-uploaded file still updates rather than doubles.
"""

from __future__ import annotations

from app.domain.imports import spec


class FileUploadSource:
    """The CSV/Excel option. Reading happens in `domain/imports`."""

    key = spec.CANDIDATE.source  # "datei-import" — what the rows already say
    label = "CSV / Excel"
    hint = "Export aus dem bisherigen System hochladen — Spalten werden zugeordnet"
    mode = "file"

    @property
    def entities(self) -> list[str]:
        """What a file may contain, so the UI can offer the right mappings."""
        return sorted(spec.SPECS)
