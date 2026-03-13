"""
Dash Theme Configuration

Centralized theme and styling configuration for Dash dashboard.
Includes Plotly template, color palette, and Bootstrap theme settings.
"""

import plotly.graph_objects as go
import plotly.io as pio

# Color palette - Lux theme inspired (elegant dark with gold accents)
COLOR_PALETTE = [
    "#d4af37",  # Gold
    "#4a90e2",  # Blue
    "#50c878",  # Emerald
    "#e74c3c",  # Red
    "#9b59b6",  # Purple
    "#f39c12",  # Amber
    "#1abc9c",  # Turquoise
    "#e67e22",  # Orange
    "#95a5a6",  # Silver
]

# Bootstrap theme for dash-bootstrap-components
BOOTSTRAP_THEME = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/lux/bootstrap.min.css"

# Create custom Plotly template - Lux dark theme
PLOTLY_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        colorway=COLOR_PALETTE,
        font=dict(family="'Nunito Sans', sans-serif", size=12, color="#adb5bd"),
        title=dict(font=dict(size=18, color="#f8f9fa"), x=0.5, xanchor="center"),
        paper_bgcolor="#1a1d20",
        plot_bgcolor="#222629",
        hovermode="closest",
        hoverlabel=dict(bgcolor="#2c3034", font_size=12, font_color="#f8f9fa"),
        xaxis=dict(
            showgrid=True,
            gridcolor="#3a3f44",
            showline=True,
            linecolor="#52575c",
            zeroline=False,
            color="#adb5bd",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#3a3f44",
            showline=True,
            linecolor="#52575c",
            zeroline=False,
            color="#adb5bd",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(42, 48, 52, 0.9)",
            font=dict(color="#f8f9fa"),
        ),
        margin=dict(l=60, r=40, t=60, b=60),
    )
)

# Register the template
pio.templates["custom_dashboard"] = PLOTLY_TEMPLATE
pio.templates.default = "custom_dashboard"

# Common chart configuration
DEFAULT_CHART_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["pan2d", "lasso2d", "select2d"],
    "toImageButtonOptions": {
        "format": "png",
        "filename": "chart",
        "height": 600,
        "width": 1200,
        "scale": 2,
    },
}

# Chart height
DEFAULT_HEIGHT = 400
PIE_HEIGHT = 500

# Metric card styles - Lux dark theme
METRIC_CARD_STYLE = {
    "textAlign": "center",
    "padding": "20px",
    "borderRadius": "8px",
    "boxShadow": "0 4px 8px rgba(0,0,0,0.3)",
    "marginBottom": "20px",
    "backgroundColor": "#222629",
    "border": "1px solid #3a3f44",
}

METRIC_TITLE_STYLE = {
    "fontSize": "14px",
    "color": "#adb5bd",
    "marginBottom": "10px",
    "fontWeight": "500",
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
}

METRIC_VALUE_STYLE = {
    "fontSize": "28px",
    "fontWeight": "bold",
    "color": "#d4af37",  # Gold accent
}

# Table styles - Lux dark theme
TABLE_STYLE = {
    "overflowX": "auto",
    "border": "1px solid #3a3f44",
    "borderRadius": "4px",
    "backgroundColor": "#222629",
}

TABLE_HEADER_STYLE = {
    "backgroundColor": "#2c3034",
    "fontWeight": "bold",
    "textAlign": "left",
    "padding": "12px",
    "borderBottom": "2px solid #3a3f44",
    "color": "#f8f9fa",
}

TABLE_CELL_STYLE = {
    "textAlign": "left",
    "padding": "10px",
    "borderBottom": "1px solid #3a3f44",
    "backgroundColor": "#222629",
    "color": "#adb5bd",
}

TABLE_DATA_CONDITIONAL = [
    {
        "if": {"row_index": "odd"},
        "backgroundColor": "#2a2e32",
    }
]
