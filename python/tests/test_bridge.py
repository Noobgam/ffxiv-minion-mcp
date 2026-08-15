from __future__ import annotations

import asyncio

import pytest

from ffxiv_minion_mcp.server import LuaBridge


@pytest.mark.asyncio
async def test_targeted_job_round_trip() -> None:
    bridge = LuaBridge()
    submitted = asyncio.create_task(bridge.submit("1+1", pid=4242, timeout=1))
    await asyncio.sleep(0)
    job = await bridge.poll(4242)
    assert job is not None
    assert job["code"] == "1+1"
    assert bridge.resolve(job["id"], {"ok": True, "result": "2", "pid": 4242})
    assert await submitted == {"ok": True, "result": "2", "pid": 4242}


@pytest.mark.asyncio
async def test_wrong_pid_does_not_take_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import ffxiv_minion_mcp.server as server

    monkeypatch.setattr(server, "POLL_HOLD_SECONDS", 0.01)
    bridge = LuaBridge()
    submitted = asyncio.create_task(bridge.submit("1+1", pid=4242, timeout=1))
    await asyncio.sleep(0)
    assert await bridge.poll(9999) is None
    job = await bridge.poll(4242)
    assert job is not None
    assert bridge.resolve(job["id"], {"ok": True, "result": "2", "pid": 4242})
    await submitted


@pytest.mark.asyncio
async def test_timeout_retracts_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import ffxiv_minion_mcp.server as server

    monkeypatch.setattr(server, "POLL_HOLD_SECONDS", 0.01)
    bridge = LuaBridge()
    with pytest.raises(asyncio.TimeoutError):
        await bridge.submit("return 1", pid=1, timeout=0.01)
    assert await bridge.poll(1) is None
