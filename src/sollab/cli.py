"""Command line entry points. Read-only collection and local paper simulation."""

from __future__ import annotations

import argparse
import logging
import time

from sollab.collect import collect
from sollab.constants import DISCLAIMER
from sollab.metalscollect import collect_metals
from sollab.metalsstrategy import NoMetalsData, run_metals
from sollab.pumpcollect import collect_pumpfun
from sollab.pumpstrategy import NoPumpData, run_pump_strategy
from sollab.reporting import (
    export_tables,
    render_report,
    write_price_sample,
    write_pump_sample,
    write_simulation_summary,
)
from sollab.status import build_status, write_status
from sollab.simulate import NoCandleData, run_strategy
from sollab.storage import connect


def configure_logging() -> None:
    logger = logging.getLogger("sollab")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s %(message)s")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sollab", description=DISCLAIMER)
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--db", default="data/sollab.db", help="SQLite path. Created if missing.")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect", parents=[parent], help="Fetch public BTC and SOL prices")
    collect_parser.add_argument(
        "--pause",
        type=float,
        default=0.25,
        help="Seconds to wait between public API calls",
    )

    sub.add_parser("run-strategy", parents=[parent], help="Replay the hourly SMA paper strategy")

    pump_collect = sub.add_parser(
        "pumpfun-collect",
        parents=[parent],
        help="Fetch public pump.fun pool and account data. No wallet and no orders.",
    )
    pump_collect.add_argument("--pause", type=float, default=0.5, help="Seconds between read-only calls")
    pump_collect.add_argument("--polls", type=int, default=1, help="How many read-only polls to store")
    pump_collect.add_argument(
        "--interval",
        type=float,
        default=35,
        help="Seconds between polls when --polls is greater than 1",
    )

    sub.add_parser(
        "pumpfun-run",
        parents=[parent],
        help="Paper-trade bonding_curve_momentum on stored pump.fun snapshots",
    )

    metals_collect = sub.add_parser(
        "metals-collect",
        parents=[parent],
        help="Fetch public PAXG, XAUT, ETF, and futures bars. No orders.",
    )
    metals_collect.add_argument("--pause", type=float, default=0.25, help="Seconds between read-only calls")
    sub.add_parser(
        "metals-run",
        parents=[parent],
        help="Paper-trade the metals baselines on stored daily bars",
    )

    report_parser = sub.add_parser("report", parents=[parent], help="Show stored prices and the paper ledger")
    report_parser.add_argument("--export-dir", default="data/exports", help="Directory for full CSV and JSON tables")
    report_parser.add_argument("--sample-json", help="Write a small labeled price sample as JSON")
    report_parser.add_argument("--sample-csv", help="Write a small labeled price sample as CSV")
    report_parser.add_argument(
        "--sample-label",
        default="STORED_PRICE_SAMPLE",
        help="Label stored on the price sample. Use a real-fetch label only after collect.",
    )
    report_parser.add_argument(
        "--simulation-summary",
        help="Write the paper replay summary. The file is labeled as simulated.",
    )
    report_parser.add_argument("--pump-sample-json", help="Write a small labeled pump.fun snapshot sample as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    conn = connect(args.db)
    try:
        if args.command == "collect":
            summary = collect(conn, pause_seconds=args.pause)
            print(DISCLAIMER)
            print(
                f"inserted={summary.inserted} skipped_duplicates={summary.skipped} "
                f"sources={','.join(summary.sources_used) or 'none'}"
            )
            for symbol, count in summary.fetched_by_symbol.items():
                print(f"fetched {symbol} points={count}")
            for error in summary.errors:
                print(f"error {error}")
            return 0 if summary.ok() else 1
        if args.command == "run-strategy":
            try:
                summary = run_strategy(conn)
            except NoCandleData as exc:
                print(str(exc))
                return 1
            print(DISCLAIMER)
            print("paper replay only; no orders were sent")
            print(f"recorded_at={summary.recorded_at.isoformat()}")
            print(f"sources={summary.sources}")
            print(f"candle_counts={summary.candle_counts}")
            print(
                f"opens={summary.opens} closes={summary.closes} "
                f"rejected_orders={summary.rejected_orders} decisions={summary.decisions}"
            )
            print(
                f"period={summary.period} ending_equity={summary.ending_equity} "
                f"realized_pnl={summary.realized_pnl} "
                f"unrealized_pnl={summary.unrealized_pnl} open_position={summary.open_position}"
            )
            for period in summary.periods:
                print(
                    f"period={period.period} opens={period.opens} closes={period.closes} "
                    f"ending_equity={period.ending_equity} realized_pnl={period.realized_pnl} "
                    f"unrealized_pnl={period.unrealized_pnl} open_position={period.open_position}"
                )
            for reason, count in sorted(summary.rejection_counts.items()):
                print(f"rejection {reason}={count}")
            for warning in summary.warnings:
                print(f"warning {warning}")
            return 0
        if args.command == "pumpfun-collect":
            summary = collect_pumpfun(
                conn,
                polls=args.polls,
                interval_seconds=args.interval,
                pause_seconds=args.pause,
            )
            print(DISCLAIMER)
            print("read-only pump.fun collection; no wallet, no transaction, no token creation")
            print(
                f"polls={summary.polls} snapshots={summary.snapshots} "
                f"sources={','.join(summary.sources_used) or 'none'}"
            )
            for error in summary.errors:
                print(f"error {error}")
            return 0 if summary.ok() else 1
        if args.command == "pumpfun-run":
            try:
                summary = run_pump_strategy(conn)
            except NoPumpData as exc:
                print(str(exc))
                return 1
            print(DISCLAIMER)
            print("simulated pump.fun paper replay only; no orders were sent")
            print(f"recorded_at={summary.recorded_at.isoformat()}")
            print(f"starting_spendable_cash={summary.starting_cash}")
            print(
                f"opens={summary.opens} closes={summary.closes} "
                f"rejected_orders={summary.rejected_orders} decisions={summary.decisions}"
            )
            print(
                f"pump_ending_equity={summary.ending_equity} realized_pnl={summary.realized_pnl} "
                f"unrealized_pnl={summary.unrealized_pnl} open_position={summary.open_position}"
            )
            print(f"sma_open={summary.sma_open}")
            print(f"note={summary.note}")
            for reason, count in sorted(summary.rejection_counts.items()):
                print(f"rejection {reason}={count}")
            return 0
        if args.command == "metals-collect":
            summary = collect_metals(conn, pause_seconds=args.pause)
            print(DISCLAIMER)
            print("read-only metals collection; no orders were sent")
            print(
                f"inserted={summary.inserted} skipped_duplicates={summary.skipped} "
                f"sources={','.join(summary.sources_used) or 'none'}"
            )
            for symbol, count in sorted(summary.fetched_by_symbol.items()):
                print(f"fetched {symbol} points={count}")
            for error in summary.errors:
                print(f"error {error}")
            return 0 if summary.ok() else 1
        if args.command == "metals-run":
            try:
                summary = run_metals(conn)
            except NoMetalsData as exc:
                print(str(exc))
                return 1
            print(DISCLAIMER)
            print("simulated metals paper replay only; no orders were sent")
            print(f"recorded_at={summary.recorded_at.isoformat()}")
            print(f"paxg_bars={summary.paxg_bars} silver_bars={summary.silver_bars}")
            for period in summary.periods:
                print(
                    f"strategy={period.strategy_id} period={period.period} "
                    f"ending_equity={period.ending_equity} realized_pnl={period.realized_pnl} "
                    f"unrealized_pnl={period.unrealized_pnl} benchmark_equity={period.benchmark_equity} "
                    f"open_position={period.open_position} opens={period.opens} closes={period.closes}"
                )
            for warning in summary.warnings:
                print(f"warning {warning}")
            return 0
        status = build_status(conn)
        status_path = write_status(conn, args.export_dir, status=status)
        export_tables(conn, args.export_dir)
        if args.sample_json or args.sample_csv:
            write_price_sample(
                conn,
                json_path=args.sample_json,
                csv_path=args.sample_csv,
                label=args.sample_label,
            )
        if args.simulation_summary:
            write_simulation_summary(conn, args.simulation_summary)
        if args.pump_sample_json:
            write_pump_sample(conn, args.pump_sample_json)
        print(render_report(conn, status))
        print(f"status_json={status_path}")
        print(f"exported_tables={args.export_dir}")
        return 0
    finally:
        conn.close()
