"""Identity, taken from a reverse proxy and from nowhere else.

The browser app does not authenticate. A proxy in front of this service --
Google Cloud IAP, an AWS ALB with an ``authenticate-oidc`` listener rule, Azure
Easy Auth, or the Caddy front door in this repository's compose stack --
terminates the SSO flow and stamps the authenticated user onto every request as
a header. This module reads that header and turns it into an :class:`Identity`.

The one hard requirement
------------------------
**This service must be unreachable except through the proxy.** It trusts a
request header, and a header is trivially forged::

    curl -H 'X-Forwarded-Email: cmo@hospital.org' https://api.example.org/api/me

If that request can reach the container from anywhere other than the proxy,
anyone can be anyone. No code in this file can make up for a routable port.
Network isolation is the security boundary:

* **Google Cloud** -- Cloud Run ingress ``internal-and-cloud-load-balancing``,
  so only the load balancer carrying IAP can reach the revision.
* **AWS** -- ECS tasks in private subnets, no public IP, task security group
  accepting inbound *only* from the ALB's security group.
* **Azure** -- Easy Auth runs in front of the app container; do not expose a
  second ingress port past it.
* **Compose** -- the ``api`` service publishes no ports; only Caddy does.

Two second locks are available, both off by default and both defense in depth
rather than a substitute for closing the port:

``TRUSTED_PROXY_CIDR``
    Reject any request whose TCP peer address is outside these ranges. This is
    why the container does **not** run uvicorn with ``--proxy-headers``: that
    would rewrite the peer address from ``X-Forwarded-For``, which the client
    controls, and the check would be checking the attacker's own claim.

``PROXY_SHARED_SECRET``
    Reject any request that does not carry a secret only the proxy knows.

Identity is never read from the request body, a query parameter, or a cookie.
The audit log's ``by`` field is overwritten with the proxy identity on write
for the same reason.

One family of routes does not use any of this: the read-only agent API under
``/api/agent/`` answers to a per-user bearer token and ignores the identity header
(``app/agent.py``, #164). Nothing in this module reads a token, and no route that
asks for an :class:`Identity` accepts one.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import json
import logging
import time
from dataclasses import dataclass, replace
from typing import Any

from fastapi import HTTPException, Request, status

from .config import Settings
from .securitylog import SecurityEvent, emit

log = logging.getLogger("chai.auth")

__all__ = [
    "ANONYMOUS",
    "DEV_BANNER",
    "Identity",
    "check_network_locks",
    "client_address",
    "identity_from_request",
    "log_auth_posture",
]


@dataclass(frozen=True)
class Identity:
    """One authenticated person, as the proxy described them."""

    id: str
    name: str
    email: str
    dev: bool = False
    # True when this identity is one the deployment configured as break-glass
    # (EMERGENCY_ACCESS_IDS). Decided from configuration and the proxy's asserted id
    # alone, never from anything the client sent. See app/emergency.py (#42).
    emergency: bool = False


ANONYMOUS = Identity(id="anonymous", name="anonymous", email="", dev=False)
"""Used only when ``REQUIRE_IDENTITY=false``. Sign-offs recorded against this
are worthless for audit, which is why the default is to refuse the request."""


DEV_BANNER = r"""
  ######################################################################
  #                                                                    #
  #   DEV_INSECURE_AUTH=1 -- EVERY REQUEST IS AUTHENTICATED AS A       #
  #   FIXED FAKE USER. THE IDENTITY HEADER IS IGNORED ENTIRELY.        #
  #   ANYONE WHO CAN REACH THIS PORT IS THAT USER.                     #
  #                                                                    #
  #   This exists so the stack runs on a laptop with no proxy.         #
  #   If you are reading this in a deployed environment, STOP and      #
  #   unset DEV_INSECURE_AUTH.                                         #
  #                                                                    #
  ######################################################################
