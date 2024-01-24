import os
import sys
import time
from multiprocessing import Pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

try:
    redis = rd.Redis(host="redis-15167.c282.east-us-mz.azure.cloud.redislabs.com", port=15167,
                     password="CViHfV4kVH6O0yP35DUayHos5xbSVx0b")
except ConnectionError:
    print("Redis Connection Error")
    redis = None
    sys.exit("Redis Connection Error")
except Exception as e:
    print(e)
    sys.exit(str(e))


@app.middleware("http")
async def check_header_timestamp(request: Request, call_next):
    if (request.url.path == "/" or request.url.path.find("/static") != -1 or request.url.path == "/test" or
            request.url.path == "/favicon.ico"):
        return await call_next(request)
    # 通配/gptac/pass/*
    if request.url.path.startswith("/gptac/pass"):
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
        return JSONResponse(status_code=403, content={"message": "Expired"})
    timestamp = int(timestamp)
    now = int(time.time())
    if now - timestamp > 300:
        print(int(time.time()))
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    return await call_next(request)


@app.get("/")
def read_root(request: Request):
    json = {
        "service": "running",
        "running_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "running_on": "Binary-Yuki's Magic Server3 at Azure in East US",
        "your_ip": request.client.host
    }
    html = os.path.join(os.path.dirname(__file__), "templates", "status.html")
    return HTMLResponse(content=open(html, "r").read().replace("{{ json}}", str(json)), status_code=200)


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


@app.post("/api/v1/gptac/jump")
async def jump(request: Request):
    data = await request.json()
    server = data.get("server")
    if not server:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    try:
        # 检查这个 server 的格式是否符合 gptac_node* 的格式
        if not server.startswith("gptac_node"):
            return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
        # 解析 server 的数字
        server = server.replace("gptac_node", "")
        server = int(server)
        server_url = f"https://ac{server}.tzpro.xyz"
        # 检查这个 server 是否存在
        async with httpx.AsyncClient() as client:
            response = await client.get(server_url)
            if response.status_code != 200:
                return JSONResponse(status_code=404, content={"msg": "服务器不在线！"})
            else:
                async with httpx.AsyncClient() as client2:
                    headers = {
                        "Accept": "application/json"
                    }
                    # data是 form-data
                    data = {'username': 'fjwj', 'password': 'bDyHZccT'}
                    headers = {
                        "Accept": "application/json"
                    }
                    response = await client2.post(server_url + "/login", headers=headers, data=data)
                    if response.status_code != 200:
                        return JSONResponse(status_code=404, content={"msg": response.text})
                    else:
                        res = JSONResponse(status_code=201, content={"url": server_url, "msg": "ok"},
                                           headers=headers)
                        try:
                            cookies = response.headers.get("Set-Cookie")
                            cookie = response.headers.get("Set-Cookie")
                            cookie = cookie.split(";")[0]
                            cookie = cookie.replace("access-token=", "")
                            cookies = cookie.replace('"', "")
                            res.set_cookie(key="access-token", value=cookies, domain='tzpro.xyz')
                            return res
                        except:
                            return JSONResponse(status_code=404, content={"msg": "cookie获取失败"})
    except ValueError:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})


@app.get("/gptac/pass")
async def get_pass(request: Request):
    username = request.query_params.get("username")
    if not username:
        return JSONResponse(status_code=406, content={"message": "Unacceptable Param"})
    user = ["skg", "hjt", "htz", "dxr", "mry"]
    if username not in user:
        print(username)
        return JSONResponse(status_code=404, content={"message": "Not Found", "username": username})
    try:
        html = os.path.join(os.path.dirname(__file__), "templates", "server_ls.html")
        return HTMLResponse(content=open(html, "r").read().replace("{{ username }}", str(username)), status_code=200)
    except:
        return JSONResponse(status_code=404, content={"message": "Not Found"})


# 自定义500error
@app.exception_handler(Exception)
async def error_handler(request: Request, exc: Exception):
    html = os.path.join(os.path.dirname(__file__), "templates", "challenge.html")
    return JSONResponse(status_code=400, content={"message": "param error"})


if __name__ == "__main__":
    p = Pool(4)
    p.apply_async(uvicorn.run(app, host="0.0.0.0", port=8000, lifespan="auto", log_level="info"))
    p.apply_async(print(run_cron()))
    p.close()
    p.join()
