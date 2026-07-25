# cron: 25 10 * * *
# new Env('统一快乐星球茄皇（五期）')
#
# 环境变量：
#   tyqh：账号凭证，格式为 wid#openId，多账号用 & 分隔
#
# 示例：tyqh=wid值#openId值

import base64
import json
import os
import random
import time
from typing import List, Tuple, Dict, Any

import requests
from notify import send

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_BACKEND = "cryptography"
except ImportError:
    try:
        from Crypto.Cipher import AES, PKCS1_OAEP
        from Crypto.Hash import SHA256
        from Crypto.PublicKey import RSA
        CRYPTO_BACKEND = "pycryptodome"
    except ImportError:
        CRYPTO_BACKEND = None


BASE_URL = "https://farmgames.ioutu.cn"
PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA70sK419vy3MabW3lEGlk"
    "7Zh1u78OdnVlioVazp5Y46eBh+/TDqo/wZ9VrQ/4MmAtoP0vJ2vmwP5gqO3WPoj"
    "b07WddXfF1eU+5M+Rj3s0eSRrvZvBcGZ3qK0dOgZJScK66IDQazt/c4xqhDcsI"
    "tIyNRahUqB/IKc6E80GZJvMvFtZVSCseAXC0mAJXhi1AdUOlP+3Pv0fiUVejTJp"
    "1j7LBNWJ7Z5/8mRcclQH0vmxsdYsaV3qZiJ2d/CfNoKcwmI2IWmeZy8NP5U8Hn"
    "0AsxPEwjdHoEqG/iy/SoA46TZL+RLtWqUSHXpaKR/VFN0rbl25SE91X8FTfLqyD"
    "8LfGMCwRQIDAQAB"
)
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.75(0x18004b43) NetType/WIFI Language/zh_CN "
    "miniProgram/wx532ecb3bdaaf92f9"
)
SUPPORTED_TASK_TYPES = {"SIGN", "BROWSE", "SHARE"}
FRIEND_TASK_TYPE = "FRIEND_STEAL_ENERGY"
FRIEND_STATUS_CLAIMABLE = "0"


def parse_users() -> List[Tuple[str, str]]:
    """解析环境变量，格式：wid#openId，多账号用 & 分隔"""
    raw = os.getenv("tyqh", "")
    accounts = []
    for item in str(raw or "").replace("&", "\n").splitlines():
        item = item.strip()
        if not item:
            continue
        parts = item.split("#")
        if len(parts) != 2:
            print(f"格式错误，跳过：{item}（正确格式：wid#openId）")
            continue
        wid, open_id = parts[0].strip(), parts[1].strip()
        if wid and open_id:
            accounts.append((wid, open_id))
    return accounts


def encrypt_payload(payload: Dict) -> Dict[str, str]:
    """Match the H5 client: RSA-OAEP-SHA256 + AES-256-GCM."""
    if CRYPTO_BACKEND is None:
        raise RuntimeError("缺少加密依赖，请安装 cryptography 或 pycryptodome")

    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    public_key_der = base64.b64decode(PUBLIC_KEY)

    if CRYPTO_BACKEND == "cryptography":
        public_key = serialization.load_der_public_key(public_key_der)
        encrypted_data = AESGCM(aes_key).encrypt(iv, plaintext, None)
        encrypted_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    else:
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        encrypted_data = ciphertext + tag
        public_key = RSA.import_key(public_key_der)
        encrypted_key = PKCS1_OAEP.new(public_key, hashAlgo=SHA256).encrypt(aes_key)

    return {
        "data": base64.b64encode(encrypted_data).decode(),
        "key": base64.b64encode(encrypted_key).decode(),
        "iv": base64.b64encode(iv).decode(),
    }


