"""MCP + loopback HTTP bridge for executing Lua inside FFXIVMinion.

The process exposes MCP over stdio for clients such as Claude Code. A companion
FFXIVMinion LuaMod holds a long-poll HTTP request to 127.0.0.1, executes one job
at a time from Gameloop.Update, and posts the result back.

Stdout is reserved for the MCP protocol. Logs always go to stderr.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

BRIDGE_HOST = os.getenv("FFXIV_MINION_MCP_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("FFXIV_MINION_MCP_PORT", "9471"))
POLL_HOLD_SECONDS = float(os.getenv("FFXIV_MINION_MCP_POLL_HOLD", "9"))
DEFAULT_JOB_TIMEOUT_SECONDS = float(os.getenv("FFXIV_MINION_MCP_TIMEOUT", "12"))
MAX_CODE_BYTES = int(os.getenv("FFXIV_MINION_MCP_MAX_CODE_BYTES", str(1024 * 1024)))
DOCS_DIR = Path(__file__).resolve().parent / "docs"

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ffxiv_minion_mcp")


class LuaBridge:
    """Single-slot dispatcher between MCP callers and long-polling game clients.

    Calls are intentionally serialized. FFXIVMinion's Lua state belongs to the
    game thread, so the addon executes only one command at a time from its frame
    callback.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._job: dict[str, Any] | None = None
        self._futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._submit_lock = asyncio.Lock()
        self.last_seen_pids: dict[str, float] = {}

    async def submit(
        self,
        code: str,
        pid: int | None = None,
        timeout: float = DEFAULT_JOB_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        if not isinstance(code, str) or not code:
            raise ValueError("code must be a non-empty string")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError(f"code exceeds the {MAX_CODE_BYTES}-byte limit")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        async with self._submit_lock:
            job = {"id": uuid.uuid4().hex, "code": code, "pid": pid}
            future = asyncio.get_running_loop().create_future()
            self._futures[job["id"]] = future
            async with self._condition:
                self._job = job
                self._condition.notify_all()
            try:
                return await asyncio.wait_for(future, timeout)
            except asyncio.TimeoutError:
                async with self._condition:
                    if self._job is job:
                        self._job = None
                raise
            finally:
                self._futures.pop(job["id"], None)

    async def poll(self, client_pid: Any) -> dict[str, str] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + POLL_HOLD_SECONDS
        async with self._condition:
            while True:
                job = self._job
                if job is not None and (
                    job["pid"] is None or str(job["pid"]) == str(client_pid)
                ):
                    self._job = None
                    return {"id": job["id"], "code": job["code"]}

                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self._condition.wait(), remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    return None

    def resolve(self, job_id: str, payload: dict[str, Any]) -> bool:
        future = self._futures.get(job_id)
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True


bridge = LuaBridge()
_use_existing_http_bridge = False


async def poll_lua(request: Request) -> JSONResponse:
    body = await request.json()
    pid = body.get("pid")
    if pid is not None:
        bridge.last_seen_pids[str(pid)] = asyncio.get_running_loop().time()
    job = await bridge.poll(pid)
    return JSONResponse(job or {})


async def lua_result(request: Request) -> JSONResponse:
    body = await request.json()
    job_id = body.get("id")
    if not job_id:
        return JSONResponse({"error": "missing id"}, status_code=400)
    if not bridge.resolve(str(job_id), body):
        logger.warning("received result for unknown or expired job %s", job_id)
    return JSONResponse({"ok": True})


async def _execute(
    code: str,
    pid: int | None,
    timeout: float,
) -> dict[str, Any]:
    if _use_existing_http_bridge:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/runLua",
                    json={"code": code, "pid": pid, "timeout": timeout},
                    timeout=timeout + 2,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            return {
                "ok": False,
                "result": None,
                "error": f"existing Lua bridge request failed: {error}",
                "pid": pid,
            }

    try:
        result = await bridge.submit(code, pid=pid, timeout=timeout)
    except ValueError as error:
        return {"ok": False, "result": None, "error": str(error), "pid": pid}
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "result": None,
            "error": (
                f"timed out after {timeout}s waiting for a matching game client "
                "(is FFXIV running with the FFXIVMinionMCP addon enabled?)"
            ),
            "pid": pid,
        }
    return {
        "ok": bool(result.get("ok")),
        "result": result.get("result"),
        "error": result.get("error"),
        "pid": result.get("pid"),
    }


