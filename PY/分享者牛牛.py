# -*- coding: utf-8 -*-
"""
牛牛视频 (com.qingbian.jz v1.6.3) TVBox / FongMi py 源

接口说明（逆向自官方 App）:
- 片库主接口: 域名由 https://nnal.oss-cn-beijing.aliyuncs.com/nn.php 下发
  (AES/ECB 密钥 @@bull!!!video$$ 解密), 接口 /types /list /detail /main /config,
  响应为 AES/ECB 加密 (密钥 = 请求 path?query 前 16 字符, 不足补 '0') 或明文 JSON。
- 播放: 多数源为直连 m3u8; 小草/牛牛(xiaocao/xm3u8) 走天际 SP 接口
  (/api/new_public/init_v2 + /api/new_video/result_v2 + /api/new_video/collection_v2,
   签名 MD5(salt+device_id+cur_time) 大写, 响应 AES/CBC 解密);
  臻享(shizi) 走真香解析接口一步出 m3u8; 其余 ID 型源做尽力解析。

兼容 T3/T4 壳: 有壳 fetch 时优先用, 否则 urllib; AES 为纯 Python 实现, 不依赖 Crypto。
"""

import base64
import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as _BaseSpider
except Exception:  # 壳外调试
    class _BaseSpider(object):
        pass


# ---------------------------------------------------------------------------
# 纯 Python AES (仅解密, 支持 128/192/256, ECB/CBC) —— 避免依赖 Crypto
# ---------------------------------------------------------------------------

def _gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _build_sboxes():
    sbox = [0] * 256
    inv = [0] * 256
    for x in range(256):
        # GF(2^8) 乘法逆元
        y = 0
        if x:
            y = 1
            base, exp = x, 254
            r = 1
            b = base
            e = exp
            while e:
                if e & 1:
                    r = _gf_mul(r, b)
                b = _gf_mul(b, b)
                e >>= 1
            y = r
        s = y
        for i in range(4):
            s ^= ((y << (i + 1)) | (y >> (7 - i))) & 0xFF
        s ^= 0x63
        sbox[x] = s & 0xFF
        inv[s & 0xFF] = x
    return sbox, inv


_SBOX, _INV_SBOX = _build_sboxes()
_M9 = [_gf_mul(x, 9) for x in range(256)]
_M11 = [_gf_mul(x, 11) for x in range(256)]
_M13 = [_gf_mul(x, 13) for x in range(256)]
_M14 = [_gf_mul(x, 14) for x in range(256)]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
         0x6C, 0xD8, 0xAB, 0x4D]


def _aes_expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = [_SBOX[t[1]] ^ _RCON[i // nk - 1], _SBOX[t[2]],
                 _SBOX[t[3]], _SBOX[t[0]]]
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _aes_decrypt_block(block, w, nr):
    # state 按列优先: s[r][c] = block[c*4+r]
    s = [[block[c * 4 + r] for c in range(4)] for r in range(4)]

    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    def inv_shift_rows():
        for r in range(1, 4):
            row = [s[r][c] for c in range(4)]
            for c in range(4):
                s[r][c] = row[(c - r) % 4]

    def inv_sub_bytes():
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]

    def inv_mix_columns():
        for c in range(4):
            a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
            s[0][c] = _M14[a0] ^ _M11[a1] ^ _M13[a2] ^ _M9[a3]
            s[1][c] = _M9[a0] ^ _M14[a1] ^ _M11[a2] ^ _M13[a3]
            s[2][c] = _M13[a0] ^ _M9[a1] ^ _M14[a2] ^ _M11[a3]
            s[3][c] = _M11[a0] ^ _M13[a1] ^ _M9[a2] ^ _M14[a3]

    add_round_key(nr)
    for rnd in range(nr - 1, 0, -1):
        inv_shift_rows()
        inv_sub_bytes()
        add_round_key(rnd)
        inv_mix_columns()
    inv_shift_rows()
    inv_sub_bytes()
    add_round_key(0)
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = s[r][c]
    return bytes(out)


try:
    from Crypto.Cipher import AES as _CryptoAES
except Exception:
    _CryptoAES = None


