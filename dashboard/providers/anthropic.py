"""
Anthropic provider client.

Hits the Anthropic Admin API to fetch workspace costs and message usage,
normalising the response into the common DataFrame schema.

Requires ANTHROPIC_ADMIN_KEY environment variable.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd

from dashboard.providers.base import ProviderClient, ProviderData


class AnthropicProviderClient(ProviderClient):
    """ProviderClient implementation for the Anthropic Admin API."""

    PROVIDER_NAME = "anthropic"
    BASE_URL = "https://api.anthropic.com/v1"
    ANTHROPIC_VERSION = "2023-06-01"
    MAX_DAYS_PER_CHUNK = 31

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_ADMIN_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_ADMIN_KEY environment variable is required.")
        self._client = httpx.Client(
            headers={
                "x-api-key": api_key,
                "anthropic-version": self.ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("ANTHROPIC_ADMIN_KEY"))

    def _get_paginated(self, endpoint: str, params: dict, data_key: str = "data") -> list[dict]:
        """Fetch all pages, using bracket notation for array params."""
        all_data = []
        url = f"{self.BASE_URL}/{endpoint}"

        def build_url(p: dict) -> str:
            parts = []
            for key, value in p.items():
                if isinstance(value, list):
                    for item in value:
                        parts.append(f"{key}[]={item}")
                else:
                    parts.append(f"{key}={value}")
            return f"{url}?{'&'.join(parts)}" if parts else url

        full_url = build_url(params)
        while True:
            response = self._client.get(full_url)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {error_detail}",
                    request=response.request,
                    response=response,
                )
            result = response.json()
            all_data.extend(result.get(data_key, []))

            if result.get("has_more") and result.get("next_page"):
                params["page"] = result["next_page"]
                full_url = build_url(params)
            else:
                break

        return all_data

    def _date_chunks(self, start_time: datetime, end_time: datetime):
        """Yield (chunk_start, chunk_end) pairs of at most MAX_DAYS_PER_CHUNK days."""
        chunk = timedelta(days=self.MAX_DAYS_PER_CHUNK)
        current = start_time
        while current < end_time:
            yield current, min(current + chunk, end_time)
            current = current + chunk

    @staticmethod
    def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
        """Parse ISO8601+Z timestamp to naive UTC datetime."""
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return None

    def get_costs(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        rows = []
        for chunk_start, chunk_end in self._date_chunks(start_time, end_time):
            params = {
                "start_date": chunk_start.strftime("%Y-%m-%d"),
                "end_date": chunk_end.strftime("%Y-%m-%d"),
                "group_by": ["workspace_id"],
            }
            try:
                data = self._get_paginated("organizations/cost_report", params)
            except Exception:
                continue

            for item in data:
                ts = self._parse_timestamp(item.get("timestamp"))
                date = ts.date() if ts else chunk_start.date()
                try:
                    cost_usd = float(item.get("amount_in_cents", 0) or 0) / 100.0
                except (ValueError, TypeError):
                    cost_usd = 0.0
                rows.append({
                    "date": datetime.combine(date, datetime.min.time()),
                    "start_time": int(datetime.combine(date, datetime.min.time()).timestamp()),
                    "end_time": int((datetime.combine(date, datetime.min.time()) + timedelta(days=1)).timestamp()),
                    "provider": "anthropic",
                    "project_id": item.get("workspace_id") or "default",
                    "line_item": item.get("description") or "unknown",
                    "cost_usd": cost_usd,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df["cost_usd"] = pd.to_numeric(df["cost_usd"], errors="coerce").fillna(0.0)
        return df

    def get_usage(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        rows = []
        for chunk_start, chunk_end in self._date_chunks(start_time, end_time):
            params = {
                "start_date": chunk_start.strftime("%Y-%m-%d"),
                "end_date": chunk_end.strftime("%Y-%m-%d"),
                "group_by": ["workspace_id", "model"],
            }
            try:
                data = self._get_paginated("organizations/usage_report/messages", params)
            except Exception:
                continue

            for item in data:
                ts = self._parse_timestamp(item.get("timestamp"))
                date = ts.date() if ts else chunk_start.date()
                date_dt = datetime.combine(date, datetime.min.time())

                def safe_int(val):
                    try:
                        return int(val) if val else 0
                    except (ValueError, TypeError):
                        return 0

                input_tokens = safe_int(item.get("input_tokens", 0))
                output_tokens = safe_int(item.get("output_tokens", 0))
                rows.append({
                    "date": date_dt,
                    "start_time": int(date_dt.timestamp()),
                    "end_time": int((date_dt + timedelta(days=1)).timestamp()),
                    "provider": "anthropic",
                    "project_id": item.get("workspace_id") or "default",
                    "model": item.get("model") or "unknown",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "input_cached_tokens": safe_int(item.get("cache_read_input_tokens", 0)),
                    "num_model_requests": 0,
                    "total_tokens": input_tokens + output_tokens,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            for col in ["input_tokens", "output_tokens", "input_cached_tokens", "num_model_requests", "total_tokens"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        return df

    def get_projects(self) -> list[dict]:
        try:
            raw = self._get_paginated("organizations/workspaces", {"limit": 100})
        except Exception:
            raw = []

        projects = [
            {
                "id": ws.get("id", "unknown"),
                "name": ws.get("name", ws.get("id", "unknown")),
                "provider": "anthropic",
            }
            for ws in raw
        ]

        # Synthesise a default workspace entry if any usage rows would use "default"
        ids = {p["id"] for p in projects}
        if "default" not in ids:
            projects.append({"id": "default", "name": "Default Workspace", "provider": "anthropic"})

        return projects
