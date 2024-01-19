import os
import time
from multiprocessing import Pool
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.responses import RedirectResponse, Response, HTMLResponse
from redis import Redis as RedisClient
import redis as rd
from redis.exceptions import ConnectionError
import uvicorn
import dotenv
import httpx
import uuid
import json

dotenv.load_dotenv()

env = dotenv.dotenv_values()

app = FastAPI()

redis_url = env.get("REDIS_URL")

redis = rd.Redis(host="redis-15167.c282.east-us-mz.azure.cloud.redislabs.com", port=15167,
                 password="CViHfV4kVH6O0yP35DUayHos5xbSVx0b")


@app.middleware("http")
async def check_header_timestamp(request: Request, call_next):
    if (request.url.path == "/" or request.url.path.find("/static") != -1 or request.url.path == "/test" or
            request.url.path == "/favicon.ico"):
        return await call_next(request)
    if request.url.path == "/challenge/process" and request.method == "GET":
        if redis.get(request.query_params.get("challenge_id")):
            return await call_next(request)
        else:
            return JSONResponse(status_code=404, content={"message": "Not Found"})
    if request.url.path == "/challenge/request/get_url":
        if redis.get(request.query_params.get("challenge_id")):
            return await call_next(request)
        else:
            return JSONResponse(status_code=404, content={"message": "Not Found"})
    timestamp = request.headers.get("X-Timestamp")
    if not timestamp:
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    timestamp = int(timestamp)
    now = int(time.time())
    if now - timestamp > 300:
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    return await call_next(request)


@app.middleware("http")
async def print_request(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    end_time = time.time()
    response.headers["X-Timestamp"] = str(int((end_time - start_time) * 1000))
    print(request.url.path)
    print(response)
    return response


@app.get("/")
def read_root(request: Request):
    return {
        "service": "running",
        "running_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "running_on": "Binary-Yuki's Magic Server3 at Azure in East US",
        "your_ip": request.client.host
    }


@app.get("/test")
def test(request: Request):
    payload = {
        "redirect_url": "baidu.com",
        "code": str(999),
        "reason": "you are entering a test page"
    }
    headers = {
        "X-Timestamp": str(int(time.time()))
    }
    try:
        r = httpx.post(url=f"{request.base_url}challenge/request", json=payload, headers=headers)
        print(r.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    return RedirectResponse(url=f"{request.base_url}challenge/process?challenge_id={r.json()['challenge_id']}",
                            headers=headers, status_code=302)


@app.get("/static/{path}")
def read_static(path: str):
    try:
        try:
            os.stat(f"templates/static/{path}")
        except:
            raise Exception("Not Found")
        return FileResponse(f"templates/static/{path}")
    except:
        return JSONResponse(status_code=404, content={"message": "Not Found"})


@app.get("/challenge/request")
async def get_challenge():
    return JSONResponse(status_code=400, content={"message": "Deprecated"})


# noinspection PyAsyncCall
@app.post("/challenge/request")
async def apply_challenge(request: Request):
    try:
        data = await request.json()
        redirect_url = data.get("redirect_url")
        if data.get("challenge_id"):
            challenge_id = data.get("challenge_id")
            return RedirectResponse(url="/challenge/process?challenge_id=" + challenge_id)
        if data.get("code"):
            code = data.get("code")
        else:
            code = 429
        if data.get("reason"):
            reason = data.get("reason")
        else:
            reason = "you click too fast..."
    except Exception as e:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    if not redirect_url:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    # 获取ip
    ip = request.client.host
    # challenge_id取ip的hash值
    challenge_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, ip))
    # 如果这个link没有http或者https开头，就加上https
    if not redirect_url.startswith("http"):
        redirect_url = "https://" + redirect_url
    # 如果redis没有连接，就直接跳转
    if not redis:
        return RedirectResponse(url=redirect_url)
    payload = {
        "redirect_url": redirect_url,
        "challenge_id": challenge_id,
        "code": code,
        "reason": reason
    }
    payload = json.dumps(payload)
    # 将challenge_id和redirect_url存入redis
    # noinspection PyAsyncCall
    redis.set(challenge_id, payload, ex=300)  # 5分钟过期
    redis.set(challenge_id + "_status", "pending", ex=1800)  # 30分钟过期
    return JSONResponse(status_code=201, content={"challenge_id": challenge_id})


