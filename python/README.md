# Python MCP server

This directory contains the stdio MCP server and its loopback HTTP transport for
the FFXIVMinion addon.

## Install

From this directory:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e .
```

Or with [`uv`](https://docs.astral.sh/uv/):

```powershell
uv sync
```

## Run directly

```powershell
.venv\Scripts\python -m ffxiv_minion_mcp
```

The process uses:

- stdout for MCP stdio protocol messages;
- stderr for logs;
- `127.0.0.1:9471` for the Lua addon transport.

## Claude Code

From the repository root, add it as a project-scoped stdio server:

```powershell
claude mcp add --scope project --transport stdio ffxiv-minion-lua -- `
  "$PWD\.venv\Scripts\python.exe" -m ffxiv_minion_mcp
```

Alternatively copy `.mcp.json.example` to `.mcp.json` at the repository root and
adjust the Python path if necessary. Claude Code's project MCP configuration uses
an `mcpServers` object with `type`, `command`, and `args` for stdio servers.

Check it with:

```powershell
claude mcp list
```

or `/mcp` inside Claude Code.

## Optional HTTP CLI

After the server is running:

```powershell
.venv\Scripts\ffxiv-minion-lua "Player.name"
.venv\Scripts\ffxiv-minion-lua -j "{pid=GetCurrentPID(), map=Player.localmapid}"
```

## Configuration

Environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `FFXIV_MINION_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `FFXIV_MINION_MCP_PORT` | `9471` | HTTP bridge port |
| `FFXIV_MINION_MCP_POLL_HOLD` | `9` | Long-poll hold time in seconds |
| `FFXIV_MINION_MCP_TIMEOUT` | `12` | Default MCP job timeout |
| `FFXIV_MINION_MCP_MAX_CODE_BYTES` | `1048576` | Maximum submitted source size |

Keep the host on loopback. This bridge executes arbitrary Lua inside the game.