class TomatoClient:
    def __init__(self, wid: str, open_id: str, index: int):
        self.wid = wid
        self.open_id = open_id
        self.index = index
        self.tomato_user_id = None
        self.logs: List[str] = [f"账号{index}"]
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/?wid={wid}&openId={open_id}",
        })

    def log(self, msg: str):
        """记录日志并打印"""
        print(msg)
        self.logs.append(msg)

    def format_home_status(self, data: Dict, prefix: str = "当前状态") -> str:
        return (
            f"{prefix}：能量 {data.get('energyBalance', 0)}，"
            f"番茄 {data.get('tomatoBalance', 0)}，"
            f"{data.get('stageName', '未知阶段')} "
            f"{data.get('currentExp', 0)}/{data.get('stageRequiredExp', 0)}"
        )

    def request(self, method: str, path: str, payload: Any = None, encrypted: bool = True, retry: int = 2) -> Dict:
        url = f"{BASE_URL}{path}"
        for attempt in range(retry + 1):
            kwargs = {"timeout": 20}
            if payload:
                kwargs["json"] = encrypt_payload(payload) if encrypted else payload
                if encrypted:
                    kwargs["headers"] = {"X-Request-Encrypted": "true"}
            
            response = self.session.request(method, url, **kwargs)
            
            if response.status_code == 429 and attempt < retry:
                retry_after = response.headers.get("Retry-After", "2")
                try:
                    wait_seconds = max(1.0, float(retry_after))
                except ValueError:
                    wait_seconds = 2.0
                time.sleep(wait_seconds + attempt)
                continue
            
            response.raise_for_status()
            
            try:
                result = response.json()
            except ValueError as exc:
                raise RuntimeError(f"接口返回非 JSON 数据：{response.text[:200]}") from exc

            msg = str(result.get("msg", ""))
            if result.get("code") == 200:
                return result
            
            if attempt < retry and (response.status_code == 429 or "频繁" in msg or "稍后" in msg):
                time.sleep(2.5 + attempt * 1.5)
                continue
                
            raise RuntimeError(msg or f"接口返回 code={result.get('code')}")
        raise RuntimeError("请求重试后仍未成功")

    def run(self) -> List[str]:
        """执行该账号的完整业务流"""
        try:
            self._do_login()
            home_data = self._get_home()
            self.log(self.format_home_status(home_data))
            
            self._do_tasks()
            self._steal_friend_energy()
            
            home_data = self._get_home()
            self.log(self.format_home_status(home_data, "任务后状态"))
            
            self._use_energy(home_data)
            
            final_home = self._get_home()
            self.log(self.format_home_status(final_home, "最终状态"))
            
        except Exception as exc:
            self.log(f"处理异常：{exc}")
            
        return self.logs

    def _do_login(self):
        result = self.request(
            "POST",
            "/api/web/open/tomato/login",
            {"shareTomatoUserId": None, "openId": self.open_id, "wid": self.wid, "queryCardStatus": True},
        )
        data = result.get("data") or {}
        token = data.get("token")
        if not token:
            raise RuntimeError("登录响应中没有 token")
        
        self.session.headers["Authorization"] = token
        self.tomato_user_id = data.get("tomatoUserId")
        self.log(f"登录成功：{data.get('nickName') or '未设置昵称'}")

    def _get_home(self) -> Dict:
        return self.request("GET", "/api/web/member/tomato/home").get("data") or {}

    def _do_tasks(self):
        tasks = self.request("GET", "/api/web/member/tomato/tasks").get("data") or []
        completed, skipped = 0, 0
        
        for task in tasks:
            name = task.get("taskName") or task.get("taskCode") or "未知任务"
            task_type = task.get("taskType")
            
            if task_type == FRIEND_TASK_TYPE:
                self.friend_task = task
                if str(task.get("completed")) == "1":
                    self.log(f"任务已完成：{name}")
                continue
                
            if str(task.get("completed")) == "1":
                self.log(f"任务已完成：{name}")
                continue
                
            if task_type not in SUPPORTED_TASK_TYPES:
                skipped += 1
                self.log(f"跳过任务：{name}（需在小程序内操作）")
                continue
                
            try:
                payload = {"taskType": task_type}
                if task_type != "SHARE":
                    payload["browseTarget"] = task.get("browseTarget") or ""
                elif self.tomato_user_id:
                    self._create_miniprogram_qrcode()

                result = self.request("POST", "/api/web/member/tomato/tasks/complete", payload)
                data = result.get("data") or {}
                reward = data.get("rewardText") or task.get("rewardText") or "已领取"
                self.log(f"任务完成：{name}，{reward}")
                completed += 1
            except Exception as exc:
                self.log(f"任务失败：{name}，{exc}")
                
            time.sleep(random.uniform(2.5, 3.5))
            
        self.log(f"本次完成任务 {completed} 个，跳过 {skipped} 个")

    def _create_miniprogram_qrcode(self):
        try:
            self.request(
                "POST", 
                "/api/web/member/tomato/miniprogram/qrcode/create",
                {"page": "packages/wm-cloud-qiehuang/home/index", "scene": str(self.tomato_user_id)}
            )
        except Exception:
            pass

    def _steal_friend_energy(self):
        try:
            friends = []
            page_num = 1
            while True:
                result = self.request("GET", f"/api/web/member/tomato/friends?pageNum={page_num}&pageSize=20")
                rows = result.get("rows") or []
                friends.extend(rows)
                total = int(result.get("total") or 0)
                if not rows or (total and len(friends) >= total) or len(rows) < 20:
                    break
                page_num += 1

            claimable = [
                f for f in friends 
                if str(f.get("friendStatus")) == FRIEND_STATUS_CLAIMABLE and f.get("friendTomatoUserId")
            ]
            
            stolen_count, stolen_energy, failed_count = 0, 0, 0
            
            for friend in claimable:
                f_uid = friend["friendTomatoUserId"]
                try:
                    f_home = self.request("GET", f"/api/web/member/tomato/friends/{f_uid}/home").get("data") or {}
                    amount = int(f_home.get("stealAmount") or 0)
                    
                    if str(f_home.get("canSteal")) != "1" or amount <= 0:
                        continue
                        
                    self.request("POST", "/api/web/member/tomato/friends/steal", {"friendTomatoUserId": f_uid})
                    stolen_count += 1
                    stolen_energy += amount
                except Exception:
                    failed_count += 1
                time.sleep(random.uniform(1.5, 2.5))

            if stolen_count:
                detail = f"好友能量：成功收取 {stolen_count} 位好友，共 {stolen_energy} 能量"
                if failed_count:
                    detail += f"，失败 {failed_count} 位"
                self.log(detail)
            elif failed_count:
                self.log(f"好友能量：收取失败 {failed_count} 位")
            else:
                self.log("好友能量：暂无可收取能量")
                
        except Exception as exc:
            self.log(f"好友能量失败：{exc}")

    def _use_energy(self, home_data: Dict):
        energy = int(home_data.get("energyBalance") or 0)
        if energy <= 0:
            self.log("使用能量：当前没有可用能量")
            return
            
        before_tomato = int(home_data.get("tomatoBalance") or 0)
        try:
            grown = self.request("POST", "/api/web/member/tomato/energy/use", encrypted=False).get("data") or {}
            after_tomato = int(grown.get("tomatoBalance") or 0)
            gained = int(grown.get("gainedTomatoAmount") or 0)
            
            if not gained:
                gained = max(0, after_tomato - before_tomato)
                
            self.log(
                f"使用能量：消耗 {grown.get('usedEnergyAmount', energy)}，"
                f"成长到 {grown.get('stageName', '未知阶段')} "
                f"{grown.get('currentExp', 0)}/{grown.get('stageRequiredExp', 0)}，"
                f"获得番茄 {gained}"
            )
        except Exception as exc:
            self.log(f"使用能量失败：{exc}")


def render_report(all_logs: List[List[str]]) -> str:
    lines = ["统一茄皇五期"]
    for logs in all_logs:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.extend(logs)
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def safe_send(title: str, message: str):
    try:
        send(title, message)
    except Exception as exc:
        print(f"通知发送失败（不影响脚本执行结果）：{exc}")


def main():
    if CRYPTO_BACKEND is None:
        msg = "缺少加密依赖，请安装 cryptography：pip install cryptography"
        print(msg)
        safe_send("统一茄皇五期", msg)
        return

    users = parse_users()
    if not users:
        msg = "没有可用账号：未读取到 tyqh 环境变量，格式：wid#openId"
        print(msg)
        safe_send("统一茄皇五期", msg)
        return

    all_logs = []
    for index, (wid, open_id) in enumerate(users, 1):
        print(f"\n===== 开始处理账号 {index} =====")
        client = TomatoClient(wid, open_id, index)
        logs = client.run()
        all_logs.append(logs)
        
        if index < len(users):
            time.sleep(random.uniform(3, 5))

    report = render_report(all_logs)
    safe_send("统一茄皇五期", report)


if __name__ == "__main__":
    main()
