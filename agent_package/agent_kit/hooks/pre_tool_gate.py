"""PreToolUse lifecycle hook script adhering to the camelCase stdin/stdout JSON contract."""

from __future__ import annotations

import json
import sys


def main() -> None:
    raw_stdin = sys.stdin.read().strip()
    payload = json.loads(raw_stdin) if raw_stdin else {}
    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    cmd = str(args.get("CommandLine", ""))

    # Guard against accidental destructive git/filesystem commands
    blocked_patterns = ["rm -rf /", "git push --force", "format c:"]
    for pattern in blocked_patterns:
        if pattern in cmd.lower():
            print(json.dumps({"decision": "deny", "reason": f"Blocked unsafe command pattern: {pattern}"}))
            return

    print(json.dumps({"decision": "allow", "reason": "Passed FDE PreToolUse safety gate."}))


if __name__ == "__main__":
    main()

