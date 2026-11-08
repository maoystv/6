# coding: utf-8
"""
MiNO / 秒播4K —— TVBox / FongMi Python 站源
接口：http://43.248.128.122:578（extend 里 {base: "http://x.x.x.x:port"} 可覆盖）

协议要点（逆向自 csp_MiNO 的 dex）：
  1. 普通接口 GET 明文：/api/v1/category/videos、/api/v1/video/detail、/api/v1/search
  2. /api/v1/security/init 建会话，返回 session_id（600s），仅播放取票需要
  3. 播放：详情里的 vod_url_with_player[].url 形如 "正片$tk:xxxx"，
     POST /api/v1/vod/ticket {"token": "tk:xxxx"} → data.ticket
     ticket = base64url(json) + "." + sig，json.data.url = "rose_xxx"，json.data.parse_api = 解析前缀
     最后 GET parse_api + quote(url) → {"url": "https://.../x.m3u8"}
"""

import json
import random
import string
import time
from urllib.parse import quote

from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    host = "http://43.248.128.122:578"
    ua = "okhttp/4.12.0"
    page_size = 20

    # 会话（init 一次，10 分钟内复用）
    _sid = ""
    _sid_exp = 0.0
    _dev = ""

    # init 请求体模板（来自 NativeCrypto.mnInitBody 的 Java 兜底分支）
    _init_tpl = (
        '{"platform":"android","version":"1.0.13","device_id":"%s","client_pub":"%s",'
        '"device_brand":"Xiaomi","device_manufacturer":"Xiaomi","device_model":"MI 8",'
        '"sig_src":"java","so_version":13}'
    )
    _client_pub = "BKoFI/euhNNGp/2y5LJqWrIY5B7pdTG9Py/guJivmOLyQ7Dm6lJg8Fkpg5K7ePjCt7AQD1BUO3HEWKJD7tV9DDc="

    classes = [
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "连续剧"},
        {"type_id": "3", "type_name": "综艺"},
        {"type_id": "4", "type_name": "动漫"},
        {"type_id": "20", "type_name": "短剧"},
        {"type_id": "21", "type_name": "少儿"},
        {"type_id": "22", "type_name": "漫剧"},
        {"type_id": "23", "type_name": "纪录片"},
    ]

    sort_list = [("默认", ""), ("最热", "hits"), ("评分", "score")]
    area_list = [("全部", ""), ("内地", "内地"), ("中国香港", "中国香港"), ("中国台湾", "中国台湾"),
                 ("美国", "美国"), ("韩国", "韩国"), ("日本", "日本"), ("英国", "英国"),
                 ("法国", "法国"), ("泰国", "泰国"), ("印度", "印度"), ("其他", "其他")]
    year_list = [("全部", "")] + [(str(y), str(y)) for y in range(2026, 1999, -1)]
    lang_list = [("全部", ""), ("国语", "国语"), ("英语", "英语"), ("日语", "日语"),
                 ("韩语", "韩语"), ("粤语", "粤语"), ("其他", "其他")]

    # ---------- 基础 ----------

    def getName(self):
        return "MiNO秒播4K"

    def getDependence(self):
        return []

    def setExtendInfo(self, extend):
        return None

    def init(self, extend=""):
        try:
            s_ext = extend
            if isinstance(s_ext, dict):
                cfg = s_ext
            elif isinstance(s_ext, str) and s_ext.strip().startswith("{"):
                # TVBox/FongMi 传进来的是 ext 字符串，这里只解析字符串形态
                cfg = json.loads(s_ext)
            else:
                cfg = {}
            base = (cfg.get("base") or "").strip().rstrip("/")
            if base.startswith("http"):
                self.host = base
        except Exception:
            pass
        if not self._dev:
            Spider._dev = "".join(random.choice("0123456789abcdef") for _ in range(32))

    def _hdr(self, extra=None):
        h = {"User-Agent": self.ua, "Accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    def _text(self, r):
        if r is None:
            return ""
        if hasattr(r, "text"):
            return r.text or ""
        c = getattr(r, "content", b"")
        if isinstance(c, bytes):
            return c.decode("utf-8", "ignore")
        return str(c)

    def _get(self, path, params=None):
        url = self.host + path
        if params:
            kv = []
            for k, v in params.items():
                if v is None or v == "":
                    continue
                kv.append("%s=%s" % (k, quote(str(v), safe="")))
            if kv:
                url += ("&" if "?" in url else "?") + "&".join(kv)
        try:
            r = self.fetch(url, headers=self._hdr(), timeout=20)
        except TypeError:
            r = self.fetch(url, headers=self._hdr())
        return json.loads(self._text(r))

    def _post(self, path, obj, extra=None):
        body = json.dumps(obj, ensure_ascii=False)
        try:
            r = self.post(self.host + path, data=body, headers=self._hdr(extra), timeout=20)
        except TypeError:
            r = self.post(self.host + path, body, self._hdr(extra))
        return json.loads(self._text(r))

    # ---------- 会话 ----------

    def _session(self):
        if self._sid and time.time() < self._sid_exp:
            return self._sid
        try:
            if not self._dev:
                Spider._dev = "".join(random.choice("0123456789abcdef") for _ in range(32))
            body = self._init_tpl % (self._dev, self._client_pub)
            try:
                r = self.post(self.host + "/api/v1/security/init", data=body,
                              headers={"User-Agent": self.ua, "Content-Type": "application/json"}, timeout=20)
            except TypeError:
                r = self.post(self.host + "/api/v1/security/init", body,
                              {"User-Agent": self.ua, "Content-Type": "application/json"})
            j = json.loads(self._text(r))
            data = j.get("data") or {}
            sid = data.get("session_id") or ""
            if sid:
                Spider._sid = sid
                ttl = int(data.get("expires_in") or 600)
                Spider._sid_exp = time.time() + max(60, ttl - 60)
            return sid
        except Exception:
            return ""

    def _session_hdr(self):
        sid = self._session()
        h = {"User-Agent": self.ua, "Content-Type": "application/json"}
        if sid:
            h["X-Session-Id"] = sid
            h["X-Device-Id"] = self._dev
        return h

    # ---------- 数据映射 ----------

    @staticmethod
    def _pic(u):
        return (u or "").strip()

    def _vod(self, v):
        vid = str(v.get("vod_id") or "").strip()
        name = (v.get("vod_name") or "").strip()
        if not vid or not name:
            return None
        remarks = (v.get("vod_remarks") or "").strip()
        if not remarks:
            bits = [x for x in [(v.get("vod_year") or ""), (v.get("vod_area") or "")] if x]
            remarks = "·".join(bits)
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._pic(v.get("vod_pic")),
            "vod_remarks": remarks,
        }

    def _parse_list(self, videos):
        out = []
        for v in videos or []:
            item = self._vod(v)
            if item:
                out.append(item)
        return out

    # ---------- 六方法 ----------

    def homeContent(self, filter):
        filters = {}
        if filter:
            def opts(pairs):
                return [{"n": n, "v": v} for n, v in pairs]

            for c in self.classes:
                filters[c["type_id"]] = [
                    {"key": "sort", "name": "排序", "value": opts(self.sort_list)},
                    {"key": "area", "name": "地区", "value": opts(self.area_list)},
                    {"key": "year", "name": "年份", "value": opts(self.year_list)},
                    {"key": "lang", "name": "语言", "value": opts(self.lang_list)},
                ]
        return {"class": self.classes, "filters": filters}

    def homeVideoContent(self):
        try:
            j = self._get("/api/v1/category/videos",
                          {"type_id": "2", "page": 1, "page_size": 30})
            return {"list": self._parse_list(((j.get("data") or {}).get("videos")) or [])}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        params = {"type_id": tid, "page": pg, "page_size": self.page_size}
        if isinstance(extend, dict):
            for k in ("sort", "area", "year", "lang"):
                v = extend.get(k)
                if v:
                    params[k] = v
        try:
            j = self._get("/api/v1/category/videos", params)
            data = j.get("data") or {}
            videos = data.get("videos") or []
            pag = data.get("pagination") or {}
            total = int(pag.get("total") or 0)
            pages = int(pag.get("total_pages") or 0)
            if pages <= 0:
                pages = pg if not videos else pg + 1
            return {
                "list": self._parse_list(videos),
                "page": pg,
                "pagecount": pages,
                "limit": self.page_size,
                "total": total,
            }
        except Exception:
            return {"list": [], "page": pg, "pagecount": pg, "limit": self.page_size, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0]).strip() if ids else ""
            if not vid:
                return {"list": []}
            j = self._get("/api/v1/video/detail", {"id": vid})
            info = (j.get("data") or {}).get("vod_info") or {}
            if not info:
                return {"list": []}

            froms, urls = [], []
            for line in info.get("vod_url_with_player") or []:
                name = (line.get("name") or "线路").strip()
                raw = (line.get("url") or "").strip()
                if not raw:
                    continue
                eps, seen = [], set()
                for part in raw.split("#"):
                    part = part.strip()
                    if not part:
                        continue
                    if "$" in part:
                        ep, token = part.split("$", 1)
                    else:
                        ep, token = "", part
                    token = token.strip()
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    ep = (ep or "").strip().replace("$", " ")
                    if not ep:
                        ep = "第%d集" % (len(eps) + 1)
                    eps.append("%s$%s" % (ep, token))
                if eps:
                    froms.append(name.replace("$", " "))
                    urls.append("#".join(eps))

            if not froms:
                return {"list": []}

            vod = {
                "vod_id": str(info.get("vod_id") or vid),
                "vod_name": (info.get("vod_name") or "").strip(),
                "vod_pic": self._pic(info.get("vod_pic")),
                "type_name": (info.get("vod_class") or "").strip(),
                "vod_year": str(info.get("vod_year") or "").strip(),
                "vod_area": (info.get("vod_area") or "").strip(),
                "vod_actor": (info.get("vod_actor") or "").strip(),
                "vod_director": (info.get("vod_director") or "").strip(),
                "vod_remarks": (info.get("vod_remarks") or "").strip(),
                "vod_content": (info.get("vod_content") or info.get("vod_blurb") or "").strip(),
                "vod_play_from": "$$$".join(froms),
                "vod_play_url": "$$$".join(urls),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        try:
            j = self._get("/api/v1/search", {"wd": key, "page": page, "limit": self.page_size})
            data = j.get("data") or {}
            hits = data.get("hits") or []
            total_pages = int(data.get("total_pages") or 0)
            res = {"list": self._parse_list(hits), "page": page}
            if total_pages:
                res["pagecount"] = total_pages
            return res
        except Exception:
            return {"list": [], "page": page}

    # ---------- 播放 ----------

    def _ticket(self, token):
        h = self._session_hdr()
        try:
            j = self._post("/api/v1/vod/ticket", {"token": token}, h)
        except Exception:
            return ""
        if str(j.get("code")) != "1":
            return ""
        return ((j.get("data") or {}).get("ticket")) or ""

    @staticmethod
    def _b64json(s):
        raw = s.replace("-", "+").replace("_", "/")
        raw += "=" * ((4 - len(raw) % 4) % 4)
        import base64
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8", "ignore"))
        except Exception:
            return {}

    def _resolve(self, ticket):
        """ticket -> (真实播放地址, 解析兜底地址)"""
        head = ticket.split(".")[0]
        js = self._b64json(head)
        data = js.get("data") or {}
        url = (data.get("url") or "").strip()
        api = (data.get("parse_api") or "").strip()
        if url.startswith("http"):
            return url, ""
        if not api:
            return "", ""
        if api.startswith("/"):
            api = self.host + api
        target = api
        if "{md5}" in target:
            import hashlib
            target = target.replace("{md5}", hashlib.md5(url.encode()).hexdigest())
        else:
            target = target + quote(url, safe="")
        for _ in range(2):  # 解析服务偶发 404「获取失败,请重试」，重试一次
            try:
                r = self.fetch(target, headers={"User-Agent": self.ua}, timeout=20)
                j2 = json.loads(self._text(r))
                real = j2.get("url") or ""
                if isinstance(real, dict):
                    real = real.get("url") or ""
                real = str(real).strip()
                if real.startswith("http"):
                    return real, target
            except Exception:
                pass
        return "", target

    def playerContent(self, flag, id, vipFlags):
        try:
            pid = (id or "").strip()
            if "|" in pid:
                pid = pid.split("|", 1)[1].strip()
            if not pid:
                return {"parse": 1, "url": "", "header": {"User-Agent": self.ua}}
            ticket = self._ticket(pid)
            if ticket:
                real, fallback = self._resolve(ticket)
                if real.startswith("http"):
                    return {"parse": 0, "url": real, "header": {"User-Agent": self.ua}}
                if fallback.startswith("http"):
                    return {"parse": 1, "url": fallback, "header": {"User-Agent": self.ua}}
            return {"parse": 1, "url": pid, "header": {"User-Agent": self.ua}}
        except Exception:
            return {"parse": 1, "url": id or "", "header": {"User-Agent": self.ua}}

    def localProxy(self, param):
        return None
