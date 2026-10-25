import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from sollab.httpclient import assert_allowed_rpc, assert_allowed_url
from sollab.pumpcollect import collect_pumpfun, save_snapshot
from sollab.pumpconst import (
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    TOKEN_TOTAL_SUPPLY,
    WSOL_MINT,
)
from sollab.pumpcurve import (
    apply_buy_slippage,
    b58decode,
    b58encode,
    bonding_curve_market_cap_lamports,
    bonding_curve_pda,
    decode_bonding_curve,
    decode_global,
    decode_mint,
    documented_initial_market_cap_lamports,
    encode_curve_for_test,
    encode_global_for_test,
    encode_mint_for_test,
    find_program_address,
    global_pda,
    median_observed,
    priority_fee_lamports,
    quote_buy_exact_sol_in,
    quote_sell_exact_tokens_in,
)
from sollab.pumpflags import (
    CREATOR_HOLDING_PCT,
    CREATOR_SELLING,
    FREEZE_AUTHORITY_ACTIVE,
    MINT_AUTHORITY_ACTIVE,
    THIN_LIQUIDITY,
    TOP_HOLDER_CONCENTRATION,
    VERY_YOUNG,
    WASH_TRADE_LIKE,
    compute_flags,
)
from sollab.pumpstrategy import run_pump_strategy
from sollab.storage import reset_simulation

MINT = b58encode(bytes(range(1, 33)))
FETCHED = "2026-10-25T16:00:00Z"
CREATED = "2026-10-25T15:00:00Z"


