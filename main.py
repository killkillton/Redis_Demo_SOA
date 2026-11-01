import json
import os
import platform
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager

import psutil
import redis
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pymemcache.client.base import Client as MemcacheClient

time_to_expire = 60
users_amount = 500000
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
memcached_client = MemcacheClient(('localhost', 11211))
process = psutil.Process(os.getpid())

# Store live benchmark runs for the visual dashboard
benchmark_history = []


def setup_database():
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count < users_amount:
        print(f"Seeding {users_amount} users into SQLite. This will take a few seconds...")
        cursor.execute("DELETE FROM users")
        users_data = [(i, f"User_{i}", f"user{i}@example.com") for i in range(1, users_amount + 1)]
        cursor.executemany("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", users_data)
        conn.commit()
        print(f"Database seeded with {users_amount} users")
    else:
        print(f"Database already contains {count} users. Ready to go.")
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_database()
    psutil.cpu_percent(interval=None)
    process.cpu_percent(interval=None)
    yield
    redis_client.close()
    memcached_client.close()


app = FastAPI(lifespan=lifespan, title="Redis vs No-Cache Hardware Benchmark")


def capture_telemetry(label: str, cache_status: str, start_time: float, mem_before: float):
    """Measures execution time, CPU load, Process RAM, and Redis RAM usage."""
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    
    # System CPU usage during the call
    cpu_usage = psutil.cpu_percent(interval=None)
    
    # FastAPI Python Process RAM (MB)
    mem_after = process.memory_info().rss / (1024 * 1024)
    app_ram_mb = round(mem_after, 2)
    app_ram_delta_mb = round(max(0.0, mem_after - mem_before), 2)
    
    # Redis Server RAM (MB) queried directly from Redis Engine
    try:
        redis_info = redis_client.info("memory")
        redis_ram_mb = round(redis_info.get("used_memory", 0) / (1024 * 1024), 2)
    except Exception:
        redis_ram_mb = 0.0

    entry = {
        "timestamp": time.strftime("%H:%M:%S"),
        "label": label,
        "cache": cache_status,
        "time_ms": time_ms,
        "cpu_percent": cpu_usage,
        "app_ram_mb": app_ram_mb,
        "app_ram_delta_mb": app_ram_delta_mb,
        "redis_ram_mb": redis_ram_mb
    }
    benchmark_history.append(entry)
    return entry


@app.get("/system/specs")
def get_system_specs():
    """Returns desktop hardware specifications and live resource utilization."""
    vm = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    try:
        r_info = redis_client.info("memory")
        redis_used_mb = round(r_info.get("used_memory", 0) / (1024 * 1024), 2)
        redis_peak_mb = round(r_info.get("used_memory_peak", 0) / (1024 * 1024), 2)
    except Exception:
        redis_used_mb, redis_peak_mb = 0.0, 0.0

    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "processor": platform.processor(),
        "cpu_physical_cores": psutil.cpu_count(logical=False),
        "cpu_logical_threads": psutil.cpu_count(logical=True),
        "cpu_freq_mhz": round(cpu_freq.current, 0) if cpu_freq else "N/A",
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_percent": vm.percent,
        "fastapi_process_ram_mb": round(process.memory_info().rss / (1024**2), 2),
        "redis_used_ram_mb": redis_used_mb,
        "redis_peak_ram_mb": redis_peak_mb,
        "history": benchmark_history[-15:]
    }


@app.post("/system/clear-history")
def clear_benchmark_history():
    benchmark_history.clear()
    redis_client.flushall()
    memcached_client.flush_all()
    return {"message": "Cleared benchmark history and flushed all caches."}


# ==========================================================
# LEVEL 1: SMALL PAYLOAD (Disk Scan vs RAM Lookup)
# ==========================================================
def perform_small_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE name LIKE ?", (f"%{keyword}%",))
    result = cursor.fetchone()
    conn.close()
    return result[0]


@app.get("/demo/level1/nocache/{keyword}")
def search_users_slow(keyword: str):
    psutil.cpu_percent(interval=None)
    mem_before = process.memory_info().rss / (1024 * 1024)
    start_time = time.perf_counter()

    match_count = perform_small_db_query(keyword)
    telemetry = capture_telemetry("L1: No Cache (SQLite)", "BYPASS", start_time, mem_before)

    return {
        "payload_size": f"Small ({match_count} matches)",
        **telemetry,
        "data": match_count
    }


