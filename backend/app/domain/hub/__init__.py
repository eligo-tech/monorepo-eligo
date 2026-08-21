"""Information hub — layers 1–2 (sources & ingestion, canonical corpus).

The hub aggregates companies and their open roles from public sources. It is a
*corpus*, not the system-of-record: rows here are observed evidence about the
outside world, not recruiter-entered truth. Adoption of a hub company into a
tenant's CRM (`companies`) goes through the verification gate and leaves a
receipt — that boundary is where layer 4 applies.
"""
