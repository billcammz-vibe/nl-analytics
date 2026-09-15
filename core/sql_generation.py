"""Turns a plain-English question + schema description into a SQL query via Claude.

Uses forced tool-use so the model's output is structured JSON rather than
free text we'd have to hope is parseable. The returned SQL is still fully
untrusted input — core/sql_validation.py is what actually makes it safe to
run, not anything about how it was generated.
"""

import os
from dataclasses import dataclass

from anthropic import Anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

_GENERATE_SQL_TOOL = {
    "name": "generate_sql",
    "description": "Provide the SQL query (or explain why the question can't be answered from the schema).",
    "input_schema": {
        "type": "object",
        "properties": {
            "can_answer": {
                "type": "boolean",
                "description": "True if the question can be answered with a read-only SQL query over the given schema.",
            },
            "sql": {
                "type": ["string", "null"],
                "description": "A single DuckDB-dialect SELECT statement answering the question. Null if can_answer is false.",
            },
            "reason": {
                "type": ["string", "null"],
                "description": "If can_answer is false, a short plain-English explanation of why not (e.g. missing table/column).",
            },
        },
        "required": ["can_answer", "sql", "reason"],
    },
}

SYSTEM_PROMPT = """You translate a user's plain-English question into a single read-only SQL \
query (DuckDB dialect) over the schema provided.

Rules:
- Only use tables and columns that appear in the schema. Never invent columns or tables.
- Only ever produce a single SELECT statement (a WITH ... SELECT CTE is fine). Never produce \
INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, ATTACH, COPY, PRAGMA, or any other \
non-SELECT statement.
- Never use functions that read external files or attach other databases (e.g. read_csv, \
read_parquet, glob, ATTACH) — only query the tables listed in the schema.
- Do not include a trailing semicolon.
- Do not include SQL comments.
- If the question cannot be answered from the given schema (wrong topic, missing data, \
requires a write, etc.), set can_answer to false and explain why in plain English instead of \
guessing or inventing a query.

Always respond by calling the generate_sql tool."""


@dataclass(frozen=True)
class SqlGenerationResult:
    can_answer: bool
    sql: str | None
    reason: str | None


def generate_sql(question: str, schema_description: str) -> SqlGenerationResult:
    client = Anthropic()

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[_GENERATE_SQL_TOOL],
        tool_choice={"type": "tool", "name": "generate_sql"},
        messages=[
            {
                "role": "user",
                "content": f"Schema:\n{schema_description}\n\nQuestion: {question}",
            }
        ],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "generate_sql":
            data = block.input
            return SqlGenerationResult(
                can_answer=bool(data.get("can_answer")),
                sql=data.get("sql"),
                reason=data.get("reason"),
            )

    return SqlGenerationResult(
        can_answer=False,
        sql=None,
        reason="The model did not return a usable response. Please try rephrasing your question.",
    )
