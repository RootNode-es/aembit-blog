#!/usr/bin/env python3
"""Rewrite test commands so only failures and the summary reach the context."""
import json
import re
import sys

TEST_COMMANDS = re.compile(r"^(npm test|pytest|go test)\b")

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

if not TEST_COMMANDS.match(command) or "|" in command:
    sys.exit(0)  # not a test run, or already filtered: leave it alone

filtered = (f"{command} 2>&1 | grep -E -A 5 "
            "'(FAIL|ERROR|Error|failed|passed)' | head -100")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": {**data["tool_input"], "command": filtered},
    }
}))