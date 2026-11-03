# Members of the team

- Huỳnh Trung Tín-524K0033
- Trần Minh Nghĩa-524K0032
- Phan Nguyễn Thảo Như-524V0007

# Redis & Caching Seminar Demo

This project is a FastAPI demonstration of SQLite queries, Redis caching,
Memcached caching, and Redis-backed session storage.

## Prerequisites

- Python 3.9 or newer
- Docker Desktop with Docker Compose
- Visual Studio Code (optional)

## Part 1: Local setup (at home)

Use this section to install and test the complete demo locally before the
seminar. From the project directory:

1. Create and activate a virtual environment.

   **Windows PowerShell**

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   **macOS/Linux**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install the Python dependencies.

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start Redis and Memcached. RedisInsight is also started for inspecting
   Redis data locally.

   ```bash
   docker compose up -d
   ```

4. Start the FastAPI application.

   ```bash
   python -m uvicorn main:app --reload
   ```

   On startup, the application creates and seeds `demo.db` with up to
   500,000 users. The initial startup can take a few seconds.

5. Open the telemary dashboard at
   [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard).

6. Open RedisInsight at [http://127.0.0.1:5540](http://127.0.0.1:5540).

7. Add the Redis Database by going to the Connection Settings

8. Change the host field into redis then Add the Redis Database

9. Select the newly added database to monitor/add/edit keys for your cached data

The local services use these ports:

| Service | Address |
| --- | --- |
| Dashboard | `http://127.0.0.1:8000/dashboard` |
| Redis | `localhost:6379` |
| RedisInsight | `http://127.0.0.1:5540` |
| Memcached | `localhost:11211` |

## Part 2: Live seminar demonstration (Ngrok)

In the live demonstration, the presenter will run the supporting services on
the presentation computer. Ngrok exposes the FastAPI application so attendees
use only the public benchmark dashboard.

### Before the seminar

(incase if the original presenter couldn't make it)
1. Install Ngrok and authenticate it with an Ngrok account. Follow the
   current instructions at [ngrok.com](https://ngrok.com/).
2. Confirm that Docker Desktop is running.
3. Start Redis, Memcached, and RedisInsight:

   ```bash
   docker compose up -d
   ```

4. Start the FastAPI application:

   ```bash
   python -m uvicorn main:app
   ```

5. In a second terminal, expose the local FastAPI port:

   ```bash
   ngrok http 8000
   ```

   Ngrok displays a forwarding URL similar to
   `https://example.ngrok-free.app`.

6. Share only the Telemetry Dashboard URL with attendees:
   `https://example.ngrok-free.app/dashboard`.

Do **not** expose Redis port `6379`, Memcached port `11211`, or RedisInsight
port `5540` through Ngrok. RedisInsight should remain open only on the
presenter's computer at `http://127.0.0.1:5540`.

The public URL changes when the Ngrok tunnel is restarted unless a reserved
Ngrok domain is configured. Stop Ngrok after the presentation.

### Dashboard overview

The main entry point is the live benchmark dashboard:

```text
https://example.ngrok-free.app/dashboard
```

Replace the example host with the forwarding URL shown by Ngrok. The
dashboard displays:

- Operating system, processor, CPU core/thread count, and CPU frequency
- Total and current system RAM usage
- FastAPI process RAM usage
- Redis server RAM usage and peak usage
- Recent benchmark history, including latency, CPU usage, cache status, and
  memory measurements

The dashboard refreshes its hardware and benchmark information automatically.
Use **Run Automated Benchmark** to run the complete Level 1 and Level 2
comparison sequence. Use **Reset & Flush Cache** to clear the displayed
history and reset both cache stores.

Each benchmark result includes a `time_ms` value and telemetry fields such
as `cpu_percent`, `app_ram_mb`, `app_ram_delta_mb`, `redis_ram_mb`, `label`,
and `cache`. Timings are for relative comparisons on the presentation
computer, not fixed performance guarantees. Cache entries expire after
60 seconds unless otherwise noted.

### Level 1: Small payload comparison

In the **Level 1 & 2 Triggers** panel, click:

1. **L1: No Cache (SQLite)** to record a direct database lookup.
2. **L1: Redis Cached** twice. The first run should show `MISS`; the second
   should show `HIT` while the cache entry is valid.

Use the latency chart and telemetry table to compare the two runs. Level 1
uses a small result containing only the number of matching users.

### Level 2: Large payload comparison

In the same panel, click:

1. **L2: No Cache (10k JSON)** once.
2. **L2: Redis (10k JSON)** twice to compare the initial cache population with
   a cache hit.
3. **L2: Memcached (10k JSON)** twice and compare its cache behavior with
   Redis.

Level 2 measures larger JSON results containing up to 10,000 user records.
Compare response time, CPU load, Python RAM, Redis RAM, and cache status in
the charts and telemetry table.

### Level 3: Session hash demonstration

Use the **Level 3 Session Hash Demo** panel:

1. Enter a username, or keep the default value.
2. Click **1. POST Login (Create Hash)**. The dashboard generates and fills
   the session token automatically.
3. Click **2. GET Profile (Verify Session)** to read the session and display
   the result.
4. Replace the token with an invalid value and click the verify button again
   to demonstrate the unauthorized-session result.

The session test records its timing and cache status in the telemetry
dashboard. Sessions remain valid for 30 minutes unless they expire sooner.

### End the live demo

1. Stop Ngrok with `Ctrl+C` so the public dashboard no longer works.
2. Stop the FastAPI server with `Ctrl+C`.
3. Stop the containers:

   ```bash
   docker compose down
   ```

## Stop a local practice session

Stop the FastAPI server with `Ctrl+C`, then stop the containers:

```bash
docker compose down
```

The generated `demo.db` file remains locally so later runs can reuse the
seeded database.
