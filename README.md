# Natural-Language Analytics

Ask a question about a CSV dataset in plain English. The app introspects the
schema, asks Claude to generate SQL, shows you that SQL, validates it against
a strict allowlist, runs it read-only, and renders a table + auto-picked
chart + a short plain-English summary.

```
"Which region had the highest revenue last quarter?"
        -> SQL generated and shown
        -> validated (SELECT-only, single statement, known tables only, row-limited)
        -> executed read-only, with a timeout
        -> table + bar/line/scatter chart
        -> 2-3 sentence summary
```

![screenshot placeholder](docs/screenshot.png)

## What it does

- Works on **any** CSV dataset you load — nothing is hardcoded to a
  particular schema. Drop CSV(s) in `data/`, rebuild the warehouse, ask
  questions.
- Shows the generated SQL before running it, and lets you edit it and
  re-run — you're never forced to blindly trust the model's query.
- Auto-picks a chart type (bar / line / scatter) from the shape of the
  result, with a manual override.
- Clearly says so, instead of guessing, when a question can't be answered
  from the loaded schema.

## Architecture

```
app.py                     Streamlit UI: orchestrates the question -> SQL ->
                            validate -> execute -> chart -> summary flow.
core/schema.py              Schema introspection (information_schema).
core/sql_generation.py       Claude call -> structured SQL (forced tool-use).
core/sql_validation.py       AST-based SQL allowlist. The safety-critical module.
core/query_execution.py      Timeout-bounded execution against the read-only conn.
core/charting.py              Chart-type inference + Plotly figure builders.
core/summary.py                Claude call -> plain-English result summary.
data/build_warehouse.py      The ONLY code path allowed to write to the DuckDB
                              file. Loads every data/*.csv into a table.
data/seed_data.py            Generates a realistic sample sales CSV.
```

Each concern above is a separate, independently testable module — the
validator in particular has no dependency on the generation step, so it
treats every query the same regardless of whether it came from Claude or was
hand-edited.

### Schema-introspection approach

At startup, `data/build_warehouse.py` loads every CSV in `data/` into its own
table in a DuckDB file (`data/warehouse.duckdb`), named after the file. From
then on, `core/schema.py` queries `information_schema.tables` /
`information_schema.columns` at request time and renders a compact text
block:

```
Table: sample_sales
  - order_id (BIGINT)
  - order_date (DATE)
  - region (VARCHAR)
  - revenue (DOUBLE)
  ...
```

This is what's passed to Claude as context on every question, and it's also
what the SQL validator uses to build its table allowlist — so both the
generation prompt and the safety check are always in sync with whatever
dataset is actually loaded, without any code change.

## Safety

The database interaction is the highest-risk part of this app (LLM-authored
SQL, executed against a real database, from untrusted user questions). Both
the user's question and the model's SQL output are treated as **untrusted**
input. Defense is layered so no single check carries all the weight:

1. **Read-only at the engine level.** `data/build_warehouse.py` is the only
   code path that ever opens the DuckDB file for writing. The running app
   opens it with `duckdb.connect(path, read_only=True)` — DuckDB itself
   refuses any write statement on that connection (verified: `CREATE TABLE`
   on a read-only connection raises `Invalid Input Error`). Even a validator
   bug can't turn into a mutation.
