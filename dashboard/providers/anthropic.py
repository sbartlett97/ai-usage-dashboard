"""
Anthropic provider client.

Hits the Anthropic Admin API to fetch workspace costs and message usage,
normalising the response into the common DataFrame schema.

Requires ANTHROPIC_ADMIN_KEY environment variable.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

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
            },
            timeout=30.0,
        )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("ANTHROPIC_ADMIN_KEY"))

    CHUNK_DELAY_SECONDS = 2      # pause between date-range chunks
    RATE_LIMIT_RETRY_SECONDS = 60  # wait on 429 before retrying once

    def _get_paginated(self, endpoint: str, params: dict, data_key: str = "data") -> list[dict]:
        """Fetch all pages, letting httpx handle query string encoding.

        Retries once after RATE_LIMIT_RETRY_SECONDS on a 429 response.
        """
        all_data = []
        url = f"{self.BASE_URL}/{endpoint}"
        current_params = dict(params)

        while True:
            response = self._client.get(url, params=current_params)
            if response.status_code == 429:
                logger.warning("Anthropic rate limit hit, waiting %ds before retry…", self.RATE_LIMIT_RETRY_SECONDS)
                time.sleep(self.RATE_LIMIT_RETRY_SECONDS)
                response = self._client.get(url, params=current_params)

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
                current_params = {**params, "page": result["next_page"]}
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
                "starting_at": chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ending_at": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bucket_width": "1d",
                "group_by[]": ["workspace_id", "description"],
            }
            try:
                buckets = self._get_paginated("organizations/cost_report", params)
            except Exception as e:
                logger.error("Anthropic cost_report error (%s–%s): %s", chunk_start.date(), chunk_end.date(), e)
                continue
            finally:
                time.sleep(self.CHUNK_DELAY_SECONDS)

            for bucket in buckets:
                bucket_start = self._parse_timestamp(bucket.get("starting_at"))
                date = bucket_start.date() if bucket_start else chunk_start.date()
                date_dt = datetime.combine(date, datetime.min.time())
                for item in bucket.get("results", []):
                    try:
                        cost_usd = float(item.get("amount", 0) or 0) / 100.0
                    except (ValueError, TypeError):
                        cost_usd = 0.0
                    rows.append({
                        "date": date_dt,
                        "start_time": int(date_dt.timestamp()),
                        "end_time": int((date_dt + timedelta(days=1)).timestamp()),
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

        def safe_int(val):
            try:
                return int(val) if val else 0
            except (ValueError, TypeError):
                return 0

        for chunk_start, chunk_end in self._date_chunks(start_time, end_time):
            params = {
                "starting_at": chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ending_at": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bucket_width": "1d",
                "group_by[]": ["workspace_id", "model"],
            }
            try:
                buckets = self._get_paginated("organizations/usage_report/messages", params)
            except Exception as e:
                logger.error("Anthropic usage_report error (%s–%s): %s", chunk_start.date(), chunk_end.date(), e)
                continue
            finally:
                time.sleep(self.CHUNK_DELAY_SECONDS)

            for bucket in buckets:
                bucket_start = self._parse_timestamp(bucket.get("starting_at"))
                date = bucket_start.date() if bucket_start else chunk_start.date()
                date_dt = datetime.combine(date, datetime.min.time())
                for item in bucket.get("results", []):
                    input_tokens = safe_int(item.get("uncached_input_tokens", 0))
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
