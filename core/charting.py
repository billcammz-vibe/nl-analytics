"""Infers an appropriate chart type from a query result's shape and builds
the corresponding Plotly figure. Falls back to table-only when nothing fits.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_TYPES = ["bar", "line", "scatter", "table"]


def _numeric_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _datetime_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


def infer_chart_type(df: pd.DataFrame) -> str:
    if df.empty or len(df.columns) < 2:
        return "table"

    numeric_cols = _numeric_cols(df)
    datetime_cols = _datetime_cols(df)
    other_cols = [c for c in df.columns if c not in numeric_cols and c not in datetime_cols]

    if datetime_cols and numeric_cols:
        return "line"
    if other_cols and numeric_cols and df[other_cols[0]].nunique(dropna=True) <= 50:
        return "bar"
    if len(numeric_cols) >= 2:
        return "scatter"
    return "table"


def build_chart(df: pd.DataFrame, chart_type: str) -> go.Figure | None:
    if df.empty or chart_type == "table":
        return None

    numeric_cols = _numeric_cols(df)
    datetime_cols = _datetime_cols(df)
    other_cols = [c for c in df.columns if c not in numeric_cols and c not in datetime_cols]

    fig = None
    if chart_type == "line":
        x = (datetime_cols or other_cols or list(df.columns))[0]
        y_cols = (numeric_cols or [c for c in df.columns if c != x])[:5]
        fig = px.line(df.sort_values(x), x=x, y=y_cols, markers=True)
    elif chart_type == "bar":
        x = (other_cols or list(df.columns))[0]
        y = (numeric_cols or [c for c in df.columns if c != x])[0]
        fig = px.bar(df, x=x, y=y)
    elif chart_type == "scatter":
        if len(numeric_cols) >= 2:
            x, y = numeric_cols[0], numeric_cols[1]
        else:
            x, y = df.columns[0], df.columns[-1]
        fig = px.scatter(df, x=x, y=y)

    if fig is not None:
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=420)

    return fig
