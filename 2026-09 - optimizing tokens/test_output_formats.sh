#!/bin/bash
A="Review generate_products.py and suggest improvements."

for run in 1 2 3; do
  echo "== Run $run"
  echo -n "Default:        "
  claude -p "$A" --output-format json | jq '.usage.output_tokens'
  echo -n "Simple English: "
  claude -p "/simple-english $A" --output-format json | jq '.usage.output_tokens'
done