"""


def log_auth_posture(settings: Settings) -> None:
    """Say out loud, at startup, how this process decides who you are."""
    if settings.dev_insecure_auth:
        for line in DEV_BANNER.strip("\n").splitlines():
            log.warning(line)
        log.warning(
            "dev identity: %s <%s>",
            settings.dev_identity_name,
            settings.dev_identity_email,
        )
        return

    log.info(
        "identity: mode=%s header=%r format=%s%s",
        settings.identity_mode,
        settings.identity_header,
        settings.identity_header_format,
        f" strip={settings.identity_strip_prefix!r}"
        if settings.identity_strip_prefix
        else "",
    )
    if settings.trusted_proxy_cidrs:
        log.info(
            "peer address restricted to %s", ", ".join(settings.trusted_proxy_cidrs)
        )
    else:
        log.warning(
            "TRUSTED_PROXY_CIDR is unset: any host that can open a TCP "
            "connection to this port can set the identity header. Make sure "
            "the network makes that impossible."
        )
    if not settings.require_identity:
        log.warning(
            "REQUIRE_IDENTITY=false: requests with no identity header are "
            "served as 'anonymous'. Audit attribution is meaningless."
        )


# --- peer address -----------------------------------------------------------


def _networks(cidrs: list[str]) -> list[ipaddress._BaseNetwork]:
    nets = []
    for n, cidr in enumerate(cidrs, start=1):
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            # By position, not value: the entry is operator configuration that
            # travels with the settings object, which also holds secrets.
            log.error(
                "ignoring unparseable TRUSTED_PROXY_CIDR entry %d of %d", n, len(cidrs)
            )
    return nets


def client_address(request: Request, settings: Settings) -> str:
    """Who the rate limiter should count a request against: the socket peer.

    ``X-Real-IP`` is a header, so a client that reaches the API directly chooses it.
    It is believed only when ``TRUSTED_PROXY_CIDR`` is set and the peer is inside it,
    that is, when the peer is the proxy that wrote it. Otherwise (no range set) every
    caller behind the proxy shares the proxy's address, which limits them together
    but cannot be rotated by a client.

    The result is always a parsed IP address, or the literal ``unknown``: it becomes
    a bucket key and a log field, so it is never text a client chose. (uvicorn's own
    ``--proxy-headers`` would let a loopback peer set the peer address from
    ``X-Forwarded-For``; the image starts it with ``--no-proxy-headers``.)
    """
    peer = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return "unknown"
    if not settings.trusted_proxy_cidrs:
        return str(ip)
    if not any(ip in net for net in _networks(settings.trusted_proxy_cidrs)):
        return str(ip)
    reported = (request.headers.get("x-real-ip") or "").strip()
    try:
        return str(ipaddress.ip_address(reported))
    except ValueError:
        return str(ip)


def _check_peer(request: Request, settings: Settings) -> None:
    if not settings.trusted_proxy_cidrs:
        return
    client = request.client
    if client is None:  # ASGI transports without a peer, e.g. in-process tests
        return
    try:
        peer = ipaddress.ip_address(client.host)
    except ValueError:
        emit(
            SecurityEvent.AUTH_PEER_REJECTED,
            f"unparseable peer address {client.host!r}",
            method=request.method,
            path=request.url.path,
            peer=client.host,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request did not come through the authenticating proxy.",
        ) from None
    for net in _networks(settings.trusted_proxy_cidrs):
        if peer in net:
            return
    emit(
        SecurityEvent.AUTH_PEER_REJECTED,
        f"rejected {request.method} {request.url.path} from {peer}: "
        "outside TRUSTED_PROXY_CIDR",
        method=request.method,
        path=request.url.path,
        peer=str(peer),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Request did not come through the authenticating proxy.",
    )


def _check_shared_secret(request: Request, settings: Settings) -> None:
    if not settings.proxy_shared_secret:
        return
    presented = request.headers.get(settings.proxy_secret_header, "")
    if not hmac.compare_digest(presented, settings.proxy_shared_secret):
        emit(
            SecurityEvent.AUTH_SECRET_REJECTED,
            f"rejected request without a valid {settings.proxy_secret_header} header",
            method=request.method,
            path=request.url.path,
            header=settings.proxy_secret_header,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request did not come through the authenticating proxy.",
        )


# --- header parsing ---------------------------------------------------------


def _strip_prefix(value: str, prefix: str) -> str:
    """Remove a front-door-specific scheme prefix.

    Google IAP sends ``accounts.google.com:person@example.org``. Code that
    forgets to strip that prefix stores a user id nobody can match against a
    directory, so ``IDENTITY_MODE=iap`` sets the prefix for you.
    """
    if prefix and value.startswith(prefix):
        return value[len(prefix) :].strip()
    return value


def _jwt_segments(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode a JWT's header and payload **without verifying the signature**.

    AWS's ALB puts the user's claims in ``x-amzn-oidc-data``, a JWT it signs
    itself, because ``x-amzn-oidc-identity`` carries only the opaque ``sub``.
    Reading the claims is the only way to get an email address out of an ALB.

    The signature is not checked here, and that is safe for exactly the same
    reason the plain-header mode is safe and no other: the request can only
    have come from the ALB, because nothing else can reach the port. To check
    it properly, verify at the edge, or verify ``x-amzn-oidc-data`` against
    ``https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`` and require
    the token header's ``signer`` to equal your load balancer's ARN. ``docs/deploy.md``
    walks through why step 3 -- audience, not merely validity -- is the one
    people skip.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a three-segment JWT")
    out: list[dict[str, Any]] = []
    for segment in parts[:2]:
        segment += "=" * (-len(segment) % 4)  # restore base64url padding
        try:
            raw = base64.urlsafe_b64decode(segment)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("JWT segment is not base64url") from exc
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("JWT segment is not a JSON object")
        out.append(decoded)
    return out[0], out[1]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _identity_from_jwt(raw: str, settings: Settings) -> Identity:
    try:
        header, claims = _jwt_segments(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        emit(
            SecurityEvent.AUTH_TOKEN_UNREADABLE,
            f"could not decode {settings.identity_header}: {type(exc).__name__}",
            header=settings.identity_header,
            reason=type(exc).__name__,  # never the value: it is a credential
        )
        raise _unauthorized(
            f"{settings.identity_header} is not a readable JWT."
        ) from exc

    expires = claims.get("exp")
    if isinstance(expires, (int, float)) and expires < time.time():
        raise _unauthorized(f"{settings.identity_header} has expired.")

    if settings.identity_audience:
        # Catches a token minted for a different service in the same cloud
        # account. Without signature verification this stops misconfiguration,
        # not a determined forger -- see the module docstring.
        audience = claims.get("aud")
        signer = header.get("signer")
        candidates = audience if isinstance(audience, list) else [audience]
        if settings.identity_audience not in candidates and (
            signer != settings.identity_audience
        ):
            emit(
                SecurityEvent.AUTH_AUDIENCE_REJECTED,
                f"rejected assertion: aud={audience!r} signer={signer!r}, "
                f"expected {settings.identity_audience!r}",
                aud=audience,
                signer=signer,
                expected=settings.identity_audience,
            )
            raise _unauthorized(
                f"{settings.identity_header} was not issued for this service."
            )

    email = str(claims.get(settings.identity_jwt_email_claim) or "").strip()
    name = str(claims.get(settings.identity_jwt_name_claim) or "").strip()
    subject = str(claims.get(settings.identity_jwt_id_claim) or "").strip()
    if not email and not subject:
        raise _unauthorized(
            f"{settings.identity_header} carried neither "
            f"'{settings.identity_jwt_email_claim}' nor "
            f"'{settings.identity_jwt_id_claim}'."
        )
    email = email or subject
    return Identity(id=subject or email, name=name or email, email=email)


def _normalized(identity: Identity, settings: Settings) -> Identity:
    """Strip the front door's scheme prefix from every field, on every path.

    The id is the key every access list is matched against, so two ways of
    arriving as the same person must produce the same id. The strip used to be
    applied to plain headers only, so a JWT-format front door pointed at a
    prefixed claim stored ``accounts.google.com:...`` in access lists, which
    stopped matching the moment those people arrived another way, and every
    project silently vanished from its owner (#35). Done once, here, after both
    parsers, so they cannot diverge again.
    """
    prefix = settings.identity_strip_prefix
    if not prefix:
        return identity
    return replace(
        identity,
        id=_strip_prefix(identity.id, prefix),
        name=_strip_prefix(identity.name, prefix),
        email=_strip_prefix(identity.email, prefix),
    )


def _identity_from_plain(raw: str, request: Request, settings: Settings) -> Identity:
    email = raw
    name = ""
    if settings.identity_name_header:
        name = (request.headers.get(settings.identity_name_header) or "").strip()
    user_id = ""
    if settings.identity_id_header:
        user_id = (request.headers.get(settings.identity_id_header) or "").strip()
    if not _strip_prefix(email, settings.identity_strip_prefix):
        raise _unauthorized(
            f"{settings.identity_header} was present but empty after parsing."
        )
    return Identity(id=user_id or email, name=name or email, email=email)


def check_network_locks(request: Request, settings: Settings) -> None:
    """The two second locks, ``TRUSTED_PROXY_CIDR`` then ``PROXY_SHARED_SECRET``.

    Raises 403. The agent routes (#164) answer to a bearer token and not to an
    identity header, but they sit behind the same proxy and must not be reachable
    around it either, so they take the same two locks.
    """
    _check_peer(request, settings)
    _check_shared_secret(request, settings)


def identity_from_request(request: Request, settings: Settings) -> Identity:
    """Build an :class:`Identity`, or raise 401 / 403.

    A 401 here means the identity header was missing or unreadable. In a
    correct deployment that cannot happen -- the proxy sets it on every request
    it forwards -- so a 401 in production almost always means traffic reached
    the service *around* the proxy. That is worth alerting on.
    """
    # The network locks come FIRST, including in dev mode. They used to come
    # after, which meant DEV_INSECURE_AUTH did not merely fake an identity --
    # it also switched off TRUSTED_PROXY_CIDR and PROXY_SHARED_SECRET, the two
    # things documented as defense in depth for exactly this situation. A dev
    # flag should weaken one layer, not all three.
    check_network_locks(request, settings)

    if settings.dev_insecure_auth:
        return Identity(
            id=settings.dev_identity_email,
            name=settings.dev_identity_name,
            email=settings.dev_identity_email,
            dev=True,
        )

    raw = (request.headers.get(settings.identity_header) or "").strip()
    if not raw:
        if not settings.require_identity:
            return ANONYMOUS
        emit(
            SecurityEvent.AUTH_NO_IDENTITY,
            f"no {settings.identity_header} header on {request.method} "
            f"{request.url.path} -- is this request bypassing the proxy?",
            header=settings.identity_header,
            method=request.method,
            path=request.url.path,
        )
        raise _unauthorized(
            f"No {settings.identity_header} header. This API only accepts "
            "requests from an authenticating reverse proxy."
        )

    if settings.identity_header_format == "jwt":
        identity = _normalized(_identity_from_jwt(raw, settings), settings)
    else:
        identity = _normalized(_identity_from_plain(raw, request, settings), settings)
    if identity.id in settings.emergency_access_ids:
        identity = replace(identity, emergency=True)
    return identity
