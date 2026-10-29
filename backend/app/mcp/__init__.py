"""The MCP server: AI clients (Claude) read the workspace through the action registry.

Layer: API surface, beside `app/api`. It authenticates, admits and gates; the
actions in `app/actions` do the work. See ADR 0003.
"""
