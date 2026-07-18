"""Reporting domain — read-only analytics aggregated over the existing
system-of-record (candidates, jobs, applications).

Unlike other domains it owns no table: it derives funnel, stage-dwell and
headline KPIs from live data, so numbers are always consistent with the record.
"""