def aes_decrypt(data, key, iv=None):
    """AES 解密 (ECB: iv=None; CBC: iv=16 bytes), 自动去 PKCS7 填充。"""
    if not data or len(data) % 16:
        return b""
    if _CryptoAES is not None:
        try:
            if iv is None:
                dec = _CryptoAES.new(key, _CryptoAES.MODE_ECB).decrypt(data)
            else:
                dec = _CryptoAES.new(key, _CryptoAES.MODE_CBC, iv).decrypt(data)
            if dec:
                pad = dec[-1]
                if 0 < pad <= 16 and len(dec) >= pad:
                    dec = dec[:-pad]
            return dec
        except Exception:
            pass
    w, nr = _aes_expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = _aes_decrypt_block(blk, w, nr)
        if prev is not None:
            dec = bytes(a ^ b for a, b in zip(dec, prev))
            prev = blk
        out.extend(dec)
    if out:
        pad = out[-1]
        if 0 < pad <= 16 and len(out) >= pad:
            out = out[:-pad]
    return bytes(out)


# ---------------------------------------------------------------------------
# 源主体
# ---------------------------------------------------------------------------

_NN_DISCOVERY = [
    "https://nnal.oss-cn-beijing.aliyuncs.com/nn.php",
    "https://nn-1352193558.cos.ap-guangzhou.myqcloud.com/nn.php",
]
_NN_FALLBACK_HOSTS = [
    "https://ccc.chaojichaojichanga.com:35620",
    "https://kkksss.yuechangyuehao.com:35820",
    "https://ccc.zhegeyoudianchang.com:35620",
]
_UA = "okhttp/4.11.0"

# 播放源展示名兜底 (运行时优先用 /config 的 parser 列表)
_PLAYER_ALIAS = {
    "bfzy": "暴风资源", "lzzy": "量子资源", "ffzy": "非凡资源",
    "snzy": "索尼资源", "kkzy": "豪华资源", "tkzy": "天空资源",
    "jszy": "极速资源", "jyzy": "金鹰资源", "jm3u8": "人人资源",
    "hm3u8": "人人资源", "xm": "牛牛资源", "xm3u8": "牛牛资源",
    "xiaocao": "小草资源", "hema": "河马资源", "shizi": "臻享线路",
    "juzi": "橘子资源", "shanju": "蓝光资源", "ningmeng": "秒播资源",
    "madou": "牛牛视频", "pp": "牛牛视频", "dle": "牛牛视频",
    "jzzy": "牛牛资源", "hmjc": "牛牛资源", "thzy": "牛牛资源",
     "meiju": "热舞资源", "djzy": "牛牛短剧",
    "qyzy": "牛牛短剧", "bddj": "短剧", "qmdj": "短剧",
    "douban": "预告片", "zbjx": "牛牛直播",
    "paopao": "AI短剧",  "yunbo": "云播",
}

# 小草 SP (src7 天际) 兜底配置, 运行时优先 /config
_XC_FALLBACK = {
    "tokenUrl": "https://u.yyxdmn.com/api/new_public/init_v2",
    "listUrl": "https://u.yyxdmn.com/api/new_video/result_v2",
    "detailUrl": "https://u.yyxdmn.com/api/new_video/collection_v2",
    "key": "aZ9$kU5%qI7=yC2=zH2#gM0@pX7^wF3a",
    "iv": "hY2&tN3]kF7,dL7=",
    "salt": "zD9[bM4~sF4~uY2)",
    "headers": {"version": "51000", "app_id": "tianjishipin",
                "channel_code": "tjsp_sp01", "package_name": "com.wfighter.zmz",
                "sysrelease": "10", "User-Agent": "okhttp/4.11.0"},
}
_ZHENXIANG_FALLBACK = "http://116.211.150.40:856/zhenxiang/jx.php?id="
_SJ_FALLBACK = "http://116.211.150.40:856/jx/sj.php?id="

_BUNDLED_CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "剧集"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
    {"type_id": "5", "type_name": "短剧"},
    {"type_id": "11", "type_name": "直播"},
    {"type_id": "10", "type_name": "热舞"},
]


# 播放器 -> 额外的后端解析接口 (src 编号), 模板失败时继续试
_SRC_BACKEND = {
    "madou": "src4",     # 吃瓜
    "paopao": "src11",   # AI短剧
}
_SRC_FALLBACK = {
    "src4": "http://116.211.150.40:5231/cg/jx.php?id=",
    "src11": "http://116.211.150.40:856/duanju/dj.php?id=",
}


