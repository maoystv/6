# coding=utf-8
# ================== 影视·正经·小鸡看看 · TVBox ==================
# 🏷️ 源头：软件 小鸡看看 App(com.xmoebr.bdx v1.0.5) / TV版(com.kankan.tv) 接口 https://xjggg.top/api.php/app
# 👤 作者：无聊  |  📅 2026-10-28
# 🏷️ 平台：TVBox / 影视仓  ·  csp_Spider
# 🔍 站型：Expo/RN 壳 App + PHP API，全接口强制五头签名(x-aid/x-ave/x-time/x-nonc/x-sign)
# 🎬 关键：签名 = SHA256(finger&id&nonce&sk&time&v)，sk 与证书指纹从 TV 版 APK 逆向得出
#        http://... 播放令牌(加密) → /app/decode/url 换真直链
# 📦 内容：视频（电影/剧集/动漫/综艺，多线路 7 条）
# ==========================================================
import sys
import json
import time
import random
import hashlib
import base64
import re
import ssl
import gzip
import http.client
import urllib.parse

sys.path.append('..')

# ---------------- 签名材料（逆向 libsecurity-bridge.so / TV 版 dex 得出）----------------
APP_ID = "com.kankan.tv"
APP_VER = "105"
SK = "SK-sk_13oXDZ7u9j2Tk1c0cawWVFfO"
FINGER = "SF-F5F11CB15897115AE6BCFE063C288F730CA865588F572C780A3E8477D0DD3776"
# ---------------- 设备号池（★无限解析的核心★）----------------
# decode/url 是「每设备每日 N 次」的配额制（实测：单枚设备连解 60 次仍未到顶；
# 但一枚设备被榨干后当日恒返回 code 429 "今日解析次数已用完，请明天00:00后再试"）。
# 服务端只认 x-device-id 头，不校验设备唯一性 / 不与账号绑定 → 换一枚 UUID4 立刻恢复。
# 几千人共用一份源 = 几千台「同一设备」，一枚设备几小时就被榨干 → 必须池化 + 轮转：
#   · POOL_SIZE 枚设备轮转使用，压力摊开，单枚寿命 × POOL_SIZE
#   · 429 立即拉黑该枚、换下一枚，永不中断
#   · 设备号落盘到 hiker 数据目录，跨重启复用（避免重启把好设备全丢掉）
import uuid as _uuid
import threading as _th

POOL_SIZE = 12          # 同时轮转的设备数（越大越抗压，但要平衡风控观感）
_DEV_LOCK = _th.Lock()
_DEV_POOL = []          # 可用设备号列表
_DEV_IDX = 0            # 轮转游标
_DEV_BAD = {}           # device -> 失效日期，跨天自动解封
_DEV_DAY = time.strftime("%Y-%m-%d")
_DEV_CACHE = "xjk_dev_pool.json"


def _new_device():
    return "uuid-" + str(_uuid.uuid4())


def _dev_newday():
    global _DEV_DAY
    d = time.strftime("%Y-%m-%d")
    if d != _DEV_DAY:
        _DEV_DAY = d
        _DEV_BAD.clear()


def _dev_save():
    """设备池落盘（壳环境可能无写权限，失败静默）。"""
    try:
        open(_DEV_CACHE, "w").write(json.dumps({
            "day": _DEV_DAY, "pool": _DEV_POOL, "bad": list(_DEV_BAD.keys())
        }))
    except Exception:
        pass


def _dev_load():
    """跨重启复用设备号：昨日的好设备今天多半还有额度。"""
    global _DEV_POOL, _DEV_BAD
    try:
        obj = json.loads(open(_DEV_CACHE).read())
        pool = [d for d in (obj.get("pool") or []) if isinstance(d, str) and d.startswith("uuid-")]
        bad = obj.get("bad") or []
        if obj.get("day") == _DEV_DAY:
            _DEV_BAD = dict((b, _DEV_DAY) for b in bad if isinstance(b, str))
        _DEV_POOL = [d for d in pool if d not in _DEV_BAD]
    except Exception:
        pass


