#!/usr/bin/env python3
"""When TOP10_FILTER=1, replace reads of products.csv with its 10 most expensive rows."""
import csv
import json
import os
import sys

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})
path = tool_input.get("file_path", "")

if os.environ.get("TOP10_FILTER") != "1" or not path.replace("\\", "/").endswith("/products.csv"):
    sys.exit(0)  # hook off, or another file: no change

with open(path, newline="") as f:
    rows = list(csv.DictReader(f))

top10 = sorted(rows, key=lambda r: float(r["price"]), reverse=True)[:10]

out_dir = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "tmp")
os.makedirs(out_dir, exist_ok=True)
filtered = os.path.join(out_dir, "products_top10.csv")

with open(filtered, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(top10)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": {**tool_input, "file_path": filtered},
        "additionalContext": "A hook pre-filtered products.csv to its 10 most "
                             "expensive products, sorted by price (highest first).",
    }
}))