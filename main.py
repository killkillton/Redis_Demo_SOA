import sqlite3
import time
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
def setup_database():
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count < 500000:
        print("Seeding 500,000 users into SQLite. This will take a few seconds...")
        cursor.execute("DELETE FROM users")
        users_data = [(i, f"User_{i}", f"user{i}@example.com") for i in range(1, 500001)]
        cursor.executemany("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", users_data)
        
        conn.commit()
        print("Database seeded with 500,000 users!")
    else:
        print(f"Database already contains {count} users. Ready to go.")
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_database()
    yield
    redis_client.close()

app = FastAPI(lifespan=lifespan)

def perform_heavy_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE name LIKE ?", (f"%{keyword}%",))
    result = cursor.fetchone()
    conn.close()
    return result[0]

@app.get("/search/nocache/{keyword}")
def search_users_slow(keyword: str):
    api_start_time = time.time()
    db_start_time = time.time()
    match_count = perform_heavy_db_query(keyword)
    db_time_ms = (time.time() - db_start_time) * 1000
    
    api_time_ms = (time.time() - api_start_time) * 1000
    return {
        "source": "SQLite Full Table Scan", 
        "total_api_time_ms": int(api_time_ms), 
        "db_query_time_ms": int(db_time_ms),
        "keyword": keyword,
        "matches": match_count
    }

@app.get("/search/cached/{keyword}")
def search_users_fast(keyword: str):
    api_start_time = time.time()
    cache_key = f"search:count:{keyword}"
    cached_result = redis_client.get(cache_key)
    if cached_result:
        api_time_ms = (time.time() - api_start_time) * 1000
        return {
            "source": "Redis Cache HIT", 
            "total_api_time_ms": int(api_time_ms), 
            "db_query_time_ms": 0, 
            "keyword": keyword,
            "matches": int(cached_result)
        }

    db_start_time = time.time()
    match_count = perform_heavy_db_query(keyword)
    db_time_ms = (time.time() - db_start_time) * 1000

    redis_client.setex(cache_key, 10, match_count)
    api_time_ms = (time.time() - api_start_time) * 1000
    return {
        "source": "SQLite Full Table Scan (Cache MISS)", 
        "total_api_time_ms": int(api_time_ms), 
        "db_query_time_ms": int(db_time_ms),
        "keyword": keyword,
        "matches": match_count
    }