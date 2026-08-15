--- FFXIVMinionMCP: execute MCP-submitted Lua on the game thread.
---
--- The Python server holds at most one job. This addon keeps one asynchronous
--- long-poll request open, executes a returned job from an HttpRequest callback
--- (dispatched by Minion on the game thread), posts its result, then polls again.
FFXIVMinionMCP = FFXIVMinionMCP or {}

if FFXIVMinionMCP.Enabled == nil then
    FFXIVMinionMCP.Enabled = true
end
FFXIVMinionMCP.PollInFlight = FFXIVMinionMCP.PollInFlight or false
FFXIVMinionMCP.PollStartedAt = FFXIVMinionMCP.PollStartedAt or 0
FFXIVMinionMCP.NextPollAt = FFXIVMinionMCP.NextPollAt or 0

local BRIDGE_HOST = "127.0.0.1"
local BRIDGE_PORT = 9471
local FAILURE_BACKOFF_MS = 3000
local POLL_WATCHDOG_MS = 30000

local function log(message)
    d("[FFXIVMinionMCP] " .. message)
end

--- Tables are encoded with Minion's global json library. Do not fall back to
--- tostring(table): some Minion builds recursively dump tables, which is unsafe
--- for large or cyclic values.
local function serializeValue(value)
    if value == nil then
        return nil
    end
    if type(value) == "table" then
        local ok, encoded = pcall(json.encode, value)
        if ok then
            return encoded
        end
        return nil, "result table is not JSON-serializable: " .. tostring(encoded)
    end
    return tostring(value)
end

--- Expressions are convenient for agent calls, while full chunks permit locals,
--- control flow, and actions. Only the first return value is transported.
local function executeLua(code)
    ---@diagnostic disable-next-line: deprecated
    local func, compileErr = loadstring("return " .. code)
    if func == nil then
        ---@diagnostic disable-next-line: deprecated
        func, compileErr = loadstring(code)
    end
    if func == nil then
        return false, nil, "compile error: " .. tostring(compileErr)
    end

    local ok, resultOrErr = pcall(func)
    if not ok then
        return false, nil, "runtime error: " .. tostring(resultOrErr)
    end

    local result, serializeErr = serializeValue(resultOrErr)
    if serializeErr ~= nil then
        return false, nil, serializeErr
    end
    return true, result, nil
end

local function request(path, body, onSuccess, onFailure)
    HttpRequest({
        host = BRIDGE_HOST,
        port = BRIDGE_PORT,
        path = path,
        method = "POST",
        https = false,
        body = json.encode(body),
        onsuccess = onSuccess,
        onfailure = onFailure,
    })
end

local function postResult(jobId, ok, result, err)
    request("/luaResult", {
        id = jobId,
        pid = GetCurrentPID(),
        ok = ok,
        result = result,
        error = err,
    }, function()
        -- The next Gameloop.Update starts another poll.
    end, function(error)
        log("[WARNING] failed to deliver result for " .. tostring(jobId) .. ": " .. tostring(error))
    end)
end

local function onPollSuccess(body, headers, statusCode)
    FFXIVMinionMCP.PollInFlight = false
    if statusCode ~= 200 then
        FFXIVMinionMCP.NextPollAt = GetTickCount() + FAILURE_BACKOFF_MS
        return
    end

    local response = json.decode(body)
    if response == nil or response.id == nil or response.code == nil then
        return -- empty long poll; immediately start another on the next frame
    end

    local ok, result, err = executeLua(response.code)
    if not ok then
        log("[WARNING] job " .. tostring(response.id) .. " failed: " .. tostring(err))
    end
    postResult(response.id, ok, result, err)
end

local function onPollFailure(error)
    FFXIVMinionMCP.PollInFlight = false
    FFXIVMinionMCP.NextPollAt = GetTickCount() + FAILURE_BACKOFF_MS
end

function FFXIVMinionMCP.Update()
    if not FFXIVMinionMCP.Enabled then
        return
    end

    local now = GetTickCount()
    if FFXIVMinionMCP.PollInFlight then
        if now - FFXIVMinionMCP.PollStartedAt <= POLL_WATCHDOG_MS then
            return
        end
        log("[WARNING] poll watchdog expired; starting a new poll")
        FFXIVMinionMCP.PollInFlight = false
    end
    if now < FFXIVMinionMCP.NextPollAt then
        return
    end

    FFXIVMinionMCP.PollInFlight = true
    FFXIVMinionMCP.PollStartedAt = now
    request("/pollLua", {
        pid = GetCurrentPID(),
    }, onPollSuccess, onPollFailure)
end

if not _G.FFXIVMinionMCPRegistered then
    local function update()
        local ok, err = pcall(FFXIVMinionMCP.Update)
        if not ok then
            log("[ERROR] update failed: " .. tostring(err))
            FFXIVMinionMCP.PollInFlight = false
            FFXIVMinionMCP.NextPollAt = GetTickCount() + FAILURE_BACKOFF_MS
        end
    end
    RegisterEventHandler("Gameloop.Update", update, "FFXIVMinionMCP.Update")
    _G.FFXIVMinionMCPRegistered = true
end

return FFXIVMinionMCP
