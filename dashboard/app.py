"""
AI Usage Dashboard — Dash Application

Multi-provider dashboard for viewing AI organization usage statistics.
Supports OpenAI (OPENAI_ADMIN_KEY) and Anthropic (ANTHROPIC_ADMIN_KEY).

Usage:
    python main.py
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback_context, dash_table, dcc, html
from dotenv import load_dotenv

from dashboard.data.layer import (
    add_project_names,
    filter_data,
    get_monthly_summary,
    get_model_summary,
    get_period_breakdown,
    get_project_summary,
    process_usage_data,
)
from dashboard.data.models import DashboardData
from dashboard.data.pricing import get_pricing_table
from dashboard.data.store import (
    get_database_stats,
    get_last_updated,
    get_provider_last_updated,
    init_database,
    load_all_data,
    load_projects,
    needs_backfill,
    save_costs_data,
    save_usage_data,
    set_last_updated,
    set_provider_last_updated,
    upsert_projects,
)
from dashboard.charts import (
    create_breakdown_chart,
    create_cache_efficiency_chart,
    create_cost_by_model_chart,
    create_cost_by_project_chart,
    create_cumulative_token_chart,
    create_daily_cost_chart,
    create_model_usage_pie_chart,
    create_mom_spend_chart,
    create_project_timeline_chart,
    create_token_trend_chart,
    create_tokens_by_model_chart,
    create_tokens_by_project_chart,
)
from dashboard.providers.anthropic import AnthropicProviderClient
from dashboard.providers.openai import OpenAIProviderClient
from dashboard.theme import (
    BOOTSTRAP_THEME,
    DEFAULT_CHART_CONFIG,
    METRIC_CARD_STYLE,
    METRIC_TITLE_STYLE,
    METRIC_VALUE_STYLE,
    TABLE_CELL_STYLE,
    TABLE_DATA_CONDITIONAL,
    TABLE_HEADER_STYLE,
    TABLE_STYLE,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_cached_data: Optional[DashboardData] = None
_configured_providers = []

for _cls in [OpenAIProviderClient, AnthropicProviderClient]:
    if _cls.is_configured():
        try:
            _configured_providers.append(_cls())
        except Exception as _e:
            logger.warning(f"Failed to initialise {_cls.PROVIDER_NAME} provider: {_e}")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _backfill_start_time() -> datetime:
    """Return the backfill start date from BACKFILL_START_DATE env var (YYYY-MM-DD), defaulting to 2026-01-01."""
    raw = os.environ.get("BACKFILL_START_DATE", "2026-01-01")
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid BACKFILL_START_DATE %r, using 2026-01-01", raw)
        return datetime(2026, 1, 1)


def backfill_historical_data(providers=None) -> None:
    """Fetch and store historical data from BACKFILL_START_DATE (default 2026-01-01).

    Only runs for providers that actually need a backfill (i.e. have no rows in
    the DB yet). Passing an explicit list overrides this check.
    """
    start_time = _backfill_start_time()
    end_time = datetime.utcnow()
    targets = providers if providers is not None else [
        p for p in _configured_providers if needs_backfill(p.PROVIDER_NAME)
    ]
    for provider_client in targets:
        logger.info(f"Backfilling {provider_client.PROVIDER_NAME} from {os.environ.get("BACKFILL_START_DATE", "2026-01-01")}...")
        try:
            costs_df = provider_client.get_costs(start_time, end_time)
            usage_df = provider_client.get_usage(start_time, end_time)
            usage_df = process_usage_data(usage_df)
            save_costs_data(costs_df)
            save_usage_data(usage_df)
            set_provider_last_updated(provider_client.PROVIDER_NAME, end_time)
            logger.info(f"Backfill complete for {provider_client.PROVIDER_NAME}")
        except Exception as e:
            logger.error(f"Backfill failed for {provider_client.PROVIDER_NAME}: {e}")
    set_last_updated(datetime.utcnow())


def fetch_incremental_data() -> None:
    """Fetch new data since last update for each configured provider."""
    for provider_client in _configured_providers:
        last = get_provider_last_updated(provider_client.PROVIDER_NAME) or get_last_updated()
        if last is None:
            logger.warning(f"No last_updated for {provider_client.PROVIDER_NAME}, running backfill")
            backfill_historical_data(providers=[provider_client])
            continue

        start_time = last - timedelta(days=1)
        end_time = datetime.utcnow()
        logger.info(f"Fetching incremental {provider_client.PROVIDER_NAME} from {start_time.date()}")
        try:
            costs_df = provider_client.get_costs(start_time, end_time)
            usage_df = provider_client.get_usage(start_time, end_time)
            usage_df = process_usage_data(usage_df)
            save_costs_data(costs_df)
            save_usage_data(usage_df)
            set_provider_last_updated(provider_client.PROVIDER_NAME, end_time)
        except Exception as e:
            logger.error(f"Incremental fetch failed for {provider_client.PROVIDER_NAME}: {e}")

    set_last_updated(datetime.utcnow())
    load_data_from_database()
    logger.info("Incremental data fetch completed")


def load_data_from_database() -> DashboardData:
    """Load SQLite data and fetch live projects from all configured providers."""
    global _cached_data

    logger.info("Loading data from database...")
    costs_df, usage_df = load_all_data()

    # Fetch live projects from each configured provider and cache them in DB.
    # Then merge with DB-cached projects so names resolve even for providers
    # that aren't currently configured (e.g. OpenAI key absent but data exists).
    live_projects = []
    providers_updated = {}
    for provider_client in _configured_providers:
        try:
            fetched = provider_client.get_projects()
            live_projects.extend(fetched)
            upsert_projects(fetched)
        except Exception as e:
            logger.warning(f"Failed to fetch {provider_client.PROVIDER_NAME} projects: {e}")
        ts = get_provider_last_updated(provider_client.PROVIDER_NAME)
        if ts:
            providers_updated[provider_client.PROVIDER_NAME] = ts

    # Merge: DB cache takes lower priority — live results override by (id, provider)
    cached_projects = load_projects()
    live_keys = {(p.get("id"), p.get("provider", "openai")) for p in live_projects}
    all_projects = live_projects + [
        p for p in cached_projects
        if (p["id"], p.get("provider", "openai")) not in live_keys
    ]

    costs_df = add_project_names(costs_df, all_projects)
    usage_df = add_project_names(usage_df, all_projects)

    _cached_data = DashboardData(
        costs_df=costs_df,
        usage_df=usage_df,
        projects=all_projects,
        last_updated=get_last_updated() or datetime.utcnow(),
        providers_updated=providers_updated,
    )

    if not costs_df.empty:
        now = datetime.utcnow()
        _cached_data.total_spend = costs_df["cost_usd"].sum()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        _cached_data.current_month_spend = costs_df[costs_df["date"] >= current_month_start]["cost_usd"].sum()
        prev_end = current_month_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        prev = costs_df[(costs_df["date"] >= prev_start) & (costs_df["date"] <= prev_end)]
        _cached_data.previous_month_spend = prev["cost_usd"].sum()
        if _cached_data.previous_month_spend > 0:
            _cached_data.mom_change_percent = (
                (_cached_data.current_month_spend - _cached_data.previous_month_spend)
                / _cached_data.previous_month_spend
            ) * 100

    if not usage_df.empty:
        _cached_data.total_tokens = int(usage_df["total_tokens"].sum())
        total_input = usage_df["input_tokens"].sum()
        total_cached = usage_df["input_cached_tokens"].sum()
        _cached_data.cache_rate = (total_cached / total_input) * 100 if total_input > 0 else 0

    logger.info(f"Loaded {len(costs_df)} cost records and {len(usage_df)} usage records")
    return _cached_data


def initialize_data_store() -> None:
    logger.info("Initializing data store...")
    init_database()

    providers_needing_backfill = [
        p for p in _configured_providers if needs_backfill(p.PROVIDER_NAME)
    ]
    if providers_needing_backfill:
        names = [p.PROVIDER_NAME for p in providers_needing_backfill]
        logger.info(f"Backfill needed for: {names}")
        backfill_historical_data(providers=providers_needing_backfill)
    else:
        logger.info("Database already contains data")
        logger.info(f"Database stats: {get_database_stats()}")

    load_data_from_database()
    logger.info("Data store initialization completed")


def start_scheduler() -> None:
    """No-op: auto-refresh is handled by dcc.Interval."""
    logger.info("Scheduler skipped — using Dash Interval for auto-refresh")


def get_data() -> DashboardData:
    global _cached_data
    if _cached_data is None:
        return load_data_from_database()
    return _cached_data


def get_filter_choices(provider: Optional[str] = None):
    """Return (project_options, models) for dropdowns, optionally scoped to a provider."""
    data = get_data()

    projects = data.projects
    if provider and provider != "All":
        prov_lower = provider.lower()
        projects = [p for p in projects if p.get("provider", "").lower() == prov_lower]

    project_options = [{"label": "All", "value": "All"}]
    if projects:
        project_options.extend([
            {"label": p.get("name", p.get("id", "unknown")), "value": p.get("id", "unknown")}
            for p in projects
        ])
    elif not data.usage_df.empty:
        for pid in data.usage_df["project_id"].unique().tolist():
            project_options.append({"label": pid, "value": pid})

    usage_df = data.usage_df
    if provider and provider != "All" and "provider" in usage_df.columns and not usage_df.empty:
        usage_df = usage_df[usage_df["provider"] == provider.lower()]

    models = ["All"]
    if not usage_df.empty:
        models.extend(sorted(usage_df["model"].unique().tolist()))

    return project_options, models


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[BOOTSTRAP_THEME],
    suppress_callback_exceptions=True,
    title="AI Usage Dashboard",
)
server = app.server

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body { background-color: #1a1d20 !important; color: #adb5bd; }
            .dash-dropdown .Select-control { background-color: #222629 !important; border-color: #3a3f44 !important; color: #f8f9fa !important; }
            .dash-dropdown .Select-menu-outer { background-color: #222629 !important; border-color: #3a3f44 !important; }
            .dash-dropdown .Select-option { background-color: #222629 !important; color: #f8f9fa !important; }
            .dash-dropdown .Select-option:hover { background-color: #2c3034 !important; }
            .dash-dropdown .Select-value-label { color: #f8f9fa !important; }
            .form-control { background-color: #222629 !important; border-color: #3a3f44 !important; color: #f8f9fa !important; }
            .form-control::placeholder { color: #6c757d !important; }
            .card { background-color: #222629 !important; border-color: #3a3f44 !important; }
            .card-body { color: #adb5bd !important; }
            label { color: #adb5bd !important; }
            h1, h2, h3, h4, h5, h6 { color: #f8f9fa !important; }
            .tab-content { background-color: transparent !important; }
            .nav-tabs .nav-link { color: #adb5bd !important; }
            .nav-tabs .nav-link.active { background-color: #222629 !important; border-color: #3a3f44 !important; color: #d4af37 !important; }
            .badge { background-color: #d4af37 !important; color: #1a1d20 !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# ---------------------------------------------------------------------------
# Layout — built conditionally based on configured providers
# ---------------------------------------------------------------------------

if not _configured_providers:
    app.layout = dbc.Container([
        html.H1("AI Usage Dashboard", className="mt-4 mb-4"),
        dbc.Alert([
            html.H4("Error: API Key Required", className="alert-heading"),
            html.P("No AI provider API keys are configured. Set at least one:"),
            html.Ul([
                html.Li("OPENAI_ADMIN_KEY — for OpenAI usage data"),
                html.Li("ANTHROPIC_ADMIN_KEY — for Anthropic usage data"),
            ]),
            html.Hr(),
            html.Pre("export OPENAI_ADMIN_KEY=your-openai-admin-key\n"
                     "export ANTHROPIC_ADMIN_KEY=your-anthropic-admin-key\n"
                     "python main.py"),
        ], color="danger"),
    ], fluid=True)
else:
    try:
        initialize_data_store()
        start_scheduler()
        project_options, models = get_filter_choices()
    except Exception as _init_err:
        app.layout = dbc.Container([
            html.H1("AI Usage Dashboard", className="mt-4 mb-4"),
            dbc.Alert([
                html.H4("Error initializing dashboard", className="alert-heading"),
                html.Pre(str(_init_err)),
            ], color="danger"),
        ], fluid=True)
    else:
        app.layout = dbc.Container([
            # Header
            dbc.Row([
                dbc.Col(html.H1("AI Usage Dashboard", className="mb-0"), width=8),
                dbc.Col([
                    dbc.Button("Refresh", id="refresh-btn", color="primary", className="me-2"),
                    dbc.Badge("Last Updated: --:--:--", id="last-updated-badge", color="secondary"),
                ], width=4, className="text-end"),
            ], className="mt-4 mb-4 align-items-center"),

            # Filters (collapsible)
            dbc.Row([
                dbc.Col([
                    dbc.Button("Filters", id="collapse-button", className="mb-3",
                               color="light", n_clicks=0),
                    dbc.Collapse(
                        dbc.Card(dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    html.Label("Provider"),
                                    dcc.Dropdown(
                                        id="provider-filter",
                                        options=[
                                            {"label": "All", "value": "All"},
                                            {"label": "OpenAI", "value": "openai"},
                                            {"label": "Anthropic", "value": "anthropic"},
                                        ],
                                        value="All",
                                        clearable=False,
                                    ),
                                ], md=3),
                                dbc.Col([
                                    html.Label("Project"),
                                    dcc.Dropdown(
                                        id="project-filter",
                                        options=project_options,
                                        value="All",
                                        clearable=False,
                                    ),
                                ], md=3),
                                dbc.Col([
                                    html.Label("Model"),
                                    dcc.Dropdown(
                                        id="model-filter",
                                        options=[{"label": m, "value": m} for m in models],
                                        value="All",
                                        clearable=False,
                                    ),
                                ], md=3),
                                dbc.Col([
                                    html.Label("Start Date"),
                                    dcc.Input(id="start-date-input", type="text",
                                              placeholder="YYYY-MM-DD", className="form-control"),
                                ], md=1),
                                dbc.Col([
                                    html.Label("End Date"),
                                    dcc.Input(id="end-date-input", type="text",
                                              placeholder="YYYY-MM-DD", className="form-control"),
                                ], md=2),
                            ]),
                        ])),
                        id="filters-collapse",
                        is_open=False,
                    ),
                ], width=12),
            ], className="mb-4"),

            # Metrics Row
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H6("Total Spend", style=METRIC_TITLE_STYLE),
                    html.H3(id="total-spend-metric", style=METRIC_VALUE_STYLE),
                ]), style=METRIC_CARD_STYLE), md=2),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H6("This Month", style=METRIC_TITLE_STYLE),
                    html.H3(id="current-month-metric", style=METRIC_VALUE_STYLE),
                ]), style=METRIC_CARD_STYLE), md=2),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H6("MoM Change", style=METRIC_TITLE_STYLE),
                    html.H3(id="mom-change-metric", style=METRIC_VALUE_STYLE),
                ]), style=METRIC_CARD_STYLE), md=2),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H6("Total Tokens", style=METRIC_TITLE_STYLE),
                    html.H3(id="total-tokens-metric", style=METRIC_VALUE_STYLE),
                ]), style=METRIC_CARD_STYLE), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H6("Cache Rate", style=METRIC_TITLE_STYLE),
                    html.H3(id="cache-rate-metric", style=METRIC_VALUE_STYLE),
                ]), style=METRIC_CARD_STYLE), md=3),
            ], className="mb-4"),

            # Tabs
            dbc.Tabs([
                dbc.Tab(label="Overview", children=[
                    dbc.Row([dbc.Col(dcc.Graph(id="mom-spend-chart", config=DEFAULT_CHART_CONFIG))],
                            className="mt-3"),
                    dbc.Row([dbc.Col([
                        html.H5("Monthly Summary", className="mt-3 mb-2"),
                        html.Div(id="monthly-table-container"),
                    ])]),
                ]),
                dbc.Tab(label="Spending", children=[
                    dbc.Row([dbc.Col(dcc.Graph(id="daily-cost-chart", config=DEFAULT_CHART_CONFIG))],
                            className="mt-3"),
                    dbc.Row([
                        dbc.Col(dcc.Graph(id="cost-by-model-chart", config=DEFAULT_CHART_CONFIG), md=6),
                        dbc.Col(dcc.Graph(id="cost-by-project-chart", config=DEFAULT_CHART_CONFIG), md=6),
                    ]),
                ]),
                dbc.Tab(label="Tokens", children=[
                    dbc.Row([dbc.Col(dcc.Graph(id="token-trend-chart", config=DEFAULT_CHART_CONFIG))],
                            className="mt-3"),
                    dbc.Row([
                        dbc.Col(dcc.Graph(id="cumulative-token-chart", config=DEFAULT_CHART_CONFIG), md=6),
                        dbc.Col(dcc.Graph(id="cache-efficiency-chart", config=DEFAULT_CHART_CONFIG), md=6),
                    ]),
                    dbc.Row([dbc.Col(dcc.Graph(id="tokens-by-model-chart", config=DEFAULT_CHART_CONFIG))]),
                ]),
                dbc.Tab(label="Models", children=[
                    dbc.Row([dbc.Col([
                        html.H5("Model Comparison", className="mt-3 mb-2"),
                        html.Div(id="model-table-container"),
                    ])]),
                    dbc.Row([dbc.Col(dcc.Graph(id="model-usage-pie-chart", config=DEFAULT_CHART_CONFIG))]),
                ]),
                dbc.Tab(label="Projects", children=[
                    dbc.Row([dbc.Col(dcc.Graph(id="tokens-by-project-chart", config=DEFAULT_CHART_CONFIG))],
                            className="mt-3"),
                    dbc.Row([dbc.Col([
                        html.H5("Project Summary", className="mt-3 mb-2"),
                        html.Div(id="project-table-container"),
                    ])]),
                    dbc.Row([dbc.Col(dcc.Graph(id="project-timeline-chart", config=DEFAULT_CHART_CONFIG))]),
                ]),
                dbc.Tab(label="Data", children=[
                    dbc.Row([dbc.Col([
                        html.H5("Detailed Usage Data", className="mt-3 mb-2"),
                        dbc.Button("Download CSV", id="download-btn", color="success", className="mb-3"),
                        dcc.Download(id="download-csv"),
                        html.Div(id="full-data-table-container"),
                    ])]),
                    dbc.Row([dbc.Col([
                        html.H5("Model Pricing Reference", className="mt-4 mb-2"),
                        html.Div(id="pricing-table-container"),
                    ])]),
                ]),
                dbc.Tab(label="Breakdown", children=[
                    dbc.Row([dbc.Col([
                        html.Label("Quick Range", className="me-2 fw-semibold"),
                        dbc.ButtonGroup([
                            dbc.Button("7D",  id="preset-7d",  color="outline-secondary", size="sm"),
                            dbc.Button("30D", id="preset-30d", color="outline-secondary", size="sm"),
                            dbc.Button("90D", id="preset-90d", color="outline-secondary", size="sm"),
                            dbc.Button("6M",  id="preset-6m",  color="outline-secondary", size="sm"),
                            dbc.Button("1Y",  id="preset-1y",  color="outline-secondary", size="sm"),
                            dbc.Button("All", id="preset-all", color="outline-secondary", size="sm"),
                        ]),
                    ], className="mt-3 mb-3 d-flex align-items-center")]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Granularity"),
                            dbc.RadioItems(id="breakdown-granularity",
                                           options=[{"label": "Daily", "value": "day"},
                                                    {"label": "Weekly", "value": "week"},
                                                    {"label": "Monthly", "value": "month"}],
                                           value="month", inline=True),
                        ], md=4),
                        dbc.Col([
                            html.Label("Breakdown by"),
                            dbc.RadioItems(id="breakdown-dimension",
                                           options=[{"label": "Project", "value": "project"},
                                                    {"label": "Model", "value": "model"}],
                                           value="project", inline=True),
                        ], md=4),
                        dbc.Col([
                            html.Label("Metric"),
                            dbc.RadioItems(id="breakdown-metric",
                                           options=[{"label": "Cost", "value": "cost_usd"},
                                                    {"label": "Total Tokens", "value": "total_tokens"},
                                                    {"label": "Input Tokens", "value": "input_tokens"},
                                                    {"label": "Output Tokens", "value": "output_tokens"},
                                                    {"label": "Requests", "value": "num_model_requests"}],
                                           value="cost_usd", inline=True),
                        ], md=4),
                    ], className="mb-3"),
                    dbc.Row([dbc.Col(dcc.Graph(id="breakdown-chart", config=DEFAULT_CHART_CONFIG))]),
                ]),
            ]),

            dcc.Interval(id="interval-component", interval=3600 * 1000, n_intervals=0),
        ], fluid=True, style={
            "maxWidth": "1400px",
            "backgroundColor": "#1a1d20",
            "minHeight": "100vh",
            "paddingBottom": "40px",
        })


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("filters-collapse", "is_open"),
    Input("collapse-button", "n_clicks"),
    State("filters-collapse", "is_open"),
)
def toggle_collapse(n, is_open):
    if n:
        return not is_open
    return is_open


@app.callback(
    Output("project-filter", "options"),
    Output("project-filter", "value"),
    Input("provider-filter", "value"),
)
def update_project_options(provider):
    """Refresh project dropdown when the provider filter changes."""
    project_options, _ = get_filter_choices(provider)
    return project_options, "All"


@app.callback(
    [
        Output("total-spend-metric", "children"),
        Output("current-month-metric", "children"),
        Output("mom-change-metric", "children"),
        Output("total-tokens-metric", "children"),
        Output("cache-rate-metric", "children"),
        Output("last-updated-badge", "children"),
        Output("mom-spend-chart", "figure"),
        Output("monthly-table-container", "children"),
        Output("daily-cost-chart", "figure"),
        Output("cost-by-model-chart", "figure"),
        Output("cost-by-project-chart", "figure"),
        Output("token-trend-chart", "figure"),
        Output("cumulative-token-chart", "figure"),
        Output("cache-efficiency-chart", "figure"),
        Output("tokens-by-model-chart", "figure"),
        Output("model-table-container", "children"),
        Output("model-usage-pie-chart", "figure"),
        Output("tokens-by-project-chart", "figure"),
        Output("project-table-container", "children"),
        Output("project-timeline-chart", "figure"),
        Output("full-data-table-container", "children"),
        Output("pricing-table-container", "children"),
    ],
    [
        Input("refresh-btn", "n_clicks"),
        Input("interval-component", "n_intervals"),
        Input("provider-filter", "value"),
        Input("project-filter", "value"),
        Input("model-filter", "value"),
        Input("start-date-input", "value"),
        Input("end-date-input", "value"),
    ],
)
def update_dashboard(n_clicks, n_intervals, provider, project, model, start_date, end_date):
    ctx = callback_context
    if ctx.triggered:
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger_id in ["refresh-btn", "interval-component"]:
            logger.info(f"Data refresh triggered by {trigger_id}")
            fetch_incremental_data()

    data = get_data()

    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            pass

    filtered_data = filter_data(
        data,
        project_id=project if project != "All" else None,
        model=model if model != "All" else None,
        start_date=start_dt,
        end_date=end_dt,
        provider=provider if provider != "All" else None,
    )

    total_spend    = f"${filtered_data.total_spend:,.2f}"
    current_month  = f"${filtered_data.current_month_spend:,.2f}"
    mom_change     = f"{filtered_data.mom_change_percent:+.1f}%"
    total_tokens   = f"{filtered_data.total_tokens:,}"
    cache_rate     = f"{filtered_data.cache_rate:.1f}%"
    last_updated   = f"Last Updated: {data.last_updated.strftime('%H:%M:%S')}"

    mom_chart              = create_mom_spend_chart(filtered_data)
    daily_cost_chart       = create_daily_cost_chart(filtered_data)
    cost_by_model_chart    = create_cost_by_model_chart(filtered_data)
    cost_by_project_chart  = create_cost_by_project_chart(filtered_data)
    token_trend_chart      = create_token_trend_chart(filtered_data)
    cumulative_chart       = create_cumulative_token_chart(filtered_data)
    cache_chart            = create_cache_efficiency_chart(filtered_data)
    tokens_by_model_chart  = create_tokens_by_model_chart(filtered_data)
    model_pie_chart        = create_model_usage_pie_chart(filtered_data)
    tokens_by_project_chart = create_tokens_by_project_chart(filtered_data)
    project_timeline_chart = create_project_timeline_chart(filtered_data)

    def make_table(df, page_size=10, sort=True, filter_=True):
        if df.empty:
            return html.P("No data available")
        return dash_table.DataTable(
            data=df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df.columns],
            style_table=TABLE_STYLE,
            style_header=TABLE_HEADER_STYLE,
            style_cell=TABLE_CELL_STYLE,
            style_data_conditional=TABLE_DATA_CONDITIONAL,
            page_size=page_size,
            sort_action="native" if sort else "none",
            filter_action="native" if filter_ else "none",
        )

    model_table = get_model_summary(filtered_data.usage_df, filtered_data.costs_df)
    model_table_component = make_table(model_table.round(2) if not model_table.empty else model_table)

    project_table = get_project_summary(filtered_data.usage_df, filtered_data.costs_df)
    if not project_table.empty:
        project_table = project_table.round(2)
        display_cols = [c for c in project_table.columns
                        if not (c == "project_id" and "project_name" in project_table.columns)]
        project_table_component = make_table(project_table[display_cols])
    else:
        project_table_component = html.P("No project data available")

    monthly_table = get_monthly_summary(filtered_data.costs_df, filtered_data.usage_df)
    monthly_table_component = make_table(
        monthly_table.round(2) if not monthly_table.empty else monthly_table,
        page_size=12, filter_=False,
    )

    if not filtered_data.usage_df.empty:
        full_data = filtered_data.usage_df.copy()
        full_data["date"] = full_data["date"].dt.strftime("%Y-%m-%d")
        full_display_cols = [c for c in full_data.columns
                             if not (c == "project_id" and "project_name" in full_data.columns)]
        full_data_component = make_table(full_data[full_display_cols], page_size=20)
    else:
        full_data_component = html.P("No usage data available")

    pricing_table = pd.DataFrame(get_pricing_table())
    pricing_table_component = make_table(pricing_table, page_size=20)

    return (
        total_spend, current_month, mom_change, total_tokens, cache_rate, last_updated,
        mom_chart, monthly_table_component, daily_cost_chart, cost_by_model_chart,
        cost_by_project_chart, token_trend_chart, cumulative_chart, cache_chart,
        tokens_by_model_chart, model_table_component, model_pie_chart,
        tokens_by_project_chart, project_table_component, project_timeline_chart,
        full_data_component, pricing_table_component,
    )


@app.callback(
    Output("download-csv", "data"),
    Input("download-btn", "n_clicks"),
    prevent_initial_call=True,
)
def download_csv(n_clicks):
    data = get_data()
    if data.usage_df.empty:
        return None
    return dcc.send_data_frame(data.usage_df.to_csv, "ai_usage_data.csv", index=False)


@app.callback(
    Output("start-date-input", "value"),
    Output("end-date-input", "value"),
    [
        Input("preset-7d",  "n_clicks"),
        Input("preset-30d", "n_clicks"),
        Input("preset-90d", "n_clicks"),
        Input("preset-6m",  "n_clicks"),
        Input("preset-1y",  "n_clicks"),
        Input("preset-all", "n_clicks"),
    ],
    prevent_initial_call=True,
)
def set_preset_dates(n7, n30, n90, n6m, n1y, nall):
    trigger = callback_context.triggered[0]["prop_id"].split(".")[0]
    today = datetime.utcnow().date()
    delta_map = {"preset-7d": 7, "preset-30d": 30, "preset-90d": 90, "preset-6m": 183, "preset-1y": 365}
    if trigger == "preset-all":
        return "", ""
    start = today - timedelta(days=delta_map[trigger])
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.callback(
    Output("breakdown-chart", "figure"),
    Input("breakdown-granularity", "value"),
    Input("breakdown-dimension",   "value"),
    Input("breakdown-metric",      "value"),
    Input("provider-filter",       "value"),
    Input("project-filter",        "value"),
    Input("model-filter",          "value"),
    Input("start-date-input",      "value"),
    Input("end-date-input",        "value"),
    Input("interval-component",    "n_intervals"),
)
def update_breakdown_chart(granularity, dimension, metric,
                           provider, project, model, start_date, end_date, n_intervals):
    data = get_data()
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            pass
    filtered = filter_data(
        data,
        project_id=project if project != "All" else None,
        model=model if model != "All" else None,
        start_date=start_dt,
        end_date=end_dt,
        provider=provider if provider != "All" else None,
    )
    breakdown_df = get_period_breakdown(
        filtered.costs_df, filtered.usage_df, filtered.projects,
        period=granularity, dimension=dimension,
    )
    return create_breakdown_chart(breakdown_df, metric=metric, dimension=dimension)
