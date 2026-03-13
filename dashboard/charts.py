"""
Chart creation functions for the AI Usage Dashboard.

All functions accept DashboardData and return plotly.graph_objects.Figure objects.
"""

import pandas as pd
import plotly.graph_objects as go

from dashboard.data.models import DashboardData
from dashboard.data.layer import (
    get_monthly_summary,
    get_daily_summary,
    get_model_summary,
    get_project_summary,
)
from dashboard.theme import COLOR_PALETTE, DEFAULT_HEIGHT, PIE_HEIGHT


def create_empty_figure(message: str = "No data available") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=16, color="#999"),
    )
    fig.update_layout(
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        height=DEFAULT_HEIGHT,
    )
    return fig


def create_mom_spend_chart(data: DashboardData) -> go.Figure:
    monthly_df = get_monthly_summary(data.costs_df, data.usage_df)
    if monthly_df.empty:
        return create_empty_figure("No cost data available")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly_df["month"].astype(str),
        y=monthly_df["cost_usd"],
        name="Monthly Spend",
        marker_color=COLOR_PALETTE[0],
        text=monthly_df["cost_usd"].apply(lambda x: f"${x:,.2f}"),
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Spend: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(title="Month-on-Month Spend Comparison", xaxis_title="Month",
                      yaxis_title="Spend (USD)", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_daily_cost_chart(data: DashboardData) -> go.Figure:
    daily_df = get_daily_summary(data.costs_df, data.usage_df)
    if daily_df.empty or "cost_usd" not in daily_df.columns:
        return create_empty_figure("No cost data available")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["cost_usd"],
        mode="lines+markers", name="Daily Cost",
        line=dict(shape="spline", width=2, color=COLOR_PALETTE[0]),
        marker=dict(size=6),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Cost: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(title="Daily Cost Trend", xaxis_title="Date", yaxis_title="Cost (USD)",
                      height=DEFAULT_HEIGHT, hovermode="x unified")
    return fig


def create_cost_by_model_chart(data: DashboardData) -> go.Figure:
    if data.costs_df.empty:
        return create_empty_figure("No cost data available")
    model_costs = data.costs_df.groupby("line_item")["cost_usd"].sum().reset_index()
    model_costs = model_costs.sort_values("cost_usd", ascending=True).tail(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=model_costs["line_item"], x=model_costs["cost_usd"],
        orientation="h", name="Cost", marker_color=COLOR_PALETTE[1],
        text=model_costs["cost_usd"].apply(lambda x: f"${x:,.2f}"),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Cost: $%{x:,.2f}<extra></extra>",
    ))
    fig.update_layout(title="Cost by Line Item (Top 10)", xaxis_title="Cost (USD)",
                      yaxis_title="Line Item", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_cost_by_project_chart(data: DashboardData) -> go.Figure:
    if data.costs_df.empty:
        return create_empty_figure("No cost data available")
    has_name = "project_name" in data.costs_df.columns
    label_col = "project_name" if has_name else "project_id"
    project_costs = data.costs_df.groupby(label_col)["cost_usd"].sum().reset_index()
    project_costs = project_costs.sort_values("cost_usd", ascending=True).tail(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=project_costs[label_col], x=project_costs["cost_usd"],
        orientation="h", name="Cost", marker_color=COLOR_PALETTE[2],
        text=project_costs["cost_usd"].apply(lambda x: f"${x:,.2f}"),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Cost: $%{x:,.2f}<extra></extra>",
    ))
    fig.update_layout(title="Cost by Project (Top 10)", xaxis_title="Cost (USD)",
                      yaxis_title="Project", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_token_trend_chart(data: DashboardData) -> go.Figure:
    daily_df = get_daily_summary(data.costs_df, data.usage_df)
    if daily_df.empty or "input_tokens" not in daily_df.columns:
        return create_empty_figure("No usage data available")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily_df["date"], y=daily_df["input_tokens"],
                             mode="lines+markers", name="Input Tokens",
                             line=dict(shape="spline", width=2, color=COLOR_PALETTE[0]),
                             marker=dict(size=6)))
    fig.add_trace(go.Scatter(x=daily_df["date"], y=daily_df["output_tokens"],
                             mode="lines+markers", name="Output Tokens",
                             line=dict(shape="spline", width=2, color=COLOR_PALETTE[2]),
                             marker=dict(size=6)))
    fig.update_layout(title="Token Usage Over Time", xaxis_title="Date",
                      yaxis_title="Tokens", height=DEFAULT_HEIGHT, hovermode="x unified")
    return fig


