"""Command line entry points. Read-only collection and local paper simulation."""

from __future__ import annotations

import argparse
import logging
import time

from sollab.collect import collect
from sollab.constants import DISCLAIMER
from sollab.reporting import export_tables, render_report, write_price_sample, write_simulation_summary
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
                f"ending_equity={summary.ending_equity} realized_pnl={summary.realized_pnl} "
                f"unrealized_pnl={summary.unrealized_pnl} open_position={summary.open_position}"
            )
            for reason, count in sorted(summary.rejection_counts.items()):
                print(f"rejection {reason}={count}")
            for warning in summary.warnings:
                print(f"warning {warning}")
            return 0
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
        print(render_report(conn))
        print(f"exported_tables={args.export_dir}")
        return 0
    finally:
        conn.close()