@app.get("/demo/level1/cached/{keyword}")
def search_users_fast(keyword: str):
    psutil.cpu_percent(interval=None)
    mem_before = process.memory_info().rss / (1024 * 1024)
    start_time = time.perf_counter()
    cache_key = f"search:count:{keyword}"

    cached_result = redis_client.get(cache_key)
    if cached_result is not None:
        telemetry = capture_telemetry("L1: Redis (HIT)", "HIT", start_time, mem_before)
        return {
            "payload_size": f"Small ({int(cached_result)} matches)",
            **telemetry,
            "data": int(cached_result)
        }

    match_count = perform_small_db_query(keyword)
    redis_client.setex(cache_key, time_to_expire, match_count)
    telemetry = capture_telemetry("L1: Redis (MISS)", "MISS", start_time, mem_before)

    return {
        "payload_size": f"Small ({match_count} matches)",
        **telemetry,
        "data": match_count
    }


# ==========================================================
# LEVEL 2: LARGE PAYLOAD (10,000 JSON Records + CPU Serialization)
# ==========================================================
def perform_heavy_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name LIKE ? ORDER BY RANDOM() LIMIT 10000", (f"%{keyword}%",))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1]} for row in rows]


@app.get("/demo/level2/nocache/{keyword}")
def level2_large_payload_slow(keyword: str):
    psutil.cpu_percent(interval=None)
    mem_before = process.memory_info().rss / (1024 * 1024)
    start_time = time.perf_counter()

    result = perform_heavy_db_query(keyword)
    telemetry = capture_telemetry("L2: No Cache (10k Rows)", "BYPASS", start_time, mem_before)

    return {
        "payload_size": f"Large ({len(result)} records)",
        **telemetry,
        "data": result
    }


@app.get("/demo/level2/cached/{keyword}")
def level2_large_payload_fast(keyword: str):
    psutil.cpu_percent(interval=None)
    mem_before = process.memory_info().rss / (1024 * 1024)
    start_time = time.perf_counter()
    cache_key = f"level2:data:{keyword}"

    cached_data = redis_client.get(cache_key)
    if cached_data:
        telemetry = capture_telemetry("L2: Redis (HIT)", "HIT", start_time, mem_before)
        custom_response_string = (
            f'{{"payload_size": "Large (From RAM)", '
            f'"time_ms": {telemetry["time_ms"]}, '
            f'"cpu_percent": {telemetry["cpu_percent"]}, '
            f'"app_ram_mb": {telemetry["app_ram_mb"]}, '
            f'"redis_ram_mb": {telemetry["redis_ram_mb"]}, '
            f'"cache": "HIT", '
            f'"data": {cached_data}}}'
        )
        return Response(content=custom_response_string, media_type="application/json")

    result = perform_heavy_db_query(keyword)
    redis_client.setex(cache_key, time_to_expire, json.dumps(result))
    telemetry = capture_telemetry("L2: Redis (MISS)", "MISS", start_time, mem_before)

    return {
        "payload_size": f"Large ({len(result)} records)",
        **telemetry,
        "data": result
    }


@app.get("/demo/level2/memcached/{keyword}")
def level2_large_payload_memcached(keyword: str):
    psutil.cpu_percent(interval=None)
    mem_before = process.memory_info().rss / (1024 * 1024)
    start_time = time.perf_counter()
    cache_key = f"level2_data_{keyword}"

    cached_data = memcached_client.get(cache_key)
    if cached_data:
        parsed = json.loads(cached_data.decode('utf-8'))
        telemetry = capture_telemetry("L2: Memcached (HIT)", "HIT", start_time, mem_before)
        return {
            "payload_size": "Large (From Memcached)",
            **telemetry,
            "data": parsed
        }

    result = perform_heavy_db_query(keyword)
    memcached_client.set(cache_key, json.dumps(result).encode('utf-8'), expire=time_to_expire)
    telemetry = capture_telemetry("L2: Memcached (MISS)", "MISS", start_time, mem_before)

    return {
        "payload_size": f"Large ({len(result)} records)",
        **telemetry,
        "data": result
    }


# ==========================================================
# LEVEL 3: SESSION STORAGE (Redis Hash Structure)
# ==========================================================
@app.post("/demo/level3/login/{username}")
def login_user(username: str):
    start_time = time.perf_counter()
    session_token = str(uuid.uuid4())

    redis_client.hset(f"session:{session_token}", mapping={
        "username": username,
        "role": "admin",
        "login_time": time.time()
    })
    redis_client.expire(f"session:{session_token}", 1800)

    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "message": "Login successful",
        "session_token": session_token,
        "redis_write_time_ms": time_ms
    }


