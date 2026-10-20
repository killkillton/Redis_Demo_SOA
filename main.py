import sqlite3
import time
from contextlib import asynccontextmanager
import json
import redis
from fastapi import FastAPI
import uuid

time_to_expire = 60
users_amount=500000
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
def setup_database():
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count < users_amount:
        print(f"Seeding {users_amount} users into SQLite. This will take a few seconds...")
        cursor.execute("DELETE FROM users")
        users_data = [(i, f"User_{i}", f"user{i}@example.com") for i in range(1, users_amount+1)]
        cursor.executemany("INSERT INTO users (id, name, email) VALUES (?, ?, ?)", users_data)
        
        conn.commit()
        print(f"Database seeded with {users_amount} users")
    else:
        print(f"Database already contains {count} users. Ready to go.")
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_database()
    yield
    redis_client.close()

app = FastAPI(lifespan=lifespan)

def perform_small_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE name LIKE ?", (f"%{keyword}%",))
    result = cursor.fetchone()
    conn.close()
    return result[0]

@app.get("/demo/level1/nocache/{keyword}")
def search_users_slow(keyword: str):
    start_time = time.perf_counter()
    match_count = perform_small_db_query(keyword)

    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "payload_size": f"Small ({match_count} matches)",
        "time_ms": time_ms,
        "data": match_count,
        "cache": "BYPASS"
    }

@app.get("/demo/level1/cached/{keyword}")
def search_users_fast(keyword: str):
    start_time = time.perf_counter()
    cache_key = f"search:count:{keyword}"
    cached_result = redis_client.get(cache_key)
    if cached_result is not None:
        time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "payload_size": f"Small ({int(cached_result)} matches)",
            "time_ms": time_ms,
            "data": int(cached_result),
            "cache": "HIT"
        }

    match_count = perform_small_db_query(keyword)
    redis_client.setex(cache_key, time_to_expire, match_count)
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "payload_size": f"Small ({match_count} matches)",
        "time_ms": time_ms,
        "data": match_count,
        "cache": "MISS"
    }

def perform_heavy_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name LIKE ? ORDER BY RANDOM() LIMIT 10000", (f"%{keyword}%",))
    rows = cursor.fetchall()
    conn.close()
    result = [{"id": row[0], "name": row[1]} for row in rows]

    return result


@app.get("/demo/level2/nocache/{keyword}")
def level2_large_payload_slow(keyword: str):
    start_time = time.perf_counter()
    
    result=perform_heavy_db_query(keyword)
    
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    
    return {
        "payload_size": f"Large ({len(result)} records)",
        "time_ms": time_ms,
        "data": result,
        "cache": "BYPASS"
    }
    
    
@app.get("/demo/level2/cached/{keyword}")
def level2_large_payload_fast(keyword: str):
    start_time = time.perf_counter()
    cache_key = f"level2:data:{keyword}"
    
    
    cached_data = redis_client.get(cache_key)
    if cached_data:
        time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "payload_size": "Large (From RAM)", 
            "time_ms": time_ms,
            "data": json.loads(cached_data), 
            "cache": "HIT"
        }

    result=perform_heavy_db_query(keyword)

    redis_client.setex(cache_key, time_to_expire, json.dumps(result))
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {"payload_size": "Large", 
            "time_ms": time_ms, 
            "data": result, 
            "cache": "MISS"
            }
    
    
    

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
        return {"error": "Invalid or expired session. Please login again."}
        
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "source": "Redis Session Storage", 
        "time_ms": time_ms,
        "user_data": session_data
    }