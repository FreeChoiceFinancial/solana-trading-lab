from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from sollab.collect import collect
from sollab.storage import connect
from sollab.timeutil import parse_timestamp

ALLOWED_HOSTS = {
    "api.exchange.coinbase.com",
    "api.coingecko.com",
    "api.kraken.com",
}


def _offline(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "timed out",
        "timeout",
        "connection",
        "name or service not known",
        "temporary failure",
        "network",
        "429",
        "rate limit",
        "503",
        "502",
        "504",
    )
    return any(marker in lowered for marker in markers)


@pytest.mark.network
def test_live_public_btc_and_sol_prices(tmp_path):
    """Hit the real public APIs. Skip only when the network itself is unavailable."""
    conn = connect(tmp_path / "live.db")
    try:
        summary = collect(conn, pause_seconds=0.2, max_retries=2)
        rows = list(conn.execute("SELECT * FROM prices").fetchall())
        if not rows:
            detail = "; ".join(summary.errors) or "no error recorded"
            if summary.errors and all(_offline(error) for error in summary.errors):
                pytest.skip(f"public market APIs unreachable: {detail}")
            pytest.fail(f"collector stored no prices: {detail}")
        symbols = {row["symbol"] for row in rows}
        assert {"BTC", "SOL"} <= symbols
        intervals = {row["interval"] for row in rows}
        assert "spot" in intervals
        assert "1h" in intervals
        now = datetime.now(timezone.utc)
        for row in rows:
            assert row["source_name"]
            assert row["endpoint"].startswith("https://")
            assert urlparse(row["endpoint"]).hostname in ALLOWED_HOSTS
            assert row["fetched_at"]
            assert row["source_timestamp"]
            price = Decimal(row["close"])
            assert price > 0
            fetched = parse_timestamp(row["fetched_at"])
            assert abs((now - fetched).total_seconds()) < 1800
            if row["symbol"] == "BTC":
                assert price > Decimal("1000")
            if row["symbol"] == "SOL":
                assert price > Decimal("1")
    finally:
        conn.close()
