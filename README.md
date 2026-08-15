# FFXIVMinion MCP

A local [Model Context Protocol](https://modelcontextprotocol.io/) server that
allows Claude Code and other MCP clients to execute Lua inside a running
FFXIVMinion client.

## Architecture

```text
Claude Code / MCP client
          │ MCP over stdio
          ▼
Python server
  127.0.0.1:9471
          ▲
          │ HTTP long poll + result POST
          ▼
FFXIVMinion Lua addon
  Gameloop.Update → loadstring → pcall
```

The addon keeps an asynchronous long poll open. Python answers it when the MCP
`run_lua` tool receives a command. Code executes on Minion's game/Lua thread and
the first return value is sent back.

This version deliberately uses only FFXIVMinion's Lua and `HttpRequest` APIs. It
does not inject DLLs, patch memory, or require build-specific offsets.

## Repository layout

```text
python/                 MCP server and optional HTTP CLI
addon/                  standalone FFXIVMinion LuaMod
addon/globals.lua       Lua language-server declarations copied as-is
docs/QUESTING.md        live quest inspection and datamining
docs/ADDON_DEVELOPMENT.md public addon lifecycle, GUI, files, and packaging
RUNTIME.md              observed runtime behavior and safety notes
.mcp.json.example       Claude Code project configuration example
```

## Quick start

### 1. Install the addon

Copy `addon/` to the active Minion `LuaMods` directory as
`FFXIVMinionMCP/`. See [`addon/README.md`](addon/README.md).

### 2. Install Python dependencies

```powershell
cd python
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e .
```

### 3. Configure Claude Code

From the repository root:

```powershell
claude mcp add --scope project --transport stdio ffxiv-minion-lua -- `
  "$PWD\python\.venv\Scripts\python.exe" -m ffxiv_minion_mcp
```

Or copy `.mcp.json.example` to `.mcp.json` and adjust its command path.

### 4. Test it

In Claude Code, ask it to use `run_lua`, or run the optional direct client while
the MCP server is running:

```powershell
python\.venv\Scripts\ffxiv-minion-lua -j `
  "{pid=GetCurrentPID(), name=Player.name, map=Player.localmapid}"
```

Typical MCP input:

```lua
{
    pid = GetCurrentPID(),
    name = Player.name,
    map = Player.localmapid,
    queued = Duty:GetQueueStatus()
}
```

## Tool

### `run_lua`

Arguments:

- `code` — Lua expression or full chunk;
- `pid` — optional FFXIV process ID for multi-client setups;
- `timeout_seconds` — maximum time to wait for a matching polling client.

Expressions are compiled as `return <code>`. If that fails, the source is
compiled as a full chunk. Only the first return value is transported. Tables are
encoded using Minion's global `json.encode`; scalar values use `tostring`.

The MCP server also publishes documentation resources, so clients do not need to
locate repository files on the host filesystem:

```text
ffxivminion://docs/runtime
ffxivminion://docs/addon-development
ffxivminion://docs/questing
```

The tool returns a JSON envelope as MCP text:

```json
{"ok":true,"result":"Noobgam Grimalkin","error":null,"pid":12345}
```

## Addon development

[`docs/ADDON_DEVELOPMENT.md`](docs/ADDON_DEVELOPMENT.md) documents the public
Minion Lua addon model, including:

- `module.def` and file load order;
- `RegisterEventHandler`;
- `Module.Initalize`, `Gameloop.Update`, and `Gameloop.Draw`;
- GUI windows and Minion menu integration;
- settings/local files and private packaged files;
- reload-safe addon structure.

It is also exposed as MCP resource:

```text
ffxivminion://docs/addon-development
```

## Quest information

[`docs/QUESTING.md`](docs/QUESTING.md) explains:

- fetching active/completed/current-step quest state from the live game;
- deriving static actors, listeners, sequences, and locations from
  [`xivapi/ffxiv-datamining`](https://github.com/xivapi/ffxiv-datamining);
- using that repository's Git history as the source of patch data/changes;
- validating quest sequences against the live client.

## Safety

This server provides arbitrary code execution inside the FFXIV process.

- It binds to `127.0.0.1` by default. Do not expose it to a network.
- Lua runs on the game thread. Keep snippets fast.
- Batch related reads into one call.
- Do not sleep or busy-wait in submitted snippets.
- Treat game APIs as stateful and potentially unsafe.
- Read [`RUNTIME.md`](RUNTIME.md) before developing against the runtime.

## Compatibility

The bridge targets the observed FFXIVMinion Lua environment. It is expected to be
largely independent of FFXIV region, but currently documents tested/observed
behavior rather than an official Minion compatibility guarantee.

## License

MIT. See [`LICENSE`](LICENSE).
