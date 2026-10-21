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

5. Open the interactive API documentation at
   [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

6. Open RedisInsight at [http://127.0.0.1:5540](http://127.0.0.1:5540).

7. Add the Redis Database by going to the Connection Settings

8. Change the host field into redis then Add the Redis Database

9. Select the newly added database to monitor/add/edit keys for your cached data

The local services use these ports:

| Service | Address |
| --- | --- |
| FastAPI | `http://127.0.0.1:8000` |
| Redis | `localhost:6379` |
| RedisInsight | `http://127.0.0.1:5540` |
| Memcached | `localhost:11211` |

## Part 2: Live seminar demonstration (Ngrok)

In the live demonstration, the presenter will run the API, Redis, Memcached, and
RedisInsight on the presentation computer. Ngrok exposes only the FastAPI
application so attendees can use the public Swagger UI while the presenter
shows RedisInsight locally.

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

6. Share only the Swagger UI URL with attendees:
   `https://example.ngrok-free.app/docs`.

Do **not** expose Redis port `6379`, Memcached port `11211`, or RedisInsight
port `5540` through Ngrok. RedisInsight should remain open only on the
presenter's computer at `http://127.0.0.1:5540`.

The public URL changes when the Ngrok tunnel is restarted unless a reserved
Ngrok domain is configured. Anyone with the public URL can call these demo
endpoints while the tunnel is running, so stop Ngrok after the presentation.

### Live demonstration flow

The examples below use the public Ngrok URL. Replace
`https://example.ngrok-free.app` with the URL shown by your Ngrok terminal.
The `cache` field identifies whether the request bypassed the cache, populated
it, or used a cached value. Cache entries expire after 60 seconds.

### Level 1: Small payloads (count search)

**Endpoints**

- `GET /demo/level1/nocache/{keyword}` — query SQLite directly
- `GET /demo/level1/cached/{keyword}` — query Redis after a cache miss

**Try it**

1. Open `https://example.ngrok-free.app/docs`.
2. Call `GET /demo/level1/nocache/User` and note `time_ms`.
3. Call `GET /demo/level1/cached/User`. The first request should report
   `cache: "MISS"`.
4. Call it again within 60 seconds. It should report `cache: "HIT"` and
   generally be faster.

### Level 2: Large payloads (up to 10,000 records)

**Endpoints**

- `GET /demo/level2/nocache/{keyword}` — query SQLite directly
- `GET /demo/level2/cached/{keyword}` — cache the JSON result in Redis
- `GET /demo/level2/memcached/{keyword}` — cache the JSON result in Memcached

The database query returns at most 10,000 matching records; it can return
fewer if the keyword has fewer matches. Timing depends on the machine and
should be used for relative comparisons, not as a fixed benchmark.

**Try it**

1. Call `/demo/level2/nocache/1`.
2. Call `/demo/level2/cached/1` twice and compare the `MISS` and `HIT` responses.
3. Call `/demo/level2/memcached/1` twice and compare its `MISS` and `HIT`
   responses with Redis.
4. In the presenter's RedisInsight window, inspect the `level2:data:*` keys
   created by the Redis example and refresh the view after each request.

### Level 3: Session management with Redis hashes

**Endpoints**

- `POST /demo/level3/login/{username}` — creates a Redis hash session
- `GET /demo/level3/profile/{session_token}` — reads the session hash

Sessions expire after 30 minutes.

**Try it**

1. Call `POST /demo/level3/login/Alice` and copy the returned
   `session_token`.
2. Call `GET /demo/level3/profile/{session_token}` using that token.
3. Try an invalid or expired token. The endpoint returns HTTP
   `401 Unauthorized`, because the request is not authenticated.
4. In RedisInsight, inspect the corresponding `session:{session_token}` hash
   and its expiration.

### End the live demo

1. Stop Ngrok with `Ctrl+C` so the public Swagger URL no longer works.
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
