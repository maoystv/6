#!/usr/bin/python
# -*- coding: utf-8 -*-
import re
import json
import sys
import time
import uuid
import base64
import hashlib
import zlib
from urllib.parse import quote

try:
    import requests
except Exception:
    requests = None

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except Exception:
    AES = None
    pad = None
    unpad = None

sys.path.append('..')
from base.spider import Spider
from secrets import token_bytes


class Spider(Spider):
    def getName(self):
        return "APP99"

    def init(self, extend=""):
        self.ext = self._load_ext(extend)
        self.host = str(self.ext.get("host", "")).rstrip("/")
        self.appkey = str(self.ext.get("appkey", ""))
        self.name = str(self.ext.get("name", ""))
        self.build_signature = str(self.ext.get("buildSignature", ""))
        self.build_number = str(self.ext.get("buildNumber", ""))
        self.version_name = str(self.ext.get("versionName", ""))
        self.package = str(self.ext.get("package", ""))
        self.ua = str(self.ext.get("ua", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"))
        self.api_version = str(self.ext.get("version", "0b4328287a5d953e"))
        self.login_path = str(self.ext.get("LoginPath", "/app/log"))
        self.uuid = str(self.ext.get("uuid", "")) or str(uuid.uuid4())
        self.token = str(self.ext.get("token", ""))
        self.player_config = {}
        self.parser_apis = []
        self.categories = []

        self.global_play_order = self.ext.get("play_order", []) or [
            "蓝光4K", "4K蓝光", "真4K", "超清4K", "4K", "UHD",
            "臻影4K", "鲸宝4K", "咕噜4K", "菲乐4K", "候补4K", "炫彩4K", "JD4K",
            "蓝光原盘", "蓝光Remux", "蓝光",
            "NB蓝光", "YY蓝光", "YD蓝光", "JD蓝光", "企鹅蓝光A",
            "蓝光①", "蓝光②", "蓝光③", "蓝光④",
            "蓝光1", "蓝光2", "蓝光3", "蓝光4",
            "超清", "高清", "HD", "H265", "HEVC",
            "鲸宝2K", "精品2K", "2K",
            "专线1", "专线2", "专线3", "专线4",
            "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
            "采集", "采集A", "采集B", "采集C",
            "备用1", "备用2", "备用3", "备用4", "海外"
        ]

        self.site_play_orders = self._build_site_play_orders()
        self.play_order = self._resolve_site_play_order()

        self.default_classes = [
            {"type_id": "1", "type_name": "剧集"},
            {"type_id": "2", "type_name": "电影"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "5", "type_name": "短剧"}
        ]
        self._init_app()

    def _load_ext(self, extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend:
            try:
                return json.loads(extend)
            except Exception:
                return {}
        return {}

    def _build_site_play_orders(self):
        return {
            "咕噜咕噜": [
                "咕噜4K", "菲乐4K","鲸宝4K", "鲸宝2K", "精品2K", 
                "蚂蚁", "☆讯飞☆", "☆奇趣☆", "☆果汁☆", "☆酷萌☆",
                "臻影4K", "咖啡", "量子", "非凡", "暴风", "小熊", "海外"
            ],
            "剧圈圈": [
                "咕噜4K", "菲乐4K", "JD4K", "NB蓝光", "YY蓝光", "YD蓝光", "JD蓝光", "4K", "蓝光",
                "高清", "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊"
            ],
            "顾我追剧": [
                "JD4K", "蓝光④", "蓝光③", "蓝光②", "蓝光①", "蓝光",
                "高清③", "高清②", "高清①",
                "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
                "采集", "备用1", "备用2", "备用3", "备用4"
            ],
            "追番达人": [
                "臻彩4K", "候补4K", "企鹅蓝光A", "专线1", "专线2", "专线3", "专线4",
                "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
                "备用1", "备用2", "备用3", "备用4"
            ],
            "听心视频": [
                "4K", "蓝光", "超清", "高清",
                "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
                "采集", "备用1", "备用2"
            ],
            "双子星动漫": [
                "4K", "蓝光", "超清", "高清",
                "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
                "采集", "备用1", "备用2"
            ],  
            "小橙子": [
                "JD4K", "4k", "蓝光④", "蓝光③", "蓝光②", "蓝光①", "蓝光",
                "高清③", "高清②", "高清①",
                "蚂蚁", "咖啡", "量子", "非凡", "暴风", "小熊",
                "采集", "备用1", "备用2", "备用3", "备用4"
            ]
        }

    def _resolve_site_play_order(self):
        custom = self.ext.get("site_play_order") or self.ext.get("source_priority")
        if isinstance(custom, list) and custom:
            return custom
        name = str(self.name or "").strip()
        if name in self.site_play_orders:
            return self.site_play_orders[name]
        return self.global_play_order

    def _norm_source_name(self, s):
        s = str(s or "").strip()
        if not s:
            return ""
        s = s.replace("线路", "")
        s = s.replace("频道", "")
        s = s.replace("资源", "")
        s = s.replace("（", "(").replace("）", ")")
        s = s.replace("☆", "")
        s = s.replace(" ", "").replace("-", "").replace("_", "")
        s = s.replace("蓝盤", "蓝光").replace("藍光", "蓝光")
        return s.lower()

    def _source_aliases(self, src_code):
        src_code = str(src_code or "").strip()
        aliases = set()
        if not src_code:
            return aliases

        aliases.add(src_code)
        aliases.add(self._norm_source_name(src_code))

        cfg = self.player_config.get(src_code, {})
        if isinstance(cfg, dict):
            for k in ["code", "name", "show", "title"]:
                v = str(cfg.get(k, "")).strip()
                if v:
                    aliases.add(v)
                    aliases.add(self._norm_source_name(v))

        manual_map = {
            "baofeng": ["暴风"],
            "liangzi": ["量子"],
            "kafei": ["咖啡"],
            "xiaoxiong": ["小熊"],
            "mayi": ["蚂蚁"],
            "feifan": ["非凡"],
            "haiwai": ["海外"],
            "gulu4k": ["咕噜4K", "4K"],
            "feile4k": ["菲乐4K", "4K"],
            "zhenying4k": ["臻影4K", "4K"],
            "jingbao4k": ["鲸宝4K", "4K"],
            "jingbao2k": ["鲸宝2K", "2K"],
            "jingpin2k": ["精品2K", "2K"],
            "qihuan4k": ["候补4K", "4K"],
            "houbu4k": ["候补4K", "4K"],
            "xuancai4k": ["炫彩4K", "4K"],
            "xuancai": ["炫彩4K", "4K"],
            "jd4k": ["JD4K", "4K"],
            "jdblue": ["JD蓝光", "蓝光"],
            "ydblue": ["YD蓝光", "蓝光"],
            "yyblue": ["YY蓝光", "蓝光"],
            "nbblue": ["NB蓝光", "蓝光"],
            "penguinblue": ["企鹅蓝光A", "蓝光"],
            "qiebluea": ["企鹅蓝光A", "蓝光"],
            "xunfei": ["☆讯飞☆", "讯飞"],
            "qiqu": ["☆奇趣☆", "奇趣"],
            "guozhi": ["☆果汁☆", "果汁"],
            "kumeng": ["☆酷萌☆", "酷萌"],
            "caiji": ["采集"],
            "caiji1": ["采集1", "采集"],
            "caiji2": ["采集2", "采集"],
            "caiji3": ["采集3", "采集"],
            "zx1": ["专线1"], "zx2": ["专线2"], "zx3": ["专线3"], "zx4": ["专线4"],
            "by1": ["备用1"], "by2": ["备用2"], "by3": ["备用3"], "by4": ["备用4"]
        }

        code_key = self._norm_source_name(src_code)
        for k, vals in manual_map.items():
            if code_key == self._norm_source_name(k):
                for v in vals:
                    aliases.add(v)
                    aliases.add(self._norm_source_name(v))

        return aliases

    def _keyword_score(self, src_code):
        aliases = self._source_aliases(src_code)
        text = "|".join([x for x in aliases if x])
        nt = self._norm_source_name(text)
        score = 0

        if any(x in nt for x in ["4k", "2160", "uhd"]):
            score += 1200
        if "蓝光" in text or any(x in nt for x in ["bluray", "blu", "remux", "原盘"]):
            score += 900
        if any(x in nt for x in ["2k", "1440"]):
            score += 500
        if any(x in nt for x in ["1080", "超清", "高清", "h265", "hevc"]):
            score += 300
        if "专线" in text:
            score += 80
        if "采集" in text or "caiji" in nt:
            score -= 180
        if "备用" in text:
            score -= 120
        if "海外" in text:
            score -= 60
        return score

    def _priority_index(self, src_code):
        order_index = {}
        for i, name in enumerate(self.play_order):
            n = self._norm_source_name(name)
            if n and n not in order_index:
                order_index[n] = i
        best = len(order_index) + 999
        for alias in self._source_aliases(src_code):
            idx = order_index.get(self._norm_source_name(alias))
            if idx is not None and idx < best:
                best = idx
        return best

    def _sort_play_sources(self, play_froms, play_urls):
        if not play_froms or not play_urls:
            return play_froms, play_urls
        paired = list(enumerate(zip(play_froms, play_urls)))

        def sort_key(item):
            original_idx, pair = item
            src_code = str(pair[0]).strip()
            return (self._priority_index(src_code), -self._keyword_score(src_code), original_idx)

        paired.sort(key=sort_key)
        sorted_froms = [x[1][0] for x in paired]
        sorted_urls = [x[1][1] for x in paired]
        return sorted_froms, sorted_urls

    def _aes_decrypt(self, data, key):
        try:
            if AES is None:
                return ""
            decoded = base64.b64decode(data)
            iv = decoded[:16]
            ciphertext = decoded[16:]
            k = key.replace("-", "")
            kb = k.encode("utf-8")
            if len(kb) not in (16, 24, 32):
                kb = (kb + (b"0" * 32))[:32]
            cipher = AES.new(kb, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(ciphertext)
            try:
                return zlib.decompress(decrypted).decode("utf-8")
            except Exception:
                try:
                    return unpad(decrypted, AES.block_size).decode("utf-8")
                except Exception:
                    return decrypted.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _aes_encrypt(self, data, key):
        if AES is None:
            return ""
        k = key.replace("-", "")
        kb = k.encode("utf-8")
        if len(kb) not in (16, 24, 32):
            kb = (kb + (b"0" * 32))[:32]
        cipher = AES.new(kb, AES.MODE_CBC)
        encrypted = cipher.encrypt(pad(data.encode(), AES.block_size))
        return base64.b64encode(cipher.iv + encrypted).decode()

    def _sign(self, nonce, timestamp, body):
        raw = f"{body}:{timestamp}:{nonce}:{self.token}:{self.appkey}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _headers(self, nonce, timestamp, body):
        return {
            "User-Agent": self.ua,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "client_type": "android",
            "uuid": self.uuid,
            "timestamp": timestamp,
            "sign": self._sign(nonce, timestamp, body),
            "nonce": nonce,
            "appkey": self.appkey,
            "version": self.api_version,
            "api_version": "v1"
        }

    def _request(self, endpoint, data):
        nonce = base64.b64encode(token_bytes(16)).decode()
        ts = str(int(time.time() * 1000))
        payload = dict(data or {})
        payload.setdefault("token", self.token)
        payload.setdefault("timestamp", ts)
        payload.setdefault("nonce", nonce)
        encrypted = self._aes_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), self.uuid)
        headers = self._headers(nonce, ts, encrypted)
        try:
            if requests is not None:
                resp = requests.post(f"{self.host}{endpoint}", data=encrypted, headers=headers, timeout=15)
                return self._aes_decrypt(resp.text, self.uuid)
            resp = self.post(f"{self.host}{endpoint}", data=encrypted, headers=headers)
            return self._aes_decrypt(getattr(resp, "text", ""), self.uuid)
        except Exception:
            return ""

    def _update_parser_apis(self, data):
        arr = []
        if isinstance(data, list):
            arr = data
        elif isinstance(data, dict):
            for k in ["data", "list", "items", "result"]:
                v = data.get(k)
                if isinstance(v, list):
                    arr = v
                    break
        if isinstance(arr, list):
            self.parser_apis = arr

    def _init_app(self):
        try:
            ts = str(int(time.time() * 1000))
            nonce = base64.b64encode(token_bytes(16)).decode()
            init_data = {
                "v": self.version_name,
                "n": self.name,
                "s": self.build_signature,
                "pl": "1",
                "apiVersion": "v2",
                "token": "",
                "timestamp": ts,
                "nonce": nonce
            }
            encrypted = self._aes_encrypt(json.dumps(init_data, ensure_ascii=False, separators=(",", ":")), self.uuid)
            headers = self._headers(nonce, ts, encrypted)
            if requests is not None:
                resp = requests.post(f"{self.host}/app/systemInit", data=encrypted, headers=headers, timeout=15)
                text = resp.text
            else:
                resp = self.post(f"{self.host}/app/systemInit", data=encrypted, headers=headers)
                text = getattr(resp, "text", "")
            data = json.loads(self._aes_decrypt(text, self.uuid) or "{}")
            if isinstance(data.get("player"), dict):
                self.player_config = data.get("player", {})
            if isinstance(data.get("parser_api"), list):
                self._update_parser_apis(data.get("parser_api"))
            if isinstance(data.get("parserapi"), list):
                self._update_parser_apis(data.get("parserapi"))
            if isinstance(data.get("parses"), list):
                self._update_parser_apis(data.get("parses"))
            if "categorys" in data:
                cat_data = data["categorys"]
                if isinstance(cat_data, dict) and "data" in cat_data:
                    self.categories = cat_data["data"]
                elif isinstance(cat_data, list):
                    self.categories = cat_data
            elif isinstance(data.get("categories"), list):
                self.categories = data.get("categories", [])
            self._login()
        except Exception:
            pass

    def _login(self):
        if self.token:
            return
        paths = []
        if self.login_path:
            paths.append(self.login_path)
        if "/app/log" not in paths:
            paths.append("/app/log")
        if "/app/userInfo" not in paths:
            paths.append("/app/userInfo")
        for path in paths:
            try:
                ts = str(int(time.time() * 1000))
                nonce = base64.b64encode(token_bytes(16)).decode()
                login_data = {
                    "appName": self.name,
                    "appkey": self.appkey,
                    "package": self.package,
                    "buildNumber": self.build_number,
                    "buildSignature": self.build_signature,
                    "uuid": self.uuid,
                    "version": self.version_name,
                    "timestamp": ts,
                    "nonce": nonce
                }
                encrypted = self._aes_encrypt(json.dumps(login_data, ensure_ascii=False, separators=(",", ":")), self.uuid)
                headers = self._headers(nonce, ts, encrypted)
                if requests is not None:
                    resp = requests.post(f"{self.host}{path}", data=encrypted, headers=headers, timeout=15)
                    text = resp.text
                else:
                    resp = self.post(f"{self.host}{path}", data=encrypted, headers=headers)
                    text = getattr(resp, "text", "")
                data = json.loads(self._aes_decrypt(text, self.uuid) or "{}")
                if isinstance(data.get("data"), dict):
                    info = data.get("data", {})
                    self.token = str(info.get("token", self.token) or info.get("usertoken", self.token) or self.token)
                    self.uuid = str(info.get("uuid", self.uuid)) or self.uuid
                    if isinstance(info.get("player"), dict):
                        self.player_config = info.get("player", self.player_config)
                    if isinstance(info.get("parser_api"), list):
                        self._update_parser_apis(info.get("parser_api"))
                    if isinstance(info.get("parserapi"), list):
                        self._update_parser_apis(info.get("parserapi"))
                if data.get("userInfo") and data["userInfo"].get("user_token"):
                    self.token = data["userInfo"]["user_token"]
                if self.token:
                    return
            except Exception:
                continue

    def _parse_videos(self, arr):
        result = []
        if not isinstance(arr, list):
            return result
        for v in arr:
            if not isinstance(v, dict):
                continue
            result.append({
                "vod_id": str(v.get("id", "")),
                "vod_name": v.get("name", ""),
                "vod_pic": v.get("pic", ""),
                "vod_remarks": v.get("remarks", ""),
                "vod_year": v.get("year", ""),
                "vod_content": v.get("blurb", ""),
                "type_name": v.get("class", ""),
                "vod_area": v.get("area", ""),
                "vod_actor": v.get("actor", ""),
                "vod_director": v.get("director", "")
            })
        return result

    def _extract_pagecount(self, r):
        for k in ["page_count", "pagecount", "pageCount"]:
            if isinstance(r, dict) and r.get(k) not in (None, ""):
                try:
                    return int(r.get(k))
                except Exception:
                    pass
        return 1

    def homeContent(self, filter):
        classes = []
        filters = {}
        try:
            for cat in self.categories:
                cid = str(cat.get("id", ""))
                cname = cat.get("name", "")
                if not cid or not cname:
                    continue
                classes.append({"type_id": cid, "type_name": cname})
                ext = cat.get("typeextend") or cat.get("type_extend") or {}
                if isinstance(ext, str) and ext:
                    try:
                        ext = json.loads(ext)
                    except Exception:
                        ext = {}
                fl = []
                if isinstance(ext, dict):
                    cls = ext.get("class", [])
                    areas = ext.get("areas", ext.get("area", []))
                    langs = ext.get("lang", [])
                    years = ext.get("years", ext.get("year", []))
                    if isinstance(cls, str):
                        cls = [x for x in cls.split(",") if x]
                    if isinstance(areas, str):
                        areas = [x for x in areas.split(",") if x]
                    if isinstance(langs, str):
                        langs = [x for x in langs.split(",") if x]
                    if isinstance(years, str):
                        years = [x for x in years.split(",") if x]
                    fl.append({"key": "class", "name": "类型", "value": [{"n": "全部", "v": ""}] + [{"n": v, "v": v} for v in cls]})
                    fl.append({"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] + [{"n": v, "v": v} for v in areas]})
                    fl.append({"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}] + [{"n": v, "v": v} for v in langs]})
                    fl.append({"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + [{"n": v, "v": v} for v in years]})
                filters[cid] = fl
        except Exception:
            pass
        if not classes:
            classes = self.default_classes
        videos = []
        try:
            r = json.loads(self._request("/vod/search", {"kw": "", "page": "1", "limit": 21, "pid": "1", "orderBy": "time", "isCategory": 1}) or "{}")
            if "data" in r and isinstance(r["data"], list):
                videos = self._parse_videos(r["data"])
        except Exception:
            pass
        return {"class": classes, "list": videos[:20], "filters": filters if filter else {}}

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        videos = []
        pagecount = 1
        try:
            extend = extend or {}
            data = {"kw": "", "page": str(pg), "limit": 21, "pid": str(tid), "orderBy": "time", "isCategory": 1}
            if isinstance(extend, dict):
                if extend.get("class"):
                    data["class"] = extend["class"]
                if extend.get("area"):
                    data["area"] = extend["area"]
                if extend.get("lang"):
                    data["lang"] = extend["lang"]
                if extend.get("year"):
                    data["year"] = extend["year"]
            r = json.loads(self._request("/vod/search", data) or "{}")
            if "data" in r and isinstance(r["data"], list):
                videos = self._parse_videos(r["data"])
                pagecount = self._extract_pagecount(r)
        except Exception:
            pass
        return {"page": int(pg), "pagecount": pagecount, "limit": 21, "total": pagecount * 21, "list": videos}

    def detailContent(self, ids):
        try:
            r = json.loads(self._request("/vod/detail", {"id": ids[0], "eps": "1", "v": "2.0.0", "pl": 1}) or "{}")
            if "data" not in r or not isinstance(r["data"], dict):
                return {"list": []}
            d = r["data"]
            vod = {
                "vod_id": d.get("id", ""),
                "vod_name": d.get("name", ""),
                "vod_pic": d.get("pic", ""),
                "vod_remarks": d.get("remarks", ""),
                "vod_year": d.get("year", ""),
                "vod_content": d.get("content", ""),
                "type_name": d.get("class", ""),
                "vod_area": d.get("area", ""),
                "vod_actor": d.get("actor", ""),
                "vod_director": d.get("director", ""),
                "vod_play_from": "",
                "vod_play_url": ""
            }
            play_from_raw = d.get("play_from", d.get("playfrom", ""))
            play_url_raw = d.get("play_url", d.get("playurl", ""))
            play_froms = play_from_raw.split("$$$") if play_from_raw else []
            play_urls = play_url_raw.split("$$$") if play_url_raw else []
            play_froms, play_urls = self._sort_play_sources(play_froms, play_urls)
            new_froms = []
            for src in play_froms:
                src = src.strip()
                if src in self.player_config:
                    new_froms.append(self.player_config[src].get("name", src))
                else:
                    new_froms.append(src)
            new_urls = []
            for i, url_block in enumerate(play_urls):
                src_name = play_froms[i] if i < len(play_froms) else ""
                eps = url_block.split("#") if url_block else []
                ep_list = []
                for ep in eps:
                    parts = ep.split("$", 1)
                    if len(parts) < 2:
                        continue
                    ep_name = parts[0]
                    ep_url = parts[1]
                    ep_num = re.sub(r"D+", "", ep_name) or "1"
                    ep_list.append(f"{ep_name}${ep_url}@{src_name}@{vod['vod_name']}@{ep_num}")
                if ep_list:
                    new_urls.append("#".join(ep_list))
            vod["vod_play_from"] = "$$$".join(new_froms)
            vod["vod_play_url"] = "$$$".join(new_urls)
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        videos = []
        page = int(pg)
        pagecount = 1
        try:
            r = json.loads(self._request("/vod/search", {"kw": key, "page": page, "limit": 21, "orderBy": "vod_hits_month", "sort": "desc"}) or "{}")
            if "data" in r and isinstance(r["data"], list):
                videos = self._parse_videos(r["data"])
                pagecount = self._extract_pagecount(r)
            if not videos:
                r = json.loads(self._request("/vod/search", {"kw": key, "page": page, "limit": 21, "orderBy": "vodhitsmonth", "sort": "desc"}) or "{}")
                if "data" in r and isinstance(r["data"], list):
                    videos = self._parse_videos(r["data"])
                    pagecount = self._extract_pagecount(r)
        except Exception:
            pass
        return {"list": videos, "page": page, "pagecount": pagecount}

    def _parser_api_url(self, parser):
        if not isinstance(parser, dict):
            return ""
        return str(parser.get("api_url", "") or parser.get("apiurl", "") or parser.get("apiUrl", "") or parser.get("url", "")).strip()

    def _parse_candidates(self, api_url, url):
        out = []
        if not api_url or not url:
            return out
        if "{url}" in api_url:
            out.append(api_url.replace("{url}", quote(url, safe="")))
            out.append(api_url.replace("{url}", url))
        else:
            out.append(api_url + url)
            out.append(api_url + quote(url, safe=""))
        uniq = []
        for x in out:
            if x and x not in uniq:
                uniq.append(x)
        return uniq

    def _extract_real_url(self, data):
        if isinstance(data, dict):
            for k in ["url", "playUrl", "play_url"]:
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            for k in ["data", "result"]:
                v = data.get(k)
                if isinstance(v, dict):
                    for kk in ["url", "playUrl", "play_url"]:
                        vv = v.get(kk)
                        if isinstance(vv, str) and vv.strip():
                            return vv.strip()
        return ""

    def playerContent(self, flag, id, vipFlags):
        try:
            parts = id.split("@")
            url = parts[0]
            src_code = parts[1] if len(parts) > 1 else ""
            vod_name = parts[2] if len(parts) > 2 else ""
            vod_index = parts[3] if len(parts) > 3 else "1"

            if src_code in self.player_config:
                p_cfg = self.player_config[src_code]
                if int(p_cfg.get("type", 0) or 0) != 0:
                    if not self.parser_apis:
                        self._init_app()
                    if self.parser_apis:
                        parse_urls = p_cfg.get("parseUrl", "") or p_cfg.get("parseurl", "") or ""
                        parse_ids = [x.strip() for x in str(parse_urls).split(",") if x.strip()]
                        selected = []
                        for parser in self.parser_apis:
                            pid = str(parser.get("id", "")).strip()
                            if parse_ids and pid not in parse_ids:
                                continue
                            selected.append(parser)
                        if not selected and parse_ids:
                            selected = self.parser_apis
                        for parser in selected:
                            api_url = self._parser_api_url(parser)
                            if not api_url:
                                continue
                            for target in self._parse_candidates(api_url, url):
                                try:
                                    resp = self.fetch(target, headers={"User-Agent": self.ua}, timeout=10)
                                    text = resp if isinstance(resp, str) else getattr(resp, "text", "")
                                    r = json.loads(text)
                                    real_url = self._extract_real_url(r)
                                    if real_url:
                                        url = real_url
                                        extra_header = r.get("header") if isinstance(r.get("header"), dict) else {"User-Agent": self.ua}
                                        return {
                                            "parse": 0,
                                            "url": url,
                                            "header": json.dumps(extra_header, ensure_ascii=False),
                                            "danmaku": f"http://127.0.0.1:9978/proxy?do=appdanmu&vodName={vod_name}&vodIndex={vod_index}&vodUrl="
                                        }
                                except Exception:
                                    continue
                        if parse_ids:
                            return {
                                "parse": 1,
                                "url": url,
                                "header": json.dumps({"User-Agent": self.ua}, ensure_ascii=False),
                                "danmaku": f"http://127.0.0.1:9978/proxy?do=appdanmu&vodName={vod_name}&vodIndex={vod_index}&vodUrl="
                            }
            danmu_url = f"http://127.0.0.1:9978/proxy?do=appdanmu&vodName={vod_name}&vodIndex={vod_index}&vodUrl="
            return {"parse": 0, "url": url, "header": json.dumps({"User-Agent": self.ua}, ensure_ascii=False), "danmaku": danmu_url}
        except Exception:
            return {"parse": 0, "url": "", "header": json.dumps({"User-Agent": self.ua}, ensure_ascii=False), "danmaku": ""}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return True

    def proxy(self, params):
        pass

    def localProxy(self, params):
        pass