"""Reading a bearer token out of an Authorization header, in one place.

Used by the HTTP front (does the request carry one?) and by the tools (which one?).
"""

from __future__ import annotations


def bearer_token(header: str | None) -> str | None:
    """The credential of ``Authorization: Bearer <credential>``, or None.

    The scheme name is case-insensitive (RFC 7235). Nothing is checked about the
    credential itself: whether it is right is the agent API's answer to give.
    """
    scheme, _, credentials = (header or "").partition(" ")
    credentials = credentials.strip()
    if scheme.lower() != "bearer" or not credentials:  # enum-ok: RFC 6750 scheme name
        return None
    return credentials