def _dev_fill():
    """补足池到一个足够大的规模。"""
    while len(_DEV_POOL) < POOL_SIZE:
        n = _new_device()
        if n in _DEV_BAD or n in _DEV_POOL:
            continue
        _DEV_POOL.append(n)


def _dev_get():
    """轮转取一枚设备号（分散压力，避免单枚被快速榨干）。"""
    global _DEV_IDX
    with _DEV_LOCK:
        _dev_newday()
        if not _DEV_POOL:
            _dev_load()
        _dev_fill()
        _DEV_IDX = (_DEV_IDX + 1) % len(_DEV_POOL)
        return _DEV_POOL[_DEV_IDX]


def _dev_fail(dev):
    """该设备今日配额耗尽 → 拉黑并补新号，返回下一枚。"""
    with _DEV_LOCK:
        _dev_newday()
        if dev:
            _DEV_BAD[dev] = _DEV_DAY
            if dev in _DEV_POOL:
                _DEV_POOL.remove(dev)
        _dev_fill()
        _dev_save()
        return _DEV_POOL[0]


def _dev_ok(dev):
    """解码成功：只做记账，不打断轮转（保持压力分散）。"""
    with _DEV_LOCK:
        if dev and dev not in _DEV_POOL and dev not in _DEV_BAD:
            _DEV_POOL.append(dev)


_dev_load()
_dev_fill()
DEVICE = _DEV_POOL[0]
UA = "okhttp/4.12.0"
PLAY_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 主域名 + 逆出的备用端点（App 内置 endpointConfig 加密块解出的两枚 API 域名）
HOSTS = [
    ("xjggg.top", 443),
    ("50.118.186.185", 8090),
    ("179.255.99.4", 8090),
]

# 端点自愈：主域名全挂时，从这几个公开配置页解出最新 API 端点（App 同款流程）
ENDPOINT_SOURCES = [
    "https://res.cloudinary.com/wygbngdd/raw/upload/1.txt",
    "https://anotepad.com/notes/wcqhmtf9",
]
EP_AES_KEY = "3EoMYcMw9X1igBsCb7CLCTKGTqWv9OpAAJr2xGa3co0="
EP_AAD = "TVAPP_ENDPOINT_CONFIG_V1:TVAPP:production:A256GCM\x00"

CATS = [
    ("c_movie", "🎬电影", "电影"),
    ("c_tv", "📺剧集", "剧集"),
    ("c_anime", "🌸动漫", "动漫"),
    ("c_show", "🎤综艺", "综艺"),
]
RANK_TID = "c_rank"
RANK_NAME = "🔥排行榜"

YEAR_ALL = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018",
            "2017", "2016", "2015", "2010", "2005", "2000"]

FILTER_DEF = {
    "电影": {
        "class": ["动作", "喜剧", "爱情", "科幻", "恐怖", "悬疑", "剧情", "战争", "犯罪",
                  "动画", "奇幻", "冒险", "灾难", "纪录片", "历史", "武侠", "青春", "家庭",
                  "古装", "运动"],
        "area": ["中国大陆", "美国", "韩国", "日本", "英国", "法国", "中国香港", "中国台湾",
                 "泰国", "印度", "俄罗斯", "加拿大", "澳大利亚", "德国", "西班牙", "意大利"],
        "year": YEAR_ALL + ["1995", "1990"],
    },
    "剧集": {
        "class": ["国产剧", "欧美剧", "美剧", "英剧", "日韩剧", "韩剧", "日剧", "港台剧",
                  "香港剧", "台湾剧", "电视剧", "古装", "悬疑", "都市", "爱情", "犯罪",
                  "战争", "奇幻", "喜剧"],
        "area": ["中国大陆", "美国", "韩国", "日本", "英国", "中国香港", "中国台湾", "泰国",
                 "法国", "加拿大"],
        "year": YEAR_ALL,
    },
    "动漫": {
        "class": ["日本动漫", "国产动漫", "欧美动漫", "国创（B站）", "动画", "热血", "奇幻",
                  "冒险", "恋爱", "搞笑", "科幻", "儿童", "亲子", "魔幻", "悬疑", "武侠",
                  "古装", "真人"],
        "area": ["日本", "中国大陆", "美国", "英国", "韩国", "加拿大", "法国"],
        "year": YEAR_ALL,
    },
    "综艺": {
        "class": ["大陆综艺", "日韩综艺", "欧美综艺", "港台综艺", "真人秀", "脱口秀", "选秀",
                  "音乐", "竞技", "晚会", "明星", "情感", "搞笑", "文化", "戏曲"],
        "area": ["中国大陆", "韩国", "日本", "美国", "英国", "中国香港", "中国台湾", "泰国"],
        "year": ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018",
                 "2017", "2016", "2015", "2010"],
    },
}

