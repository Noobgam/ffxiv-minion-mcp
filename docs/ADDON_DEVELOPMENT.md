# FFXIVMinion addon development

This guide describes the public Lua addon model visible through Minion's Lua API
and public MMOMinion documentation. It does not rely on private internals,
reverse-engineered offsets, or native injection.

Public references:

- [MMOMinion private addon developer help](https://wiki.mmominion.com/doku.php?id=private_addon_developer_help)
- [MinionLib Lua API](https://wiki.mmominion.com/doku.php?id=minionlib)
- [Minion Lua API index](https://wiki.mmominion.com/doku.php?id=lua_api)

The words **module** and **addon** are commonly used synonymously.

## Directory layout

An addon is a directory under the active `LuaMods` folder:

```text
LuaMods/
└── ExampleAddon/
    ├── module.def
    ├── example.lua
    └── gui.lua
```

Use the runtime to discover the active root:

```lua
local luaModsPath = GetLuaModsPath()
local startupPath = GetStartupPath()
```

Beta and live clients may have different active `LuaMods` roots, so avoid
hard-coding one channel's path.

## `module.def`

A minimal public addon definition is:

```ini
[Module]
Name=ExampleAddon
Dependencies=minionlib
Version=1
Files=example.lua,gui.lua
Enabled=1
```

Fields:

- `Name` — addon/module name. For private/store addons, the public docs say this
  also identifies the addon's local folder and store name.
- `Dependencies` — comma-separated modules that must load first. Add
  `minionlib` to use the Minion core library.
- `Version` — addon version metadata.
- `Files` — comma-separated Lua files in load/merge order.
- `Enabled` — `1` to enable the addon by default.
- `CreateFolders` — optional comma-separated single-level local folders, for
  example `CreateFolders=logs,settings,data`. Names are case-sensitive.
- `ExportFiles` — optional packaged files that must be written to the user's
  local addon directory. The public docs warn that exported files are
  overwritten when the addon loads and require matching `CreateFolders` paths.
- `SharedAccess` — private-addon UUID allowlist used with private module table
  sharing; see the official private-addon guide.

All Lua files must appear in `Files`. Private/store packaging merges them into a
single Lua chunk in the listed order while retaining the declared folder
structure for packaged resources. Consequently, top-level `local` values from
one listed file can share the merged module scope in packaged builds. During
ordinary loose-file development, do not depend on that merge behavior unless
you also test the packaged addon.

## Lifecycle and event handlers

Subscribe with the public API:

```lua
RegisterEventHandler(eventName, handlerFunction, uniqueIdentifier)
```

Use a stable, addon-prefixed identifier to make logs and registrations
recognizable:

```lua
RegisterEventHandler(
    "Gameloop.Update",
    ExampleAddon.Update,
    "ExampleAddon.Update"
)
```

The public API describes `RegisterEventHandler` as registering a local handler to
an event. Handler arguments are event-specific; lifecycle and game-loop handlers
are commonly written to tolerate `(event, ticks)` even when those arguments are
not needed.

### Initialization: `Module.Initalize`

The event name is spelled **`Initalize`** in the observed/public Minion API. Use
that exact spelling:

```lua
function ExampleAddon.Init(event, ticks)
    d("[ExampleAddon] initialized")
end

RegisterEventHandler(
    "Module.Initalize",
    ExampleAddon.Init,
    "ExampleAddon.Init"
)
```

Use initialization for one-time setup that requires the module environment to be
ready, such as:

- setting default configuration values;
- adding Minion menu entries;
- constructing addon state;
- checking dependencies;
- registering integration callbacks that must be registered during module init.

Do not perform slow loops or blocking I/O in initialization.

### Update: `Gameloop.Update`

This is the normal recurring game-loop pulse:

```lua
ExampleAddon.LastUpdate = 0

function ExampleAddon.Update(event, ticks)
    local now = GetTickCount()
    if now - ExampleAddon.LastUpdate < 250 then
        return
    end
    ExampleAddon.LastUpdate = now

    if Player and Player.alive then
        -- Read state and advance one small state-machine step.
    end
end

RegisterEventHandler(
    "Gameloop.Update",
    ExampleAddon.Update,
    "ExampleAddon.Update"
)
```

Update handlers run on the game/Lua thread:

- keep each call short;
- throttle work with `GetTickCount()`, `Now()`, or `TimeSince()`;
- do not sleep or busy-wait;
- model multi-frame work as explicit state (`phase`, `nextAt`, etc.);
- issue one asynchronous UI/game transition, then verify it on a later pulse;
- wrap only expected failure boundaries with `pcall`; log errors rather than
  silently swallowing them.

### Drawing/UI: `Gameloop.Draw`

Draw addon windows from the draw event, not from the update event:

```lua
ExampleAddon.WindowOpen = false

function ExampleAddon.Draw(event, ticks)
    if not ExampleAddon.WindowOpen then
        return
    end

    local visible
    visible, ExampleAddon.WindowOpen =
        GUI:Begin("Example Addon", ExampleAddon.WindowOpen)

    if visible then
        GUI:Text("Hello from ExampleAddon")
        if GUI:Button("Close") then
            ExampleAddon.WindowOpen = false
        end
    end

    GUI:End()
end

RegisterEventHandler(
    "Gameloop.Draw",
    ExampleAddon.Draw,
    "ExampleAddon.Draw"
)
```

Important GUI rules:

- pair every successful/window `GUI:Begin` path with `GUI:End`;
- keep persistent open/selected/input values in addon state;
- many widgets return updated value(s), often plus a `changed` boolean;
- use `##suffix` in labels when separate widgets need the same visible text but
  unique IDs;
- balance pushed style colors/variables and item widths with corresponding pops;
- do not put automation side effects in draw code unless they are direct user
  button actions.

The exact GUI function signatures and constants are listed in `addon/globals.lua`.

### Other events

Minion and game-specific modules expose additional events. Register only event
names documented for the installed runtime or observed in public addon examples.
The core pattern remains:

```lua
RegisterEventHandler("Some.Event", handler, "ExampleAddon.SomeEvent")
```

Custom events can be dispatched with the public `QueueEvent` API. Its documented
form requires at least one string argument, even if that argument is empty:

```lua
QueueEvent("ExampleAddon.Toggle", "")
RegisterEventHandler(
    "ExampleAddon.Toggle",
    function() ExampleAddon.Enabled = not ExampleAddon.Enabled end,
    "ExampleAddon.Toggle"
)
```

## Recommended addon skeleton

```lua
ExampleAddon = ExampleAddon or {
    Enabled = true,
    WindowOpen = false,
    NextUpdateAt = 0,
}

local function log(message)
    d("[ExampleAddon] " .. tostring(message))
end

function ExampleAddon.Init()
    log("initialized")
end

function ExampleAddon.Update()
    if not ExampleAddon.Enabled then
        return
    end

    local now = GetTickCount()
    if now < ExampleAddon.NextUpdateAt then
        return
    end
    ExampleAddon.NextUpdateAt = now + 250

    -- Advance at most one small automation state here.
end

function ExampleAddon.Draw()
    if not ExampleAddon.WindowOpen then
        return
    end

    local visible
    visible, ExampleAddon.WindowOpen =
        GUI:Begin("Example Addon##ExampleAddon", ExampleAddon.WindowOpen)
    if visible then
        ExampleAddon.Enabled = GUI:Checkbox("Enabled", ExampleAddon.Enabled)
        GUI:Text("Current map: " .. tostring(Player and Player.localmapid))
    end
    GUI:End()
end

RegisterEventHandler(
    "Module.Initalize",
    ExampleAddon.Init,
    "ExampleAddon.Init"
)
RegisterEventHandler(
    "Gameloop.Update",
    ExampleAddon.Update,
    "ExampleAddon.Update"
)
RegisterEventHandler(
    "Gameloop.Draw",
    ExampleAddon.Draw,
    "ExampleAddon.Draw"
)

return ExampleAddon
```

For a local development addon, a global main table makes console inspection and
reload debugging convenient. For a packaged private addon, the public developer
guide recommends making the main table local when its data should not be globally
accessible.

## Minion menu integration

The public MinionLib API documents menu components, members, and submembers:

```lua
local component = {
    header = {
        id = "EXAMPLEADDON##MENU_HEADER",
        name = "Example Addon",
        expanded = false,
    },
    members = {},
}

ml_gui.ui_mgr:AddComponent(component)
ml_gui.ui_mgr:AddMember({
    id = "EXAMPLEADDON##OPEN",
    name = "Open",
    tooltip = "Open Example Addon",
    onClick = function()
        ExampleAddon.WindowOpen = not ExampleAddon.WindowOpen
    end,
}, "EXAMPLEADDON##MENU_HEADER")
```

Publicly documented calls:

```lua
ml_gui.ui_mgr:AddComponent(component)
ml_gui.ui_mgr:AddMember(member, componentId)
ml_gui.ui_mgr:AddSubMember(submember, componentId, memberId)
```

IDs should be globally distinctive. Menu callbacks should generally toggle state
or open a window; recurring work belongs in `Gameloop.Update`.

## Settings and local files

For simple persisted Lua values/tables, the public runtime exposes:

```lua
FileSave(fullPath, value)
local value = FileLoad(fullPath)
```

Build paths from the runtime root rather than assuming beta/live layout:

```lua
local addonPath = GetLuaModsPath() .. "ExampleAddon\\"
local settingsPath = addonPath .. "settings\\settings.lua"
```

Declare writable subfolders with `CreateFolders` in `module.def`. Windows paths in
Lua strings need escaped backslashes (`"\\"`) or long-bracket strings.

Additional public file APIs include `FileExists`, `FileWrite`, `FileDelete`,
`FileSize`, `FolderExists`, `FolderCreate`, `FolderDelete`, and `FolderList`.
Check return values and avoid per-frame disk writes.

## Packaged/private addon files

The public private-addon guide documents:

```lua
local moduleFunctions = GetPrivateModuleFunctions()
```

Keep that table local/private. Publicly documented members include:

- `GetModuleFiles("subfolder")` — list packaged files in a subfolder; root access
  is not provided;
- `ReadModuleFile(fileInfo)` — read one listed `{p,m,f}` entry as a Lua string;
- `CheckUserAddonOwnership(uuid)` — check store-addon ownership;
- private table sharing helpers when configured with `SharedAccess`.

Example packaged data load:

```lua
local moduleFunctions = GetPrivateModuleFunctions()
local entries = moduleFunctions.GetModuleFiles("data")
for _, entry in pairs(entries or {}) do
    local source = moduleFunctions.ReadModuleFile(entry)
    if source then
        local chunk, err = loadstring(source)
        if chunk then
            local value = chunk()
            -- consume value
        else
            d("[ExampleAddon] " .. tostring(err))
        end
    end
end
```

Do not put the private module-function table in a global unless exposing those
capabilities is intentional.

## Reload behavior

`Reload()` reloads Lua modules. Write addon initialization so repeated reloads do
not create uncontrolled duplicate state:

- use stable event identifiers;
- initialize globals with `ExampleAddon = ExampleAddon or {...}` when preserving
  state is desired;
- reset transient state explicitly when required;
- avoid anonymous recurring registrations created repeatedly from update code;
- close or invalidate addon-owned asynchronous work before assuming old callbacks
  cannot run.

During development, test both a fresh game start and `Reload()`.

## Public debugging helpers

Useful documented APIs:

```lua
d(value)             -- print to Minion console
ml_debug(message)    -- debug output when logging is enabled
ml_error(message)    -- error output
ml_log(message)      -- status-bar/pulse message
stacktrace()         -- print current Lua call stack where supported
GetTickCount()
Now()
TimeSince(previous)
```

Prefix messages with the addon name. Do not recursively print enormous runtime
tables; build a small diagnostic table instead.

## Checklist

- [ ] Addon has a valid `module.def`.
- [ ] Every Lua source file is listed in `Files` in intended load order.
- [ ] `Dependencies=minionlib` is present when core Minion APIs are used.
- [ ] One-time setup is registered on `Module.Initalize` (exact spelling).
- [ ] Recurring automation is registered on `Gameloop.Update` and throttled.
- [ ] GUI rendering is registered on `Gameloop.Draw`.
- [ ] Every event registration has a stable, unique identifier.
- [ ] Update/draw handlers do not block, sleep, or busy-wait.
- [ ] UI/game transitions are verified on later frames.
- [ ] Writable directories are declared with `CreateFolders`.
- [ ] File paths come from `GetLuaModsPath()`/`GetStartupPath()`.
- [ ] Private module functions remain in a local table.
- [ ] Fresh startup and Lua reload have both been tested.
