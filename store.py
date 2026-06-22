"""
SQLite persistence layer.

Tables:
  daily_prices(index_name, date, close)         source of truth (weekly is derived)
  history_weekly(index_name, week_ending, close, crossed, score_label)
  prev_scores(index_name, crossed, as_of)       previous run's score, for "entered today"
  snapshot(as_of, generated_at, payload_json)   the latest dashboard snapshot
  meta(key, value)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pandas as pd

import config


@contextmanager
def conn():
    c = sqlite3.connect(config.db_path())
    try:
        c.execute("PRAGMA journal_mode=WAL;")
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_prices(
                index_name TEXT NOT NULL,
                date       TEXT NOT NULL,
                close      REAL NOT NULL,
                PRIMARY KEY (index_name, date)
            );
            CREATE TABLE IF NOT EXISTS history_weekly(
                index_name  TEXT NOT NULL,
                week_ending TEXT NOT NULL,
                close       REAL NOT NULL,
                crossed     INTEGER NOT NULL,
                score_label TEXT NOT NULL,
                PRIMARY KEY (index_name, week_ending)
            );
            CREATE TABLE IF NOT EXISTS prev_scores(
                index_name TEXT PRIMARY KEY,
                crossed    INTEGER,
                as_of      TEXT
            );
            CREATE TABLE IF NOT EXISTS snapshot(
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                as_of        TEXT,
                generated_at TEXT,
                payload_json TEXT
            );
            CREATE TABLE IF NOT EXISTS meta(
                key TEXT PRIMARY KEY, value TEXT
            );
            """
        )


def reset():
    """Drop every table and recreate them empty — for a guaranteed clean rebuild."""
    with conn() as c:
        for t in ("daily_prices", "history_weekly", "prev_scores", "snapshot", "meta"):
            c.execute(f"DROP TABLE IF EXISTS {t}")
    init()


# ---- daily prices ---------------------------------------------------------
def upsert_daily(index_name: str, series: pd.Series):
    if series is None or len(series) == 0:
        return
    rows = [(index_name, pd.Timestamp(d).strftime("%Y-%m-%d"), float(v))
            for d, v in series.dropna().items()]
    with conn() as c:
        c.executemany(
            "INSERT INTO daily_prices(index_name, date, close) VALUES (?,?,?) "
            "ON CONFLICT(index_name, date) DO UPDATE SET close=excluded.close",
            rows,
        )


def load_daily(index_name: str) -> pd.Series:
    with conn() as c:
        df = pd.read_sql_query(
            "SELECT date, close FROM daily_prices WHERE index_name=? ORDER BY date",
            c, params=(index_name,),
        )
    if df.empty:
        return pd.Series(dtype="float64")
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
    s.name = index_name
    return s


def latest_daily_date(index_name: str):
    with conn() as c:
        row = c.execute(
            "SELECT MAX(date) FROM daily_prices WHERE index_name=?", (index_name,)
        ).fetchone()
    return row[0] if row else None


# ---- weekly archive -------------------------------------------------------
def write_archive(index_name: str, arch_df: pd.DataFrame):
    if arch_df is None or arch_df.empty:
        return
    rows = [(index_name, pd.Timestamp(idx).strftime("%Y-%m-%d"),
             float(r["close"]), int(r["crossed"]), str(r["score_label"]))
            for idx, r in arch_df.iterrows()]
    with conn() as c:
        c.executemany(
            "INSERT INTO history_weekly(index_name, week_ending, close, crossed, score_label) "
            "VALUES (?,?,?,?,?) ON CONFLICT(index_name, week_ending) DO UPDATE SET "
            "close=excluded.close, crossed=excluded.crossed, score_label=excluded.score_label",
            rows,
        )


def load_archive(index_name: str, limit: int | None = None) -> list[dict]:
    q = ("SELECT week_ending, close, crossed, score_label FROM history_weekly "
         "WHERE index_name=? ORDER BY week_ending DESC")
    if limit:
        q += f" LIMIT {int(limit)}"
    with conn() as c:
        df = pd.read_sql_query(q, c, params=(index_name,))
    return df.to_dict("records")


# ---- previous scores ------------------------------------------------------
def load_prev_scores() -> dict:
    with conn() as c:
        df = pd.read_sql_query("SELECT index_name, crossed FROM prev_scores", c)
    return {r.index_name: (int(r.crossed) if r.crossed is not None else None)
            for r in df.itertuples()}


def save_prev_scores(crossed_map: dict, as_of: str):
    rows = [(k, (int(v) if v is not None else None), as_of) for k, v in crossed_map.items()]
    with conn() as c:
        c.executemany(
            "INSERT INTO prev_scores(index_name, crossed, as_of) VALUES (?,?,?) "
            "ON CONFLICT(index_name) DO UPDATE SET crossed=excluded.crossed, as_of=excluded.as_of",
            rows,
        )


# ---- snapshot -------------------------------------------------------------
def save_snapshot(payload: dict):
    with conn() as c:
        c.execute(
            "INSERT INTO snapshot(id, as_of, generated_at, payload_json) VALUES (1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET as_of=excluded.as_of, "
            "generated_at=excluded.generated_at, payload_json=excluded.payload_json",
            (payload.get("as_of"), payload.get("generated_at"), json.dumps(payload)),
        )


def load_snapshot() -> dict | None:
    with conn() as c:
        row = c.execute("SELECT payload_json FROM snapshot WHERE id=1").fetchone()
    return json.loads(row[0]) if row and row[0] else None