def test_global_pda_matches_documented_address():
    assert global_pda() == "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
    program = b58decode("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
    address, bump = find_program_address([b"global"], program)
    assert b58encode(address) == "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
    assert bump == 255


def test_initial_market_cap_and_buy_fee_formula():
    assert documented_initial_market_cap_lamports() == 27_958_993_476
    assert (
        bonding_curve_market_cap_lamports(
            INITIAL_VIRTUAL_SOL_RESERVES,
            INITIAL_VIRTUAL_TOKEN_RESERVES,
            TOKEN_TOTAL_SUPPLY,
        )
        == 27_958_993_476
    )
    spendable = 1_000_000_000
    quote = quote_buy_exact_sol_in(
        virtual_token_reserves=INITIAL_VIRTUAL_TOKEN_RESERVES,
        virtual_quote_reserves=INITIAL_VIRTUAL_SOL_RESERVES,
        spendable_lamports=spendable,
        protocol_fee_bps=95,
        creator_fee_bps=30,
        real_token_reserves=INITIAL_REAL_TOKEN_RESERVES,
    )
    net = (spendable * 10_000) // (10_000 + 125)
    assert quote.net_lamports == net
    assert quote.curve_fee_lamports == spendable - net
    assert quote.protocol_fee_lamports == (net * 95 + 9_999) // 10_000
    assert quote.creator_fee_lamports == (net * 30 + 9_999) // 10_000
    assert quote.tokens_out > 0
    assert quote.exceeds_real_reserves is False
    no_fee = quote_buy_exact_sol_in(
        virtual_token_reserves=INITIAL_VIRTUAL_TOKEN_RESERVES,
        virtual_quote_reserves=INITIAL_VIRTUAL_SOL_RESERVES,
        spendable_lamports=spendable,
        protocol_fee_bps=0,
        creator_fee_bps=0,
    )
    assert quote.tokens_out < no_fee.tokens_out
    slipped = apply_buy_slippage(quote.tokens_out, 50)
    assert slipped < quote.tokens_out


def test_sell_quote_pays_fees_from_output_and_priority_fee_uses_observed_median():
    sold = quote_sell_exact_tokens_in(
        virtual_token_reserves=1_000_000,
        virtual_quote_reserves=2_000_000,
        tokens_in=1_000,
        protocol_fee_bps=95,
        creator_fee_bps=30,
        slippage_bps=50,
    )
    assert sold.model == "paper_sell_v1"
    assert sold.gross_lamports == (1_000 * 2_000_000) // (1_000_000 + 1_000)
    assert sold.net_lamports < sold.gross_lamports
    assert sold.slipped_lamports < sold.net_lamports
    assert median_observed([1000, 3000]) == 3000
    assert priority_fee_lamports(1_000_000, 200_000) == 200_000
    assert priority_fee_lamports(3000, 200_000) == 600


def test_decode_round_trip_and_missing_creator_is_unknown():
    creator = bytes([2]) * 32
    raw = encode_curve_for_test(
        virtual_token=11,
        virtual_quote=22,
        real_token=7,
        real_quote=5,
        complete=False,
        creator=creator,
    )
    decoded = decode_bonding_curve(raw)
    assert decoded is not None
    assert decoded.virtual_quote_reserves == 22
    assert decoded.creator == b58encode(creator)
    assert decoded.complete is False
    short = raw[:49]
    short_decoded = decode_bonding_curve(short)
    assert short_decoded is not None
    assert short_decoded.creator is None
    global_config = decode_global(encode_global_for_test(95))
    assert global_config is not None
    assert global_config.fee_basis_points == 95
    shifted = decode_global(encode_global_for_test(100))
    assert shifted is not None
    assert shifted.fee_basis_points == 100
    assert decode_global(b"\x00" * 113) is None
    mint = decode_mint(encode_mint_for_test(), "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    assert mint is not None
    assert mint.mint_authority == "none"
    assert mint.freeze_authority == "none"
    assert mint.decimals == 6
    active = decode_mint(encode_mint_for_test(authority=creator), None)
    assert active is not None
    assert active.mint_authority == b58encode(creator)


def test_flags_are_unknown_without_inputs_and_true_only_from_stored_fields():
    empty = compute_flags({"fetched_at": FETCHED})
    by_name = {flag.flag: flag.status for flag in empty}
    assert by_name[VERY_YOUNG] == "unknown"
    assert by_name[WASH_TRADE_LIKE] == "unknown"
    assert by_name[THIN_LIQUIDITY] == "unknown"
    assert by_name[MINT_AUTHORITY_ACTIVE] == "unknown"
    assert by_name[FREEZE_AUTHORITY_ACTIVE] == "unknown"
    assert by_name[CREATOR_HOLDING_PCT] == "unknown"
    assert by_name[TOP_HOLDER_CONCENTRATION] == "unknown"
    assert by_name[CREATOR_SELLING] == "unknown"

    wash = compute_flags({"fetched_at": FETCHED, "buyers_m5": 1, "buys_m5": 60, "sells_m5": 0})
    assert {flag.flag: flag.status for flag in wash}[WASH_TRADE_LIKE] == "true"
    calm = compute_flags({"fetched_at": FETCHED, "buyers_m5": 10, "buys_m5": 60})
    assert {flag.flag: flag.status for flag in calm}[WASH_TRADE_LIKE] == "false"
    young = compute_flags({"fetched_at": FETCHED, "created_at": "2026-10-25T15:59:30Z"})
    assert {flag.flag: flag.status for flag in young}[VERY_YOUNG] == "true"
    old = compute_flags({"fetched_at": FETCHED, "created_at": CREATED})
    assert {flag.flag: flag.status for flag in old}[VERY_YOUNG] == "false"
    authority = compute_flags({"mint_authority": "none", "freeze_authority": b58encode(bytes([3]) * 32)})
    statuses = {flag.flag: flag.status for flag in authority}
    assert statuses[MINT_AUTHORITY_ACTIVE] == "false"
    assert statuses[FREEZE_AUTHORITY_ACTIVE] == "true"
    thin = compute_flags({"reserve_usd": "9"})
    assert {flag.flag: flag.status for flag in thin}[THIN_LIQUIDITY] == "true"


def test_rpc_methods_that_send_transactions_are_refused():
    with pytest.raises(ValueError):
        assert_allowed_rpc(
            "https://api.mainnet-beta.solana.com",
            {"method": "sendTransaction"},
        )
    with pytest.raises(ValueError):
        assert_allowed_url("https://api.mainnet-beta.solana.com")
    assert_allowed_url(
        "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pump-fun/pools?page=1"
    )
    with pytest.raises(ValueError):
        assert_allowed_url("https://api.geckoterminal.com/api/v2/search/pools")


def test_strategy_enters_after_delay_and_rejects_flags(conn):
    _fee(conn, "c0")
    _fee(conn, "c1")
    _fee(conn, "c2")
    _fee(conn, "c3")
    save_snapshot(conn, _row("c0", FETCHED))
    save_snapshot(conn, _row("c1", "2026-10-25T16:00:30Z"))
    high = _row(
        "c2",
        "2026-10-25T16:01:00Z",
        virtual_quote_reserves=str(INITIAL_VIRTUAL_SOL_RESERVES * 5),
        virtual_token_reserves=str(INITIAL_VIRTUAL_TOKEN_RESERVES // 2),
    )
    save_snapshot(conn, high)
    save_snapshot(
        conn,
        _row(
            "c3",
            "2026-10-25T16:01:30Z",
            virtual_quote_reserves=str(INITIAL_VIRTUAL_SOL_RESERVES * 5),
            virtual_token_reserves=str(INITIAL_VIRTUAL_TOKEN_RESERVES // 2),
        ),
    )
    conn.commit()
    summary = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 17, tzinfo=timezone.utc))
    assert summary.opens == 1
    assert summary.closes == 1
    assert summary.realized_pnl > 0
    fill = conn.execute("SELECT * FROM pump_fills WHERE intent = 'open'").fetchone()
    assert fill["simulated_label"] == "SIMULATED_PUMPFUN_NOT_A_LIVE_TRADE"
    assert fill["market"] == "pump.fun"
    assert int(fill["execution_delay_seconds"]) == 30
    assert Decimal(fill["notional_usd"]) <= Decimal("10")
    assert Decimal(fill["notional_usd"]) >= Decimal("1")
    assert int(fill["protocol_fee_bps"]) == 95
    assert int(fill["creator_fee_bps"]) == 30
    assert int(fill["solana_base_lamports"]) == 5000
    closed = conn.execute("SELECT exit_reason, realized_pnl FROM pump_positions").fetchone()
    assert closed["exit_reason"] == "take_profit"
    assert summary.ending_equity == summary.starting_cash + summary.realized_pnl

    wash = _row("wash", FETCHED, buyers_m5=1, buys_m5=60, sells_m5=0)
    # fresh database state: the replay above replaced pump sim rows but snapshots remain.
    # A second run sees every snapshot, including the profitable path. Use a new connection
    # state by deleting snapshots first.
    conn.execute("DELETE FROM pump_flags")
    conn.execute("DELETE FROM pump_snapshots")
    conn.execute("DELETE FROM pump_network_fees")
    _fee(conn, "wash")
    save_snapshot(conn, wash)
    conn.commit()
    blocked = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 17, tzinfo=timezone.utc))
    assert blocked.opens == 0
    assert blocked.rejection_counts["red_flag:wash_trade_like"] == 1


