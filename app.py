"""Natural-language analytics over a CSV dataset.

Flow: question -> generated SQL (shown + editable) -> validated -> executed
read-only -> table + auto-picked chart -> plain-English summary.
"""

import os

import duckdb
import streamlit as st
from dotenv import load_dotenv

from core import schema as schema_mod
from core.charting import CHART_TYPES, build_chart, infer_chart_type
from core.query_execution import QueryExecutionError, QueryTimeoutError, execute_query
from core.sql_generation import generate_sql
from core.sql_validation import validate_and_prepare_sql
from core.summary import generate_summary
from data.build_warehouse import build_warehouse

load_dotenv()

MAX_ROWS = int(os.environ.get("MAX_ROWS", "1000"))
QUERY_TIMEOUT_SECONDS = int(os.environ.get("QUERY_TIMEOUT_SECONDS", "10"))
DATA_DIR = os.environ.get("DATA_DIR", "data")
WAREHOUSE_PATH = os.environ.get("WAREHOUSE_PATH", "data/warehouse.duckdb")

st.set_page_config(page_title="NL Analytics", page_icon="📊", layout="wide")


@st.cache_resource(show_spinner=False)
def get_connection() -> duckdb.DuckDBPyConnection:
    if not os.path.exists(WAREHOUSE_PATH):
        build_warehouse(data_dir=DATA_DIR, warehouse_path=WAREHOUSE_PATH)
    # The app process only ever holds a read-only handle. No code path below
    # this line can open WAREHOUSE_PATH for writing.
    return duckdb.connect(WAREHOUSE_PATH, read_only=True)


def init_state():
    defaults = {
        "sql_text": "",
        "sql_version": 0,
        "generation_reason": None,
        "result_df": None,
        "chart_type": None,
        "summary": None,
        "error": None,
        "last_sql_run": None,
        "result_version": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def run_pipeline(raw_sql: str, question: str, allowed_tables: list[str], conn: duckdb.DuckDBPyConnection):
    """Validates, executes, charts, and summarizes one SQL query.

    This is the single choke point every query passes through, whether it
    came fresh from the model or was hand-edited by the user — nothing gets
    executed without going through validate_and_prepare_sql first.
    """
    st.session_state["result_df"] = None
    st.session_state["summary"] = None
    st.session_state["error"] = None

    validation = validate_and_prepare_sql(raw_sql, allowed_tables, MAX_ROWS)
    if not validation.is_valid:
        st.session_state["error"] = f"Safety layer rejected this query: {validation.error}"
        return

    st.session_state["last_sql_run"] = validation.sql

    try:
        with st.spinner("Running query..."):
            result = execute_query(conn, validation.sql, QUERY_TIMEOUT_SECONDS)
    except QueryTimeoutError as e:
        st.session_state["error"] = str(e)
        return
    except QueryExecutionError as e:
        st.session_state["error"] = f"The database rejected this query: {e}"
        return

    df = result.dataframe
    st.session_state["result_df"] = df
    st.session_state["chart_type"] = infer_chart_type(df)
    st.session_state["result_version"] += 1

    try:
        with st.spinner("Summarizing result..."):
            st.session_state["summary"] = generate_summary(question, validation.sql, df)
    except Exception as e:
        st.session_state["summary"] = None
        st.session_state["error"] = f"Query succeeded, but the summary could not be generated: {e}"


def main():
    init_state()

    st.title("📊 Natural-language analytics")
    st.caption("Ask a question about the dataset in plain English. Every query is generated, "
               "shown to you, validated, and run read-only before you see results.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        st.stop()

    conn = get_connection()
    tables = schema_mod.get_tables(conn)
    allowed_tables = [t.name for t in tables]
    schema_description = schema_mod.describe_schema(conn)

    with st.sidebar:
        st.subheader("Loaded dataset")
        for table in tables:
            with st.expander(table.name, expanded=False):
                for col in table.columns:
                    st.text(f"{col.name} — {col.data_type}")
        st.divider()
        st.subheader("Safety")
        st.caption(
            f"- Read-only connection\n"
            f"- SELECT-only, single statement\n"
            f"- Row limit: {MAX_ROWS}\n"
            f"- Query timeout: {QUERY_TIMEOUT_SECONDS}s"
        )

    question = st.text_input(
        "Ask a question about this data",
        placeholder="Which region had the highest revenue last quarter?",
    )
    generate_clicked = st.button("Generate SQL", type="primary", disabled=not question.strip())

    if generate_clicked:
        st.session_state["generation_reason"] = None
        with st.spinner("Generating SQL..."):
            try:
                gen = generate_sql(question, schema_description)
            except Exception as e:
                st.session_state["error"] = f"SQL generation failed: {e}"
                gen = None

        if gen is not None:
            if not gen.can_answer:
                st.session_state["generation_reason"] = gen.reason or (
                    "This question can't be answered from the loaded dataset."
                )
                st.session_state["sql_text"] = ""
                st.session_state["result_df"] = None
                st.session_state["summary"] = None
                st.session_state["error"] = None
            else:
                st.session_state["sql_text"] = gen.sql or ""
                st.session_state["sql_version"] += 1
                run_pipeline(gen.sql or "", question, allowed_tables, conn)

    if st.session_state["generation_reason"]:
        st.warning(st.session_state["generation_reason"])

    if st.session_state["sql_text"]:
        st.subheader("Generated SQL")
        editor_key = f"sql_editor_{st.session_state['sql_version']}"
        edited_sql = st.text_area(
            "You can edit this before running it — every run is re-validated.",
            value=st.session_state["sql_text"],
            key=editor_key,
            height=140,
        )
        if st.button("Run query"):
            run_pipeline(edited_sql, question, allowed_tables, conn)

    if st.session_state["error"]:
        st.error(st.session_state["error"])

    df = st.session_state["result_df"]
    if df is not None:
        st.subheader("Result")
        st.dataframe(df, use_container_width=True)
        st.caption(f"{len(df)} row(s) returned (limit: {MAX_ROWS}).")

        chart_type = st.radio(
            "Chart type",
            options=CHART_TYPES,
            index=CHART_TYPES.index(st.session_state["chart_type"] or "table"),
            horizontal=True,
            key=f"chart_type_radio_{st.session_state['result_version']}",
        )
        fig = build_chart(df, chart_type)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        elif chart_type != "table":
            st.info("This result shape doesn't fit that chart type — showing table only.")

        if st.session_state["summary"]:
            st.subheader("Summary")
            st.write(st.session_state["summary"])


if __name__ == "__main__":
    main()
