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

dotenv.load_dotenv()

app = FastAPI()

redis_url = os.environ.get("REDIS_URL")


@app.middleware("http")
async def check_header_timestamp(request: Request, call_next):
    if request.url.path == "/" or request.url.path == "/static" or request.url.path == "/test":
        return await call_next(request)
    timestamp = request.headers.get("X-Timestamp")
    if not timestamp:
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    timestamp = int(timestamp)
    now = int(time.time())
    print(now)
    if now - timestamp > 300:
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    return await call_next(request)


try:
    RedisClient.from_url(redis_url)
except ConnectionError:
    redis = None
    print("Redis is not connected")
else:
    RedisClient.from_url(redis_url)
    print("Redis is connected")

redis = rd.Redis(host="redis-15167.c282.east-us-mz.azure.cloud.redislabs.com", port=15167,
                 password="CViHfV4kVH6O0yP35DUayHos5xbSVx0b")


@app.get("/")
def read_root(request: Request):
    return {
        "service": "running",
        "running_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "running_on": "Binary-Yuki's Magic Server3 at Azure in East US",
        "your_ip": request.client.host
    }


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


@app.get("/test")
def test():
    # 在重定向至https://challenge.tzpro.xyz/challenge/request?redirect_url=google.com
    # 并且加入X-Timestamp这个header
    return RedirectResponse(url="https://challenge.tzpro.xyz/challenge/request?redirect_url=google.com",
                            headers={"X-Timestamp": str(int(time.time()))})


@app.get("/challenge/request")
async def apply_challenge(request: Request):
    try:
        data = await request.json()
        redirect_url = data.get("redirect_url")
    except Exception as e:
        # 从query中获取redirect_url
        redirect_url = request.query_params.get("redirect_url")
        print(e)
    else:
        return JSONResponse(status_code=400, content={"message": "Bad Request"})
    # 获取ip
    ip = request.client.host
    # challenge_id取ip的hash值
    challenge_id = str(hash(ip))
    # 如果这个link没有http或者https开头，就加上https
    if not redirect_url.startswith("http"):
        redirect_url = "https://" + redirect_url
    # 如果redis没有连接，就直接跳转
    if not redis:
        return RedirectResponse(url=redirect_url)
    # 将challenge_id和redirect_url存入redis
    # noinspection PyAsyncCall
    redis.set(challenge_id, redirect_url, ex=300)
    return RedirectResponse(url=f"/challenge/process?challenge_id={challenge_id}")


@app.get("/challenge/process")
async def challenge(request: Request):
    if not request.query_params.get("challenge_id"):
        return Response(status_code=204)
    html = os.path.join(os.path.dirname(__file__), "templates", "challenge.html")
    return HTMLResponse(
        content=open(html, "r").read().replace("{{ error_code }}", "429").replace("{{ error_reason }}",
                                                                                  "you click too fast..."),
        status_code=202)


@app.get("/challenge/request/get_url")
def get_url(request: Request):
    challenge_id = request.query_params.get("challenge_id")
    redirect_url = redis.get(challenge_id)
    redirect_url = str(redirect_url).replace("b'", "").replace("'", "")
    if redirect_url:
        return Response(content=redirect_url, status_code=200)
    else:
        return JSONResponse(status_code=404, content={"message": "Not Found"})


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
