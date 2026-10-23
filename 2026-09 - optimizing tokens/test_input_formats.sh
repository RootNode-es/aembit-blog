#!/bin/bash
# Compare the token cost of the same data as CSV, JSON, and HTML.

FILTER='(.usage.input_tokens + .usage.cache_read_input_tokens + .usage.cache_creation_input_tokens)'

measure() {
  claude -p "$1" --disallowedTools "Bash" --output-format json | jq "$FILTER"
}

echo "== Baseline (no file)"
BASE=$(measure "Reply only 'done'.")
echo "Input tokens: $BASE"

for f in products.csv products.json products.html; do
  TOTAL=$(measure "Read $f in full with the Read tool and reply only 'done'. Don't analyze it.")
  echo "== $f"
  echo "Input tokens: $TOTAL  (file cost: $((TOTAL - BASE)))"
done