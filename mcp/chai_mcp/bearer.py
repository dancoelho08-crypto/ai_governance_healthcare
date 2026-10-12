"""Reading a bearer token out of an Authorization header, in one place.

Used by the HTTP front (does the request carry one?) and by the tools (which one?).
"""

from __future__ import annotations

import re


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


# A token exactly as the agent API mints one (server/app/agent_tokens.py): agt_, 16 hex
# characters of public id, a dot, 43 characters of URL-safe base64. A credential of any
# other shape cannot be a token, so it is refused here, before a slot is taken and
# before any request is made. ASCII only: a header with another character is not one.
TOKEN_SHAPE = re.compile(r"agt_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}", re.ASCII)


def is_token_shaped(credential: str) -> bool:
    return TOKEN_SHAPE.fullmatch(credential) is not None
