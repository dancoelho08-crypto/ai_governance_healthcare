"""A read-only MCP server over the governance dashboard's agent API (#164, R-73, D-91).

Optional and off by default. It holds no credential of its own: each request's own
bearer token is forwarded, for that request only, to the agent API's three GET routes.
"""
