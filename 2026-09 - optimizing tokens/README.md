# Token Optimization Exercises

Hands-on exercises for the article **"Optimizing tokens when automating and using LLMs"**. Each script runs the same task in Claude Code two ways and compares the tokens consumed, so you can see the effect of each technique with real numbers.

| Script | Technique | What it compares |
|---|---|---|
| `test_output_formats.sh` | Simplify input | The same product catalog sent as HTML, JSON, and CSV |
| `test_clear.sh` | Use context efficiently | A small task run after a context-heavy one, with and without clearing the context |
| `test_hook.sh` | Hooks | A calculation on the full CSV vs. a CSV pre-filtered by a `PreToolUse` hook |

## Requirements

- Python 3.9 or later
- [Claude Code](https://code.claude.com) installed and signed in (`claude --version` should work)
- `jq` for reading the JSON output (`brew install jq` on macOS, `sudo apt install jq` on Debian/Ubuntu)
- `git` (used by `test_clear.sh` to reset the folder between runs)

> **Note on cost:** every script calls Claude Code several times. On an API key this is billed per token; on a Pro or Max plan it counts toward your usage limits.

## 1. Create a Python virtual environment

From this folder:

```bash
python3 -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

Your prompt shows `(.venv)` while the environment is active. Install the test runner used by the `/clear` exercise:

```bash
pip install pytest
```

To leave the environment later, run `deactivate`.

> On Debian or Ubuntu, if `python3 -m venv` fails with an `ensurepip` error, install the module first: `sudo apt install python3-venv`.

## 2. Generate the product files

```bash
python3 generate_products.py
```

This writes the same product catalog in three formats:

- `products.csv`
- `products.json`
- `products.html`

The content is identical in all three; only the packaging differs. The generator uses a fixed random seed, so the files are the same every time you run it. To make the differences in the exercises more visible, increase the number of products in `generate_products.py` (for example, `range(1000)`).

## 3. Commit a baseline

`test_clear.sh` resets the folder between runs with `git clean` and `git checkout`, so it needs a committed starting point:

```bash
git init -q
printf ".venv/\n.claude/tmp/\n" > .gitignore
git add . && git commit -qm "baseline"
```

> `slugify.py` and `test_slugify.py` are created by the `/clear` exercise itself. If they already exist from a previous run, delete them before committing the baseline.

## 4. Register the hook

The hook exercise needs `hook_filter_tests.py` registered as a `PreToolUse` hook. Create `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PROJECT_DIR}/hook_filter_tests.py"]
          }
        ]
      }
    ]
  }
}
```

The hook only acts when the `TOP10_FILTER=1` environment variable is set, so it doesn't affect the other exercises. Run `claude` in this folder and type `/hooks` to confirm it's loaded.

## 5. Run the exercises

Make the scripts executable once:

```bash
chmod +x test_*.sh
```

Then run each one from this folder:

### Simplify input: HTML vs. JSON vs. CSV

```bash
./test_output_formats.sh
```

Asks Claude Code to read each product file and reports the input tokens for each. Run it once with a prompt that reads no file to get Claude Code's fixed baseline, and subtract it from each result: the difference is what each format cost.

**What to look for:** CSV states the field names once, JSON repeats them on every record, and HTML wraps every value in markup, so the same data costs very different amounts.

### Use context efficiently: the effect of `/clear`

```bash
./test_clear.sh
```

Runs a context-heavy task (reading the product files), then a small unrelated task (creating `slugify.py` with a test). It measures the small task twice: continuing the same session, and in a fresh session, which is what `/clear` gives you.

**What to look for:** input tokens for the small task are far higher when it carries the earlier history, because every step re-sends the whole context. The cost gap is smaller than the token gap, since most of the carried-over context is served from the prompt cache.

### Hooks: full CSV vs. pre-filtered CSV

First, compute the correct answer in code so you can check both runs:

```bash
python3 -c "
import csv
rows = sorted(csv.DictReader(open('products.csv')), key=lambda r: float(r['price']), reverse=True)[:10]
print('Average price:', round(sum(float(r['price']) for r in rows) / 10, 2))
print('Total stock value:', round(sum(float(r['price']) * int(r['stock']) for r in rows), 2))
"
```

Then run the comparison:

```bash
./test_hook.sh
```

Asks for the average price and total stock value of the 10 most expensive products, once reading the full CSV and once with the hook enabled (`TOP10_FILTER=1`), which hands Claude only the 10 relevant rows.

**What to look for:** the hook run uses a fraction of the input tokens, and its answer is more reliable, because code did the sorting instead of the model scanning every row.

## Reading the results

- **Average several runs.** LLMs don't take exactly the same steps every time, so run each script a few times and compare averages, not single runs.
- **Total input = all three input fields.** The scripts add `input_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens`, since most of each request is served from the prompt cache.
- **The first run may cost more.** It writes Claude Code's system prompt to the cache; later runs within a few minutes read it at a fraction of the price. Token totals are unaffected.
- **Interactive alternative:** for screenshots, run the same prompts in `claude` and use `/context` to see what fills the context window, and `/usage` to see session totals.

## Troubleshooting

- **`jq` reports a missing field:** run the `claude -p ... --output-format json` command on its own to check the JSON structure your version returns.
- **The hook doesn't fire:** check `/hooks` inside Claude Code, and make sure the prompt asks Claude to use the Read tool. If Claude opens the file another way (for example with a Python script), the hook isn't triggered.
- **`test_clear.sh` leaves files behind:** run `git clean -fdq && git checkout -q .` to return to the baseline.
