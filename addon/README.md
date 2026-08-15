# FFXIVMinion addon

This is a standalone FFXIVMinion LuaMod that connects the running game to the
Python MCP server.

## Install

Copy this directory into your active FFXIVMinion `LuaMods` directory and give it
a stable directory name, for example:

```text
C:\MINIONAPP\Bots\FFXIVMinion64\LuaMods\FFXIVMinionMCP\
    module.def
    agent_bridge.lua
```

Beta clients may use a separate path such as:

```text
C:\MINIONAPP\Bots\FFXIVMinion64\beta\LuaMods\FFXIVMinionMCP\
```

`GetLuaModsPath()` in the Minion console reveals the active path.

Start the Python server, then restart Minion or reload its Lua modules. The
console should show the addon polling. It backs off harmlessly when the Python
server is not running.

## How it works

1. `Gameloop.Update` starts an asynchronous `HttpRequest` to `/pollLua`.
2. Python holds that request for up to nine seconds.
3. When an MCP caller submits code, Python completes the waiting request.
4. The callback compiles and executes the source with `loadstring` + `pcall`.
5. The addon posts the first return value to `/luaResult`.
6. The next frame starts another long poll.

Execution is sequential and happens on Minion's Lua/game thread. Never submit a
snippet that sleeps, busy-waits, or performs unbounded work.

## Configuration

The defaults at the top of `agent_bridge.lua` match the Python server:

```lua
local BRIDGE_HOST = "127.0.0.1"
local BRIDGE_PORT = 9471
```

The bridge is enabled by default. At runtime:

```lua
FFXIVMinionMCP.Enabled = false -- pause polling
FFXIVMinionMCP.Enabled = true  -- resume polling
```

Keep the server on loopback. Anyone who can submit to it can execute arbitrary
Lua in the game process.