2. **AST-based SQL validation** (`core/sql_validation.py`), not regex
   keyword-matching. Every query — freshly generated *or* user-edited —
   is parsed with `sqlglot` before it can run:
   - Must parse to exactly **one** statement. A raw semicolon check runs
     first, since a naive parser will happily parse
     `SELECT ...; DROP TABLE ...` as two statements.
   - The parsed root must be a `SELECT` (or `WITH ... SELECT` / `UNION`).
     `INSERT` / `UPDATE` / `DELETE` / `DROP` / `ALTER` / `CREATE` /
     `TRUNCATE` / `MERGE` / `ATTACH` / `COPY` / `PRAGMA` and any other
     non-`SELECT` statement type is rejected outright, and the same check
     runs again by walking the full tree so nothing can be smuggled inside
     a subquery.
   - **Comments are rejected, not stripped.** `--` or `/*` anywhere in the
     raw string is an automatic rejection — correctly stripping comments
     per-dialect is itself a smuggling surface, so it's simpler and safer
     to refuse them entirely.
   - **Function blocklist.** File-reading / extension-loading table
     functions (`read_csv`, `read_parquet`, `glob`, `sqlite_scan`,
     `postgres_scan`, etc.) are rejected even inside an otherwise
     well-formed `SELECT`, so a query can't reach outside the loaded
     dataset.
   - **Table allowlist.** Every table reference in the parsed query is
     checked against the live schema from `core/schema.py`. Unknown tables
     (including the empty table-name sqlglot returns for table-function
     calls) are rejected.
   - **Row limit enforcement.** If the query has no `LIMIT`, one is
     injected on the AST; if it has one above the configured max, it's
     clamped down. This is done by rewriting the parsed tree, not by string
     concatenation.
3. **Query timeout.** Every execution runs in a worker thread with a hard
   wall-clock timeout (`QUERY_TIMEOUT_SECONDS`); on timeout the query's
   DuckDB cursor is interrupted (verified against a real long-running query)
   and a clear timeout error is shown instead of hanging the UI.
4. **No string interpolation into SQL.** The model's SQL text is validated
   and then executed as-is — it is never concatenated into a larger
   app-built query string, which is the classic way a "safe" LLM SQL layer
   quietly reintroduces injection.
5. **Clear rejection messages.** A query that fails validation shows the
   specific reason ("Only SELECT statements are allowed", "Unknown or
   disallowed table 'x'", "SQL comments are not allowed", etc.) rather than
   a generic error, so it's obvious to the user this is a safety rejection
   and not a bug.

None of this is theoretical — every rule above has a corresponding test case
(multi-statement smuggling, `DROP`/`DELETE`/`ATTACH`/`PRAGMA`, comment
smuggling, `read_csv_auto('/etc/passwd')`, unknown tables, oversized
`LIMIT`) that was run against the actual validator during development.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY

python data/seed_data.py        # generates data/sample_sales.csv
python data/build_warehouse.py  # builds data/warehouse.duckdb (read-write, once)

streamlit run app.py
```

Then open the local URL Streamlit prints (default `http://localhost:8501`).

### Using your own dataset

Drop one or more `.csv` files into `data/` (each becomes a table named after
the file) and re-run `python data/build_warehouse.py`. No code changes
needed — the schema introspection and the SQL validator's table allowlist
both pick up the new tables automatically.

### Environment variables

See `.env.example`:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key, used for SQL generation and summaries |
| `CLAUDE_MODEL` | Model id (defaults to `claude-sonnet-5`) |
| `MAX_ROWS` | Row cap enforced on every query (default 1000) |
| `QUERY_TIMEOUT_SECONDS` | Hard query timeout (default 10s) |
| `DATA_DIR` | Directory scanned for CSVs (default `data`) |
| `WAREHOUSE_PATH` | Path to the DuckDB warehouse file |

## Deploying

This is a standard Streamlit app, so [Streamlit Community
Cloud](https://streamlit.io/cloud) is the simplest path:

1. Push this repo to GitHub (`data/warehouse.duckdb` and `.env` are
   gitignored — the deploy step below rebuilds the warehouse).
2. On Streamlit Community Cloud, create a new app pointing at `app.py`.
3. Add `ANTHROPIC_API_KEY` (and any other `.env.example` values you want to
   override) as app secrets.
4. Add a build step (or a one-line `if not os.path.exists(...)` guard,
   already present in `app.py`) so `data/build_warehouse.py` runs on first
   boot — it already does, via `get_connection()`.

It also runs anywhere that can run `streamlit run app.py` — a container,
a VM, etc. — with the same environment variables.

## Limitations

- Single read-only DuckDB file, not a live production database — swapping
  in an actual Postgres read-only role would mean changing
  `core/query_execution.py`'s connection and the (still applicable)
  validator; the validation module itself is not DuckDB-specific.
- Chart auto-selection is a small set of heuristics, not exhaustive —
  it's meant to get the common cases right and always leaves the user a
  manual override.
