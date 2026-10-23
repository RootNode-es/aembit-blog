#!/bin/bash
TASK_A="Read products.html and products.json in full, then summarize the product categories and price ranges."
TASK_B="Create slugify.py with a function that converts a string into a URL slug, add a pytest test for it in test_slugify.py, and run the test."
SUM='.usage | {input_total: (.input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens), cache_read: .cache_read_input_tokens, output: .output_tokens}'

reset() { git clean -fdq && git checkout -q .; }

echo "== Task B after Task A, same session (no /clear)"
reset
claude -p "$TASK_A" > /dev/null
claude -p --continue "$TASK_B" --permission-mode acceptEdits --output-format json | jq "$SUM"

echo "== Task B in a fresh session (/clear equivalent)"
reset
claude -p "$TASK_B" --permission-mode acceptEdits --output-format json | jq "$SUM"