import os
import re
import sys
import time
from multiprocessing import Pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.responses import RedirectResponse, Response, HTMLResponse
import redis as rd
from redis.exceptions import ConnectionError
import uvicorn
import dotenv
import httpx
import uuid
import json
import hashlib

dotenv.load_dotenv()

env = dotenv.dotenv_values()

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8000",
    "https://challenge.tzpro.xyz",
    os.environ.get("BASE_URL"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
host = env.get("REDIS_HOST")
port = env.get("REDIS_PORT")
passwd = env.get("REDIS_PASSWD")
try:
    redis = rd.Redis(host=host, port=port, password=passwd, decode_responses=True)
except ConnectionError:
    print("Redis Connection Error")
    redis = None
    sys.exit("Redis Connection Error")
except Exception as e:
    print(e)
    sys.exit(str(e))


def pre_process():
    # 初始化redis 清空所有数据
    redis.flushall()

    try:
        gptac_user = env.get("GPTAC_USER")
    except Exception as e:
        print(e)
        sys.exit(str(e))
    try:
        redis.flushall()
        # 数据列表
        data_str = gptac_user
        data = re.findall(r'\("(.*?)", "(.*?)"\)', data_str)
        user_list = []
        # 创建一个本地文件，用于存储sha256值
        if os.path.exists("sha256.txt"):
            os.remove("sha256.txt")
        # 遍历数据
        for i, (account, password) in enumerate(data, 1):
            # 生成账户名和密码的散列值
            sha256_result = hashlib.sha256((account + password).encode()).hexdigest()
            # 创建字典存储账户名和密码
            account_dict = {"username": account, "password": password}
            # 将字典转换为 JSON 格式
            account_json = json.dumps(account_dict)
            # 将数据存储在 redis 中
            print(f"正在存储第{i}条数据", "用户名", account, "特征值", sha256_result)
            if redis.get(sha256_result):
                print(f"sha254: {sha256_result} 已存在")
                continue
            redis.set(sha256_result, account_json, ex=86400)
            user_list.append(account)
            # 有个 bug：文件会被覆盖，导致只能存储最后一条数据
            with open("sha256.txt", "a") as f:
                f.write(sha256_result + "\n")
    except Exception as e:
        print(e)
        sys.exit(str(e))
    print("初始化完成")
    return


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
    i = str(uuid.uuid3(uuid.NAMESPACE_DNS, ip))
    f = str(uuid.uuid3(uuid.NAMESPACE_DNS, redirect_url))
    challenge_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, i + f))
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
    redirect_url = data["redirect_url"]
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
        if status == "success":
            return JSONResponse(status_code=200, content={"status": "success"})
        elif status == "fail":
            return JSONResponse(status_code=200, content={"status": "fail"})
        elif status == "pending":
            return JSONResponse(status_code=200, content={"status": "pending"})
        elif status == "processing":
            return JSONResponse(status_code=200, content={"status": "processing"})
        else:
            return JSONResponse(status_code=200, content={"status": status})
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


# 一个监视器 检查 check_user_available 在3分钟内运行的次数
# 如果超过10次 就返回 429
# 如果没有超过10次 就返回 200
class Monitor:
    # wrapper
    def __init__(self, func):
        self.func = func
        self.count = 0
        self.timestamp = time.time()

    def __call__(self, *args, **kwargs):
        if time.time() - self.timestamp > 180:
            self.count = 0
            self.timestamp = time.time()
        if self.count > 10:
            raise Exception("Too Many Requests")
        else:
            self.count += 1
            return self.func(*args, **kwargs)


@Monitor
def check_user_available():
    # 读取sha256.txt文件
    with open("sha256.txt", "r") as f:
        data = f.readlines()
    # 随机取一行
    import random
    data = random.choice(data)
    # 去除换行符
    data = data.replace("\n", "")
    # 验证这个值是不是 sha256
    if len(data) != 64:
        return check_user_available()
    if redis.get(data + "_status"):
        # 重新获取
        return check_user_available()
    # 从redis中获取这个值
    json_info = redis.get(data)
    if not json_info:
        return check_user_available()
    # 从redis中添加 1 h 占用时间
    redis.set(data + "_status", "pending", ex=3600)
    # 返回用户名和密码
    return json_info


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
        print(server)
        if server == 1:
            return JSONResponse(status_code=404, content={"msg": "主集群暂不支持免密登录！"})
        elif server == 2:
            server_url = "https://ac1.tzpro.xyz"
        elif server == 3:
            server_url = "https://ac2.tzpro.xyz"
        else:
            server_url = f"https://ac{int(server) - 1}.tzpro.xyz"
        # 检查这个 server 是否存在
        async with httpx.AsyncClient() as client:
            response = await client.get(server_url)
            if response.status_code != 403:
                return JSONResponse(status_code=400, content={"msg": "服务器不在线！", "url": server_url,
                                                              "code": response.status_code})
            else:
                async with httpx.AsyncClient() as client2:
                    # data是 form-data
                    data = check_user_available()
                    data = json.loads(data)
                    username = data.get("username")
                    password = data.get("password")
                    data = {'username': username, 'password': password}
                    print(data)
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
    except Exception as e:
        return JSONResponse(status_code=404, content={"message": "Not Found"})


@app.post("/get_base_url")
def get_base_url(request: Request):
    try:
        os.environ.get("BASE_URL")
    except Exception as e:
        return JSONResponse(status_code=404, content={"message": "Not Found", "error": str(e)})
    return JSONResponse(status_code=200, content={"message": os.environ.get("BASE_URL")})


# 自定义500error
@app.exception_handler(Exception)
async def error_handler(request: Request, exc: Exception):
    html = os.path.join(os.path.dirname(__file__), "templates", "challenge.html")
    return JSONResponse(status_code=400, content={"message": "param error"})


if __name__ == "__main__":
    p = Pool(4)
    p.apply_async(pre_process)
    p.apply_async(uvicorn.run(app, host="0.0.0.0", port=8000, lifespan="auto", log_level="info"))
    p.apply_async(print(run_cron()))
    p.close()
    p.join()
