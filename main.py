import sqlite3
#Để sử dụng mấy cái SQL commands
import time
#Để đo thời gian
from contextlib import asynccontextmanager

import redis
#Cái mà mình đang làm seminar về
from fastapi import FastAPI
#Để cài đặt cái database và tắt kết nối dễ hơn

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
#Tạo một cái redis server bên hằng Docker
def setup_database():
    conn = sqlite3.connect("demo.db")
    #Kết nối db
    cursor = conn.cursor()
    #Tạo một cái chuỗi/cursor để duyệt qua cái db
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    #Tạo table
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    #Đếm số lượng entities trong db
    if count < 500000:
        print("Seeding 500,000 users into SQLite. This will take a few seconds...")
        cursor.execute("DELETE FROM users")
        #Đề phòng DB thừa data
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
    #Chuẩn bị db
    yield
    #Dừng lại để fastapi xử lý
    redis_client.close()
    #Sau khi tắt uvicorn thì đóng lại kết nối tới redis

app = FastAPI(lifespan=lifespan)
#Kêu cái app mình chạy theo như lifespan trên

def perform_heavy_db_query(keyword: str):
    conn = sqlite3.connect("demo.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE name LIKE ?", (f"%{keyword}%",))
    #đặt ? để tránh sql injection(prepared statement/parameterized query)
    #% % là wIldcards để tìm ký tự NHƯ keyword
    result = cursor.fetchone()
    conn.close()
    return result[0]

@app.get("/search/nocache/{keyword}")
def search_users_slow(keyword: str):
    api_start_time = time.time()
    #bắt đầu tgian GỬI cái API
    db_start_time = time.time()
    #Bắt đầu tìm kiếm trong DB
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
#Dùng cái cache-aside pattern
@app.get("/search/cached/{keyword}")
def search_users_fast(keyword: str):
    api_start_time = time.time()
    cache_key = f"search:count:{keyword}"
    #Do redis lưu trữ cached data cùng 1 chổ
    #Mình phải dùng namespacing để tránh lỡ xóa/thay thế data
    cached_result = redis_client.get(cache_key)
    #Qua bên redis để lấy dữ liệu
    if cached_result:
        #Nếu có sẵn
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
    #Để tránh trường hợp stale data
    #Mỗi 10s xóa data cũ và lấy data mới
    api_time_ms = (time.time() - api_start_time) * 1000
    return {
        "source": "SQLite Full Table Scan (Cache MISS)", 
        "total_api_time_ms": int(api_time_ms), 
        "db_query_time_ms": int(db_time_ms),
        "keyword": keyword,
        "matches": match_count
    }