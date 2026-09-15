"""Executes already-validated SQL against the read-only DuckDB warehouse.

This module assumes the SQL it's handed has already passed
core.sql_validation.validate_and_prepare_sql. It adds the two remaining
runtime safeguards: a hard query timeout, and using a dedicated per-call
cursor so cancelling one query can never affect another.
"""

import concurrent.futures
import time
from dataclasses import dataclass

import duckdb
import pandas as pd


class QueryTimeoutError(Exception):
    pass


class QueryExecutionError(Exception):
    pass


@dataclass(frozen=True)
class QueryResult:
    dataframe: pd.DataFrame
    elapsed_seconds: float


def execute_query(conn: duckdb.DuckDBPyConnection, sql: str, timeout_seconds: int) -> QueryResult:
    cursor = conn.cursor()
    start = time.monotonic()

    def run() -> pd.DataFrame:
        return cursor.execute(sql).df()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run)
        try:
            df = future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            cursor.interrupt()
            raise QueryTimeoutError(
                f"Query exceeded the {timeout_seconds}s timeout and was cancelled."
            )
        except Exception as e:
            raise QueryExecutionError(str(e)) from e

    return QueryResult(dataframe=df, elapsed_seconds=time.monotonic() - start)
