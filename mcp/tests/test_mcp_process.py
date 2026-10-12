"""The service as a process, the way the container runs it (#164).

``python -m chai_mcp`` with an environment: it refuses to start on an unsafe setting,
and what it writes to its output, over a run that includes every failure, holds no
token. The in-process tests sweep the logging module; this sweeps the bytes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx

from .harness import FakeAPI, Served, call, free_port, session

TOKEN = "agt_0123456789abcdef.PROCESSSECRETPROCESSSECRETPROCESSSECRET12"


def env_for(**over: str) -> dict[str, str]:
    keep = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "HOME"}}
    return {**keep, "PYTHONUNBUFFERED": "1", **over}


def test_it_refuses_to_start_with_no_allowed_host() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "chai_mcp"],
        env=env_for(API_BASE_URL="http://127.0.0.1:1"),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2
    assert "MCP_ALLOWED_HOSTS" in done.stderr
    assert "refusing to start" in done.stderr


def test_it_refuses_to_start_with_no_api_address() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "chai_mcp"],
        env=env_for(MCP_ALLOWED_HOSTS="h.example"),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2 and "API_BASE_URL" in done.stderr


async def test_what_the_process_writes_holds_no_token() -> None:
    fake = FakeAPI()
    port = free_port()
    with Served(fake.app()) as upstream:
        proc = subprocess.Popen(
            [sys.executable, "-m", "chai_mcp"],
            env=env_for(
                API_BASE_URL=upstream.url,
                MCP_ALLOWED_HOSTS="mcp.example.test",
                MCP_PORT=str(port),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert proc.poll() is None and time.monotonic() < deadline
                time.sleep(0.1)
            served = type("S", (), {"url": f"http://127.0.0.1:{port}"})()
            async with session(served, TOKEN) as client:
                await client.call_tool("whoami", {})
                await client.call_tool("get_project", {"ref": "bad"})
                fake.status = 401
                await client.call_tool("list_portfolio", {})
                fake.status, fake.body = 500, {"detail": TOKEN}
                await client.call_tool("whoami", {})
            httpx.post(
                f"http://127.0.0.1:{port}/mcp?token={TOKEN}",
                json=call("whoami"),
                headers={
                    "Host": "mcp.example.test",
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
            )
            httpx.post(
                f"http://127.0.0.1:{port}/mcp",
                json=call("whoami"),
                headers={
                    "Host": "mcp.example.test",
                    "Origin": "https://evil.example",
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
            )
        finally:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
    assert "POST /mcp" in out  # it logged, so the sweep is of something
    assert "PROCESSSECRET" not in out and "agt_0123456789abcdef" not in out
    assert "token=" not in out
