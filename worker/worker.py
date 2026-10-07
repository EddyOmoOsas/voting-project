"""Vote worker.

Pops votes from the Redis list "votes", upserts them into PostgreSQL
(one row per voter, so changing your vote replaces the old one), then
refreshes the tallies in the Redis hash "results" for the API to serve.
"""
import json
import logging
import os
import time

import psycopg2
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

CHOICES = {"cats", "dogs"}
QUEUE = "votes"
RESULTS_KEY = "results"

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
DATABASE_URL = os.environ["DATABASE_URL"]


def connect_redis():
    while True:
        try:
            client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
            client.ping()
            log.info("Connected to Redis at %s", REDIS_HOST)
            return client
        except redis.RedisError as exc:
            log.warning("Redis not ready (%s), retrying in 2s", exc)
            time.sleep(2)


def connect_db():
    while True:
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS votes (
                        voter_id   TEXT PRIMARY KEY,
                        choice     TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            log.info("Connected to PostgreSQL")
            return conn
        except psycopg2.Error as exc:
            log.warning("Database not ready (%s), retrying in 3s", exc)
            time.sleep(3)


def refresh_results(conn, r):
    """Rebuild the tallies in Redis from the source of truth (Postgres)."""
    with conn.cursor() as cur:
        cur.execute("SELECT choice, COUNT(*) FROM votes GROUP BY choice")
        counts = {choice: int(n) for choice, n in cur.fetchall()}
    pipe = r.pipeline()
    pipe.delete(RESULTS_KEY)
    if counts:
        pipe.hset(RESULTS_KEY, mapping=counts)
    pipe.execute()


def save_vote(conn, voter_id, choice):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO votes (voter_id, choice) VALUES (%s, %s)
            ON CONFLICT (voter_id)
            DO UPDATE SET choice = EXCLUDED.choice, updated_at = now()
            """,
            (voter_id, choice),
        )


def main():
    r = connect_redis()
    conn = connect_db()
    refresh_results(conn, r)  # rebuild tallies after a Redis restart

    while True:
        try:
            item = r.blpop(QUEUE, timeout=5)
            if item is None:
                continue
            raw = item[1]

            try:
                vote = json.loads(raw)
                voter_id, choice = str(vote["voter_id"]), str(vote["choice"])
                if choice not in CHOICES:
                    raise ValueError(f"bad choice {choice!r}")
            except (ValueError, KeyError, TypeError) as exc:
                log.warning("Dropping malformed vote %r: %s", raw, exc)
                continue

            try:
                save_vote(conn, voter_id, choice)
                refresh_results(conn, r)
                log.info("Saved vote: %s -> %s", voter_id, choice)
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                log.exception("Database connection lost, requeueing vote")
                r.lpush(QUEUE, raw)  # put it back at the front
                conn = connect_db()

        except redis.RedisError:
            log.exception("Redis error, reconnecting")
            r = connect_redis()


if __name__ == "__main__":
    main()
