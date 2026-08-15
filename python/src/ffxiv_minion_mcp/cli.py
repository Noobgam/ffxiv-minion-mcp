"""Small stdlib-only client for the bridge's optional /runLua endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="run Lua inside FFXIVMinion")
    parser.add_argument("code", help="Lua expression/chunk, or '-' to read stdin")
    parser.add_argument("-p", "--pid", type=int, help="target game PID")
    parser.add_argument("-t", "--timeout", type=float, default=12.0)
    parser.add_argument("-j", "--json", action="store_true", help="print full envelope")
    args = parser.parse_args()

    code = sys.stdin.read() if args.code == "-" else args.code
    port = os.getenv("FFXIV_MINION_MCP_PORT", "9471")
    endpoint = f"http://127.0.0.1:{port}/runLua"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            {"code": code, "pid": args.pid, "timeout": args.timeout}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout + 5) as response:
            payload = json.loads(response.read())
    except urllib.error.URLError as error:
        print(f"bridge server is not reachable at {endpoint}: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload))
    elif payload.get("ok"):
        print(payload.get("result"))
    else:
        print(payload.get("error"), file=sys.stderr)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