async def run_lua_http(request: Request) -> JSONResponse:
    body = await request.json()
    code = body.get("code")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)
    try:
        timeout = float(body.get("timeout", DEFAULT_JOB_TIMEOUT_SECONDS))
        pid = int(body["pid"]) if body.get("pid") is not None else None
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid pid or timeout"}, status_code=400)
    return JSONResponse(await _execute(code, pid, timeout))


async def health(_: Request) -> JSONResponse:
    loop = asyncio.get_running_loop()
    clients = {
        pid: max(0.0, loop.time() - seen)
        for pid, seen in bridge.last_seen_pids.items()
    }
    return JSONResponse({"ok": True, "clients": clients})


http_app = Starlette(
    routes=[
        Route("/pollLua", poll_lua, methods=["POST"]),
        Route("/luaResult", lua_result, methods=["POST"]),
        Route("/runLua", run_lua_http, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
)

MCP_INSTRUCTIONS = """Execute Lua in a running FFXIVMinion client.

Runtime essentials:
- Code runs synchronously on the game's main Lua thread. Keep it fast, never sleep
  or busy-wait, and batch related reads into one returned plain table.
- Useful globals include Player, Duty, EntityList, GetCurrentPID(), GetGameState(),
  GetChatLines(), ActionList, ml_task_hub, and ffxiv_task_movetopos.
- The first return value is transported. Plain tables are JSON-encoded. Do not
  return userdata/functions or stringify large/cyclic runtime tables.

Addon development:
- For writing Minion addons/modules, read MCP resource
  `ffxivminion://docs/addon-development`. It documents `module.def`, file order,
  `Module.Initalize` (exact spelling), `Gameloop.Update`, `Gameloop.Draw`, GUI/menu
  patterns, settings/files, reload behavior, and public private-addon file APIs.
- Use stable unique names in `RegisterEventHandler`; keep update/draw callbacks
  short and move multi-frame work into state machines. Do not guess lifecycle
  event names or search the host filesystem for this guide.

Questing:
- Live state: use `Quest:HasQuest(id)`, `Quest:IsQuestCompleted(id, false)`, and
  `Quest:GetQuestCurrentStep(id, false)` (plus `HasQuest`, `QuestCompleted`, or
  `GetQuestInfo(id,"step")` where available).
- Static quest research: read MCP resource `ffxivminion://docs/questing`.
  It explains how to derive actors/listeners/sequences/locations from the
  versioned CSVs at https://github.com/xivapi/ffxiv-datamining and validate
  them against the live client. Do not search the host filesystem for QUESTING.md.
- Do not guess a quest from listener order alone; validate against the live current
  step and check script instructions for item, emote, combat, duty, or branch steps.

Game UI controls:
- Controls are FFXIV addon windows. Check IsControlOpen("Name"), then inspect with
  GetControlByName, GetControlData, GetControlStrings, or GetControlRawData.
- Prefer semantic actions: UseControlAction("Name", "Action", value) or
  control:Action(...). PushButton, DoAction, raw-data indexes, and UIEvent are
  lower-level and build/window-state specific; inspect the live control first.
- GetControls() is useful for discovery, but return a cleaned snapshot containing
  only id/name/open/ready/data/strings/rawData—not Control objects themselves.
- UI actions are asynchronous. Usually perform one action, return immediately, and
  verify the resulting control/game state in a later call.

Movement tasks are also asynchronous. ffxiv_task_movetopos.Create() only creates a
subtask; configure pos/range and attach it to a current parent task with
ml_task_hub:CurrentTask():AddSubTask(task).
"""

mcp = FastMCP("ffxiv-minion-lua", instructions=MCP_INSTRUCTIONS)


def _read_bundled_doc(filename: str) -> str:
    return (DOCS_DIR / filename).read_text(encoding="utf-8")


@mcp.resource(
    "ffxivminion://docs/addon-development",
    name="FFXIVMinion addon development guide",
    description=(
        "Public Lua addon structure, module.def, lifecycle/update/draw event "
        "registration, GUI/menu patterns, files, reloads, and private packaging."
    ),
    mime_type="text/markdown",
)
def addon_development_documentation() -> str:
    return _read_bundled_doc("ADDON_DEVELOPMENT.md")


@mcp.resource(
    "ffxivminion://docs/questing",
    name="FFXIVMinion questing guide",
    description=(
        "Live quest-state inspection, xivapi/ffxiv-datamining CSV workflow, "
        "and validation against the live client."
    ),
    mime_type="text/markdown",
)
def questing_documentation() -> str:
    return _read_bundled_doc("QUESTING.md")


@mcp.resource(
    "ffxivminion://docs/runtime",
    name="FFXIVMinion runtime guide",
    description="Lua threading, serialization, controls, and safety notes.",
    mime_type="text/markdown",
)
def runtime_documentation() -> str:
    return _read_bundled_doc("RUNTIME.md")


@mcp.tool()
async def run_lua(
    code: str,
    pid: int | None = None,
    timeout_seconds: float = DEFAULT_JOB_TIMEOUT_SECONDS,
) -> str:
    """Execute Lua inside a running FFXIVMinion game client.

    `code` can be an expression (`Player.name`) or a complete chunk
    (`local x = 1; return x + 1`). The addon first tries `return <code>`, then
    falls back to compiling `code` as a chunk. The first return value is used;
    tables are JSON-encoded and scalar values are converted with `tostring`.

    Keep snippets short because they execute on the game's main thread. Prefer
    one call returning a table over many small calls. Use `pid` to select a game
    process when multiple clients are polling.

    For addon/module authoring, read MCP resource
    `ffxivminion://docs/addon-development` for the public `module.def`,
    `RegisterEventHandler`, initialization, update, drawing, GUI/menu, file, and
    reload contracts before writing code.

    For quests, inspect live state with `Quest:HasQuest`,
    `Quest:IsQuestCompleted`, and `Quest:GetQuestCurrentStep`. For static quest
    research, read MCP resource `ffxivminion://docs/questing`. It references the
    versioned `xivapi/ffxiv-datamining` CSV source and explains how to validate
    quest sequences against the live client. Do not locate these docs with
    shell/filesystem searches.

    For game UI, discover and inspect controls before acting. Prefer
    `IsControlOpen`, `GetControlData`, `GetControlStrings`, and
    `UseControlAction`. Raw-data indexes, `PushButton`, and `UIEvent` are
    low-level and may vary by client build. UI actions complete asynchronously,
    so issue an action and verify the resulting control state in a later call.

    Args:
        code: Lua expression or chunk to execute.
        pid: Optional target FFXIV process ID.
        timeout_seconds: Maximum time to wait for the matching game client.
    """
    return json.dumps(await _execute(code, pid, timeout_seconds))


async def main() -> None:
    global _use_existing_http_bridge

    bridge_url = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{bridge_url}/health", timeout=1)
            response.raise_for_status()
        _use_existing_http_bridge = True
    except httpx.HTTPError:
        _use_existing_http_bridge = False

    if _use_existing_http_bridge:
        logger.info("Using existing Lua bridge at %s; MCP on stdio", bridge_url)
        await mcp.run_stdio_async()
        return

    config = uvicorn.Config(
        http_app,
        host=BRIDGE_HOST,
        port=BRIDGE_PORT,
        log_level="warning",
        workers=1,
    )
    server = uvicorn.Server(config)
    logger.info("Lua bridge HTTP listening on %s; MCP on stdio", bridge_url)
    await asyncio.gather(server.serve(), mcp.run_stdio_async())


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
