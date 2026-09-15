"""Generates a short plain-English interpretation of a query result via Claude."""

import os

import pandas as pd
from anthropic import Anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You write a short plain-English interpretation of a SQL query result \
for a business user. 2-3 sentences. State the key finding(s) directly using the actual \
values shown. Do not describe the SQL or mention that you're looking at a table. Do not \
speculate beyond what the data shows."""


def generate_summary(question: str, sql: str, df: pd.DataFrame, max_preview_rows: int = 30) -> str:
    client = Anthropic()

    preview = df.head(max_preview_rows).to_csv(index=False)
    truncated_note = "" if len(df) <= max_preview_rows else f"\n(showing first {max_preview_rows} of {len(df)} rows)"

    user_content = (
        f"Question: {question}\n\n"
        f"SQL used:\n{sql}\n\n"
        f"Result ({len(df)} row(s), {len(df.columns)} column(s)):\n{preview}{truncated_note}"
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    parts = [block.text for block in message.content if block.type == "text"]
    return "".join(parts).strip() or "No summary was generated."
