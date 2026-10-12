"""What a hostile caller can and cannot do to the MCP service (#164, review H3, M2, M3).

Each test is an attack the review made, kept as a test: garbage credentials that must not
take a slot, one source that must not take them all, a request body trickled forever, a
body that tries to write the log, and a flood that must not become a larger flood of log.
The service is real (a real socket, or a real process); the agent API is a recording
stand-in, so what the service sends it can be counted.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from chai_mcp.bearer import is_token_shaped
from chai_mcp.logs import Bound, OneLine, Reduce, configure_logging
from chai_mcp.server import Slots, ToolFailure
from chai_mcp.upstream import Message

from .harness import (
    INIT,
    TOKEN_OK,
    FakeAPI,
    ServiceProcess,
    call,
    raw_exchange,
    running_service,
    session,
)

HOST = {"Host": "mcp.example.test"}
JSON_HEADERS = {
    **HOST,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def tool_post(svc, token: bytes | str, source: str | None = None, name="whoami"):
    headers = {**JSON_HEADERS, "Authorization": token}
    if source:
        headers["X-Client-Address"] = source
    return httpx.AsyncClient().post(
        f"{svc.url}/mcp", json=call(name), headers=headers, timeout=20
    )


def said(response: httpx.Response) -> str:
    return json.dumps(response.json())


# --- a credential that cannot be a token is refused at once (H3a, L1) ------------------


@pytest.mark.parametrize(
    "token",
    [
        "Bearer x",
        "Bearer agt_short",
        "Bearer agt_0123456789abcdef." + "A" * 42,
        "Bearer agt_0123456789abcdef." + "A" * 44,
        "Bearer agt_0123456789ABCDEF." + "A" * 43,  # the id is lowercase hex
        "Bearer xgt_0123456789abcdef." + "A" * 43,
        "Bearer agt_0123456789abcdef." + "A" * 42 + "=",
        "Bearer " + "ZZ" + "é" * 30,
        "Bearer agt_0123456789abcdef." + "A" * 42 + "é",
        "Bearer " + "A" * 5000,
    ],
)
async def test_garbage_is_the_one_rejected_message_with_no_slot_and_no_request(
    token: str,
) -> None:
    api = FakeAPI()
    from .harness import Served

    with (
        Served(api.app()) as upstream,
        running_service(
            upstream.url, max_in_flight=1, max_in_flight_per_source=1
        ) as svc,
    ):
        header = token.encode("utf-8") if not token.isascii() else token
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{svc.url}/mcp",
                json=call("whoami"),
                headers={**JSON_HEADERS, "Authorization": header},
            )
        assert r.status_code == 200, r.text
        assert r.json()["result"]["isError"] is True
        assert Message.REJECTED.value in said(r)
        assert "complete the request" not in said(r)
        # The one slot is still free, and nothing was asked of the governance server.
        assert api.seen == []
        async with session(svc) as client:
            assert not (await client.call_tool("whoami", {})).isError


def test_a_token_shaped_credential_is_exactly_what_the_api_mints() -> None:
    assert is_token_shaped(TOKEN_OK)
    assert is_token_shaped("agt_" + "0" * 16 + "." + "a-_Z9" * 8 + "abc")
    assert not is_token_shaped("agt_" + "0" * 15 + "." + "A" * 43)
    assert not is_token_shaped(TOKEN_OK + "\n")
    assert not is_token_shaped(TOKEN_OK.replace("agt_", "AGT_"))


async def test_the_scheme_is_normalized_before_the_token_is_forwarded() -> None:
    api = FakeAPI()
    from .harness import Served

    with Served(api.app()) as upstream, running_service(upstream.url) as svc:
        async with httpx.AsyncClient() as http:
            await http.post(
                f"{svc.url}/mcp",
                json=call("whoami"),
                headers={**JSON_HEADERS, "Authorization": f"bEaReR   {TOKEN_OK}"},
            )
    assert [s.headers["authorization"] for s in api.seen] == [f"Bearer {TOKEN_OK}"]


# --- the slots (H3b, H3c) ---------------------------------------------------------------


async def test_slots_are_exactly_the_limit_and_are_given_back() -> None:
    slots = Slots(total=2, per_source=2, wait=0)
    async with slots.slot("a"), slots.slot("b"):
        with pytest.raises(ToolFailure, match="busy"):
            async with slots.slot("c"):
                raise AssertionError("a third slot was granted")
    # Every one released: far more than the limit can pass in turn.
    for _ in range(50):
        async with slots.slot("a"), slots.slot("a"):
            pass
    assert slots.sources == 0
    # And a refused call gave nothing it had taken back wrongly.
    async with slots.slot("a"), slots.slot("b"):
        pass


async def test_one_source_cannot_take_every_slot() -> None:
    slots = Slots(total=10, per_source=2, wait=0)
    async with slots.slot("greedy"), slots.slot("greedy"):
        with pytest.raises(ToolFailure, match="busy"):
            async with slots.slot("greedy"):
                raise AssertionError("a source took more than its share")
        async with slots.slot("other"):
            pass
    assert slots.sources == 0


async def test_a_call_waits_a_short_bounded_time_for_a_slot() -> None:
    slots = Slots(total=1, per_source=1, wait=0.6)
    started = time.monotonic()

    async def hold() -> None:
        async with slots.slot("a"):
            await asyncio.sleep(0.15)

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.02)
    async with slots.slot("b"):  # freed after 0.15s, inside the wait
        pass
    await task
    assert time.monotonic() - started < 0.6
    # Past the wait it is refused, and does not wait longer.
    slots = Slots(total=1, per_source=1, wait=0.2)
    async with slots.slot("a"):
        begun = time.monotonic()
        with pytest.raises(ToolFailure, match="busy"):
            async with slots.slot("b"):
                raise AssertionError
        assert 0.15 < time.monotonic() - begun < 1.0
    assert slots.sources == 0


async def test_a_canceled_call_gives_its_slot_back() -> None:
    slots = Slots(total=1, per_source=1, wait=0)

    async def hold() -> None:
        async with slots.slot("a"):
            await asyncio.sleep(10)

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with slots.slot("a"):
        pass
    assert slots.sources == 0


# --- the two attacks of the review, as permanent tests ----------------------------------


async def test_garbage_bearers_from_many_threads_do_not_starve_a_legitimate_caller():
    api = FakeAPI(delay=0.2)
    from .harness import Served

    with (
        Served(api.app()) as upstream,
        running_service(
            upstream.url,
            max_in_flight=4,
            max_in_flight_per_source=2,
            queue_wait_seconds=3.0,
        ) as svc,
    ):
        async with httpx.AsyncClient(timeout=30) as http:

            async def garbage(i: int):
                return await http.post(
                    f"{svc.url}/mcp",
                    json=call("whoami"),
                    headers={**JSON_HEADERS, "Authorization": f"Bearer junk{i}"},
                )

            async def legit(i: int):
                return await http.post(
                    f"{svc.url}/mcp",
                    json=call("whoami"),
                    headers={
                        **JSON_HEADERS,
                        "Authorization": f"Bearer {TOKEN_OK}",
                        "X-Client-Address": "198.51.100.20",
                    },
                )

            results = await asyncio.gather(
                *[garbage(i) for i in range(80)], *[legit(i) for i in range(6)]
            )
        junk, good = results[:80], results[80:]
    assert all(Message.REJECTED.value in said(r) for r in junk)
    assert all(r.json()["result"]["isError"] is False for r in good), [
        said(r) for r in good if r.json()["result"]["isError"]
    ]
    # Only the legitimate calls ever reached the governance server.
    assert len(api.seen) == 6


async def test_one_source_alternating_valid_tokens_cannot_starve_another_source():
    api = FakeAPI(delay=0.3)
    from .harness import Served

    other = "agt_0123456789abcdef." + "B" * 43
    with (
        Served(api.app()) as upstream,
        running_service(
            upstream.url,
            max_in_flight=8,
            max_in_flight_per_source=2,
            queue_wait_seconds=0.1,
        ) as svc,
    ):
        async with httpx.AsyncClient(timeout=30) as http:

            async def call_as(token: str, source: str):
                return await http.post(
                    f"{svc.url}/mcp",
                    json=call("whoami"),
                    headers={
                        **JSON_HEADERS,
                        "Authorization": f"Bearer {token}",
                        "X-Client-Address": source,
                    },
                )

            attackers = [
                call_as(TOKEN_OK if i % 2 else other, "203.0.113.7") for i in range(60)
            ]
            victims = [call_as(TOKEN_OK, "198.51.100.20") for _ in range(2)]
            results = await asyncio.gather(*attackers, *victims)
    bad, good = results[:60], results[60:]
    refused = [r for r in bad if r.json()["result"]["isError"]]
    assert len(refused) >= 40, "one source took more than its share"
    assert all(Message.BUSY.value in said(r) for r in refused)
    assert all(r.json()["result"]["isError"] is False for r in good)


# --- a body that never ends (M3) --------------------------------------------------------


def test_a_body_trickled_forever_is_dropped_with_408() -> None:
    api = FakeAPI()
    from .harness import Served

    with (
        Served(api.app()) as upstream,
        running_service(upstream.url, body_timeout_seconds=1.0) as svc,
    ):
        started = time.monotonic()
        answer = raw_exchange(
            svc.port,
            (
                "POST /mcp HTTP/1.1\r\nHost: mcp.example.test\r\n"
                "Content-Type: application/json\r\nContent-Length: 98\r\n"
                f"Authorization: Bearer {TOKEN_OK}\r\n\r\n{{"
            ).encode(),
            wait=6,
            until=b"\r\n\r\n",
        )
        took = time.monotonic() - started
    assert b" 408 " in answer.split(b"\r\n", 1)[0], answer[:200]
    assert took < 4
    assert api.seen == []


def test_a_slow_but_complete_body_is_served_and_nothing_is_cut_after_it() -> None:
    api = FakeAPI()
    from .harness import Served

    with (
        Served(api.app()) as upstream,
        running_service(upstream.url, body_timeout_seconds=2.0) as svc,
    ):
        body = json.dumps(call("whoami")).encode()
        answer = raw_exchange(
            svc.port,
            (
                "POST /mcp HTTP/1.1\r\nHost: mcp.example.test\r\n"
                "Content-Type: application/json\r\nAccept: application/json\r\n"
                f"Content-Length: {len(body)}\r\nAuthorization: Bearer {TOKEN_OK}\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            + body[:10],
            then=body[10:],
            wait=6,
        )
        # The response is written after the deadline would have passed, and is whole.
        assert b" 200 " in answer.split(b"\r\n", 1)[0], answer[:200]
        assert b'"isError":false' in answer.replace(b" ", b"")


async def test_a_compressed_body_is_a_clean_415_not_a_traceback() -> None:
    api = FakeAPI()
    from .harness import Served

    with Served(api.app()) as upstream, running_service(upstream.url) as svc:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{svc.url}/mcp",
                content=b"\x1f\x8b\x08\x00garbage",
                headers={
                    **JSON_HEADERS,
                    "Authorization": f"Bearer {TOKEN_OK}",
                    "Content-Encoding": "gzip",
                },
            )
    assert r.status_code == 415 and "Traceback" not in r.text


# --- the log (M2): a hostile request cannot write it ------------------------------------


MARKER = "BODYMARK_7731"
FORGED = "FORGEDLINE_5512"


def attack(svc: ServiceProcess) -> None:
    """Every repro of the review, sent to a real process."""
    forged_name = f"x\n2026-10-12 01:10:34,440 chai.mcp.access POST /mcp 200 {FORGED}"
    with httpx.Client(timeout=10) as http:
        base = {**JSON_HEADERS, "Authorization": f"Bearer {TOKEN_OK}"}
        http.post(f"{svc.url}/mcp", json=call(forged_name), headers=base)
        http.post(
            f"{svc.url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": MARKER, "params": {}},
            headers=base,
        )
        http.post(
            f"{svc.url}/mcp",
            content=b"\x1f\x8b garbage",
            headers={**base, "Content-Encoding": "gzip"},
        )
        http.post(f"{svc.url}/mcp", content=b"{" + MARKER.encode(), headers=base)
        http.post(f"{svc.url}/mcp", json=INIT, headers=base)
        raw_exchange(
            svc.port,
            f"GET /{MARKER}%0A{FORGED} HTTP/1.1\r\nHost: mcp.example.test\r\n"
            "Connection: close\r\n\r\n".encode(),
        )
        raw_exchange(
            svc.port,
            f"GET /{MARKER}\x01\x1b[31m{FORGED} HTTP/1.1\r\nHost: mcp.example.test\r\n"
            "Connection: close\r\n\r\n".encode("latin-1"),
        )
        http.post(
            f"{svc.url}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "completion/complete",
                "params": {
                    "ref": {"type": "ref/prompt", "name": MARKER},
                    "argument": {"name": "a", "value": "b"},
                },
            },
            headers=base,
        )


def test_a_hostile_request_cannot_write_a_line_or_a_marker_into_the_log() -> None:
    api = FakeAPI()
    from .harness import Served

    with Served(api.app()) as upstream:
        with ServiceProcess(upstream.url) as svc:
            attack(svc)
    out = svc.output
    assert out.strip(), "the service logged nothing, so this proved nothing"
    assert FORGED not in "\n".join(
        line for line in out.splitlines() if line.startswith("chai.mcp")
    )
    assert MARKER not in out and FORGED not in out.replace("\\n", "")
    assert "Traceback" not in out and "input_value" not in out
    for line in out.splitlines():
        entry = json.loads(line)  # every line is one JSON object
        assert set(entry) <= {"ts", "level", "logger", "msg", "error"}
        assert len(line) <= 300


def test_a_small_request_cannot_make_a_large_log() -> None:
    api = FakeAPI()
    from .harness import Served

    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "completion/complete",
            "params": {"ref": {"type": "x"}},
        }
    )
    assert len(request) < 120
    with Served(api.app()) as upstream:
        with ServiceProcess(upstream.url) as svc:
            with httpx.Client() as http:
                http.post(
                    f"{svc.url}/mcp",
                    content=request,
                    headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN_OK}"},
                )
    assert len(svc.output) < 1500, len(svc.output)


def test_a_flood_of_bad_requests_is_a_bounded_amount_of_log() -> None:
    api = FakeAPI()
    from .harness import Served

    with Served(api.app()) as upstream:
        with ServiceProcess(upstream.url) as svc:
            with httpx.Client() as http:
                for i in range(300):
                    http.post(
                        f"{svc.url}/mcp?{i}",
                        json=INIT,
                        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN_OK}"},
                    )
    lines = svc.output.splitlines()
    assert len(lines) < 150, len(lines)
    assert any("records dropped" in line for line in lines)


def test_an_upstream_failure_logs_the_class_and_never_the_exception_text() -> None:
    from .harness import free_port

    marker = "hostmark-QZ91.invalid"
    with ServiceProcess(f"http://{marker}:{free_port()}") as svc:
        with httpx.Client(timeout=20) as http:
            r = http.post(
                f"{svc.url}/mcp",
                json=call("whoami"),
                headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN_OK}"},
            )
    assert Message.UNAVAILABLE.value in r.text
    assert marker not in svc.output and "hostmark" not in svc.output
    assert "upstream call failed" in svc.output and "ConnectError" in svc.output


# --- the log's own pieces ---------------------------------------------------------------


def make_record(name: str, msg: str, *args, exc=None):
    import logging

    return logging.LogRecord(name, logging.WARNING, "", 0, msg, args, exc)


def test_only_our_own_loggers_may_say_anything() -> None:
    import logging

    foreign = make_record("mcp.server", "bad input %s", "SECRETBODY")
    own = make_record("chai.mcp", "upstream answered %s", 401)
    for record in (foreign, own):
        assert Reduce().filter(record)
    assert "SECRETBODY" not in OneLine().format(foreign)
    assert "withheld" in OneLine().format(foreign)
    assert "upstream answered 401" in OneLine().format(own)
    assert isinstance(logging.getLogger("chai.mcp"), logging.Logger)


def test_a_traceback_is_reduced_to_its_class() -> None:
    try:
        raise ValueError("SECRETINSIDE")
    except ValueError:
        import sys

        record = make_record("chai.mcp", "failed", exc=sys.exc_info())
    Reduce().filter(record)
    line = OneLine().format(record)
    assert "SECRETINSIDE" not in line and "Traceback" not in line
    assert json.loads(line)["error"] == "ValueError"


def test_a_line_is_one_json_object_whatever_the_message_holds() -> None:
    record = make_record(
        "chai.mcp.access", "GET %s", "/x\r\n2026 FAKE chai.mcp 200 \x00\x1b"
    )
    Reduce().filter(record)
    line = OneLine().format(record)
    assert "\n" not in line and "\r" not in line and "\x1b" not in line
    assert json.loads(line)["msg"].startswith("GET /x")
    long = make_record("chai.mcp.access", "GET %s", "a" * 5000)
    Reduce().filter(long)
    assert len(OneLine().format(long)) <= 300


def test_a_burst_is_bounded_and_the_loss_is_said_once() -> None:
    bound = Bound(burst=5, rate=0.0)
    kept = [bound.filter(make_record("chai.mcp", "x")) for _ in range(20)]
    assert kept.count(True) == 5
    bound._tokens = 1  # the burst is over: the next record says what was lost
    record = make_record("chai.mcp", "after")
    assert bound.filter(record) and "15 records dropped" in record.getMessage()


def test_the_root_logger_is_quiet_and_only_our_access_line_is_info() -> None:
    import logging

    configure_logging()
    assert logging.getLogger().level == logging.WARNING
    assert logging.getLogger("chai.mcp.access").getEffectiveLevel() == logging.INFO
    for name in (
        "mcp",
        "mcp.server",
        "pydantic",
        "asyncio",
        "httpx",
    ):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name
