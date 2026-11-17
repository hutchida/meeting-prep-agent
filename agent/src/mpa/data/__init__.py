"""Data access: DataSource implementations and the factory that picks one from Settings."""

from __future__ import annotations

from mpa.contract import DataSource, DataSourceError, Settings
from mpa.data.fake import FakeDataSource
from mpa.data.graph import GraphDataSource
from mpa.data.loader import DataFormatError


def build_data_source(settings: Settings) -> DataSource:
    if settings.data_source == "graph":
        return GraphDataSource()
    return FakeDataSource(settings.data_dir)


__all__ = [
    "DataFormatError",
    "DataSource",
    "DataSourceError",
    "FakeDataSource",
    "GraphDataSource",
    "build_data_source",
]
