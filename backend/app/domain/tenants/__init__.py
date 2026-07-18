"""Tenants domain — the organization boundary.

A Tenant maps a Clerk **organization** (`clerk_org_id`) to the internal
`tenant_id` that every other table is scoped by. This is the single place the
external identity provider meets the data model: auth resolves the org, this
maps it to a tenant, and every query (and, in production, Postgres RLS) isolates
on that tenant.

Unlike other domains, Tenant is NOT itself tenant-scoped (no `tenant_id`).
"""
