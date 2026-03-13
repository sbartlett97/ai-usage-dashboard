# AI Usage Dashboard

A self-hosted Dash dashboard for monitoring AI API spend and token usage across **OpenAI** and **Anthropic** organizations. Data is fetched from each provider's Admin API, persisted locally in SQLite, and refreshed automatically every hour.

![Python](https://img.shields.io/badge/python-3.12-blue) ![Dash](https://img.shields.io/badge/dash-2.14%2B-informational) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Multi-provider**: OpenAI and Anthropic side-by-side, with per-provider last-updated timestamps
- **Cost tracking**: Daily spend, month-over-month comparison, cumulative cost curves
- **Token analytics**: Usage by model and project, cache hit rates, token trend lines
- **Project filtering**: Filter all charts and tables by project/workspace
- **SQLite persistence**: All data stored locally — no external database required
- **Auto-refresh**: Dashboard polls for new data every hour via `dcc.Interval`
- **Docker-ready**: Single `docker-compose up` for a fully containerized deployment

---

## Requirements

- Python 3.12+
- An **OpenAI Admin API key** (`OPENAI_ADMIN_KEY`) and/or an **Anthropic Admin API key** (`ANTHROPIC_ADMIN_KEY`)
- At least one key must be set; both are optional if you only use one provider

---

## Quickstart (local)

```bash
# 1. Clone the repo
git clone <repo-url>
cd openai-dashboard

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key(s)
export OPENAI_ADMIN_KEY=sk-admin-...
export ANTHROPIC_ADMIN_KEY=sk-ant-admin-...  # optional

# 5. Run the dashboard
python main.py
```

Open [http://localhost:8050](http://localhost:8050) in your browser.

On first launch the app backfills historical data from **2024-01-01**. Subsequent starts skip backfill and only fetch missing days.

---

## Docker

### docker-compose (recommended)

```bash
# Create a .env file with your keys
echo "OPENAI_ADMIN_KEY=sk-admin-..." > .env
echo "ANTHROPIC_ADMIN_KEY=sk-ant-admin-..." >> .env  # optional

docker-compose up -d
```

The `dashboard_data` named volume persists the SQLite database across restarts.

### Manual Docker

```bash
docker build -t ai-dashboard .
docker run -d \
  -p 8050:8050 \
  -e OPENAI_ADMIN_KEY=sk-admin-... \
  -v ai_data:/app/data \
  ai-dashboard
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_ADMIN_KEY` | One of the two | OpenAI organization Admin API key |
| `ANTHROPIC_ADMIN_KEY` | One of the two | Anthropic Admin API key |

---

## Architecture

```
main.py
  └── dashboard/
        ├── app.py          # Dash layout, all callbacks, global _cached_data
        ├── charts.py       # Pure functions: DashboardData → go.Figure
        ├── theme.py        # Bootswatch Lux dark theme + shared Plotly template
        ├── providers/
        │     ├── base.py   # ProviderClient ABC + ProviderData dataclass
        │     ├── openai.py # OpenAI Admin API client
        │     └── anthropic.py  # Anthropic Admin API client
        └── data/
              ├── models.py  # DashboardData dataclass
              ├── layer.py   # Fetch, filter, aggregate helpers
              ├── store.py   # SQLite CRUD (init, upsert, load)
              └── pricing.py # Static MODEL_PRICING lookup + cost estimation
```

### Data flow

```
OpenAI / Anthropic Admin APIs
  → providers/{openai,anthropic}.py   (httpx, chunked 31-day pagination)
  → data/layer.py                     (flatten JSON → DataFrames)
  → data/store.py                     (upsert into SQLite at /app/data/dashboard.db)
  → app.py: load_all_data()           → _cached_data global (DashboardData)
  → data/layer.py: filter_data()      (applies UI filters, recomputes metrics)
  → charts.py                         (Plotly figures)
  → app.py callbacks                  (render to browser)
```

### Key design notes

- **`DashboardData`** holds `costs_df`, `usage_df`, `projects`, computed metrics, and `last_updated`. `filter_data()` returns a *new* `DashboardData` — it never mutates.
- **SQLite upsert strategy**: DELETE all rows for the affected dates, then INSERT fresh data. This avoids stale rows when API responses change.
- **API chunking**: the OpenAI Admin API limits requests to 31 daily buckets. Both provider clients loop over long date ranges automatically.
- **Provider abstraction**: adding a new provider means implementing `get_costs()`, `get_usage()`, and `get_projects()` on a `ProviderClient` subclass.

---

## Project Structure

```
openai-dashboard/
├── main.py               # Entry point
├── dashboard/            # Application package
│   ├── app.py
│   ├── charts.py
│   ├── theme.py
│   ├── providers/
│   └── data/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## License

MIT — see [LICENSE](LICENSE).
