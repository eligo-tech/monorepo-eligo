"""Reading a job advert into a proposed Suchprofil (ELI-6)."""

from app.domain.jobs.jobspec.base import JobSpec, JobSpecExtractor, ProposedField, html_to_text
from app.domain.jobs.jobspec.factory import get_job_spec_extractor
from app.domain.jobs.jobspec.fetch import NotFetchable, check_url, fetch_posting

__all__ = [
    "JobSpec",
    "JobSpecExtractor",
    "NotFetchable",
    "ProposedField",
    "check_url",
    "fetch_posting",
    "get_job_spec_extractor",
    "html_to_text",
]
