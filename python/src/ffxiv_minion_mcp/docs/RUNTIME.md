# FFXIVMinion Lua runtime notes

This document records observed behavior used by the bridge. It is not official
FFXIVMinion documentation and can change between Minion builds.

## Runtime model

FFXIVMinion embeds a modified Lua 5.1-family runtime and exposes game and bot
objects as globals. Common examples include:

```lua
Player
Duty
EntityList
GetCurrentPID()
GetGameState()
GetTickCount()
GetChatLines()
RegisterEventHandler(...)
HttpRequest({...})
json.encode(...)
json.decode(...)
```

See [`addon/globals.lua`](addon/globals.lua) for the included Lua language-server
declarations. It is copied as-is from the development addon repository and
contains core Minion declarations plus declarations discovered or added while
developing other addons. It is reference material, not a promise that every
global exists in every installation.

## Addon lifecycle

For public addon/module structure and lifecycle event registration, read
[`docs/ADDON_DEVELOPMENT.md`](docs/ADDON_DEVELOPMENT.md) or MCP resource
`ffxivminion://docs/addon-development`. It covers `module.def`,
`Module.Initalize`, `Gameloop.Update`, `Gameloop.Draw`, GUI/menu integration,
files, private packaging, and reload behavior.

## Main-thread requirement

The game owns the Lua state. Submitted snippets execute through the addon from a
`Gameloop.Update` callback/HTTP completion dispatched by Minion. Keep code short:
a slow snippet stalls the game frame.

Good:

```lua
return {
    name = Player.name,
    map = Player.localmapid,
    level = Player.level,
    queued = Duty:GetQueueStatus(),
}
```

Bad:

```lua
while not someCondition do end -- freezes the game
```

Batching related values into one returned table is both faster and safer than
many bridge round trips.

## Compilation behavior

The addon supports expressions and complete chunks:

1. Try `loadstring("return " .. code)`.
2. If that does not compile, try `loadstring(code)`.
3. Execute with `pcall`.
4. Transport only the first returned value.

Examples:

```lua
Player.name
```

```lua
local info = Duty:GetActiveDutyInfo()
return {pid = GetCurrentPID(), duty = info}
```

## Serialization

- `nil` becomes a null/missing result in the JSON protocol.
- tables are encoded with the runtime's `json.encode`;
- other values use `tostring`.

Functions, userdata, threads, cycles, and unsupported table contents are not
portable JSON values. Return a deliberately constructed plain table instead of a
large runtime object.

Some observed Minion builds override `tostring(table)` with a recursive object
dump. Calling it on a large or cyclic table (especially `_G`) can crash the
client. The addon therefore never uses `tostring` as a fallback for tables.

## Libraries

Observed builds retain `loadstring`, `pcall`, and ordinary base/table/string/math
functionality, but may omit libraries expected in desktop Lua. In particular,
the standard `debug` and `package` tables may be absent. Do not assume arbitrary
filesystem, dynamic-library, or debug APIs are available.

## HTTP API used by the addon

The bridge uses Minion's asynchronous API in this form:

```lua
HttpRequest({
    host = "127.0.0.1",
    port = 9471,
    path = "/pollLua",
    method = "POST",
    https = false,
    body = json.encode({pid = GetCurrentPID()}),
    onsuccess = function(body, headers, statusCode) end,
    onfailure = function(error, headers, statusCode) end,
})
```

A hold time of nine seconds is used because a roughly ten-second request timeout
has been observed to work reliably. Empty poll responses are normal; the addon
starts another poll on the next frame.

## Event registration

The standalone addon registers:

```lua
RegisterEventHandler(
    "Gameloop.Update",
    callback,
    "FFXIVMinionMCP.Update"
)
```

The callback performs only bridge state management. Actual network operations are
asynchronous through `HttpRequest`.

## Quest state and static research

