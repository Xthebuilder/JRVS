"""
Unit tests for data_analysis.analyzer — DataAnalyzer class.

These tests run whether or not pandas is installed.
"""

import csv
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_analysis.analyzer import DataAnalyzer, PANDAS_AVAILABLE


# Skip the whole module if pandas is absent — those code paths return early
# with a clear error anyway, and we test that separately.
needs_pandas = pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas not installed")


class TestDataAnalyzerNoPandas:
    """Edge-case: ensure graceful degradation when pandas is missing."""

    @pytest.mark.asyncio
    async def test_load_csv_without_pandas(self):
        if PANDAS_AVAILABLE:
            pytest.skip("pandas IS installed — nothing to test here")
        analyzer = DataAnalyzer()
        result = await analyzer.load_csv("/tmp/fake.csv")
        assert result["success"] is False
        assert "pandas" in result["error"].lower()


@needs_pandas
class TestDataAnalyzerCSV:
    """Tests for CSV loading and analysis (requires pandas)."""

    @pytest.fixture
    def csv_file(self, tmp_path):
        p = tmp_path / "data.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "age", "score"])
            w.writerow(["Alice", 30, 95.5])
            w.writerow(["Bob", 25, 87.0])
            w.writerow(["Carol", 35, 91.2])
        return str(p)

    @pytest.mark.asyncio
    async def test_load_csv_success(self, csv_file):
        analyzer = DataAnalyzer()
        result = await analyzer.load_csv(csv_file, name="people")
        assert result["success"] is True
        assert result["rows"] == 3
        assert result["columns"] == 3
        assert "name" in result["column_names"]

    @pytest.mark.asyncio
    async def test_load_csv_missing_file(self):
        analyzer = DataAnalyzer()
        result = await analyzer.load_csv("/tmp/does_not_exist.csv")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_list_datasets(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="ds1")
        listing = analyzer.list_datasets()
        names = [d["name"] for d in listing["datasets"]]
        assert "ds1" in names

    @pytest.mark.asyncio
    async def test_query_data_filter(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.query_data("people", "age > 28")
        assert result["success"] is True
        assert result["rows"] == 2  # Alice (30) and Carol (35)

    @pytest.mark.asyncio
    async def test_query_data_equality(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.query_data("people", "name == Alice")
        assert result["success"] is True
        assert result["rows"] == 1

    @pytest.mark.asyncio
    async def test_query_data_unknown_dataset(self):
        analyzer = DataAnalyzer()
        result = await analyzer.query_data("nope", "x > 1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_query_data_unknown_column(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.query_data("people", "nonexistent > 5")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_column_stats_numeric(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.get_column_stats("people", "age")
        assert result["success"] is True
        stats = result["stats"]
        assert stats["count"] == 3
        assert stats["min"] == 25.0
        assert stats["max"] == 35.0
        assert "mean" in stats

    @pytest.mark.asyncio
    async def test_get_column_stats_string(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.get_column_stats("people", "name")
        assert result["success"] is True
        assert result["stats"]["unique_count"] == 3
        # String columns don't have mean/min/max
        assert "mean" not in result["stats"]

    @pytest.mark.asyncio
    async def test_get_column_stats_missing_col(self, csv_file):
        analyzer = DataAnalyzer()
        await analyzer.load_csv(csv_file, name="people")
        result = await analyzer.get_column_stats("people", "nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_column_stats_missing_dataset(self):
        analyzer = DataAnalyzer()
        result = await analyzer.get_column_stats("nope", "col")
        assert result["success"] is False