def create_cumulative_token_chart(data: DashboardData) -> go.Figure:
    daily_df = get_daily_summary(data.costs_df, data.usage_df)
    if daily_df.empty or "total_tokens" not in daily_df.columns:
        return create_empty_figure("No usage data available")
    daily_df = daily_df.sort_values("date")
    daily_df["cumulative_tokens"] = daily_df["total_tokens"].cumsum()
    r, g, b = int(COLOR_PALETTE[1][1:3], 16), int(COLOR_PALETTE[1][3:5], 16), int(COLOR_PALETTE[1][5:7], 16)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["cumulative_tokens"],
        mode="lines", name="Cumulative Tokens",
        line=dict(shape="spline", width=2, color=COLOR_PALETTE[1]),
        fill="tozeroy", fillcolor=f"rgba({r}, {g}, {b}, 0.3)",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Cumulative: %{y:,}<extra></extra>",
    ))
    fig.update_layout(title="Cumulative Token Usage", xaxis_title="Date",
                      yaxis_title="Cumulative Tokens", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_cache_efficiency_chart(data: DashboardData) -> go.Figure:
    daily_df = get_daily_summary(data.costs_df, data.usage_df)
    if daily_df.empty or "input_cached_tokens" not in daily_df.columns:
        return create_empty_figure("No cache data available")
    daily_df["cache_rate"] = (daily_df["input_cached_tokens"] / daily_df["input_tokens"].replace(0, 1)) * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["cache_rate"],
        mode="lines+markers", name="Cache Rate",
        line=dict(shape="spline", width=2, color=COLOR_PALETTE[7]),
        marker=dict(size=6),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Cache Rate: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(title="Cache Efficiency Over Time", xaxis_title="Date",
                      yaxis_title="Cache Rate (%)", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_tokens_by_model_chart(data: DashboardData) -> go.Figure:
    model_stats = get_model_summary(data.usage_df, data.costs_df)
    if model_stats.empty:
        return create_empty_figure("No usage data available")
    model_stats = model_stats.sort_values("total_tokens", ascending=True).tail(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=model_stats["model"], x=model_stats["input_tokens"],
                         orientation="h", name="Input Tokens", marker_color=COLOR_PALETTE[0],
                         hovertemplate="<b>%{y}</b><br>Input: %{x:,}<extra></extra>"))
    fig.add_trace(go.Bar(y=model_stats["model"], x=model_stats["output_tokens"],
                         orientation="h", name="Output Tokens", marker_color=COLOR_PALETTE[2],
                         hovertemplate="<b>%{y}</b><br>Output: %{x:,}<extra></extra>"))
    fig.update_layout(title="Tokens by Model (Top 10)", xaxis_title="Tokens",
                      yaxis_title="Model", barmode="stack", height=DEFAULT_HEIGHT)
    return fig


def create_model_usage_pie_chart(data: DashboardData) -> go.Figure:
    model_stats = get_model_summary(data.usage_df, data.costs_df)
    if model_stats.empty:
        return create_empty_figure("No usage data available")
    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=model_stats["model"], values=model_stats["total_tokens"],
        hole=0.3, marker=dict(colors=COLOR_PALETTE),
        textposition="inside", textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>Tokens: %{value:,}<br>Percentage: %{percent}<extra></extra>",
    ))
    fig.update_layout(title="Model Usage Share", height=PIE_HEIGHT, showlegend=True,
                      legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05))
    return fig


