"""Schema introspection over whatever tables are loaded in the DuckDB warehouse.

Nothing here is hardcoded to a particular dataset: it reads
information_schema at request time, so any CSV(s) loaded via
data/build_warehouse.py are automatically describable.
"""

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[ColumnInfo]


def get_tables(conn: duckdb.DuckDBPyConnection) -> list[TableInfo]:
    """Introspects every base table in the main schema."""
    table_rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()

    tables = []
    for (table_name,) in table_rows:
        column_rows = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            ORDER BY ordinal_position
            """,
            [table_name],
        ).fetchall()
        columns = [ColumnInfo(name=name, data_type=dtype) for name, dtype in column_rows]
        tables.append(TableInfo(name=table_name, columns=columns))

    return tables


def get_table_names(conn: duckdb.DuckDBPyConnection) -> list[str]:
    return [t.name for t in get_tables(conn)]


def describe_schema(conn: duckdb.DuckDBPyConnection) -> str:
    """Renders the schema as compact text suitable for a model prompt."""
    tables = get_tables(conn)
    if not tables:
        return "(no tables loaded)"

    lines = []
    for table in tables:
        lines.append(f"Table: {table.name}")
        for col in table.columns:
            lines.append(f"  - {col.name} ({col.data_type})")
    return "\n".join(lines)
