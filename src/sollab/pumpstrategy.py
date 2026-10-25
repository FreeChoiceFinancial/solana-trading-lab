"""Bonding-curve momentum paper replay.

Signals use one stored snapshot. Fills use the first later snapshot of the same
mint at least EXECUTION_DELAY_SECONDS after the signal. Missing prices stay
missing. This module does not send transactions.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from sollab.constants import MAX_NOTIONAL, MIN_NOTIONAL, STARTING_CASH
from sollab.ledger import q
from sollab.pumpconst import (
    ASSUMED_SWAP_COMPUTE_UNITS,
    BASE_SIGNATURE_LAMPORTS,
    EXECUTION_DELAY_SECONDS,
    EXTRA_SLIPPAGE_BPS,
    MAX_HOLD_SECONDS,
    MAX_PROGRESS,
    MIN_BUYERS_M5,
    MIN_BUYS_M5,
    MIN_PROGRESS,
    PINNED_PROTOCOL_FEE_BPS,
    PUBLISHED_CREATOR_FEE_BPS,
    PUMP_MARKET,
    PUMP_STRATEGY_ID,
    PUMP_STRATEGY_NAME,
    PUMP_STRATEGY_VERSION,
    SIMULATED_LABEL,
    STOP_LOSS,
    TAKE_PROFIT,
)
from sollab.pumpcurve import apply_buy_slippage, quote_buy_exact_sol_in, quote_sell_exact_tokens_in
from sollab.pumpflags import BLOCKING_FLAGS
from sollab.storage import dec_text, reset_pump_simulation, upsert_strategy
from sollab.timeutil import iso_z, parse_timestamp

MONEY = Decimal("0.00000001")


class NoPumpData(Exception):
    """No pump.fun snapshots are stored."""


@dataclass(frozen=True)
class PumpRunSummary:
    recorded_at: datetime
    starting_cash: Decimal
    ending_equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    opens: int
    closes: int
    decisions: int
    rejected_orders: int
    rejection_counts: dict[str, int]
    open_position: str | None
    sma_open: str | None
    note: str


def parameters_json() -> str:
    payload = {
        "market": PUMP_MARKET,
        "min_progress": format(MIN_PROGRESS, "f"),
        "max_progress": format(MAX_PROGRESS, "f"),
        "min_buys_m5": MIN_BUYS_M5,
        "min_buyers_m5": MIN_BUYERS_M5,
        "buy_flow": "buys_m5 > sells_m5",
        "protocol_fee_bps": PINNED_PROTOCOL_FEE_BPS,
        "creator_fee_bps": PUBLISHED_CREATOR_FEE_BPS,
        "creator_fee_source": "pump.fun/docs/fees 2026-10-17 published bonding-curve schedule",
        "extra_slippage_bps": EXTRA_SLIPPAGE_BPS,
        "execution_delay_seconds": EXECUTION_DELAY_SECONDS,
        "base_signature_lamports": BASE_SIGNATURE_LAMPORTS,
        "assumed_compute_units": ASSUMED_SWAP_COMPUTE_UNITS,
        "take_profit": format(TAKE_PROFIT, "f"),
        "stop_loss": format(STOP_LOSS, "f"),
        "max_hold_seconds": MAX_HOLD_SECONDS,
        "max_notional": format(MAX_NOTIONAL, "f"),
        "min_notional": format(MIN_NOTIONAL, "f"),
        "starting_cash_rule": "latest SMA ledger cash_free when that book exists, else 300",
        "sell_model": "paper_sell_v1",
        "buy_model": "idl_buy_exact_sol_in",
        "blocking_flags": list(BLOCKING_FLAGS),
        "informational_flags_do_not_block": [
            "creator_holding_pct",
            "top_holder_concentration",
            "creator_selling",
        ],
    }
    return json.dumps(payload, sort_keys=True)


def rules_text() -> str:
    return "\n".join(
        [
            "bonding_curve_momentum 1.0.0. Long only, market pump.fun, max one open position.",
            "The position lock includes an open milestone-1 position in the positions table.",
            "Entry requires a stored on-curve SOL-quoted snapshot with decoded virtual reserves,",
            f"progress in [{format(MIN_PROGRESS, 'f')}, {format(MAX_PROGRESS, 'f')}),",
            f"m5 buys >= {MIN_BUYS_M5}, m5 buyers >= {MIN_BUYERS_M5}, and buys_m5 > sells_m5.",
            "Blocking flags must be the stored status false. True rejects as red_flag:<name>.",
            "Unknown on a blocking flag rejects as flag_unknown:<name>. Informational flags",
            "(creator holding, top holder, creator selling) stay unknown and do not block,",
            "because those inputs are not in the stored sources.",
            f"Global.fee_basis_points must equal the pinned protocol fee {PINNED_PROTOCOL_FEE_BPS} bps.",
            f"Creator fee is the published {PUBLISHED_CREATOR_FEE_BPS} bps bonding-curve schedule, not a live decode.",
            "The app platform fee is not added. This model is a direct curve trade, not the pump.fun app.",
            f"Fill at the first later snapshot of the same mint at least {EXECUTION_DELAY_SECONDS}s after the signal.",
            "Buy size is 10 USD of spendable quote, converted with the stored SOL/USD price.",
            "Curve impact uses the IDL buy_exact_sol_in formula on the fill snapshot's virtual reserves.",
            f"Extra slippage of {EXTRA_SLIPPAGE_BPS} bps then reduces tokens received.",
            "A quote that wants more tokens than real_token_reserves is rejected, not partially filled.",
            f"Solana cost is {BASE_SIGNATURE_LAMPORTS} lamports plus the median recent priority fee",
            f"times an assumed {ASSUMED_SWAP_COMPUTE_UNITS} compute units, converted with stored SOL/USD.",
            "If SOL/USD, reserves, priority fee, or the delayed snapshot is missing, the fill is rejected.",
            f"Exit signals: take profit at +{format(TAKE_PROFIT * 100, 'f')}% curve proceeds versus entry notional,",
            f"stop at -{format(STOP_LOSS * 100, 'f')}%, max hold {MAX_HOLD_SECONDS}s, or graduation.",
            "Exit fills use paper_sell_v1 on a later on-curve snapshot. A completed curve is not given a PumpSwap price.",
            "Cash falls by the curve spend and the network fee. Realized P&L is booked on close.",
            "Unrealized P&L is the open token's sell quote minus entry notional and entry network fee.",
            "All fills are simulated.",
        ]
    )


@dataclass
class _Position:
    id: int
    mint: str
    tokens_raw: int
    token_ui: Decimal
    decimals: int
    entry_notional: Decimal
    entry_network: Decimal
    entry_effective: Decimal
    opened_at: datetime
    skip_graduation_retry: bool = False


@dataclass
class _Pending:
    mint: str
    signal_time: datetime
    kind: str
    reason: str | None = None


def run_pump_strategy(conn: sqlite3.Connection, *, clock: datetime | None = None) -> PumpRunSummary:
    recorded_at = clock or datetime.now(timezone.utc)
    snapshots = list(conn.execute("SELECT * FROM pump_snapshots ORDER BY fetched_at, id").fetchall())
    if not snapshots:
        raise NoPumpData("no pump.fun snapshots stored. Run: python -m sollab pumpfun-collect")
    flags = _load_flags(conn)
    fees = {
        row["collect_id"]: row
        for row in conn.execute("SELECT * FROM pump_network_fees").fetchall()
    }
    starting_cash, inherited = _inherited_spendable(conn)
    sma_open = inherited.get("sma_open")
    version_id = upsert_strategy(
        conn,
        strategy_id=PUMP_STRATEGY_ID,
        version=PUMP_STRATEGY_VERSION,
        name=PUMP_STRATEGY_NAME,
        parameters_json=parameters_json(),
        rules_text=rules_text(),
        created_at=recorded_at,
    )
    with conn:
        reset_pump_simulation(conn)
        run_id = _insert_run(conn, version_id, recorded_at, starting_cash, inherited)
        summary = _replay(
            conn,
            snapshots=snapshots,
            flags=flags,
            fees=fees,
            version_id=version_id,
            run_id=run_id,
            starting_cash=starting_cash,
            sma_open=sma_open,
            recorded_at=recorded_at,
        )
        conn.execute(
            """
            UPDATE pump_simulation_runs
            SET ending_equity = ?, realized_pnl = ?, unrealized_pnl = ?, note = ?, sma_open_json = ?
            WHERE id = ?
            """,
            (
                dec_text(summary.ending_equity),
                dec_text(summary.realized_pnl),
                dec_text(summary.unrealized_pnl),
                summary.note,
                json.dumps(sma_open) if sma_open else None,
                run_id,
            ),
        )
    return summary


def _replay(
    conn: sqlite3.Connection,
    *,
    snapshots: list[sqlite3.Row],
    flags: dict[int, dict[str, str]],
    fees: dict[str, sqlite3.Row],
    version_id: int,
    run_id: int,
    starting_cash: Decimal,
    sma_open: dict[str, object] | None,
    recorded_at: datetime,
) -> PumpRunSummary:
    cash = starting_cash
    realized = Decimal("0")
    position: _Position | None = None
    pending: _Pending | None = None
    opens = 0
    closes = 0
    decisions = 0
    rejected_orders = 0
    reasons: dict[str, int] = {}
    unrealized: Decimal | None = Decimal("0")
    equity: Decimal | None = cash
    _ledger(conn, run_id, recorded_at, parse_timestamp(snapshots[0]["fetched_at"]), "seed", None, cash, Decimal("0"), Decimal("0"), realized, Decimal("0"), equity, "paper_starting_spendable_cash")

    batches: list[list[sqlite3.Row]] = []
    for snap in snapshots:
        if not batches or batches[-1][0]["fetched_at"] != snap["fetched_at"]:
            batches.append([snap])
        else:
            batches[-1].append(snap)

    for batch in batches:
        batch_time = parse_timestamp(batch[0]["fetched_at"])
        by_mint = {row["mint"]: row for row in batch}
        if pending is not None and pending.kind == "entry" and batch_time >= pending.signal_time + timedelta(seconds=EXECUTION_DELAY_SECONDS):
            snap = by_mint.get(pending.mint)
            if snap is not None:
                filled, cash, position, rejected_orders, decisions = _try_entry_fill(
                    conn,
                    snap,
                    pending,
                    cash,
                    version_id,
                    run_id,
                    recorded_at,
                    rejected_orders,
                    decisions,
                    reasons,
                )
                pending = None
                if filled:
                    opens += 1
        if (
            pending is not None
            and pending.kind == "exit"
            and position is not None
            and batch_time >= pending.signal_time + timedelta(seconds=EXECUTION_DELAY_SECONDS)
        ):
            snap = by_mint.get(position.mint)
            if snap is not None:
                closed, cash, realized, position, rejected_orders, decisions = _try_exit_fill(
                    conn,
                    snap,
                    position,
                    pending,
                    cash,
                    realized,
                    version_id,
                    run_id,
                    recorded_at,
                    rejected_orders,
                    decisions,
                    reasons,
                )
                pending = None
                if closed:
                    closes += 1
        if position is not None and pending is None and position.opened_at < batch_time:
            snap = by_mint.get(position.mint)
            if snap is not None:
                exit_reason = _exit_signal(position, snap, batch_time)
                if exit_reason == "graduated" and position.skip_graduation_retry:
                    exit_reason = None
                if exit_reason is not None:
                    decisions += 1
                    _decision(conn, version_id, run_id, position.mint, snap["id"], batch_time, "exit", None, exit_reason, recorded_at)
                    pending = _Pending(position.mint, batch_time, "exit", exit_reason)
        if position is None and pending is None:
            decisions, pending = _consider_entries(
                conn,
                batch,
                flags,
                fees,
                sma_open,
                version_id,
                run_id,
                recorded_at,
                decisions,
                reasons,
            )
        mark_snap = by_mint.get(position.mint) if position else None
        if position is None or mark_snap is not None:
            unrealized, equity = _mark(position, mark_snap, cash, realized)
        _ledger(
            conn,
            run_id,
            recorded_at,
            batch_time,
            "mark",
            None if position is None else position.mint,
            cash,
            Decimal("0"),
            Decimal("0"),
            realized,
            unrealized,
            equity,
            "mark",
        )

    if pending is not None:
        decisions += 1
        reason = "no_fill_after_delay"
        reasons[reason] = reasons.get(reason, 0) + 1
        _decision(
            conn,
            version_id,
            run_id,
            pending.mint,
            None,
            pending.signal_time,
            pending.kind,
            reason,
            "no later snapshot at or after the delay",
            recorded_at,
        )
        rejected_orders += 1

    note = _run_note(sma_open, position, opens)
    return PumpRunSummary(
        recorded_at=recorded_at,
        starting_cash=starting_cash,
        ending_equity=equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        opens=opens,
        closes=closes,
        decisions=decisions,
        rejected_orders=rejected_orders,
        rejection_counts=reasons,
        open_position=None if position is None else position.mint,
        sma_open=None if not sma_open else f"{sma_open.get('direction')} {sma_open.get('symbol')}",
        note=note,
    )


def _consider_entries(
    conn: sqlite3.Connection,
    batch: list[sqlite3.Row],
    flags: dict[int, dict[str, str]],
    fees: dict[str, sqlite3.Row],
    sma_open: dict[str, object] | None,
    version_id: int,
    run_id: int,
    recorded_at: datetime,
    decisions: int,
    reasons: dict[str, int],
) -> tuple[int, _Pending | None]:
    passed: list[tuple[Decimal, str, sqlite3.Row]] = []
    for snap in batch:
        reason, note = _entry_block(snap, flags.get(snap["id"], {}), fees.get(snap["collect_id"]))
        if reason is None:
            passed.append((Decimal(str(snap["progress"])), snap["mint"], snap))
            continue
        decisions += 1
        reasons[reason] = reasons.get(reason, 0) + 1
        _decision(conn, version_id, run_id, snap["mint"], snap["id"], parse_timestamp(snap["fetched_at"]), "enter", reason, note, recorded_at)
    if not passed:
        return decisions, None
    passed.sort(key=lambda item: (-item[0], item[1]))
    _progress, mint, winner = passed[0]
    signal_time = parse_timestamp(winner["fetched_at"])
    if sma_open is not None:
        reason = "blocked_by_open_position"
        note = f"filters_passed milestone1_open {sma_open.get('direction')} {sma_open.get('symbol')}"
        decisions += 1
        reasons[reason] = reasons.get(reason, 0) + 1
        _decision(conn, version_id, run_id, mint, winner["id"], signal_time, "enter", reason, note, recorded_at)
        for _progress, other_mint, other in passed[1:]:
            decisions += 1
            reasons["lower_priority_same_timestamp"] = reasons.get("lower_priority_same_timestamp", 0) + 1
            _decision(
                conn,
                version_id,
                run_id,
                other_mint,
                other["id"],
                signal_time,
                "enter",
                "lower_priority_same_timestamp",
                f"winner={mint}",
                recorded_at,
            )
        return decisions, None
    decisions += 1
    _decision(conn, version_id, run_id, mint, winner["id"], signal_time, "enter", None, "filters_passed", recorded_at)
    for _progress, other_mint, other in passed[1:]:
        decisions += 1
        reasons["lower_priority_same_timestamp"] = reasons.get("lower_priority_same_timestamp", 0) + 1
        _decision(
            conn,
            version_id,
            run_id,
            other_mint,
            other["id"],
            signal_time,
            "enter",
            "lower_priority_same_timestamp",
            f"winner={mint}",
            recorded_at,
        )
    return decisions, _Pending(mint, signal_time, "entry")


def _entry_block(
    snap: sqlite3.Row,
    flag_status: dict[str, str],
    fee_row: sqlite3.Row | None,
) -> tuple[str | None, str | None]:
    if _dec(snap["sol_usd"]) is None:
        return "unknown_sol_price", None
    observed_fee = snap["global_fee_basis_points"]
    if observed_fee is None:
        return "unknown_protocol_fee", None
    if int(observed_fee) != PINNED_PROTOCOL_FEE_BPS:
        return "protocol_fee_mismatch", f"observed={observed_fee}"
    status = snap["graduation_status"]
    if status == "graduated" or snap["curve_complete"] == 1:
        return "already_graduated", None
    if status != "on_curve" or snap["curve_complete"] != 0:
        return "unknown_graduation", None
    if snap["quote_is_sol"] is None:
        return "unknown_quote", None
    if snap["quote_is_sol"] != 1:
        return "non_sol_quote", None
    if snap["decimals"] is None:
        return "unknown_decimals", None
    if _int(snap["virtual_token_reserves"]) is None or _int(snap["virtual_quote_reserves"]) is None:
        return "unknown_reserves", None
    if _int(snap["real_token_reserves"]) is None:
        return "unknown_reserves", None
    progress = _dec(snap["progress"])
    if progress is None:
        return "unknown_progress", None
    if progress < MIN_PROGRESS:
        return "progress_below_threshold", format(progress, "f")
    if progress >= MAX_PROGRESS:
        return "progress_above_threshold", format(progress, "f")
    hits = [name for name in BLOCKING_FLAGS if flag_status.get(name) == "true"]
    if hits:
        return f"red_flag:{hits[0]}", ",".join(hits)
    buys = snap["buys_m5"]
    buyers = snap["buyers_m5"]
    sells = snap["sells_m5"]
    if buys is None or buyers is None or sells is None:
        return "unknown_buy_flow", None
    if int(buys) < MIN_BUYS_M5 or int(buyers) < MIN_BUYERS_M5:
        return "buy_flow_below_threshold", f"buys={buys} buyers={buyers}"
    if int(buys) <= int(sells):
        return "buy_flow_not_positive", f"buys={buys} sells={sells}"
    unknown = [name for name in BLOCKING_FLAGS if flag_status.get(name) != "false"]
    if unknown:
        return f"flag_unknown:{unknown[0]}", ",".join(unknown)
    if fee_row is None or fee_row["priority_fee_lamports"] is None:
        return "unknown_network_fee", None
    return None, "creator_fee_bps=30 source=published_schedule"


def _try_entry_fill(
    conn: sqlite3.Connection,
    snap: sqlite3.Row | None,
    pending: _Pending,
    cash: Decimal,
    version_id: int,
    run_id: int,
    recorded_at: datetime,
    rejected_orders: int,
    decisions: int,
    reasons: dict[str, int],
) -> tuple[bool, Decimal, _Position | None, int, int]:
    if snap is None:
        return False, cash, None, rejected_orders, decisions
    reason = _fill_data_reason(snap)
    sol_usd = _dec(snap["sol_usd"])
    fee_row = conn.execute(
        "SELECT * FROM pump_network_fees WHERE collect_id = ?",
        (snap["collect_id"],),
    ).fetchone()
    if reason is None and (fee_row is None or fee_row["priority_fee_lamports"] is None):
        reason = "unknown_network_fee"
    if reason is None and sol_usd is not None:
        spendable = _usd_to_lamports(MAX_NOTIONAL, sol_usd)
        notional = _q_down(Decimal(spendable) / Decimal(1_000_000_000) * sol_usd)
        quote = quote_buy_exact_sol_in(
            virtual_token_reserves=_int(snap["virtual_token_reserves"]) or 0,
            virtual_quote_reserves=_int(snap["virtual_quote_reserves"]) or 0,
            spendable_lamports=spendable,
            protocol_fee_bps=PINNED_PROTOCOL_FEE_BPS,
            creator_fee_bps=PUBLISHED_CREATOR_FEE_BPS,
            real_token_reserves=_int(snap["real_token_reserves"]),
        )
        tokens = apply_buy_slippage(quote.tokens_out, EXTRA_SLIPPAGE_BPS)
        if quote.exceeds_real_reserves:
            reason = "trade_would_complete_curve"
        elif tokens <= 0 or spendable <= 0:
            reason = "no_tokens_after_slippage"
        elif notional > MAX_NOTIONAL:
            reason = "notional_exceeds_limit"
        elif notional < MIN_NOTIONAL:
            reason = "below_min_notional"
        else:
            priority = int(fee_row["priority_fee_lamports"])
            network_lamports = BASE_SIGNATURE_LAMPORTS + priority
            network_usd = q(Decimal(network_lamports) / Decimal(1_000_000_000) * sol_usd)
            if cash < notional + network_usd:
                reason = "insufficient_cash"
            else:
                decimals = int(snap["decimals"])
                token_ui = Decimal(tokens) / (Decimal(10) ** decimals)
                effective = q(notional / token_ui)
                cash = q(cash - notional - network_usd)
                position_id = _insert_position(
                    conn,
                    version_id,
                    run_id,
                    snap["mint"],
                    tokens,
                    token_ui,
                    decimals,
                    notional,
                    network_usd,
                    effective,
                    parse_timestamp(snap["fetched_at"]),
                    recorded_at,
                )
                order_id = _order(conn, version_id, run_id, None, snap["mint"], "open", "filled", notional, None, snap["fetched_at"], recorded_at)
                _fill(
                    conn,
                    order_id,
                    position_id,
                    snap,
                    "open",
                    pending.signal_time,
                    spendable,
                    quote.net_lamports,
                    quote.curve_fee_lamports,
                    tokens,
                    token_ui,
                    effective,
                    notional,
                    priority,
                    network_usd,
                    recorded_at,
                )
                _ledger(
                    conn,
                    run_id,
                    recorded_at,
                    parse_timestamp(snap["fetched_at"]),
                    "open",
                    snap["mint"],
                    cash,
                    q(-(notional + network_usd)),
                    network_usd,
                    Decimal("0"),
                    None,
                    None,
                    SIMULATED_LABEL,
                )
                position = _Position(
                    id=position_id,
                    mint=snap["mint"],
                    tokens_raw=tokens,
                    token_ui=token_ui,
                    decimals=decimals,
                    entry_notional=notional,
                    entry_network=network_usd,
                    entry_effective=effective,
                    opened_at=parse_timestamp(snap["fetched_at"]),
                )
                return True, cash, position, rejected_orders, decisions
    decisions += 1
    rejected_orders += 1
    reasons[reason or "fill_rejected"] = reasons.get(reason or "fill_rejected", 0) + 1
    _decision(conn, version_id, run_id, pending.mint, None if snap is None else snap["id"], pending.signal_time, "enter_fill", reason, SIMULATED_LABEL, recorded_at)
    _order(conn, version_id, run_id, None, pending.mint, "open", "rejected", MAX_NOTIONAL, reason, pending.signal_time.isoformat(), recorded_at)
    return False, cash, None, rejected_orders, decisions


def _try_exit_fill(
    conn: sqlite3.Connection,
    snap: sqlite3.Row | None,
    position: _Position,
    pending: _Pending,
    cash: Decimal,
    realized: Decimal,
    version_id: int,
    run_id: int,
    recorded_at: datetime,
    rejected_orders: int,
    decisions: int,
    reasons: dict[str, int],
) -> tuple[bool, Decimal, Decimal, _Position | None, int, int]:
    reason = None if snap is not None else "no_reserves_at_fill"
    if snap is not None:
        if snap["curve_complete"] == 1 or snap["graduation_status"] == "graduated":
            reason = "graduated_no_curve_quote"
        else:
            reason = _fill_data_reason(snap)
    sol_usd = None if snap is None else _dec(snap["sol_usd"])
    fee_row = None
    if snap is not None:
        fee_row = conn.execute(
            "SELECT * FROM pump_network_fees WHERE collect_id = ?",
            (snap["collect_id"],),
        ).fetchone()
    if reason is None and (fee_row is None or fee_row["priority_fee_lamports"] is None or sol_usd is None):
        reason = "unknown_network_fee"
    if reason is None and snap is not None and sol_usd is not None and fee_row is not None:
        quote = quote_sell_exact_tokens_in(
            virtual_token_reserves=_int(snap["virtual_token_reserves"]) or 0,
            virtual_quote_reserves=_int(snap["virtual_quote_reserves"]) or 0,
            tokens_in=position.tokens_raw,
            protocol_fee_bps=PINNED_PROTOCOL_FEE_BPS,
            creator_fee_bps=PUBLISHED_CREATOR_FEE_BPS,
            slippage_bps=EXTRA_SLIPPAGE_BPS,
        )
        if quote.slipped_lamports <= 0:
            reason = "no_proceeds_at_exit"
        else:
            proceeds = _q_down(Decimal(quote.slipped_lamports) / Decimal(1_000_000_000) * sol_usd)
            priority = int(fee_row["priority_fee_lamports"])
            network_usd = q(Decimal(BASE_SIGNATURE_LAMPORTS + priority) / Decimal(1_000_000_000) * sol_usd)
            if cash + proceeds < network_usd:
                reason = "insufficient_cash"
            else:
                trade_realized = q(proceeds - position.entry_notional - position.entry_network - network_usd)
                realized = q(realized + trade_realized)
                cash = q(cash + proceeds - network_usd)
                effective = q(proceeds / position.token_ui)
                closed_at = parse_timestamp(snap["fetched_at"])
                holding = int((closed_at - position.opened_at).total_seconds())
                conn.execute(
                    """
                    UPDATE pump_positions
                    SET status = 'closed', closed_at = ?, exit_proceeds_usd = ?, exit_network_fee_usd = ?,
                        exit_effective_price_usd = ?, realized_pnl = ?, exit_reason = ?, holding_seconds = ?
                    WHERE id = ?
                    """,
                    (
                        iso_z(closed_at),
                        dec_text(proceeds),
                        dec_text(network_usd),
                        dec_text(effective),
                        dec_text(trade_realized),
                        pending.reason,
                        holding,
                        position.id,
                    ),
                )
                order_id = _order(conn, version_id, run_id, None, position.mint, "close", "filled", proceeds, None, snap["fetched_at"], recorded_at)
                _fill(
                    conn,
                    order_id,
                    position.id,
                    snap,
                    "close",
                    pending.signal_time,
                    quote.gross_lamports,
                    quote.slipped_lamports,
                    quote.protocol_fee_lamports + quote.creator_fee_lamports,
                    position.tokens_raw,
                    position.token_ui,
                    effective,
                    proceeds,
                    priority,
                    network_usd,
                    recorded_at,
                )
                _ledger(
                    conn,
                    run_id,
                    recorded_at,
                    closed_at,
                    "close",
                    position.mint,
                    cash,
                    q(proceeds - network_usd),
                    network_usd,
                    realized,
                    Decimal("0"),
                    cash,
                    f"{SIMULATED_LABEL} exit={pending.reason}",
                )
                return True, cash, realized, None, rejected_orders, decisions
    if reason == "graduated_no_curve_quote":
        position.skip_graduation_retry = True
    decisions += 1
    rejected_orders += 1
    reasons[reason or "fill_rejected"] = reasons.get(reason or "fill_rejected", 0) + 1
    _decision(
        conn,
        version_id,
        run_id,
        position.mint,
        None if snap is None else snap["id"],
        pending.signal_time,
        "exit_fill",
        reason,
        SIMULATED_LABEL,
        recorded_at,
    )
    _order(
        conn,
        version_id,
        run_id,
        None,
        position.mint,
        "close",
        "rejected",
        None,
        reason,
        pending.signal_time.isoformat(),
        recorded_at,
    )
    return False, cash, realized, position, rejected_orders, decisions


def _fill_data_reason(snap: sqlite3.Row) -> str | None:
    if snap["global_fee_basis_points"] is None:
        return "unknown_protocol_fee"
    if int(snap["global_fee_basis_points"]) != PINNED_PROTOCOL_FEE_BPS:
        return "protocol_fee_mismatch"
    if snap["curve_complete"] != 0 or snap["graduation_status"] != "on_curve":
        return "already_graduated"
    if snap["decimals"] is None or _dec(snap["sol_usd"]) is None:
        return "unknown_sol_price" if _dec(snap["sol_usd"]) is None else "unknown_decimals"
    if _int(snap["virtual_token_reserves"]) is None or _int(snap["virtual_quote_reserves"]) is None:
        return "no_reserves_at_fill"
    if (_int(snap["virtual_token_reserves"]) or 0) <= 0 or (_int(snap["virtual_quote_reserves"]) or 0) <= 0:
        return "no_reserves_at_fill"
    return None


def _exit_signal(position: _Position, snap: sqlite3.Row, batch_time: datetime) -> str | None:
    if snap["curve_complete"] == 1 or snap["graduation_status"] == "graduated":
        return "graduated"
    if int((batch_time - position.opened_at).total_seconds()) >= MAX_HOLD_SECONDS:
        return "time_limit"
    sol_usd = _dec(snap["sol_usd"])
    virtual_token = _int(snap["virtual_token_reserves"])
    virtual_quote = _int(snap["virtual_quote_reserves"])
    if sol_usd is None or virtual_token is None or virtual_quote is None or virtual_token <= 0 or virtual_quote <= 0:
        return None
    if snap["curve_complete"] not in {0, None} or snap["global_fee_basis_points"] not in {None, PINNED_PROTOCOL_FEE_BPS}:
        return None
    quote = quote_sell_exact_tokens_in(
        virtual_token_reserves=virtual_token,
        virtual_quote_reserves=virtual_quote,
        tokens_in=position.tokens_raw,
        protocol_fee_bps=PINNED_PROTOCOL_FEE_BPS,
        creator_fee_bps=PUBLISHED_CREATOR_FEE_BPS,
    )
    proceeds = Decimal(quote.slipped_lamports) / Decimal(1_000_000_000) * sol_usd
    if position.entry_notional <= 0:
        return None
    change = (proceeds - position.entry_notional) / position.entry_notional
    if change >= TAKE_PROFIT:
        return "take_profit"
    if change <= -STOP_LOSS:
        return "stop"
    return None


def _mark(
    position: _Position | None,
    snap: sqlite3.Row | None,
    cash: Decimal,
    realized: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    if position is None:
        return Decimal("0"), q(cash)
    if snap is None or snap["curve_complete"] == 1:
        return None, None
    sol_usd = _dec(snap["sol_usd"])
    virtual_token = _int(snap["virtual_token_reserves"])
    virtual_quote = _int(snap["virtual_quote_reserves"])
    if sol_usd is None or not virtual_token or not virtual_quote:
        return None, None
    quote = quote_sell_exact_tokens_in(
        virtual_token_reserves=virtual_token,
        virtual_quote_reserves=virtual_quote,
        tokens_in=position.tokens_raw,
        protocol_fee_bps=PINNED_PROTOCOL_FEE_BPS,
        creator_fee_bps=PUBLISHED_CREATOR_FEE_BPS,
    )
    proceeds = Decimal(quote.slipped_lamports) / Decimal(1_000_000_000) * sol_usd
    unrealized = q(proceeds - position.entry_notional - position.entry_network)
    equity = q(cash + proceeds)
    return unrealized, equity


def _inherited_spendable(conn: sqlite3.Connection) -> tuple[Decimal, dict[str, object]]:
    ledger = conn.execute("SELECT * FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    open_row = conn.execute(
        """
        SELECT symbol, direction, status, entry_notional, opened_at
        FROM positions WHERE status = 'open' ORDER BY id LIMIT 1
        """
    ).fetchone()
    sma_open = None if open_row is None else dict(open_row)
    if ledger is None:
        return STARTING_CASH, {"source": "starting_cash", "sma_open": sma_open}
    return Decimal(ledger["cash_free"]), {
        "source": "sma_ledger.cash_free",
        "ledger_id": ledger["id"],
        "cash_free": ledger["cash_free"],
        "locked_notional": ledger["locked_notional"],
        "equity": ledger["equity"],
        "sma_open": sma_open,
    }


def _run_note(sma_open: dict[str, object] | None, position: _Position | None, opens: int) -> str:
    parts = [SIMULATED_LABEL]
    if sma_open:
        parts.append(
            "milestone-1 position is open "
            f"({sma_open.get('direction')} {sma_open.get('symbol')}); "
            "pump entries that pass filters are rejected blocked_by_open_position. "
            "Pump spendable cash is the SMA ledger cash_free and is not combined account equity."
        )
    elif opens == 0:
        parts.append("no pump.fun fill. Spendable cash is unchanged.")
    if position is not None:
        parts.append(f"open simulated pump.fun long {position.mint}")
    return " ".join(parts)


def _load_flags(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    found: dict[int, dict[str, str]] = {}
    for row in conn.execute("SELECT snapshot_id, flag, status FROM pump_flags").fetchall():
        found.setdefault(int(row["snapshot_id"]), {})[row["flag"]] = row["status"]
    return found


def _insert_run(conn: sqlite3.Connection, version_id: int, recorded_at: datetime, starting_cash: Decimal, inherited: dict[str, object]) -> int:
    conn.execute(
        """
        INSERT INTO pump_simulation_runs (
            strategy_version_id, recorded_at, parameters_json, starting_cash,
            ending_equity, realized_pnl, unrealized_pnl, note, sma_open_json, inherited_cash_json
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
        """,
        (
            version_id,
            iso_z(recorded_at),
            parameters_json(),
            dec_text(starting_cash),
            "pending",
            json.dumps(inherited.get("sma_open")),
            json.dumps({key: value for key, value in inherited.items() if key != "sma_open"}),
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def _decision(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    mint: str,
    snapshot_id: int | None,
    signal_time: datetime,
    action: str,
    reason: str | None,
    note: str | None,
    recorded_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO pump_decisions (
            strategy_version_id, simulation_run_id, market, mint, snapshot_id,
            signal_time, action, rejection_reason, note, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            run_id,
            PUMP_MARKET,
            mint,
            snapshot_id,
            iso_z(signal_time),
            action,
            reason,
            note,
            iso_z(recorded_at),
        ),
    )


def _order(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    decision_id: int | None,
    mint: str,
    intent: str,
    status: str,
    requested: Decimal | None,
    reason: str | None,
    simulated_at: str,
    recorded_at: datetime,
) -> int:
    conn.execute(
        """
        INSERT INTO pump_orders (
            strategy_version_id, simulation_run_id, decision_id, market, mint, intent,
            status, requested_notional, rejection_reason, simulated_at, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            run_id,
            decision_id,
            PUMP_MARKET,
            mint,
            intent,
            status,
            dec_text(requested) if isinstance(requested, Decimal) else requested,
            reason,
            simulated_at,
            iso_z(recorded_at),
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def _insert_position(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    mint: str,
    tokens: int,
    token_ui: Decimal,
    decimals: int,
    notional: Decimal,
    network: Decimal,
    effective: Decimal,
    opened_at: datetime,
    recorded_at: datetime,
) -> int:
    conn.execute(
        """
        INSERT INTO pump_positions (
            strategy_version_id, simulation_run_id, market, mint, status, tokens_raw, token_ui,
            decimals, entry_notional_usd, entry_network_fee_usd, entry_effective_price_usd,
            opened_at, recorded_at
        ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            run_id,
            PUMP_MARKET,
            mint,
            str(tokens),
            format(token_ui, "f"),
            decimals,
            dec_text(notional),
            dec_text(network),
            dec_text(effective),
            iso_z(opened_at),
            iso_z(recorded_at),
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def _fill(
    conn: sqlite3.Connection,
    order_id: int,
    position_id: int,
    snap: sqlite3.Row,
    intent: str,
    signal_time: datetime,
    spendable_lamports: int,
    net_lamports: int,
    curve_fee_lamports: int,
    tokens: int,
    token_ui: Decimal,
    effective: Decimal,
    notional: Decimal,
    priority_lamports: int,
    network_usd: Decimal,
    recorded_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO pump_fills (
            order_id, position_id, market, mint, intent, signal_time, fill_time,
            execution_delay_seconds, virtual_token_reserves, virtual_quote_reserves,
            spendable_lamports, net_quote_lamports, curve_fee_lamports, tokens_raw, token_ui,
            effective_price_usd, notional_usd, extra_slippage_bps, solana_base_lamports,
            solana_priority_lamports, network_fee_usd, sol_usd, sol_usd_source,
            protocol_fee_bps, creator_fee_bps, simulated_label, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            position_id,
            PUMP_MARKET,
            snap["mint"],
            intent,
            iso_z(signal_time),
            snap["fetched_at"],
            EXECUTION_DELAY_SECONDS,
            snap["virtual_token_reserves"],
            snap["virtual_quote_reserves"],
            str(spendable_lamports),
            str(net_lamports),
            str(curve_fee_lamports),
            str(tokens),
            format(token_ui, "f"),
            dec_text(effective),
            dec_text(notional),
            str(EXTRA_SLIPPAGE_BPS),
            BASE_SIGNATURE_LAMPORTS,
            str(priority_lamports),
            dec_text(network_usd),
            snap["sol_usd"],
            snap["sol_usd_source"],
            PINNED_PROTOCOL_FEE_BPS,
            PUBLISHED_CREATOR_FEE_BPS,
            SIMULATED_LABEL,
            iso_z(recorded_at),
        ),
    )


def _ledger(
    conn: sqlite3.Connection,
    run_id: int,
    recorded_at: datetime,
    simulated_at: datetime,
    event: str,
    mint: str | None,
    cash: Decimal,
    cash_delta: Decimal,
    network: Decimal,
    realized: Decimal,
    unrealized: Decimal | None,
    equity: Decimal | None,
    note: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pump_ledger (
            simulation_run_id, simulated_at, recorded_at, event, market, mint, cash, cash_delta,
            network_fee_usd, realized_pnl, unrealized_pnl, equity, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            iso_z(simulated_at),
            iso_z(recorded_at),
            event,
            PUMP_MARKET,
            mint,
            dec_text(cash),
            dec_text(cash_delta),
            dec_text(network),
            dec_text(realized),
            dec_text(unrealized),
            dec_text(equity),
            note,
        ),
    )


def _usd_to_lamports(usd: Decimal, sol_usd: Decimal) -> int:
    lamports = (usd / sol_usd) * Decimal(1_000_000_000)
    return int(lamports.to_integral_value(rounding=ROUND_DOWN))


def _q_down(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_DOWN)


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))
