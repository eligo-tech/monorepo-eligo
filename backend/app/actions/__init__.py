"""The action registry: every capability, named once, with its effect and who may use it.

Layer: between the API surfaces (REST today, MCP next) and the domain
services. An action wraps a service call; it never builds a query itself.
"""
