"""Idempotent paper-job gate.

Redundant crons exist because GitHub drops the busy minute. A second start
inside the window records nothing and must not replay. Only a completed run
closes the window, so a failed attempt leaves the backup free to try.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sollab.timeutil import iso_z, parse_timestamp

HOURLY_JOB = "hourly"
PUMP_JOB = "pumpfun"
JOBS = (HOURLY_JOB, PUMP_JOB)

# Longer than the backup offset (30 minutes) and shorter than the next real slot.
HOURLY_WINDOW = timedelta(minutes=50)
PUMP_WINDOW = timedelta(minutes=90)
WINDOWS = {HOURLY_JOB: HOURLY_WINDOW, PUMP_JOB: PUMP_WINDOW}

GAP_LIMIT = timedelta(hours=2)
GAP_LOOKBACK = timedelta(hours=24)
HOUR = Decimal(3600)


class UnknownJob(ValueError):
    """The caller named a job this lab does not schedule."""


def record_job_run(conn: sqlite3.Connection, job: str, recorded_at: datetime) -> None:
    """Store one completed paper run. A skip does not call this."""
    name = _job(job)
    with conn:
        conn.execute(
            "INSERT INTO job_runs (job, recorded_at) VALUES (?, ?)",
            (name, iso_z(recorded_at)),
        )


def decide(conn: sqlite3.Connection, job: str, now: datetime) -> str:
    """Return ``run`` or ``skip``. ``skip`` means this window already completed."""
    name = _job(job)
    moment = _utc(now)
    last = latest_job_run(conn, name)
    if last is None or moment < last:
        return "run"
    if moment - last < WINDOWS[name]:
        return "skip"
    return "run"


def latest_job_run(conn: sqlite3.Connection, job: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT recorded_at FROM job_runs
        WHERE job = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        """,
        (_job(job),),
    ).fetchone()
    if row is None:
        return None
    return parse_timestamp(row["recorded_at"])


def recent_job_runs(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    lookback: timedelta = GAP_LOOKBACK,
) -> list[dict[str, str]]:
    moment = _utc(now)
    start = iso_z(moment - lookback)
    return [
        {"job": str(row["job"]), "recorded_at": str(row["recorded_at"])}
        for row in conn.execute(
            """
            SELECT job, recorded_at FROM job_runs
            WHERE recorded_at >= ? AND recorded_at <= ?
            ORDER BY recorded_at, id
            """,
            (start, iso_z(moment)),
        ).fetchall()
    ]


def collection_gaps(
    times: list[datetime],
    now: datetime,
    *,
    job: str,
    lookback: timedelta = GAP_LOOKBACK,
    limit: timedelta = GAP_LIMIT,
) -> list[dict[str, str]]:
    """Intervals inside the lookback whose silence is longer than ``limit``.

    A gap of exactly two hours is not listed. The pump slot is two hours apart,
    and that cadence is not a hole.
    """
    moment = _utc(now)
    window_start = moment - lookback
    ordered = sorted(_utc(item) for item in times if _utc(item) <= moment)
    prior = [item for item in ordered if item < window_start]
    inside = [item for item in ordered if item >= window_start]
    left_edge = prior[-1] if prior else window_start
    found: list[dict[str, str]] = []
    for left, right in zip([left_edge, *inside], [*inside, moment]):
        overlap_left = max(left, window_start)
        overlap_right = min(right, moment)
        if overlap_right - overlap_left <= limit:
            continue
        seconds = Decimal(str((overlap_right - overlap_left).total_seconds()))
        hours = (seconds / HOUR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        found.append(
            {
                "job": job,
                "from": iso_z(overlap_left),
                "to": iso_z(overlap_right),
                "hours": format(hours, "f"),
            }
        )
    return found


def gaps_for_connection(conn: sqlite3.Connection, now: datetime) -> list[dict[str, str]]:
    moment = _utc(now)
    found: list[dict[str, str]] = []
    for job in JOBS:
        times = [
            parse_timestamp(row["recorded_at"])
            for row in conn.execute(
                "SELECT recorded_at FROM job_runs WHERE job = ? ORDER BY recorded_at, id",
                (job,),
            ).fetchall()
        ]
        found.extend(collection_gaps(times, moment, job=job))
    return found


def _job(job: str) -> str:
    if job not in WINDOWS:
        raise UnknownJob(job)
    return job


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
