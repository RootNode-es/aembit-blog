#!/bin/bash
TASK="Read products.csv with the Read tool, then tell me the average price and the total stock value (price × stock) of the 10 most expensive products."
SUM='{input: (.usage.input_tokens + .usage.cache_read_input_tokens + .usage.cache_creation_input_tokens), output: .usage.output_tokens, answer: .result}'

for run in 1 2 3; do
  echo "== Run $run: full CSV"
  claude -p "$TASK" --output-format json | jq "$SUM"
  echo "== Run $run: with hook"
  TOP10_FILTER=1 claude -p "$TASK" --output-format json | jq "$SUM"
done