SORTS = [("", "默认"), ("hot", "最热"), ("score", "评分"), ("time", "最新")]

# 显示名 → 真实 vodFrom（decode 接口只认真实 from，传显示名会返回"未知的vodFrom类型"）
FRM_ALIAS = {
    "ZJ4K": "zijianm3u8", "BB蓝光": "BBA", "QS蓝光": "qsvip",
    "ZY蓝光": "zy1080_01", "JD4K": "JD4K", "TM蓝光": "tmdb", "NBY": "NBY",
}
# token 前缀 → 真实 vodFrom（从 token 自身反推，比线路名更可靠）
TOK_FRM = {"zijian": "zijianm3u8", "qqqq": "BBA", "qsvip": "qsvip",
           "JD": "JD4K", "tmdb": "tmdb", "NBY": "NBY"}


# ---------------- 纯标准库 AES-256（只为解 App 端点配置，GCM 数据段=CTR） ----------------
def _xt(a):
    a <<= 1
    return (a ^ 0x1b) & 0xff if a & 0x100 else a


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _gpow(a, n):
    r = 1
    while n:
        if n & 1:
            r = _gmul(r, a)
        a = _gmul(a, a)
        n >>= 1
    return r


def _mk_sbox():
    box = [0] * 256
    for i in range(256):
        x = _gpow(i, 254) if i else 0
        s = x
        for _ in range(4):
            x = ((x << 1) | (x >> 7)) & 0xff
            s ^= x
        box[i] = s ^ 0x63
    return box


_SBOX = _mk_sbox()