For live quest state, use Minion's `Quest` object and convenience functions. For
static quest research, see [`docs/QUESTING.md`](docs/QUESTING.md). That guide
references the versioned CSVs and patch history in
[`xivapi/ffxiv-datamining`](https://github.com/xivapi/ffxiv-datamining).

## Game UI controls

FFXIV's visible addon windows are exposed as **controls**. Examples include
`SelectString`, `SelectYesno`, `Shop`, `ContentsFinder`, `RecipeNote`, and
`Synthesis`. Control names and data layouts come from the active game UI and can
change between patches, languages, and window states.

### Discovery

Start with the highest-level inspection APIs:

```lua
return {
    selectStringOpen = IsControlOpen("SelectString"),
    yesNoOpen = IsControlOpen("SelectYesno"),
    shopOpen = IsControlOpen("Shop"),
}
```

To enumerate currently open controls without returning native `Control` objects:

```lua
local out = {}
for id, control in pairs(GetControls() or {}) do
    if control:IsOpen() then
        out[#out + 1] = {
            id = id,
            name = control.name,
            ready = control:IsReady(),
            data = control:GetData(),
            strings = control:GetStrings(),
            rawData = control:GetRawData(),
        }
    end
end
table.sort(out, function(a, b) return a.name < b.name end)
return out
```

Build a deliberately cleaned table as above. Do not return `Control` userdata or
the entire global table.

### Reading controls

There are three useful views:

```lua
GetControlData("ContentsFinderSetting", "UnderSizedParty")
GetControlStrings("SelectString", 2)
GetControlRawData("AOZNotebook", 18)
```

- `GetControlData(name, key?)` returns Minion's semantic/named view where one is
  available. Prefer this over numeric indexes.
- `GetControlStrings(name, index)` returns a string slot used by many menus and
  confirmation windows.
- `GetControlRawData(name, index)` returns `{type=..., value=...}` for one raw
  AtkValue slot. Raw indexes are window-state and build specific.
- `control:GetData()`, `control:GetStrings()`, and `control:GetRawData()` return
  the corresponding full views for a `Control` obtained from
  `GetControlByName(name)`.

Always check that a control is open/ready and that returned values are non-nil.
UI data can change between frames.

### Acting on controls

Prefer semantic actions when known:

```lua
if IsControlOpen("SelectYesno") then
    UseControlAction("SelectYesno", "Yes")
end
```

```lua
local control = GetControlByName("Trade")
if control and control:IsOpen() then
    control:Action("Trade")
end
```

Available levels, from highest to lowest:

1. `UseControlAction(controlName, actionName, value?, preDelay?, postDelay?)`
2. `control:Action(actionName, args?)`
3. `control:PushButton(a, b)` / `control:DoAction(number)`
4. `UIEvent(agentIndexOrName, eventId, typedArguments)`

`PushButton`, `DoAction`, and especially `UIEvent` are reverse-engineered,
control-specific primitives. Do not guess their numbers. Inspect the target
window and use a known sequence captured for that exact control/build.

`UIEvent` arguments are typed AtkValues:

```lua
UIEvent("RecipeNote", 0, { {3, 10} })
UIEvent("RecipeNote", 2, { {3, 0}, {5, 0}, {2, false} })
```

Observed type IDs include `0=None`, `2=Bool`, `3=Int`, `4=Int64`, `5=UInt`,
`6=UInt64`, and `7=Float`. Event IDs and argument positions are not universal.

### Asynchronous behavior

Opening a window, interacting with an NPC, pressing a button, and closing a
window generally complete on later game frames. A bridge call should usually do
one transition and return:

```lua
if not IsControlOpen("ContentsFinder") then
    ActionList:Get(10, 33):Cast()
    return {requested="open", open=false}
end
return {requested=nil, open=true}
```

Verify the expected next control in a later `run_lua` call. Do not busy-wait in
one snippet. Throttle repeated actions; calling the same UI action every frame
can produce duplicate inputs or invalid state.

## Errors and actions

A successful Lua call does not guarantee an in-game action succeeded. Game and
addon APIs may report failures only through chat, logs, UI state, or later game
state. When debugging an action, return relevant state in the same call, for
example:

```lua
SomeGameAction()
return {
    chat = GetChatLines(),
    state = GetGameState(),
}
```

## Multi-client behavior

Each polling addon identifies itself with `GetCurrentPID()`. `run_lua` accepts an
optional PID. Without a PID, whichever matching client receives the single
pending job first will execute it. Specify a PID when multiple game processes are
running.

The current Python dispatcher serializes all calls globally. That conservative
design ensures only one command is pending at a time.
