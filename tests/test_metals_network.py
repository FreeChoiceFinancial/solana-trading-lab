from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from sollab.metalscollect import collect_metals
from sollab.storage import connect

ALLOWED = {
    "api.exchange.coinbase.com",
    "api.kraken.com",
    "api.coingecko.com",
    "query1.finance.yahoo.com",
}


def _offline(message: str) -> bool:
    lowered = message.lower()
    markers = ("timed out", "timeout", "connection", "network", "429", "503", "502", "504")
    return any(marker in lowered for marker in markers)


@pytest.mark.network
def test_live_public_metals_prices(tmp_path):
    conn = connect(tmp_path / "live.db")
    try:
        summary = collect_metals(conn, pause_seconds=0.2, max_retries=1)
        rows = list(
            conn.execute(
                """
                SELECT * FROM prices
                WHERE symbol IN ('PAXG', 'XAUT', 'GLD', 'SLV', 'PPLT', 'PALL', 'GC', 'SI', 'PL', 'PA')
                """
            ).fetchall()
        )
        if not rows:
            detail = "; ".join(summary.errors) or "no error recorded"
            if summary.errors and all(_offline(error) for error in summary.errors):
                pytest.skip(f"metals APIs unreachable: {detail}")
            pytest.fail(f"metals collector stored no prices: {detail}")
        symbols = {row["symbol"] for row in rows}
        assert "PAXG" in symbols
        assert "SI" in symbols
        now = datetime.now(timezone.utc)
        for row in rows:
            assert urlparse(row["endpoint"]).hostname in ALLOWED
            assert row["source_timestamp"]
            assert Decimal(row["close"]) > 0
            fetched = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
            assert abs((now - fetched).total_seconds()) < 1800
    finally:
        conn.close()
