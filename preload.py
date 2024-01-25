import hashlib
import json
import os
import re
import sys
import dotenv
import redis

# 加载环境变量
env = dotenv.load_dotenv()

print(os.environ.get("REDIS_HOST"))
print(os.environ.get("REDIS_PORT"))
print(os.environ.get("REDIS_PASSWD"))
# 连接 redis
redis = redis.Redis(host=os.environ.get("REDIS_HOST"), port=(os.environ.get("REDIS_PORT")),
                    password=os.environ.get("REDIS_PASSWD"), decode_responses=True)


# 初始化数据
def pre_process(redis=redis):
    # 初始化redis 清空所有数据
    redis.flushall()
    gptac_user = ""
    try:
        gptac_user = os.environ.get("GPTAC_USER")
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


if __name__ == '__main__':
    pre_process(redis)