class Spider(_BaseSpider):

    def __init__(self):
        super().__init__()
        self._nn_hosts = None
        self._config = None
        self._parser_map = {}
        self._types_cache = None
        self._device_id = hashlib.md5(
            ("niuniu" + str(time.time())).encode()).hexdigest()[:16]
        self._xc_token = ""
        self._xc_eps = {}       # sp vod_id -> (ts, {collection_str: ep})
        self._probe_cache = {}  # url -> (ts, alive)
        self._ext_host = ""

    def getName(self):
        return "牛牛视频"

    def init(self, extend=""):
        try:
            if extend:
                ext = extend if isinstance(extend, dict) else json.loads(extend)
                if isinstance(ext, dict):
                    self._ext_host = (ext.get("host") or "").rstrip("/")
        except Exception:
            pass
        return None

    def destroy(self):
        return None

    # ------------------------- HTTP 基础 -------------------------

    def _http(self, url, headers=None, data=None, timeout=12):
        """返回响应文本。urllib 优先 (表单 POST 必须走 urllib,
        壳 fetch 多半只支持 GET), 失败时回退壳 fetch。"""
        headers = headers or {}
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
        try:
            req = urllib.request.Request(
                url, data=body, headers=headers,
                method="POST" if data is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return raw.decode("utf-8", "ignore")
        except Exception:
            pass
        fetch = getattr(self, "fetch", None)
        if callable(fetch):
            try:
                r = fetch(url, headers)
                txt = self._fetch_text(r)
                if txt is not None:
                    return txt
            except Exception:
                pass
        raise IOError("http failed: " + url)

    @staticmethod
    def _fetch_text(r):
        if r is None:
            return None
        if isinstance(r, str):
            return r
        if isinstance(r, bytes):
            return r.decode("utf-8", "ignore")
        if isinstance(r, dict):
            for k in ("content", "text", "body", "data"):
                if isinstance(r.get(k), (str, bytes)):
                    return Spider._fetch_text(r[k])
            return None
        for attr in ("text", "content"):
            v = getattr(r, attr, None)
            if isinstance(v, (str, bytes)):
                return Spider._fetch_text(v)
        return None

    # ------------------------- 片库主接口 -------------------------

    def _nn_hosts_list(self):
        if self._nn_hosts:
            return self._nn_hosts
        hosts = []
        if self._ext_host:
            hosts.append(self._ext_host)
        for url in _NN_DISCOVERY:
            try:
                txt = self._http(url, {"User-Agent": _UA}, timeout=8)
                dec = aes_decrypt(base64.b64decode(txt.strip()),
                                   b"@@bull!!!video$$")
                for line in dec.decode("utf-8", "ignore").splitlines():
                    line = line.strip().rstrip("/")
                    if line.startswith("http") and line not in hosts:
                        hosts.append(line)
            except Exception:
                continue
            if hosts:
                break
        for h in _NN_FALLBACK_HOSTS:
            if h not in hosts:
                hosts.append(h)
        self._nn_hosts = hosts
        return hosts

    def _nn_api(self, path, params=None):
        """调用片库接口, 返回 data 字段 (失败返回 None)。"""
        params = params or {}
        query = urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        hosts = self._nn_hosts_list()
        ordered = hosts
        if getattr(self, "_nn_ok", None) in hosts:
            ordered = [self._nn_ok] + [h for h in hosts if h != self._nn_ok]
        for host in ordered:
            url = host + path + ("?" + query if query else "")
            try:
                txt = self._http(url, self._nn_headers(), timeout=12)
            except Exception:
                continue
            obj = self._nn_decode(txt, path, query)
            if obj is not None:
                self._nn_ok = host
                return obj.get("data")
        return None

    def _nn_headers(self):
        return {
            "p": "android",
            "pkg": "com.qingbian.jz",
            "t": "",
            "d": self._device_id,
            "v": "1.6.3",
            "y": "0",
            "product": "Pixel",
            "os": "13",
            "User-Agent": _UA,
        }

    @staticmethod
    def _nn_decode(txt, path, query):
        if not txt:
            return None
        txt = txt.strip()
        try:
            return json.loads(txt)
        except Exception:
            pass
        keysrc = path + ("?" + query if query else "")
        key = keysrc.encode("utf-8")[:16].ljust(16, b"0")
        try:
            dec = aes_decrypt(base64.b64decode(txt), key)
            return json.loads(dec.decode("utf-8", "ignore"))
        except Exception:
            return None

    def _remote_config(self):
        if self._config is not None:
            return self._config
        self._config = {}
        try:
            data = self._nn_api("/config")
            if isinstance(data, dict):
                self._config = data
                for p in data.get("parser") or []:
                    pid = p.get("player_id")
                    if pid:
                        self._parser_map[pid] = p
        except Exception:
            pass
        return self._config

    def _player_name(self, player_id):
        p = self._parser_map.get(player_id) or {}
        name = p.get("player_name") or _PLAYER_ALIAS.get(player_id) or player_id
        return name.strip() or player_id

    # ------------------------- 首页 / 分类 / 搜索 -------------------------

    def _types(self):
        if self._types_cache is not None:
            return self._types_cache
        classes = []
        for _ in range(2):
            try:
                data = self._nn_api("/types")
                if isinstance(data, list) and data:
                    for t in data:
                        classes.append({
                            "type_id": str(t.get("type_id")),
                            "type_name": t.get("type_name") or "",
                            "_extend": t.get("type_extend") or {},
                        })
                    break
            except Exception:
                pass
        if not classes:
            # 接口没拉到时用 App 内置的完整分类兜底, 但不缓存, 下次继续重试
            return [dict(c, _extend={}) for c in _BUNDLED_CLASSES]
        self._types_cache = classes
        return classes

    @staticmethod
    def _filters_of(extend):
        filters = []
        for key, name in (("class", "类型"), ("area", "地区"),
                          ("year", "年份"), ("state", "状态")):
            raw = (extend or {}).get(key) or ""
            vals = [v.strip() for v in str(raw).split(",") if v.strip()]
            if vals:
                filters.append({
                    "key": key, "name": name,
                    "value": [{"n": "全部", "v": ""}] +
                             [{"n": v, "v": v} for v in vals],
                })
        return filters

    def homeContent(self, filter=False):
        try:
            classes = self._types()
            filters = {}
            out_classes = []
            for c in classes:
                out_classes.append({"type_id": c["type_id"],
                                    "type_name": c["type_name"]})
                f = self._filters_of(c.get("_extend"))
                if f:
                    filters[c["type_id"]] = f
            return {"class": out_classes, "filters": filters}
        except Exception:
            return {"class": [dict(c) for c in _BUNDLED_CLASSES], "filters": {}}

    def homeVideoContent(self):
        try:
            data = self._nn_api("/main")
            videos, seen = [], set()
            if isinstance(data, list):
                for sec in data:
                    for v in sec.get("list") or []:
                        vid = str(v.get("vod_id"))
                        if vid in seen:
                            continue
                        seen.add(vid)
                        videos.append(self._video(v))
            if not videos:
                data = self._nn_api("/list", {"type_id": "1", "page": "1"})
                videos = [self._video(v) for v in data or []]
            return {"list": videos}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
            params = {"type_id": str(tid), "page": str(pg)}
            for k in ("class", "area", "year", "state"):
                v = (extend or {}).get(k)
                if v:
                    params[k] = v
            data = self._nn_api("/list", params)
            videos = [self._video(v) for v in data or []]
            pagecount = pg + 1 if len(videos) >= 12 else pg
            return {"list": videos, "page": pg, "pagecount": pagecount,
                    "limit": 12, "total": pagecount * 12}
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1,
                    "limit": 12, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg or 1)
            data = self._nn_api("/list", {"wd": key, "page": str(pg)})
            videos = [self._video(v) for v in data or []]
            return {"list": videos, "page": pg}
        except Exception:
            return {"list": [], "page": int(pg or 1)}

    @staticmethod
    def _video(v):
        return {
            "vod_id": str(v.get("vod_id") or ""),
            "vod_name": v.get("vod_name") or "",
            "vod_pic": v.get("vod_pic") or "",
            "vod_remarks": v.get("vod_remarks") or "",
        }

    # ------------------------- 详情 -------------------------

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, (list, tuple)) else ids
            data = self._nn_api("/detail", {"vod_id": str(vod_id)})
            if not isinstance(data, dict):
                return {"list": []}
            self._remote_config()
            sources = []
            for s in data.get("sources") or []:
                eps = []
                for e in s.get("episodes") or []:
                    raw = e.get("url") or ""
                    eps.append({"name": e.get("name") or "",
                                "raw": raw,
                                "player": s.get("player_id") or ""})
                if eps:
                    sources.append({"player": s.get("player_id") or "",
                                    "prio": s.get("prio") or 0,
                                    "eps": eps})
            sources.sort(key=lambda s: s["prio"])
            sources = self._health_sort(sources)
            self._xc_prefetch(sources)
            play_from, play_url = [], []
            for s in sources:
                play_from.append(self._player_name(s["player"]))
                play_url.append("#".join(
                    "%s$%s|%s" % (e["name"], e["player"], e["raw"])
                    for e in s["eps"]))
            type_name = ""
            for c in self._types():
                if c["type_id"] == str(data.get("type_id")):
                    type_name = c["type_name"]
                    break
            vod = {
                "vod_id": str(data.get("vod_id") or vod_id),
                "vod_name": data.get("vod_name") or "",
                "vod_pic": data.get("vod_pic") or "",
                "vod_remarks": data.get("vod_remarks") or "",
                "vod_year": data.get("vod_year") or "",
                "vod_area": data.get("vod_area") or "",
                "vod_actor": data.get("vod_actor") or "",
                "vod_director": data.get("vod_director") or "",
                "vod_content": re.sub(r"<[^>]+>", "",
                                      data.get("vod_content") or ""),
                "type_name": type_name,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    # 直连线路健康排序: 首集探活, 活的在前死的在后, 不删线路
    def _health_sort(self, sources):
        try:
            targets = []
            for s in sources:
                raw = s["eps"][0]["raw"] if s["eps"] else ""
                if raw.startswith("http") and self._is_media(raw):
                    targets.append((s, raw))
            if len(targets) < 2:
                return sources
            targets = targets[:10]
            alive = {}
            now = time.time()
            todo = []
            for s, raw in targets:
                hit = self._probe_cache.get(raw)
                if hit and now - hit[0] < 1800:
                    alive[id(s)] = hit[1]
                else:
                    todo.append((s, raw))
            if todo:
                try:
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=6) as ex:
                        results = list(ex.map(
                            lambda t: self._probe(t[1]), todo))
                    for (s, raw), ok in zip(todo, results):
                        alive[id(s)] = ok
                        self._probe_cache[raw] = (now, ok)
                except Exception:
                    for s, raw in todo:
                        alive[id(s)] = True
            sources.sort(key=lambda s: (0 if alive.get(id(s), True) else 1,
                                        s["prio"]))
        except Exception:
            pass
        return sources

    @staticmethod
    def _is_media(url):
        u = url.lower().split("?")[0]
        return u.endswith((".m3u8", ".mp4", ".mpd", ".flv", ".ts"))

    def _probe(self, url):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status not in (200, 206):
                    return False
                body = resp.read(1024)
            if url.lower().split("?")[0].endswith((".m3u8", ".mpd")):
                return body.lstrip().startswith(b"#EXT")
            return True
        except Exception:
            return False

    # ------------------------- 小草 SP (天际) -------------------------

    def _xc_conf(self):
        conf = dict(_XC_FALLBACK)
        try:
            cfg = self._remote_config()
            src = cfg.get("src7") or {}
            if src.get("tokenUrl"):
                conf["tokenUrl"] = src["tokenUrl"]
            if src.get("listUrl"):
                conf["listUrl"] = src["listUrl"]
            if src.get("detailUrl"):
                conf["detailUrl"] = src["detailUrl"]
            if src.get("key"):
                conf["key"] = src["key"]
            if src.get("iv"):
                conf["iv"] = src["iv"]
            if src.get("salt"):
                conf["salt"] = src["salt"]
            hdrs = {}
            for h in src.get("headers") or []:
                if h.get("key"):
                    hdrs[h["key"]] = h.get("value") or ""
            if hdrs:
                conf["headers"] = hdrs
        except Exception:
            pass
        return conf

    def _xc_post(self, url, form, conf, token=""):
        cur = str(int(time.time() * 1000))
        sign = hashlib.md5(
            (conf["salt"] + self._device_id + cur).encode()).hexdigest().upper()
        headers = dict(conf["headers"])
        headers.update({
            "log-header": "I am the log request header.",
            "cur_time": cur,
            "device_id": self._device_id,
            "mob_mfr": "google",
            "mobmodel": "Pixel",
            "sys_platform": "2",
            "sign": sign,
            "token": token,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        txt = self._http(url, headers, data=form, timeout=15)
        if not txt:
            return None
        txt = txt.strip()
        try:
            return json.loads(txt)
        except Exception:
            pass
        try:
            dec = aes_decrypt(base64.b64decode(txt),
                              conf["key"].encode(),
                              conf["iv"].encode())
            return json.loads(dec.decode("utf-8", "ignore"))
        except Exception:
            return None

    def _xc_token_get(self, conf, force=False):
        if self._xc_token and not force:
            return self._xc_token
        r = self._xc_post(conf["tokenUrl"],
                          {"invited_by": "", "is_install": "1"}, conf)
        token = ""
        try:
            token = r["result"]["user_info"]["token"]
        except Exception:
            pass
        self._xc_token = token
        return token

    def _xc_episodes(self, sp_vod_id, conf, token):
        hit = self._xc_eps.get(sp_vod_id)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        r = self._xc_post(conf["listUrl"], {"vod_id": sp_vod_id}, conf, token)
        eps = {}
        try:
            for e in r["result"]["vod_collection"] or []:
                eps[str(e.get("collection"))] = e
        except Exception:
            pass
        if eps:
            self._xc_eps[sp_vod_id] = (time.time(), eps)
        return eps

    def _xc_prefetch(self, sources):
        """详情打开时后台预热小草 token + 集数列表, 点播时只剩一次请求。"""
        try:
            sp_vod_id = ""
            for s in sources:
                if s["player"] in ("xiaocao", "xm3u8") and s["eps"]:
                    raw = s["eps"][0]["raw"]
                    if "@" in raw:
                        sp_vod_id = raw.split("@")[0]
                        break
            if not sp_vod_id or sp_vod_id in self._xc_eps:
                return

            def warm():
                try:
                    conf = self._xc_conf()
                    token = self._xc_token_get(conf)
                    if token:
                        self._xc_episodes(sp_vod_id, conf, token)
                except Exception:
                    pass

            t = threading.Thread(target=warm)
            t.daemon = True
            t.start()
        except Exception:
            pass

    def _xc_resolve(self, raw):
        """raw = 'spVodId@集号' -> 真实 m3u8, 失败返回 ''"""
        url = self._xc_resolve_once(raw, force_token=False)
        if not url:
            url = self._xc_resolve_once(raw, force_token=True)
        return url

    def _xc_resolve_once(self, raw, force_token=False):
        try:
            parts = raw.split("@")
            sp_vod_id, coll = parts[0], parts[1]
            conf = self._xc_conf()
            if force_token:
                self._xc_eps.pop(sp_vod_id, None)
            token = self._xc_token_get(conf, force=force_token)
            if not token:
                return ""
            eps = self._xc_episodes(sp_vod_id, conf, token)
            ep = eps.get(coll)
            if not ep:
                return ""
            form = {"collection_id": str(ep.get("id") or ""), "sig": "",
                    "nc_token": "", "code": "", "phone": "",
                    "vod_id": sp_vod_id, "session_id": "",
                    "vod_token": ep.get("vod_token") or "",
                    "cur_time": str(ep.get("cur_time") or int(time.time()))}
            r = self._xc_post(conf["detailUrl"], form, conf, token)
            try:
                return r["result"]["vod_url"] or ""
            except Exception:
                return ""
        except Exception:
            return ""

    # ------------------------- 解析型接口 -------------------------

    def _jx_first_step(self, base_url, raw):
        """GET 解析接口, 返回 dict 或 None"""
        try:
            url = base_url + urllib.parse.quote(raw, safe="@")
            txt = self._http(url, {"User-Agent": "Mozilla/5.0"}, timeout=12)
            if not txt:
                return None
            return json.loads(txt)
        except Exception:
            return None

    @staticmethod
    def _jx_headers(text):
        headers = {}
        for line in re.split(r"\\r\\n|\r\n|\n", text or ""):
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip():
                    headers[k.strip()] = v.strip()
        if "User-Agent" not in headers:
            headers["User-Agent"] = "Mozilla/5.0"
        return headers

    def _zhenxiang_url(self):
        try:
            src = (self._remote_config().get("src10") or {})
            if src.get("yUrl"):
                return src["yUrl"]
        except Exception:
            pass
        return _ZHENXIANG_FALLBACK

    def _sj_url(self):
        try:
            src = (self._remote_config().get("src8") or {})
            if src.get("yUrl"):
                return src["yUrl"]
        except Exception:
            pass
        return _SJ_FALLBACK

    def _jx_resolve(self, raw):
        """臻享一步解析 + 通用多步解析尽力跟随, 返回 (url, headers) 或 ('', {})"""
        data = self._jx_first_step(self._zhenxiang_url(), raw)
        if data and str(data.get("code")) == "200" and data.get("url"):
            return data["url"], self._jx_headers(data.get("headers"))
        # 通用多步: 豆瓣类接口第一步返回下一步 URL
        data = data or self._jx_first_step(self._sj_url(), raw)
        for _ in range(3):
            if not data:
                break
            url = data.get("url") or ""
            if url and self._is_media(url):
                return url, self._jx_headers(data.get("headers"))
            if data.get("type") == "url" and url:
                try:
                    txt = self._http(
                        url, self._jx_headers(data.get("headers")),
                        timeout=12)
                    m = re.search(r"https?://[^\s\"'\\<>]+\.m3u8[^\s\"'\\<>]*",
                                  txt or "")
                    if m:
                        return m.group(0), {}
                    data = json.loads(txt)
                    continue
                except Exception:
                    break
            break
        return "", {}

    # ------------------------- 播放 -------------------------

    def _template_resolve(self, player, raw):
        """播放器自带解析模板/短剧后端: GET 后从 JSON 里取真实媒体地址。"""
        if not self._parser_map:
            self._remote_config()
        templates = []
        src_key = _SRC_BACKEND.get(player)
        if src_key:
            try:
                y = (self._remote_config().get(src_key) or {}).get("yUrl")
                if y:
                    templates.append(y + "%s")
            except Exception:
                pass
            if _SRC_FALLBACK.get(src_key):
                templates.append(_SRC_FALLBACK[src_key] + "%s")
        p = self._parser_map.get(player) or {}
        if p.get("url"):
            templates.append(p["url"])
        for t in templates:
            try:
                if "%s" in t:
                    url = t.replace(
                        "%s", urllib.parse.quote(raw, safe="@"))
                else:
                    url = t + urllib.parse.quote(raw, safe="@")
                txt = self._http(url, {"User-Agent": "Mozilla/5.0"},
                                 timeout=12)
                data = json.loads(txt)
                u = data.get("url") or ""
                if u and self._is_media(u):
                    return u, self._jx_headers(data.get("headers"))
                if data.get("type") == "url" and u.startswith("http"):
                    txt2 = self._http(
                        u, self._jx_headers(data.get("headers")),
                        timeout=12)
                    m = re.search(
                        r"https?://[^\s\"'\\<>]+\.m3u8[^\s\"'\\<>]*",
                        txt2 or "")
                    if m:
                        return m.group(0), {}
            except Exception:
                continue
        return "", {}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            player, _, raw = (id or "").partition("|")
            raw = raw or (id or "")
            if raw.startswith("http"):
                return self._play_http(player, raw)
            # 小草 / 牛牛 SP 源
            if player in ("xiaocao", "xm3u8") and "@" in raw:
                url = self._xc_resolve(raw)
                if url:
                    return {"parse": 0, "url": url,
                            "header": {"User-Agent": _UA}}
            # 播放器自带解析模板 (热舞/午夜/香蕉/AI短剧等 ID 型源)
            url, headers = self._template_resolve(player, raw)
            if url:
                return {"parse": 0, "url": url, "header": headers}
            # ID 型源: 解析接口尽力
            if "@" in raw:
                url, headers = self._jx_resolve(raw)
                if url:
                    return {"parse": 0, "url": url, "header": headers}
            return self._play_parse_fallback(player, raw)
        except Exception:
            return {"parse": 1, "url": id or ""}

    def _play_http(self, player, raw):
        p = self._parser_map.get(player) or {}
        no_parse = (p.get("no_parse_rule") or "").lower()
        low = raw.lower()
        if self._is_media(raw) or any(
                x.strip() and x.strip() in low
                for x in no_parse.split(",")):
            return {"parse": 0, "url": raw, "header": {"User-Agent": _UA}}
        template = p.get("url") or ""
        if template:
            return {"parse": 1, "playUrl": template.replace("%s", raw),
                    "url": raw, "header": {"User-Agent": _UA}}
        return {"parse": 1, "url": raw, "header": {"User-Agent": _UA}}

    def _play_parse_fallback(self, player, raw):
        p = self._parser_map.get(player) or {}
        template = p.get("url") or ""
        if template:
            return {"parse": 1,
                    "playUrl": template.replace(
                        "%s", urllib.parse.quote(raw, safe="")),
                    "url": raw}
        return {"parse": 1, "url": raw}