@app.get("/demo/level3/profile/{session_token}")
def get_profile(session_token: str):
    start_time = time.perf_counter()
    session_data = redis_client.hgetall(f"session:{session_token}")

    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please login again.")

    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "source": "Redis Session Storage",
        "time_ms": time_ms,
        "user_data": session_data
    }


# ==========================================================
# VISUAL TELEMETRY & BENCHMARK DASHBOARD UI
# ==========================================================
@app.get("/dashboard", response_class=HTMLResponse)
def benchmark_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Redis Hardware & Latency Telemetry</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 p-6 font-sans">
        <div class="max-w-7xl mx-auto space-y-6">
            <!-- Header -->
            <div class="flex justify-between items-center border-b border-slate-700 pb-4">
                <div>
                    <h1 class="text-2xl font-bold text-white">Redis vs. SQLite: Live Hardware & Speed Telemetry</h1>
                    <p class="text-slate-400 text-sm">Real-time CPU, RAM, and Latency Profiler (500,000 SQLite Records)</p>
                </div>
                <div class="space-x-2">
                    <button onclick="runFullSuite()" class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded font-semibold text-sm transition">
                        ▶ Run Automated Benchmark
                    </button>
                    <button onclick="clearHistory()" class="bg-rose-700 hover:bg-rose-600 px-4 py-2 rounded font-semibold text-sm transition">
                        Reset & Flush Cache
                    </button>
                </div>
            </div>

            <!-- Hardware Specs Banner -->
            <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <div class="text-xs text-slate-400 uppercase">OS & Architecture</div>
                    <div id="spec-os" class="text-sm font-semibold mt-1 truncate">Loading...</div>
                </div>
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <div class="text-xs text-slate-400 uppercase">CPU Specs</div>
                    <div id="spec-cpu" class="text-sm font-semibold mt-1">Loading...</div>
                </div>
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <div class="text-xs text-slate-400 uppercase">System RAM Usage</div>
                    <div id="spec-ram" class="text-sm font-semibold mt-1 text-sky-400">Loading...</div>
                </div>
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <div class="text-xs text-slate-400 uppercase">FastAPI Process RAM</div>
                    <div id="spec-app-ram" class="text-sm font-semibold mt-1 text-amber-400">Loading...</div>
                </div>
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <div class="text-xs text-slate-400 uppercase">Redis Engine RAM</div>
                    <div id="spec-redis-ram" class="text-sm font-semibold mt-1 text-emerald-400">Loading...</div>
                </div>
            </div>

            <!-- Manual Test Triggers -->
            <div class="bg-slate-800 p-4 rounded-lg border border-slate-700 flex flex-wrap gap-2 items-center">
                <span class="text-xs font-bold uppercase text-slate-400 mr-2">Trigger Test:</span>
                <button onclick="callApi('/demo/level1/nocache/777')" class="bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded text-xs">L1: No Cache (SQLite)</button>
                <button onclick="callApi('/demo/level1/cached/777')" class="bg-indigo-700 hover:bg-indigo-600 px-3 py-1.5 rounded text-xs">L1: Redis Cached</button>
                <button onclick="callApi('/demo/level2/nocache/1')" class="bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded text-xs">L2: No Cache (10k JSON)</button>
                <button onclick="callApi('/demo/level2/cached/1')" class="bg-emerald-700 hover:bg-emerald-600 px-3 py-1.5 rounded text-xs">L2: Redis (10k JSON)</button>
                <button onclick="callApi('/demo/level2/memcached/1')" class="bg-amber-700 hover:bg-amber-600 px-3 py-1.5 rounded text-xs">L2: Memcached (10k JSON)</button>
                <span id="status-indicator" class="ml-auto text-xs text-slate-400">Ready</span>
            </div>

            <!-- Charts Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <h2 class="text-sm font-bold text-slate-300 mb-3">1. Execution Latency (ms) — Lower is Better</h2>
                    <canvas id="latencyChart" height="180"></canvas>
                </div>
                <div class="bg-slate-800 p-4 rounded-lg border border-slate-700">
                    <h2 class="text-sm font-bold text-slate-300 mb-3">2. CPU Load (%) & Redis RAM Footprint (MB)</h2>
                    <canvas id="resourceChart" height="180"></canvas>
                </div>
            </div>

            <!-- Telemetry Log Table -->
            <div class="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
                <table class="w-full text-left text-xs">
                    <thead class="bg-slate-950 text-slate-400 uppercase">
                        <tr>
                            <th class="p-3">Time</th>
                            <th class="p-3">Endpoint Scenario</th>
                            <th class="p-3">Cache Status</th>
                            <th class="p-3">Response Time (ms)</th>
                            <th class="p-3">CPU Spike (%)</th>
                            <th class="p-3">Python RAM (MB)</th>
                            <th class="p-3">Redis RAM Used (MB)</th>
                        </tr>
                    </thead>
                    <tbody id="telemetry-table" class="divide-y divide-slate-700"></tbody>
                </table>
            </div>
        </div>

        <script>
            const latencyCtx = document.getElementById('latencyChart').getContext('2d');
            const resourceCtx = document.getElementById('resourceChart').getContext('2d');

            const latencyChart = new Chart(latencyCtx, {
                type: 'bar',
                data: { labels: [], datasets: [{ label: 'Response Time (ms)', data: [], backgroundColor: [] }] },
                options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: '#334155' } } } }
            });

            const resourceChart = new Chart(resourceCtx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [
                        { label: 'CPU Usage (%)', data: [], backgroundColor: '#f59e0b' },
                        { label: 'Redis RAM (MB)', data: [], backgroundColor: '#10b981' }
                    ]
                },
                options: { responsive: true, scales: { y: { beginAtZero: true, grid: { color: '#334155' } } } }
            });

            async function refreshTelemetry() {
                const res = await fetch('/system/specs');
                const data = await res.json();

                document.getElementById('spec-os').innerText = data.os;
                document.getElementById('spec-cpu').innerText = `${data.cpu_physical_cores} Cores / ${data.cpu_logical_threads} Threads @ ${data.cpu_freq_mhz}MHz`;
                document.getElementById('spec-ram').innerText = `${data.ram_used_gb} / ${data.ram_total_gb} GB (${data.ram_percent}%)`;
                document.getElementById('spec-app-ram').innerText = `${data.fastapi_process_ram_mb} MB`;
                document.getElementById('spec-redis-ram').innerText = `${data.redis_used_ram_mb} MB (Peak: ${data.redis_peak_ram_mb} MB)`;

                const history = data.history;
                latencyChart.data.labels = history.map(h => `${h.label} [${h.cache}]`);
                latencyChart.data.datasets[0].data = history.map(h => h.time_ms);
                latencyChart.data.datasets[0].backgroundColor = history.map(h =>
                    h.cache === 'HIT' ? '#10b981' : (h.cache === 'MISS' ? '#f59e0b' : '#ef4444')
                );
                latencyChart.update();

                resourceChart.data.labels = history.map(h => `${h.label} [${h.cache}]`);
                resourceChart.data.datasets[0].data = history.map(h => h.cpu_percent);
                resourceChart.data.datasets[1].data = history.map(h => h.redis_ram_mb);
                resourceChart.update();

                const tbody = document.getElementById('telemetry-table');
                tbody.innerHTML = history.slice().reverse().map(h => `
                    <tr class="hover:bg-slate-750">
                        <td class="p-3 text-slate-400">${h.timestamp}</td>
                        <td class="p-3 font-semibold">${h.label}</td>
                        <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${h.cache === 'HIT' ? 'bg-emerald-900 text-emerald-300' : (h.cache === 'MISS' ? 'bg-amber-900 text-amber-300' : 'bg-rose-900 text-rose-300')}">${h.cache}</span></td>
                        <td class="p-3 font-mono font-bold ${h.cache === 'HIT' ? 'text-emerald-400' : 'text-rose-400'}">${h.time_ms} ms</td>
                        <td class="p-3 font-mono">${h.cpu_percent}%</td>
                        <td class="p-3 font-mono">${h.app_ram_mb} MB (+${h.app_ram_delta_mb} MB)</td>
                        <td class="p-3 font-mono text-emerald-400">${h.redis_ram_mb} MB</td>
                    </tr>
                `).join('');
            }

            async function callApi(url) {
                document.getElementById('status-indicator').innerText = `Running ${url}...`;
                await fetch(url);
                await refreshTelemetry();
                document.getElementById('status-indicator').innerText = 'Completed';
            }

            async function clearHistory() {
                await fetch('/system/clear-history', { method: 'POST' });
                await refreshTelemetry();
            }

            async function runFullSuite() {
                await clearHistory();
                const steps = [
                    '/demo/level1/nocache/777',
                    '/demo/level1/cached/777',
                    '/demo/level1/cached/777',
                    '/demo/level2/nocache/1',
                    '/demo/level2/cached/1',
                    '/demo/level2/cached/1',
                    '/demo/level2/memcached/1',
                    '/demo/level2/memcached/1'
                ];
                for (const step of steps) {
                    await callApi(step);
                    await new Promise(r => setTimeout(r, 300));
                }
            }

            refreshTelemetry();
            setInterval(refreshTelemetry, 3000);
        </script>
    </body>
    </html>
    """