def create_tokens_by_project_chart(data: DashboardData) -> go.Figure:
    project_stats = get_project_summary(data.usage_df, data.costs_df)
    if project_stats.empty or "total_tokens" not in project_stats.columns:
        return create_empty_figure("No project data available")
    has_name = "project_name" in project_stats.columns
    label_col = "project_name" if has_name else "project_id"
    project_stats = project_stats.sort_values("total_tokens", ascending=True).tail(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=project_stats[label_col], x=project_stats["total_tokens"],
        orientation="h", name="Total Tokens", marker_color=COLOR_PALETTE[4],
        text=project_stats["total_tokens"].apply(lambda x: f"{x:,}"),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Tokens: %{x:,}<extra></extra>",
    ))
    fig.update_layout(title="Tokens by Project (Top 10)", xaxis_title="Total Tokens",
                      yaxis_title="Project", height=DEFAULT_HEIGHT, showlegend=False)
    return fig


def create_project_timeline_chart(data: DashboardData) -> go.Figure:
    if data.usage_df.empty:
        return create_empty_figure("No usage data available")
    has_name = "project_name" in data.usage_df.columns
    top_projects = (
        data.usage_df.groupby("project_id")["total_tokens"].sum().nlargest(5).index.tolist()
    )
    if has_name:
        name_lookup = (
            data.usage_df[["project_id", "project_name"]]
            .drop_duplicates("project_id")
            .set_index("project_id")["project_name"]
            .to_dict()
        )
    else:
        name_lookup = {}
    df = data.usage_df[data.usage_df["project_id"].isin(top_projects)]
    daily_by_project = (
        df.groupby([pd.Grouper(key="date", freq="D"), "project_id"])["total_tokens"]
        .sum().reset_index()
    )
    fig = go.Figure()
    for idx, project_id in enumerate(top_projects):
        project_data = daily_by_project[daily_by_project["project_id"] == project_id]
        legend_name = name_lookup.get(project_id, project_id)
        fig.add_trace(go.Scatter(
            x=project_data["date"], y=project_data["total_tokens"],
            mode="lines+markers", name=str(legend_name),
            line=dict(shape="spline", width=2, color=COLOR_PALETTE[idx % len(COLOR_PALETTE)]),
            marker=dict(size=4),
        ))
    fig.update_layout(title="Project Usage Timeline (Top 5 Projects)", xaxis_title="Date",
                      yaxis_title="Total Tokens", height=DEFAULT_HEIGHT, hovermode="x unified")
    return fig


def create_breakdown_chart(breakdown_df: pd.DataFrame, metric: str, dimension: str) -> go.Figure:
    if breakdown_df is None or breakdown_df.empty:
        return create_empty_figure("No data available")
    if metric == "cost_usd" and dimension == "model":
        return create_empty_figure(
            "Cost breakdown by model is not available.\nUse the Spending tab for cost by line item."
        )
    metric_labels = {
        "cost_usd": "Cost (USD)", "total_tokens": "Total Tokens",
        "input_tokens": "Input Tokens", "output_tokens": "Output Tokens",
        "num_model_requests": "Requests",
    }
    metric_label = metric_labels.get(metric, metric)
    dim_label = "Project" if dimension == "project" else "Model"
    periods_ordered = (
        breakdown_df[["period_sort_key", "period_label"]].drop_duplicates()
        .sort_values("period_sort_key")["period_label"].tolist()
    )
    dimension_values = breakdown_df["dimension_value"].unique().tolist()
    fig = go.Figure()
    for idx, dim_val in enumerate(dimension_values):
        subset = breakdown_df[breakdown_df["dimension_value"] == dim_val]
        fig.add_trace(go.Bar(
            x=subset["period_label"], y=subset[metric], name=str(dim_val),
            marker_color=COLOR_PALETTE[idx % len(COLOR_PALETTE)],
            hovertemplate=f"<b>{dim_val}</b><br>Period: %{{x}}<br>{metric_label}: %{{y:,}}<extra></extra>",
        ))
    fig.update_layout(
        title=f"{metric_label} by {dim_label} Over Time",
        xaxis=dict(title="Period", categoryorder="array", categoryarray=periods_ordered),
        yaxis_title=metric_label, barmode="stack", height=DEFAULT_HEIGHT,
        legend=dict(title=dim_label),
    )
    return fig
