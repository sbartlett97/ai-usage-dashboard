"""
Abstract provider interface for AI usage data sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass
class ProviderData:
    """Raw data returned by a single provider client."""

    costs_df: pd.DataFrame
    usage_df: pd.DataFrame
    projects: list[dict]  # each dict: {"id", "name", "provider"}


class ProviderClient(ABC):
    """Abstract base class for AI provider API clients."""

    PROVIDER_NAME: str  # "openai" | "anthropic"

    @abstractmethod
    def get_costs(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """Return a costs DataFrame with a 'provider' column."""
        ...

    @abstractmethod
    def get_usage(self, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """Return a usage DataFrame with a 'provider' column."""
        ...

    @abstractmethod
    def get_projects(self) -> list[dict]:
        """Return list of project/workspace dicts including 'provider' key."""
        ...

    def fetch_all(self, start_time: datetime, end_time: datetime) -> ProviderData:
        """Fetch costs, usage, and projects in one call."""
        return ProviderData(
            costs_df=self.get_costs(start_time, end_time),
            usage_df=self.get_usage(start_time, end_time),
            projects=self.get_projects(),
        )

    @classmethod
    def is_configured(cls) -> bool:
        """Return True if the required environment variable(s) are set."""
        return False
