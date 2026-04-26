"""Tests for Charity Commission connector (M2+)."""
import pytest


@pytest.mark.skip(reason="M2+ — not yet implemented")
def test_download_stub():
    from etl.connectors.charity_commission.extract import download
    download()
