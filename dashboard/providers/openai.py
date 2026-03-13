"""
OpenAI provider client.

Contains the low-level OpenAI Admin API HTTP client (OpenAIAdminClient) and the
ProviderClient implementation (OpenAIProviderClient) that normalises its output
into the common DataFrame schema with a 'provider' column.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd

from dashboard.providers.base import ProviderClient, ProviderData


# ---------------------------------------------------------------------------
# Low-level HTTP client (moved from openai_api_client.py)
# ---------------------------------------------------------------------------

class OpenAIAdminClient:
    """Low-level client for OpenAI Admin API endpoints."""

    BASE_URL = "https://api.openai.com/v1/organization"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_ADMIN_KEY")
        if not self.api_key:
            raise ValueError(
                "OPENAI_ADMIN_KEY environment variable is required."
            )
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _get_paginated(self, endpoint: str, params: dict, data_key: str = "data") -> list[dict]:
        all_data = []
        url = f"{self.BASE_URL}/{endpoint}"

        query_parts = []
        for key, value in params.items():
            if isinstance(value, list):
                for item in value:
                    query_parts.append(f"{key}={item}")
            else:
                query_parts.append(f"{key}={value}")

        full_url = f"{url}?{'&'.join(query_parts)}" if query_parts else url

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
                query_parts_new = []
                for key, value in params.items():
                    if isinstance(value, list):
                        for item in value:
                            query_parts_new.append(f"{key}={item}")
                    else:
                        query_parts_new.append(f"{key}={value}")
                full_url = f"{url}?{'&'.join(query_parts_new)}"
            else:
                break

        return all_data

    def _get_max_limit(self, bucket_width: str) -> int:
        return {"1d": 31, "1h": 168, "1m": 1440}.get(bucket_width, 31)

    def _get_bucket_duration(self, bucket_width: str) -> timedelta:
        return {"1d": timedelta(days=1), "1h": timedelta(hours=1), "1m": timedelta(minutes=1)}.get(
            bucket_width, timedelta(days=1)
        )

    def get_costs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        group_by: Optional[list[str]] = None,
        bucket_width: str = "1d",
        project_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        if start_time is None:
            start_time = datetime.utcnow() - timedelta(days=30)
        if end_time is None:
            end_time = datetime.utcnow()

        max_limit = self._get_max_limit(bucket_width)
        chunk_duration = self._get_bucket_duration(bucket_width) * max_limit

        all_data = []
        current_start = start_time
        while current_start < end_time:
            current_end = min(current_start + chunk_duration, end_time)
            params = {
                "start_time": int(current_start.timestamp()),
                "end_time": int(current_end.timestamp()),
                "bucket_width": bucket_width,
                "limit": max_limit,
            }
            if group_by:
                params["group_by"] = group_by
            if project_ids:
                params["project_ids"] = project_ids
            all_data.extend(self._get_paginated("costs", params, data_key="data"))
            current_start = current_end

        return all_data

    def get_completions_usage(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        group_by: Optional[list[str]] = None,
        bucket_width: str = "1d",
        project_ids: Optional[list[str]] = None,
        user_ids: Optional[list[str]] = None,
        models: Optional[list[str]] = None,
    ) -> list[dict]:
        if start_time is None:
            start_time = datetime.utcnow() - timedelta(days=30)
        if end_time is None:
            end_time = datetime.utcnow()

        max_limit = self._get_max_limit(bucket_width)
        chunk_duration = self._get_bucket_duration(bucket_width) * max_limit

        all_data = []
        current_start = start_time
        while current_start < end_time:
            current_end = min(current_start + chunk_duration, end_time)
            params = {
                "start_time": int(current_start.timestamp()),
                "end_time": int(current_end.timestamp()),
                "bucket_width": bucket_width,
                "limit": max_limit,
            }
            if group_by:
                params["group_by"] = group_by
            if project_ids:
                params["project_ids"] = project_ids
            if user_ids:
                params["user_ids"] = user_ids
            if models:
                params["models"] = models
            all_data.extend(self._get_paginated("usage/completions", params, data_key="data"))
            current_start = current_end

        return all_data

    def get_projects(self) -> list[dict]:
        url = f"{self.BASE_URL}/projects"
        params = {"limit": 100}
        all_projects = []
        while True:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            result = response.json()
            all_projects.extend(result.get("data", []))
            if result.get("has_more") and result.get("last_id"):
                params["after"] = result["last_id"]
            else:
                break
        return all_projects


# ---------------------------------------------------------------------------
# ProviderClient implementation
# ---------------------------------------------------------------------------

class OpenAIProviderClient(ProviderClient):
    """ProviderClient wrapping OpenAIAdminClient."""

    PROVIDER_NAME = "openai"

    def __init__(self):
        self._admin_client = OpenAIAdminClient()

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("OPENAI_ADMIN_KEY"))

    def get_costs(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        raw = self._admin_client.get_costs(
            start_time=start_time,
            end_time=end_time,
            bucket_width="1d",
            group_by=["project_id"],
        )
        if not raw:
            return pd.DataFrame()

        rows = []
        for bucket in raw:
            start_ts = bucket.get("start_time", 0)
            end_ts = bucket.get("end_time", 0)
            for result in bucket.get("results", []):
                try:
                    cost_value = float(result.get("amount", {}).get("value", 0) or 0)
                except (ValueError, TypeError):
                    cost_value = 0.0
                rows.append({
                    "date": datetime.utcfromtimestamp(start_ts),
                    "start_time": start_ts,
                    "end_time": end_ts,
                    "provider": "openai",
                    "project_id": result.get("project_id") or "unknown",
                    "line_item": result.get("line_item") or "unknown",
                    "cost_usd": cost_value,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df["cost_usd"] = pd.to_numeric(df["cost_usd"], errors="coerce").fillna(0.0)
        return df

    def get_usage(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        raw = self._admin_client.get_completions_usage(
            start_time=start_time,
            end_time=end_time,
            bucket_width="1d",
            group_by=["project_id", "model"],
        )
        if not raw:
            return pd.DataFrame()

        rows = []
        for bucket in raw:
            start_ts = bucket.get("start_time", 0)
            end_ts = bucket.get("end_time", 0)
            for result in bucket.get("results", []):
                def safe_int(val):
                    try:
                        return int(val) if val else 0
                    except (ValueError, TypeError):
                        return 0
                rows.append({
                    "date": datetime.utcfromtimestamp(start_ts),
                    "start_time": start_ts,
                    "end_time": end_ts,
                    "provider": "openai",
                    "project_id": result.get("project_id") or "unknown",
                    "model": result.get("model") or "unknown",
                    "input_tokens": safe_int(result.get("input_tokens", 0)),
                    "output_tokens": safe_int(result.get("output_tokens", 0)),
                    "input_cached_tokens": safe_int(result.get("input_cached_tokens", 0)),
                    "num_model_requests": safe_int(result.get("num_model_requests", 0)),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            for col in ["input_tokens", "output_tokens", "input_cached_tokens", "num_model_requests"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
            df["total_tokens"] = df["input_tokens"] + df["output_tokens"]
        return df

    def get_projects(self) -> list[dict]:
        raw = self._admin_client.get_projects()
        return [
            {
                "id": p.get("id", "unknown"),
                "name": p.get("name", p.get("id", "unknown")),
                "provider": "openai",
            }
            for p in raw
        ]
