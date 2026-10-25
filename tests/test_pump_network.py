"""Live read-only pump.fun collection. Skips when the public APIs are unreachable."""

from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from sollab.pumpcollect import collect_pumpfun

ALLOWED_HOSTS = {
    "api.geckoterminal.com",
    "api.dexscreener.com",
    "api.coingecko.com",
    "api.mainnet-beta.solana.com",
    "api.pump.fun",
    "frontend-api-v3.pump.fun",
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
        "503",
        "502",
        "504",
    )
    return any(marker in lowered for marker in markers)


@pytest.mark.network
def test_live_pumpfun_collect_stores_provenance(conn):
    summary = collect_pumpfun(conn, polls=1, pause_seconds=0.4, max_retries=1)
    rows = list(conn.execute("SELECT * FROM pump_snapshots").fetchall())
    errors = list(conn.execute("SELECT component, message FROM errors").fetchall())
    if not rows:
        detail = "; ".join(summary.errors) or "no error recorded"
        if summary.errors and all(_offline(error) for error in summary.errors):
            pytest.skip(f"public pump.fun sources unreachable: {detail}")
        pytest.fail(f"collector stored no pump.fun snapshots: {detail}")
    now = datetime.now(timezone.utc)
    for row in rows:
        assert row["mint"]
        assert row["source_name"]
        assert row["endpoint"].startswith("https://")
        for part in row["endpoint"].split():
            assert urlparse(part).hostname in ALLOWED_HOSTS
        assert row["fetched_at"]
        assert row["graduation_status"] in {"on_curve", "graduated", "unknown"}
        fetched = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
        assert abs((now - fetched).total_seconds()) < 1800
        if row["price_usd"] is not None:
            assert Decimal(row["price_usd"]) >= 0
        if row["virtual_quote_reserves"] is not None:
            assert int(row["virtual_quote_reserves"]) >= 0
            assert row["creator"] is None or len(row["creator"]) >= 32
    messages = " ".join(row["message"] for row in errors)
    assert "API_KEY_REQUIRED" in messages or any(_offline(row["message"]) for row in errors if "pump_developer_api" in row["component"])
    fee = conn.execute("SELECT * FROM pump_network_fees").fetchone()
    assert fee is not None
    if fee["global_decode_ok"] == 1:
        assert fee["global_fee_basis_points"] == 95
