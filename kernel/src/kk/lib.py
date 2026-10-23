"""Provider library: what every service provider shares. Depends on psycopg only.

  conn = connect("kkm_example")                 # DATABASE_URL, then SET ROLE to the provider's own role
  listen(conn, step)                            # before the commit: step(conn) on start, on each NOTIFY, every sweep
  follow(conn, step)                            # after the commit: step(conn) on start and when the change feed moves
  with run(cur, MODULE) as (run_id, outputs):   # a recorded run; failed if the block raises
      submit(cur, change_set, run_id)           # the only way a provider writes (api.submit_change_set)

With OpenTelemetry configured (kk.telemetry: the standard OTEL_EXPORTER_OTLP_* variables), `follow` reports
each consumer's feed lag and step time, which is how Morphogen observes its own providers (R5-20).

The kernel enforces everything (roles, scopes, lanes); this library only removes the boilerplate.
Ported from rebuild 4 kk/lib.py. Changed: `follow` (R5-04) wakes feed consumers from the change feed
(api.feed) instead of NOTIFY; trigger patterns (D-79) and the ingest filter are not ported yet.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from kk.telemetry import metrics

CHANNEL = "kernel_change_set"


def connect(role: Optional[str] = None, url: Optional[str] = None) -> psycopg.Connection:
    """An autocommit connection from DATABASE_URL; SET ROLE to `role` when given (needs a login that
    may switch to it, e.g. kk_authenticator; without a role the login acts as itself)."""
    conn = psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True)
    if role:
        conn.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
    return conn


def sweep_seconds(sweep: Optional[float]) -> float:
    return sweep if sweep is not None else float(os.environ.get("KK_SWEEP_SECONDS", "30"))


def listen(conn: psycopg.Connection, step: Callable[[psycopg.Connection], object],
           wake: Optional[Callable[[str], bool]] = None, sweep: Optional[float] = None,
           channel: str = CHANNEL) -> None:
    """For hooks before the commit (validators), which act on submitted change sets the feed never
    carries. Run step(conn) now, then again whenever a notification on `channel` passes `wake` (any, by
    default), and at least every `sweep` seconds (KK_SWEEP_SECONDS, default 30): NOTIFY is not durable."""
    sweep = sweep_seconds(sweep)
    conn.execute(sql.SQL("listen {}").format(sql.Identifier(channel)))
    while True:
        step(conn)
        deadline = time.monotonic() + sweep
        while (left := deadline - time.monotonic()) > 0:
            # One notification at a time, the generator closed before wake() runs (LESSONS: notifies()).
            got = list(conn.notifies(timeout=left, stop_after=1))
            if not got or wake is None or wake(got[0].payload):
                break


def feed_head(conn: psycopg.Connection) -> int:
    """The last feed number this connection's role can see (0 when the feed is empty to it). Reads
    kernel.feed itself (granted to agents, under the same row-level security as api.feed): api.feed would
    assemble every entry's claims just to find the last number."""
    return conn.execute("select coalesce(max(seq), 0) from kernel.feed").fetchone()[0]


def feed_after(conn: psycopg.Connection, cursor: int, limit: int = 1000) -> list[dict]:
    """Applied change sets and redactions after `cursor`, in commit order, within the role's clearance
    (api.feed)."""
    cur = conn.execute("select seq, kind, change_set_id, scope, applied_at, claim_ids, predicates, "
                       "target_kind, target_id from api.feed(%s, %s)", (cursor, limit))
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def follow(conn: psycopg.Connection, step: Callable[[psycopg.Connection], object],
           wake: Optional[Callable[[dict], bool]] = None, poll: Optional[float] = None,
           sweep: Optional[float] = None, once: bool = False, channels: tuple[str, ...] = ()) -> None:
    """For consumers after the commit (R5-04). Run step(conn) now, then again whenever the change feed has
    an entry after the cursor (an applied change set or a redaction, R5-O3) that passes `wake` (any, by
    default), and at least every `sweep` seconds. A
    consumer woken by its own change set runs a step that finds nothing new and submits nothing, which
    ends the round. The feed is read every `poll` seconds; nothing is
    missed while the consumer is down, since each step re-reads the record from its own watermark.
    `channels` also wake it on NOTIFY between polls (e.g. kernel_redaction); the feed alone misses nothing.
    `poll` defaults to KK_POLL_SECONDS (default 1). With OpenTelemetry configured (kk.telemetry) it
    reports kk.feed.lag, the seconds from an entry's commit to this consumer reading it, and
    kk.step.duration."""
    sweep = sweep_seconds(sweep)
    poll = poll if poll is not None else float(os.environ.get("KK_POLL_SECONDS", "1"))
    m = metrics(conn.execute("select current_user").fetchone()[0])
    for channel in channels:
        conn.execute(sql.SQL("listen {}").format(sql.Identifier(channel)))
    cursor = feed_head(conn)
    while True:
        started = time.monotonic()
        step(conn)
        m.record("kk.step.duration", time.monotonic() - started, "s")
        if once:
            return
        deadline = time.monotonic() + sweep
        while time.monotonic() < deadline:
            entries = feed_after(conn, cursor)
            if entries:
                cursor = entries[-1]["seq"]
                now = datetime.now(timezone.utc)
                for e in entries:
                    m.record("kk.feed.lag", max(0.0, (now - e["applied_at"]).total_seconds()), "s")
                if wake is None or any(wake(e) for e in entries):
                    break
                continue
            if channels:
                if list(conn.notifies(timeout=poll, stop_after=1)):
                    break
            else:
                time.sleep(poll)


def my_agent(conn: psycopg.Connection) -> str:
    return conn.execute("select kernel.my_agent()").fetchone()[0]


@contextmanager
def run(cur, module: str, params: Optional[dict] = None, plan_step: Optional[str] = None,
        used: Optional[list] = None) -> Iterator[tuple[str, dict]]:
    """A run of `module` (prov:Activity), optionally carrying out `plan_step` (p-plan:correspondsToStep)
    and using `used` (prov:used: claim ids, artifacts, entities). Fill `outputs`; the run finishes
    succeeded, or failed if the block raises."""
    cur.execute("select api.start_run(%s, %s, %s, %s)", (module, plan_step, Jsonb(used or []), Jsonb(params or {})))
    run_id = str(cur.fetchone()[0])
    outputs: dict = {}
    try:
        yield run_id, outputs
    except Exception:
        cur.execute("select api.finish_run(%s, 'failed', %s)", (run_id, Jsonb(outputs)))
        raise
    cur.execute("select api.finish_run(%s, 'succeeded', %s)", (run_id, Jsonb(outputs)))


def submit(cur, change_set: dict, run_id: str) -> dict:
    """Submit one change set generated by `run_id`; returns the kernel's answer (id, status, ...)."""
    cur.execute("select api.submit_change_set(%s)", (Jsonb({**change_set, "generated_by": run_id}),))
    return cur.fetchone()[0]