def _aes_expand(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rc = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rc
            rc = _xt(rc)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _aes_block(w, nr, blk):
    s = [[blk[4 * c + r] ^ w[c][r] for c in range(4)] for r in range(4)]
    for rnd in range(1, nr + 1):
        s = [[_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        if rnd != nr:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _gmul(a[0], 2) ^ _gmul(a[1], 3) ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ _gmul(a[1], 2) ^ _gmul(a[2], 3) ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ _gmul(a[2], 2) ^ _gmul(a[3], 3)
                s[3][c] = _gmul(a[0], 3) ^ a[1] ^ a[2] ^ _gmul(a[3], 2)
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[4 * c + r] = s[r][c]
    return bytes(out)


def _aes_ctr(key, nonce, data):
    w, nr = _aes_expand(key)
    ctr = int.from_bytes(nonce + b"\x00\x00\x00\x01", "big") + 1
    out = bytearray()
    for off in range(0, len(data), 16):
        ks = _aes_block(w, nr, ctr.to_bytes(16, "big"))
        chunk = data[off:off + 16]
        out.extend(bytes(a ^ b for a, b in zip(chunk, ks)))
        ctr += 1
    return bytes(out)


def _b64u(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4))


class Spider(object):
    def __init__(self):
        self.host = None
        self.port = 443
        self.mem = {}

    # ---------------- TVBox 契约 ----------------
    def getName(self):
        return "小鸡看看"

    def isVideoFormat(self, url):
        # 站内只出 m3u8/mp4 直链，无 pics:// 图集线路
        if not url:
            return False
        return not url.startswith("pics://")

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return []

    def isVip(self):
        return False

    def getHeaders(self):
        return {"User-Agent": PLAY_UA}

    def init(self, extend=""):
        return

    # ---------------- 签名 ----------------
    def _sig_headers(self, dev=None):
        dev = dev or DEVICE
        ts = int(time.time() * 1000)
        nonce = hashlib.sha256(dev.encode()).hexdigest()[:8]
        nonce += ''.join([str(random.randint(0, 9)) for _ in range(8)])
        raw = "finger=%s&id=%s&nonce=%s&sk=%s&time=%s&v=%s" % (
            FINGER, APP_ID, nonce, SK, str(ts), APP_VER)
        sign = hashlib.sha256(raw.encode()).hexdigest().upper()
        return {
            "x-aid": APP_ID,
            "x-ave": APP_VER,
            "x-time": str(ts),
            "x-nonc": nonce,
            "x-sign": sign,
            "x-device-id": dev,
            "x-device-brand": "Xiaomi",
            "x-device-model": "M2012K11AC",
            "x-client-type": "tv",
            "x-update-id": "embedded",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": UA,
        }

    # ---------------- HTTP ----------------
    def _raw(self, host, port, path, headers, timeout=15):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if port == 443:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        enc = (resp.getheader("Content-Encoding") or "").lower()
        if "gzip" in enc:
            try:
                body = gzip.decompress(body)
            except Exception:
                pass
        conn.close()
        return resp.status, body

    def _api(self, path, params=None, retry=True, ok_codes=(200,)):
        if params:
            qs = urllib.parse.urlencode(params)
            path = path + ("&" if "?" in path else "?") + qs
        base = list(HOSTS)
        if self.host:
            base = [(self.host, self.port)] + [h for h in HOSTS if h[0] != self.host]
        order = list(base)
        last = ""
        tries = 0
        rots = 0
        conn_fail = 0
        while tries < 2:
            tries += 1
            for host, port in order:
                # 每次请求轮换取设备号：把配额压力摊到整个池上（几千人共用也不挤爆单枚）
                dev = _dev_get()
                for att in range(3):
                    try:
                        st, body = self._raw(host, port, path, self._sig_headers(dev))
                        conn_fail = 0
                        if st != 200:
                            last = "http %s" % str(st)
                            break
                        txt = body.decode("utf-8", "replace").strip()
                        if not txt.startswith("{"):
                            last = "bad body"
                            break
                        obj = json.loads(txt)
                        if obj.get("code") not in ok_codes:
                            last = str(obj.get("msg"))
                            if obj.get("code") == 401:
                                break
                            if obj.get("code") == 429 or obj.get("error_code") == 42901:
                                # 本设备今日配额耗尽 → 拉黑换号立刻重试（次数无上限）
                                rots += 1
                                dev = _dev_fail(dev)
                                if rots > 20:
                                    return None
                                print("[xjk] 429 -> rotate#%d %s" % (rots, dev[:18]))
                                continue
                            return None
                        self.host, self.port = host, port
                        _dev_ok(dev)
                        return obj.get("data")
                    except Exception as e:
                        # 连接层抖动（ConnectionAborted/超时）→ 指数退避重试
                        last = str(e)[:60]
                        conn_fail += 1
                        if att < 2:
                            time.sleep(0.35 * (att + 1))
                if last.startswith("http") or last == "bad body":
                    continue
            # 全部端点失败 → 走一次端点自愈再试
            if tries == 1:
                time.sleep(0.5)
                new = self._refresh_hosts()
                if new:
                    HOSTS[:] = new if new[0][0] != HOSTS[0][0] else HOSTS
                    base = list(HOSTS)
                order = base if not self.host else [self.host and (self.host, self.port)] + \
                    [h for h in base if h[0] != self.host]
                order = [x for x in order if x]
        if last:
            print("[xjk]", path[:50], "fail:", last)
        return None

    # ---------------- 工具 ----------------
    @staticmethod
    def _s(v, dft=""):
        if v is None:
            return dft
        if isinstance(v, (list, tuple)):
            return ",".join([str(x) for x in v if x])
        return str(v)

    @staticmethod
    def _is_url(u):
        # 真正的 URL 判据：协议 + 主机名，而不是松散的 startswith
        return bool(u) and len(u) > 10 and "://" in u and bool(urllib.parse.urlparse(u).hostname)

    def _pic(self, v):
        pic = v.get("vod_pic") or ""
        if self._is_url(pic):
            return pic
        dou = v.get("vod_douban_pic") or ""
        if self._is_url(dou):
            return "proxy://do=py&type=img&url=" + urllib.parse.quote(dou, safe="")
        return ""

    def _vod(self, v):
        return {
            "vod_id": str(v.get("vod_id")),
            "vod_name": self._s(v.get("vod_name")),
            "vod_pic": self._pic(v),
            "vod_remarks": self._s(v.get("vod_remarks")),
            "vod_year": self._s(v.get("vod_year")),
            "vod_area": self._s(v.get("vod_area")),
            "vod_class": self._s(v.get("vod_class")),
            "vod_actor": self._s(v.get("vod_actor")),
            "vod_director": self._s(v.get("vod_director")),
            "vod_content": self._s(v.get("vod_content")),
            "type_name": self._s(v.get("type_name")),
        }

    # ---------------- 端点自愈 ----------------
    def _refresh_hosts(self):
        """主域名全挂时，按 App 同款流程从公开配置页解出新 API 端点。"""
        for src in ENDPOINT_SOURCES:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                pu = urllib.parse.urlparse(src)
                conn = http.client.HTTPSConnection(pu.hostname, 443, timeout=12, context=ctx)
                conn.request("GET", pu.path + ("?" + pu.query if pu.query else ""),
                             headers={"User-Agent": PLAY_UA})
                resp = conn.getresponse()
                txt = resp.read().decode("utf-8", "replace")
                conn.close()
                m = re.search(r"TVAPP_CONFIG_V1_BEGIN([\s\S]*?)TVAPP_CONFIG_V1_END", txt)
                if not m:
                    continue
                raw = _b64u(m.group(1))
                if len(raw) < 96 or raw[0] != 1:
                    continue
                aad = EP_AAD.encode() + raw[0:3]
                plain = _aes_ctr(base64.b64decode(EP_AES_KEY), raw[3:15], raw[15:])
                body = plain[64:]
                if len(body) > 16:
                    body = body[:-16]      # 尾部 16 字节是 GCM tag，不在明文里
                obj = json.loads(body.decode("utf-8", "replace"))
                urls = obj.get("a") or []
                found = []
                for u in urls:
                    pu2 = urllib.parse.urlparse(u)
                    if pu2.hostname:
                        found.append((pu2.hostname, pu2.port or 443))
                if found:
                    print("[xjk] endpoint refresh:", found)
                    return found
            except Exception as e:
                print("[xjk] refresh err", str(e)[:60])
        return []

    # ---------------- 分类筛选 ----------------
    def _filters(self):
        out = {}
        for tid, _name, tname in CATS:
            dims = FILTER_DEF.get(tname) or {}
            arr = []
            for key, label in (("class", "类型"), ("area", "地区"), ("year", "年份")):
                vals = dims.get(key) or []
                if not vals:
                    continue
                opts = [{"n": "全部", "v": ""}]
                for v in vals:
                    opts.append({"n": v, "v": v})
                arr.append({"key": key, "name": label, "value": opts})
            srt = [{"n": "默认", "v": ""}]
            for v, n in SORTS[1:]:
                srt.append({"n": n, "v": v})
            arr.append({"key": "sort", "name": "排序", "value": srt})
            out[tid] = arr
        return out

    # ---------------- 首页 ----------------
    def homeContent(self, filter=False):
        result = {"class": [], "list": [], "filters": {}}
        for tid, name, _ in CATS:
            result["class"].append({"type_id": tid, "type_name": name})
        result["class"].append({"type_id": RANK_TID, "type_name": RANK_NAME})
        data = self._api("/api.php/app/index/home")
        vods = []
        if isinstance(data, dict):
            seen = set()
            for v in (data.get("recommend") or []):
                vid = str(v.get("vod_id"))
                if vid in seen:
                    continue
                seen.add(vid)
                vods.append(self._vod(v))
            for c in (data.get("categories") or []):
                for v in (c.get("videos") or []):
                    vid = str(v.get("vod_id"))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    vods.append(self._vod(v))
        result["list"] = vods
        result["filters"] = self._filters()
        if filter:
            return result
        return result

    def homeVideoContent(self):
        return {"list": self.homeContent(False).get("list") or []}

    # ---------------- 分类 ----------------
    def _rank_list(self):
        data = self._api("/api.php/app/ranking/list")
        vods = []
        if isinstance(data, dict):
            for rk in (data.get("rankings") or []):
                tname = self._s(rk.get("type_name"))
                for v in (rk.get("videos") or []):
                    item = self._vod(v)
                    if tname and not item.get("vod_remarks"):
                        item["vod_remarks"] = tname
                    vods.append(item)
        return vods

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        extend = extend or {}
        result = {"list": [], "page": pg, "pagecount": 999, "limit": 30, "total": 0}
        if tid == RANK_TID or str(tid).startswith("c_rank"):
            if pg > 1:
                result["list"] = []
                result["pagecount"] = 1
                return result
            result["list"] = self._rank_list()
            result["pagecount"] = 1
            result["total"] = len(result["list"])
            return result

        tname = ""
        for cid, _n, tn in CATS:
            if cid == tid:
                tname = tn
                break
        if not tname:
            tname = self._s(tid)
        params = {"type_name": tname, "page": pg, "limit": 30}
        c = self._s(extend.get("class")).strip()
        a = self._s(extend.get("area")).strip()
        y = self._s(extend.get("year")).strip()
        s = self._s(extend.get("sort")).strip()
        if c:
            params["class"] = c
        if a:
            params["area"] = a
        if y:
            params["year"] = y
        if s:
            params["sort"] = s
        data = self._api("/api.php/app/filter/vod", params)
        if isinstance(data, list):
            result["list"] = [self._vod(v) for v in data]
            result["total"] = len(result["list"])
            # 站方深翻页封顶 1000 条（limit=30 → 最多 34 页），算出真实页数
            pc = int(1000 / 30)
            if len(result["list"]) < 30:
                pc = pg
            result["pagecount"] = max(1, pc)
        else:
            result["pagecount"] = pg
        return result

    # ---------------- 详情 ----------------
    def _playback_all(self, vid):
        """一次拉全线路分集。
        ★坑：接口带 from 参数会被忽略并只回 BBA 线路，导致其它线路拿到 BBA 的 token
        → 播放时 vodFrom 与 token 不匹配，decode 返回"未知的vodFrom类型"★
        """
        data = self._api("/api.php/app/vod/playback_v2", {"vod_id": vid})
        out = {}
        if not isinstance(data, dict):
            return out
        for src in (data.get("sources") or []):
            f = src.get("from")
            eps = src.get("episodes") or []
            if f and eps:
                out[f] = eps
        return out

    def _playback(self, vid, frm="", _cache=None):
        allsrc = _cache if isinstance(_cache, dict) else self._playback_all(vid)
        if frm:
            return frm, allsrc.get(frm) or []
        for f, eps in allsrc.items():
            return f, eps
        return frm, []

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        vid = str(vid)
        data = self._api("/api.php/app/vod/detail_v2", {"vod_id": vid})
        if not isinstance(data, dict):
            return {"list": []}
        det = data.get("detail") or {}
        pb = data.get("playback") or {}
        vod = self._vod(det)
        vod["vod_id"] = vid

        lines = []       # [(display_name, from, episodes)]
        srcs = pb.get("sources") or []
        sel = pb.get("selected_source") or {}
        sel_from = sel.get("from") or ""
        order = []
        if sel_from:
            order.append(sel_from)
        for s in srcs:
            f = s.get("from")
            if not f or f in order:
                continue
            if (s.get("episode_count") or 0) <= 0 and not (s.get("episodes") or []):
                continue
            order.append(f)
        names = {}
        for s in srcs:
            names[s.get("from")] = self._s(s.get("display_name"))
        # 一次拉全线路分集（带 from 会因为服务端忽略参数而串线，见 _playback_all 注释）
        got = {}
        try:
            got = self._playback_all(vid)
        except Exception as e:
            print("[xjk] playback", e)
        for f in order:
            eps = got.get(f) or []
            if not eps and f == sel_from:
                eps = sel.get("episodes") or []
            if not eps:
                continue
            lines.append((names.get(f) or f, f, eps))

        # 线路排序：已验证可播的线路优先，已知 403 的线路（shenhua7）压到末尾并标注
        def _rank(f):
            return 1 if f == "qsvip" else 0
        lines.sort(key=lambda x: _rank(x[1]))
        for idx, (nm, f, eps) in enumerate(lines):
            if f == "qsvip":
                lines[idx] = ("%s(可能失效)" % nm, f, eps)

        froms = []
        urls = []
        for nm, f, eps in lines:
            froms.append(nm or f)
            cells = []
            for i, e in enumerate(eps):
                title = self._s(e.get("title")) or ("第%d集" % (i + 1))
                tok = self._s(e.get("url"))
                if not tok:
                    continue
                cells.append("%s$%s@@%s" % (title, tok, f))
            urls.append("#".join(cells))
        if froms:
            vod["vod_play_from"] = "$$$".join(froms)
            vod["vod_play_url"] = "$$$".join(urls)

        # 分集缓存：按集序把各线路 token 存起来，播放失败时能自动换线路（_alt_episode 用）
        try:
            rec = {}
            for nm, f, eps in lines:
                for i, e in enumerate(eps):
                    t = self._s(e.get("url"))
                    if t:
                        rec.setdefault(i, []).append((f, t))
            cache = getattr(self, "_eps_cache", None)
            if not isinstance(cache, dict):
                cache = {}
            cache[vid] = rec
            # 只留最近 8 部，防内存膨胀（几千人共用一台设备的长跑场景）
            while len(cache) > 8:
                cache.pop(next(iter(cache)))
            self._eps_cache = cache
        except Exception as e:
            print("[xjk] cache", e)

        return {"list": [vod]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        pg = int(pg) if str(pg).isdigit() else 1
        data = self._api("/api.php/app/search/index",
                         {"wd": key, "page": pg, "limit": 30})
        vods = []
        if isinstance(data, list):
            vods = [self._vod(v) for v in data]
        return {"list": vods, "page": pg, "pagecount": 999 if len(vods) >= 30 else pg}

    # ---------------- 播放 ----------------
    def _decode(self, tok, frm, _retry=0):
        """解析播放令牌 → 真直链。
        _api 内部已做「轮转取设备号 + 429 换号 + 连接退避」，
        这里再包一层整调用重试，扛住服务端瞬时抖动（几千人共用时的常态）。
        """
        data = self._api("/api.php/app/decode/url/",
                         {"url": tok, "vodFrom": frm, "_t": int(time.time() * 1000)},
                         ok_codes=(1, 200))
        if isinstance(data, str) and self._is_url(data):
            return data
        # 服务端有时把未识别线路原样返回（data == token），换线路名也没用 → 重试一次
        if _retry < 2:
            time.sleep(0.4 * (_retry + 1))
            return self._decode(tok, frm, _retry + 1)
        return ""

    def playerContent(self, flag, id, vipFlags=None):
        tok = self._s(id)
        frm = ""
        if "@@" in tok:
            tok, frm = tok.rsplit("@@", 1)
        tok = tok.strip()
        # 线路名多层纠错（decode 只认真实 vodFrom，错了就返回"未知的vodFrom类型"）
        cands = []
        if frm:
            cands.append(FRM_ALIAS.get(frm, frm))
        t = self._frm_from_token(tok)
        if t:
            cands.append(t)
        fl = self._s(flag)
        if fl:
            cands.append(FRM_ALIAS.get(fl, fl))
        cands.append("")
        url = ""
        seen = set()
        for f in cands:
            if f in seen:
                continue
            seen.add(f)
            url = self._decode(tok, f)
            if url:
                break
        if not url:
            # 兜底：本条线路解析失败 → 到其它线路取「同名集」，保证一定播得出来
            alt = self._alt_episode(tok)
            if alt:
                header = {"User-Agent": PLAY_UA}
                if "shenhua7.vip" in alt:
                    header["Referer"] = "https://www.shenhua7.vip/"
                return {"parse": 0, "playUrl": "", "url": alt, "header": header}
            return {"parse": 1, "playUrl": "", "url": tok,
                    "header": {"User-Agent": PLAY_UA}}
        header = {"User-Agent": PLAY_UA}
        if "shenhua7.vip" in url:
            header["Referer"] = "https://www.shenhua7.vip/"
        return {"parse": 0, "playUrl": "", "url": url, "header": header}

    def _alt_episode(self, tok):
        """同一集在其它线路取真直链：detail 里已把每集 token 按线路存下来，
        用「集名」跨线路配对的成本太高，这里直接按 token 反查所属影片不可行，
        改为：本进程最近一次 detailContent 的分集表里找同一集序号的其它线路。"""
        try:
            cache = getattr(self, "_eps_cache", None) or {}
            for vid, rec in cache.items():
                for pos, toks in rec.items():
                    for f, t in toks:
                        if t == tok:
                            for f2, t2 in toks:
                                if f2 == f:
                                    continue
                                u = self._decode(t2, f2)
                                if u:
                                    print("[xjk] fallback line %s -> %s" % (f, f2))
                                    return u
                            return ""
        except Exception as e:
            print("[xjk] alt", e)
        return ""

    @staticmethod
    def _frm_from_token(tok):
        """从 token 前缀推断真实 vodFrom（decode 接口按前缀判线路）。"""
        p = (tok.split("-", 1)[0] or "")
        if p and len(p) <= 14:
            return TOK_FRM.get(p, "")
        return ""

    # ---------------- 图片代理 ----------------
    def localProxy(self, param):
        try:
            raw = param if isinstance(param, str) else urllib.parse.urlencode(param)
            if raw.startswith("proxy://"):
                raw = raw[len("proxy://"):]
            qs = urllib.parse.parse_qs(raw)
            url = (qs.get("url") or [""])[0]
            typ = (qs.get("type") or [""])[0]
            if not url:
                return [404, "text/plain", {}, b"no url"]
            if typ != "img":
                return [404, "text/plain", {}, b"bad type"]
            pu = urllib.parse.urlparse(url)
            if not pu.hostname:
                return [404, "text/plain", {}, b"bad url"]
            headers = {
                "User-Agent": PLAY_UA,
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            }
            if "doubanio" in pu.hostname or "douban" in pu.hostname:
                headers["Referer"] = "https://movie.douban.com/"
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(pu.hostname, pu.port or 443,
                                               timeout=15, context=ctx)
            path = (pu.path or "/") + ("?" + pu.query if pu.query else "")
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            ctype = resp.getheader("Content-Type") or "image/jpeg"
            conn.close()
            if resp.status == 200 and body:
                return [200, ctype, {}, body]
            return [404, "text/plain", {}, b"fetch failed"]
        except Exception as e:
            print("[xjk] proxy", e)
            return [404, "text/plain", {}, b"err"]
