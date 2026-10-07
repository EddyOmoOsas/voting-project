"""Voting API.

POST /vote     -> pushes a vote onto the Redis queue (the worker saves it to Postgres)
GET  /results  -> reads the vote tallies the worker keeps in Redis
GET  /health   -> liveness check
"""
import json
import os

import redis
from flask import Flask, jsonify, request

app = Flask(__name__)

CHOICES = ("cats", "dogs")
QUEUE = "votes"
RESULTS_KEY = "results"

r = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)


@app.get("/health")
def health():
    try:
        r.ping()
        return jsonify(status="ok")
    except redis.RedisError:
        return jsonify(status="redis unavailable"), 503


@app.post("/vote")
def vote():
    data = request.get_json(silent=True) or {}
    voter_id = str(data.get("voter_id", "")).strip()[:64]
    choice = str(data.get("choice", "")).strip().lower()

    if not voter_id:
        return jsonify(error="voter_id is required"), 400
    if choice not in CHOICES:
        return jsonify(error=f"choice must be one of {list(CHOICES)}"), 400

    try:
        r.rpush(QUEUE, json.dumps({"voter_id": voter_id, "choice": choice}))
    except redis.RedisError:
        return jsonify(error="queue unavailable, try again"), 503

    return jsonify(status="queued", choice=choice), 202


@app.get("/results")
def results():
    try:
        tallies = r.hgetall(RESULTS_KEY)
    except redis.RedisError:
        return jsonify(error="results unavailable"), 503
    return jsonify({c: int(tallies.get(c, 0)) for c in CHOICES})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