def test_single_snapshot_does_not_invent_a_delayed_fill(conn):
    _fee(conn, "only")
    save_snapshot(conn, _row("only", FETCHED))
    conn.commit()
    summary = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 17, tzinfo=timezone.utc))
    assert summary.opens == 0
    assert summary.rejection_counts["no_fill_after_delay"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM pump_fills").fetchone()["n"] == 0


def test_stop_time_limit_graduation_priority_and_sma_lock(conn):
    _fee(conn, "s0")
    _fee(conn, "s1")
    _fee(conn, "s2")
    _fee(conn, "s3")
    save_snapshot(conn, _row("s0", FETCHED))
    save_snapshot(conn, _row("s1", "2026-10-25T16:00:30Z"))
    save_snapshot(
        conn,
        _row("s2", "2026-10-25T16:01:00Z", virtual_quote_reserves=str(INITIAL_VIRTUAL_SOL_RESERVES // 5)),
    )
    save_snapshot(
        conn,
        _row("s3", "2026-10-25T16:01:30Z", virtual_quote_reserves=str(INITIAL_VIRTUAL_SOL_RESERVES // 5)),
    )
    conn.commit()
    summary = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 17, tzinfo=timezone.utc))
    assert summary.closes == 1
    assert conn.execute("SELECT exit_reason FROM pump_positions").fetchone()["exit_reason"] == "stop"
    assert summary.realized_pnl < 0

    conn.execute("DELETE FROM pump_flags")
    conn.execute("DELETE FROM pump_snapshots")
    conn.execute("DELETE FROM pump_network_fees")
    for collect_id, stamp in (
        ("t0", FETCHED),
        ("t1", "2026-10-25T16:00:30Z"),
        ("t2", "2026-10-25T16:20:30Z"),
        ("t3", "2026-10-25T16:21:00Z"),
    ):
        _fee(conn, collect_id)
        save_snapshot(conn, _row(collect_id, stamp))
    conn.commit()
    timed = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 18, tzinfo=timezone.utc))
    assert timed.closes == 1
    assert conn.execute("SELECT exit_reason FROM pump_positions").fetchone()["exit_reason"] == "time_limit"

    conn.execute("DELETE FROM pump_flags")
    conn.execute("DELETE FROM pump_snapshots")
    conn.execute("DELETE FROM pump_network_fees")
    _fee(conn, "g0")
    _fee(conn, "g1")
    _fee(conn, "g2")
    _fee(conn, "g3")
    save_snapshot(conn, _row("g0", FETCHED))
    save_snapshot(conn, _row("g1", "2026-10-25T16:00:30Z"))
    save_snapshot(
        conn,
        _row("g2", "2026-10-25T16:01:00Z", curve_complete=1, graduation_status="graduated", progress="1"),
    )
    save_snapshot(
        conn,
        _row("g3", "2026-10-25T16:01:30Z", curve_complete=1, graduation_status="graduated", progress="1"),
    )
    conn.commit()
    graduated = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 18, tzinfo=timezone.utc))
    assert graduated.opens == 1
    assert graduated.closes == 0
    assert graduated.rejection_counts["graduated_no_curve_quote"] == 1
    assert conn.execute("SELECT status FROM pump_positions").fetchone()["status"] == "open"

    conn.execute("DELETE FROM pump_flags")
    conn.execute("DELETE FROM pump_snapshots")
    conn.execute("DELETE FROM pump_network_fees")
    _fee(conn, "p")
    save_snapshot(conn, _row("p", FETCHED, progress="0.61"))
    other = _row("p", FETCHED, progress="0.40")
    other["mint"] = b58encode(bytes(range(2, 34)))
    save_snapshot(conn, other)
    conn.commit()
    ranked = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 18, tzinfo=timezone.utc))
    assert ranked.rejection_counts["lower_priority_same_timestamp"] == 1
    assert ranked.rejection_counts["no_fill_after_delay"] == 1

    version_id = conn.execute("SELECT id FROM strategy_versions LIMIT 1").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO simulation_runs (
            strategy_version_id, recorded_at, parameters_json, candle_sources_json,
            candle_counts_json, starting_cash, ending_equity, realized_pnl, unrealized_pnl, note
        ) VALUES (?, '2026-10-25T16:00:00Z', '{}', '{}', '{}', '300', '297', '-3', '0', 'sma')
        """,
        (version_id,),
    )
    run_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO positions (
            strategy_version_id, simulation_run_id, symbol, direction, quantity, entry_mark,
            entry_fill, entry_notional, entry_fee, opened_at, status, recorded_at
        ) VALUES (?, ?, 'BTC', 'short', '0.0001', '80000', '80000', '10', '0.06',
                  '2026-10-25T09:00:00Z', 'open', '2026-10-25T16:00:00Z')
        """,
        (version_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO ledger (
            simulation_run_id, simulated_at, recorded_at, event, symbol, direction, cash_free,
            locked_notional, cash_delta, fee, realized_pnl, unrealized_pnl, equity, note
        ) VALUES (?, '2026-10-25T09:00:00Z', '2026-10-25T16:00:00Z', 'open', 'BTC', 'short',
                  '287.11000000', '10', '-10.06', '0.06', '0', '0', '297', 'sma')
        """,
        (run_id,),
    )
    conn.commit()
    shared = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 18, tzinfo=timezone.utc))
    assert shared.opens == 0
    assert "blocked_by_open_position" not in shared.rejection_counts
    assert shared.rejection_counts["no_fill_after_delay"] == 1
    assert shared.starting_cash == Decimal("5000")
    assert shared.sma_open is None
    conn.execute("UPDATE simulation_runs SET cash_era = '5000', starting_cash = '5000'")
    conn.execute("UPDATE positions SET market = 'pumpfun'")
    conn.commit()
    blocked = run_pump_strategy(conn, clock=datetime(2026, 10, 25, 19, tzinfo=timezone.utc))
    assert blocked.opens == 0
    assert blocked.rejection_counts["blocked_by_open_position"] == 1
    reset_simulation(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM pump_snapshots").fetchone()["n"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM positions").fetchone()["n"] == 0


def test_collector_stores_only_returned_fields_and_records_probe_errors(conn):
    mint = MINT
    curve = bonding_curve_pda(mint)
    creator = bytes([9]) * 32
    curve_raw = encode_curve_for_test(
        virtual_token=INITIAL_VIRTUAL_TOKEN_RESERVES,
        virtual_quote=INITIAL_VIRTUAL_SOL_RESERVES,
        real_token=INITIAL_REAL_TOKEN_RESERVES // 2,
        real_quote=10_000_000_000,
        creator=creator,
    )
    mint_raw = encode_mint_for_test()
    global_raw = encode_global_for_test(95)
    accounts = {
        "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf": global_raw,
        curve: curve_raw,
        mint: mint_raw,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "api.geckoterminal.com":
            body = {
                "data": [
                    {
                        "attributes": {
                            "address": "pooladdress",
                            "name": "AAA / SOL",
                            "pool_created_at": CREATED,
                            "base_token_price_usd": "0.00001",
                            "quote_token_price_usd": "100",
                            "fdv_usd": "10000",
                            "market_cap_usd": None,
                            "reserve_in_usd": "5000",
                            "transactions": {
                                "m5": {"buys": 20, "sells": 4, "buyers": 10, "sellers": 3},
                                "h1": {"buys": 20, "sells": 4, "buyers": 10, "sellers": 3},
                                "h24": {"buys": 20, "sells": 4, "buyers": 10, "sellers": 3},
                            },
                            "volume_usd": {"m5": "12", "h1": "40", "h24": "80"},
                        },
                        "relationships": {
                            "base_token": {"data": {"id": f"solana_{mint}", "type": "token"}},
                            "quote_token": {"data": {"id": f"solana_{WSOL_MINT}", "type": "token"}},
                            "dex": {"data": {"id": "pump-fun", "type": "dex"}},
                        },
                    }
                ]
            }
            return httpx.Response(200, json=body)
        if host == "api.dexscreener.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "chainId": "solana",
                        "dexId": "pump-fun",
                        "pairAddress": "dexpair",
                        "baseToken": {"address": mint, "symbol": "SHOULD_NOT_WIN", "name": "Dex Name"},
                        "quoteToken": {"address": WSOL_MINT, "symbol": "SOL"},
                        "priceUsd": "9.99",
                        "txns": {"m5": {"buys": 1, "sells": 1}},
                        "volume": {"m5": "1"},
                        "liquidity": {"usd": 1},
                        "marketCap": 1,
                        "pairCreatedAt": 1,
                    }
                ],
            )
        if host == "api.coingecko.com":
            return httpx.Response(200, json={"solana": {"usd": 100}})
        if host == "api.pump.fun":
            return httpx.Response(
                401,
                json={
                    "statusCode": 401,
                    "error": "API_KEY_REQUIRED",
                    "message": "Send Authorization: Bearer <key> or x-api-key: <key>",
                },
            )
        if host == "frontend-api-v3.pump.fun":
            return httpx.Response(403, text="Just a moment...")
        if host == "api.mainnet-beta.solana.com":
            import base64

            payload = json.loads(request.content.decode())
            method = payload["method"]
            if method == "getAccountInfo":
                raw = accounts[payload["params"][0]]
                value = {"owner": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", "data": [base64.b64encode(raw).decode(), "base64"]}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": value}})
            if method == "getMultipleAccounts":
                values = []
                for key in payload["params"][0]:
                    raw = accounts.get(key)
                    if raw is None:
                        values.append(None)
                    else:
                        owner = (
                            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
                            if key == curve
                            else "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                        )
                        values.append({"owner": owner, "data": [base64.b64encode(raw).decode(), "base64"]})
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": values}})
            if method == "getRecentPrioritizationFees":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": [
                            {"slot": 1, "prioritizationFee": 1000},
                            {"slot": 2, "prioritizationFee": 3000},
                        ],
                    },
                )
            return httpx.Response(400, json={"error": "unexpected"})
        return httpx.Response(500, text="unexpected host")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = collect_pumpfun(conn, client=client, polls=1, pause_seconds=0, max_retries=0, sleeper=lambda _seconds: None)
    assert summary.snapshots == 1
    row = conn.execute("SELECT * FROM pump_snapshots").fetchone()
    assert row["mint"] == mint
    assert row["symbol"] == "AAA"
    assert row["price_usd"] == "0.00001"
    sources = json.loads(row["field_sources_json"])
    assert sources["price_usd"] == "geckoterminal"
    assert row["market_cap_usd"] == "1"
    assert sources["market_cap_usd"] == "dexscreener"
    assert row["creator"] == b58encode(creator)
    assert row["graduation_status"] == "on_curve"
    assert row["progress"] == "0.5"
    assert row["mint_authority"] == "none"
    assert row["freeze_authority"] == "none"
    assert row["quote_is_sol"] == 1
    assert row["global_fee_basis_points"] == 95
    assert row["sol_usd_source"] == "coingecko"
    assert row["source_timestamp"] is None
    assert "geckoterminal" in row["source_name"]
    assert "solana_rpc" in row["source_name"]
    assert row["buyers_m5"] == 10
    flags = {flag["flag"]: flag["status"] for flag in conn.execute("SELECT flag, status FROM pump_flags")}
    assert flags["creator_holding_pct"] == "unknown"
    assert flags["top_holder_concentration"] == "unknown"
    assert flags["creator_selling"] == "unknown"
    assert flags["wash_trade_like"] == "false"
    fees = conn.execute("SELECT * FROM pump_network_fees").fetchone()
    assert fees["global_decode_ok"] == 1
    assert fees["global_fee_basis_points"] == 95
    assert fees["base_fee_lamports"] == 5000
    assert fees["priority_micro_lamports_per_cu"] == "3000"
    assert fees["priority_fee_lamports"] == "600"
    messages = " ".join(error["message"] for error in conn.execute("SELECT message FROM errors"))
    assert "API_KEY_REQUIRED" in messages
    assert "403" in messages
    assert conn.execute("SELECT COUNT(*) AS n FROM pump_snapshots").fetchone()["n"] == 1


def _fee(conn, collect_id: str) -> None:
    conn.execute(
        """
        INSERT INTO pump_network_fees (
            collect_id, fetched_at, endpoint, slot, base_fee_lamports,
            priority_micro_lamports_per_cu, priority_sample_count, assumed_compute_units,
            priority_fee_lamports, sol_usd, sol_usd_source, sol_usd_endpoint,
            global_fee_basis_points, global_decode_ok, initial_real_token_reserves, note
        ) VALUES (?, ?, 'https://api.mainnet-beta.solana.com', 1, 5000, '1000', 2, 200000,
                  '200', '100', 'test', 'https://api.coingecko.com/api/v3/simple/price',
                  95, 1, ?, NULL)
        """,
        (collect_id, FETCHED, str(INITIAL_REAL_TOKEN_RESERVES)),
    )


def _row(collect_id: str, fetched_at: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "collect_id": collect_id,
        "mint": MINT,
        "symbol": "TEST",
        "name": "TEST",
        "creator": None,
        "pool_address": "pool",
        "dex_id": "pump-fun",
        "quote_mint": WSOL_MINT,
        "quote_symbol": "SOL",
        "created_at": CREATED,
        "graduation_status": "on_curve",
        "price_usd": "0.00001",
        "market_cap_usd": "10000",
        "fdv_usd": "10000",
        "reserve_usd": "5000",
        "volume_m5_usd": "100",
        "volume_h1_usd": "100",
        "volume_h24_usd": "100",
        "buys_m5": 20,
        "sells_m5": 4,
        "buyers_m5": 10,
        "sellers_m5": 3,
        "buys_h1": 20,
        "sells_h1": 4,
        "buyers_h1": 10,
        "sellers_h1": 3,
        "buys_h24": 20,
        "sells_h24": 4,
        "virtual_token_reserves": str(INITIAL_VIRTUAL_TOKEN_RESERVES),
        "virtual_quote_reserves": str(INITIAL_VIRTUAL_SOL_RESERVES),
        "real_token_reserves": str(INITIAL_REAL_TOKEN_RESERVES // 2),
        "real_quote_reserves": "10000000000",
        "token_total_supply": str(TOKEN_TOTAL_SUPPLY),
        "curve_complete": 0,
        "progress": "0.5",
        "decimals": 6,
        "mint_authority": "none",
        "freeze_authority": "none",
        "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "quote_is_sol": 1,
        "global_fee_basis_points": 95,
        "initial_real_token_reserves": str(INITIAL_REAL_TOKEN_RESERVES),
        "sol_usd": "100",
        "sol_usd_source": "test",
        "field_sources_json": "{}",
        "source_name": "test",
        "endpoint": "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pump-fun/pools",
        "fetched_at": fetched_at,
        "source_timestamp": None,
    }
    row.update(overrides)
    return row
