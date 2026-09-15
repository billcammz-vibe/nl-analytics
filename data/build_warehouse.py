"""Builds a read-only DuckDB warehouse from every CSV in a data directory.

This is the ONLY code path in this project that opens DuckDB in read-write
mode. The Streamlit app (app.py / core/*) always opens the resulting file
with read_only=True, so no query the app ever issues can mutate data,
regardless of what the SQL validator does or doesn't catch.

Run directly: python data/build_warehouse.py
"""

import glob
import os

import duckdb

DEFAULT_DATA_DIR = os.path.dirname(__file__)
DEFAULT_WAREHOUSE_PATH = os.path.join(DEFAULT_DATA_DIR, "warehouse.duckdb")


def _table_name_from_csv(csv_path: str) -> str:
    base = os.path.splitext(os.path.basename(csv_path))[0]
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


def build_warehouse(data_dir: str = DEFAULT_DATA_DIR, warehouse_path: str = DEFAULT_WAREHOUSE_PATH) -> list[str]:
    """(Re)builds the warehouse file from every *.csv in data_dir.

    Returns the list of table names created.
    """
    csv_paths = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not csv_paths:
        raise FileNotFoundError(
            f"No CSV files found in {data_dir!r}. Run data/seed_data.py first, "
            "or drop your own CSV(s) into that directory."
        )

    if os.path.exists(warehouse_path):
        os.remove(warehouse_path)

    table_names = []
    conn = duckdb.connect(warehouse_path, read_only=False)
    try:
        for csv_path in csv_paths:
            table_name = _table_name_from_csv(csv_path)
            conn.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto(?, header=true)",
                [csv_path],
            )
            table_names.append(table_name)
    finally:
        conn.close()

    return table_names


if __name__ == "__main__":
    created = build_warehouse()
    print(f"Built warehouse with tables: {', '.join(created)}")
