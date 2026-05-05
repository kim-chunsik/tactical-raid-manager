from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import requests
from urllib.parse import urlparse, parse_qs
import psycopg2
import psycopg2.extras

# 🌟 공대장님의 영구 보존용 Neon 클라우드 DB 주소 🌟
DB_URL = "postgresql://neondb_owner:npg_aYZ5kTPJ8VDp@ep-quiet-mud-akqv2smy-pooler.c-3.us-west-2.aws.neon.tech/neondb?sslmode=require"

# ==========================================
# 💾 데이터베이스 초기화 (PostgreSQL)
# ==========================================
def init_db():
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS members
                 (id SERIAL PRIMARY KEY,
                  adv_name TEXT, char_name TEXT UNIQUE, job_class TEXT,
                  role TEXT, damage TEXT, buff TEXT, link TEXT, 
                  attendance TEXT DEFAULT '참석',
                  is_passenger BOOLEAN DEFAULT FALSE)''')
    
    c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='members'")
    columns = [row[0] for row in c.fetchall()]
    if "attendance" not in columns:
        c.execute("ALTER TABLE members ADD COLUMN attendance TEXT DEFAULT '참석'")
    if "is_passenger" not in columns:
        c.execute("ALTER TABLE members ADD COLUMN is_passenger BOOLEAN DEFAULT FALSE")
    
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db() 
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ==========================================
# 📦 데이터 모델
# ==========================================
class LinkRequest(BaseModel):
    url: str

class Member(BaseModel):
    advName: str
    charName: str
    jobClass: str
    role: str
    damage: str
    buff: str
    link: str
    attendance: str = "참석"
    isPassenger: bool = False

class ScoreUpdate(BaseModel):
    damage: str
    buff: str

class AttendanceUpdate(BaseModel):
    attendance: str

class JobUpdate(BaseModel):
    jobClass: str

class PassengerUpdate(BaseModel):
    isPassenger: bool

# ==========================================
# 🌟 궁극의 초고속 API 크롤링
# ==========================================
def fetch_score_from_dundam(url: str):
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        server = query_params.get('server', [''])[0]
        char_key = query_params.get('key', [''])[0]
        char_name_from_url = query_params.get('name', [''])[0]

        api_url = "https://dundam.xyz/dat//viewData.jsp"
        
        params = {'server': server}
        if char_key:
            params['image'] = char_key
        elif char_name_from_url:
            params['name'] = char_name_from_url

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://dundam.xyz',
            'Referer': url 
        }

        response = requests.post(api_url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()

        adv_name = data.get("adventure", "알수없음") 
        char_name = data.get("name", "알수없음") 
        job_class = data.get("job", "알수없음")

        buff_score = "-"
        damage_score = "-"

        buff_cal = data.get("buffCal", [])
        for item in buff_cal:
            if "4PBuffScore" in item:
                buff_score = item.get("4PBuffScore")
                break
            elif "buffScore" in item:
                buff_score = item.get("buffScore")
                break

        damage_list = data.get("damageList", {})
        vs_ranking = damage_list.get("vsRanking", []) if damage_list else data.get("vsRanking", [])
        
        for item in vs_ranking:
            if item.get("name") == "총 합":
                damage_score = item.get("dam")
                break

        role = "버퍼" if buff_score not in ["-", "0", "", None] else "딜러"

        return {
            "success": True, 
            "advName": adv_name, 
            "charName": char_name, 
            "jobClass": job_class, 
            "role": role, 
            "damage": str(damage_score), 
            "buff": str(buff_score)
        }
        
    except Exception as e:
        print(f"API 크롤링 에러: {e}")
        return {"success": False}

# ==========================================
# 📡 API 라우터 (웹서비스 연동 적용)
# ==========================================

# ⭐️ 추가된 부분: 루트 경로 접속 시 index.html 화면 띄우기
@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

@app.post("/api/get_score")
def get_dundam_score(request: LinkRequest):
    return fetch_score_from_dundam(request.url)

@app.get("/api/members")
def get_all_members():
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    c = conn.cursor()
    c.execute("SELECT * FROM members")
    rows = c.fetchall()
    conn.close()
    
    members = []
    for row in rows:
        members.append({
            "id": row["id"], "advName": row["adv_name"], "charName": row["char_name"], 
            "jobClass": row["job_class"], "role": row["role"], "damage": row["damage"], 
            "buff": row["buff"], "link": row["link"], "attendance": row["attendance"],
            "isPassenger": bool(row["is_passenger"])
        })

    def get_sort_score(score_str):
        if not score_str or score_str in ["-", "0", ""]:
            return 0
        try:
            return int(score_str.replace(",", ""))
        except ValueError:
            return 0

    members.sort(key=lambda x: (
        x["advName"], 
        0 if x["role"] == "딜러" else 1, 
        -get_sort_score(x["damage"]) if x["role"] == "딜러" else -get_sort_score(x["buff"])
    ))

    return {"success": True, "members": members}

@app.post("/api/members")
def add_member(member: Member):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM members WHERE char_name = %s", (member.charName,))
        if c.fetchone():
            return {"success": False, "message": "이미 등록된 캐릭터입니다."}
        
        c.execute("INSERT INTO members (adv_name, char_name, job_class, role, damage, buff, link, attendance, is_passenger) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                  (member.advName, member.charName, member.jobClass, member.role, member.damage, member.buff, member.link, member.attendance, member.isPassenger))
        new_id = c.fetchone()[0]
        conn.commit()
        return {"success": True, "id": new_id}
    except Exception as e:
        return {"success": False, "message": f"저장 중 오류: {str(e)}"}
    finally:
        conn.close()

@app.put("/api/members/{member_id}")
def update_member(member_id: int, score: ScoreUpdate):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("UPDATE members SET damage = %s, buff = %s WHERE id = %s", (score.damage, score.buff, member_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.put("/api/members/{member_id}/attendance")
def update_attendance(member_id: int, data: AttendanceUpdate):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("UPDATE members SET attendance = %s WHERE id = %s", (data.attendance, member_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.put("/api/members/{member_id}/job")
def update_job(member_id: int, data: JobUpdate):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("UPDATE members SET job_class = %s WHERE id = %s", (data.jobClass, member_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.put("/api/members/{member_id}/passenger")
def update_passenger(member_id: int, data: PassengerUpdate):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("UPDATE members SET is_passenger = %s WHERE id = %s", (data.isPassenger, member_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/members/{member_id}")
def delete_member(member_id: int):
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("DELETE FROM members WHERE id = %s", (member_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/members")
def delete_all_members():
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()
    c.execute("DELETE FROM members")
    conn.commit()
    conn.close()
    return {"success": True}

# ==========================================
# 🚀 서버 실행
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0 포트로 설정하여 외부(웹) 접속 허용
    uvicorn.run(app, host="0.0.0.0", port=8000)