import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, HTTPException, Response
from pymemcache.client.base import Client as MemcacheClient

time_to_expire = 60
users_amount=500000
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
memcached_client = MemcacheClient(('localhost', 11211))


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
    memcached_client.close()

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
        "cache": "BYPASS",
        "data": match_count
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
            "cache": "HIT",
            "data": int(cached_result)
        }

    match_count = perform_small_db_query(keyword)
    redis_client.setex(cache_key, time_to_expire, match_count)
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "payload_size": f"Small ({match_count} matches)",
        "time_ms": time_ms,
        "cache": "MISS",
        "data": match_count
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
        "cache": "BYPASS",
        "data": result
    }
    
    
@app.get("/demo/level2/cached/{keyword}")
def level2_large_payload_fast(keyword: str):
    start_time = time.perf_counter()
    cache_key = f"level2:data:{keyword}"
    
    
    cached_data = redis_client.get(cache_key)
    if cached_data:
        time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        custom_response_string = (
            f'{{"payload_size": "Large (From Redis)", '
            f'"time_ms": {time_ms}, '
            f'"cache": "HIT", '
            f'"data": {cached_data}}}'
        )
        
        return Response(content=custom_response_string, media_type="application/json")

    result=perform_heavy_db_query(keyword)

    redis_client.setex(cache_key, time_to_expire, json.dumps(result))
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {"payload_size": "Large", 
            "time_ms": time_ms, 
            "cache": "MISS",
            "data": result
            }
    
@app.get("/demo/level2/memcached/{keyword}")
def level2_large_payload_memcached(keyword: str):
    start_time = time.perf_counter()
    cache_key = f"level2_data_{keyword}"
    
    cached_data = memcached_client.get(cache_key)
    if cached_data:
        time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        custom_response_string = (
            f'{{"payload_size": "Large (From Memcached)", '
            f'"time_ms": {time_ms}, '
            f'"cache": "HIT", '
            f'"data": {cached_data}}}'
        )
                
        return Response(content=custom_response_string, media_type="application/json")

    result = perform_heavy_db_query(keyword)
    
    memcached_client.set(cache_key, json.dumps(result).encode('utf-8'), expire=time_to_expire)
    
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "payload_size": "Large", 
        "time_ms": time_ms, 
        "cache": "MISS",
        "data": result
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
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please login again."
        )
        
    time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return {
        "source": "Redis Session Storage", 
        "time_ms": time_ms,
        "user_data": session_data
    }