# noinspection PyAsyncCall
@app.get("/challenge/process")
async def challenge(request: Request):
    if not request.query_params.get("challenge_id"):
        return Response(status_code=204)
    html = os.path.join(os.path.dirname(__file__), "templates", "challenge.html")
    # 更新challenge_id的状态为processing
    redis.set(request.query_params.get("challenge_id") + "_status", "processing", ex=1800)
    data = redis.get(request.query_params.get("challenge_id"))
    data = json.loads(data)
    code = data.get("code")
    reason = data.get("reason")
    return HTMLResponse(
        content=open(html, "r").read().replace("{{ error_code }}", str(code)).replace("{{ error_reason }}",
                                                                                      str(reason)), status_code=202)


@app.get("/challenge/request/get_url")
def get_url(request: Request):
    challenge_id = request.query_params.get("challenge_id")
    data = redis.get(challenge_id)
    data = json.loads(data)
    redirect_url = data.get("redirect_url")
    redirect_url = str(redirect_url).replace("b'", "").replace("'", "")
    if redirect_url:
        redis.delete(challenge_id)
        redis.set(challenge_id + "_status", "success", ex=1800)
        return Response(content=redirect_url, status_code=200)
    else:
        referer = request.headers.get("Referer")
        return RedirectResponse(url=referer)


@app.get("/challenge/{challenge_id}")
def read_item(challenge_id: int, request: Request):
    return {"challenge_id": challenge_id, "ip": request.client.host}


def redis_never_die():
    if not redis:
        return
    timestamp = int(time.time())
    timestamp = str(timestamp)
    redis.set(timestamp, "alive", ex=8640)
    return


@app.post("/challenge/status")
async def challenge_status(request: Request):
    try:
        data = await request.json()
        challenge_id = data.get("challenge_id")
    except:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    if not challenge_id:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    if not redis:
        return JSONResponse(status_code=409, content={"message": "Conflict"})
    query_string = str(challenge_id + "_status")
    status = redis.get(query_string)
    if status:
        if status == b"success":
            return JSONResponse(status_code=200, content={"message": "success"})
        elif status == b"fail":
            return JSONResponse(status_code=200, content={"message": "fail"})
        elif status == b"pending":
            return JSONResponse(status_code=200, content={"message": "pending"})
        elif status == b"processing":
            return JSONResponse(status_code=200, content={"message": "processing"})
        else:
            return JSONResponse(status_code=200, content={"message": "unknown"})
    else:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})


def run_cron():
    while True:
        redis_never_die()
        print("alive")
        time.sleep(600)


@app.get("/openapi.json")
async def get_openapi_json():
    return JSONResponse(status_code=201, content={"message": "Not Found"})


@app.get("/docs")
async def get_docs():
    return JSONResponse(status_code=201, content={"message": "Not Found"})


@app.get("/docs/oauth2-redirect")
async def get_docs():
    return JSONResponse(status_code=201, content={"message": "Not Found"})


@app.get("/redoc")
async def get_docs():
    return JSONResponse(status_code=201, content={"message": "Not Found"})


# 自定义500error
@app.exception_handler(Exception)
async def error_handler(request: Request, exc: Exception):
    html = os.path.join(os.path.dirname(__file__), "templates", "challenge.html")
    return JSONResponse(status_code=400, content={"message": "param error"})


if __name__ == "__main__":
    p = Pool(4)
    p.apply_async(uvicorn.run(app, host="0.0.0.0", port=8000))
    p.apply_async(print(run_cron()))
    p.close()
    p.join()
