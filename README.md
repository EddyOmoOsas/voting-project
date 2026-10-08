# Cats vs Dogs: Two-Tier Voting App on AWS

A voting app with a queue-based backend, deployed across two EC2 instances with Docker Compose.

![Screenshot](docs/screenshot.png)

## Architecture

Browser -> Nginx + static client (frontend EC2, public subnet) -> Flask API (backend EC2, private subnet) -> Redis queue -> Worker -> PostgreSQL

## How it works

1. The browser sends `POST /api/vote` with a `voter_id` and a `choice`.
2. The API validates the request, pushes it onto a Redis list, and returns `202 Accepted`.
3. The worker pops the vote and upserts it into PostgreSQL (one row per voter, so changing your vote replaces the old one).
4. The worker rebuilds the tallies in Redis from Postgres, and `GET /api/results` serves them.

## Tech stack

Python (Flask, psycopg2, redis-py), Redis, PostgreSQL 16, Nginx, Docker Compose, AWS (EC2, VPC, security groups, SSM Session Manager).

## Run locally

```bash
cd local
docker compose up --build
# open http://localhost:8080
```

## Deploy on AWS

1. Backend instance: `cd backend`, create `.env` with `POSTGRES_PASSWORD=...`, then `sudo docker compose up -d --build`.
2. Set the backend's private IP in `frontend/nginx.conf` (`proxy_pass`).
3. Frontend instance: `cd frontend && sudo docker compose up -d --build`.
4. Security groups: frontend allows TCP 80 from the internet; backend allows TCP 5000 from the frontend's security group only.

## Known limitations

- Flask dev server should be replaced with gunicorn.
- No authentication or rate limiting on `/vote`.
- Password is loaded from `.env`; next step is AWS Secrets Manager.
