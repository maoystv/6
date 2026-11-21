# coding: utf-8
"""
未来4K —— TVBox / FongMi Python 站源

逆向来源：api.json 的 {"api":"csp_WeiLai4K"} → spider.jar(md5 f6310d33…) 内 com.github.catvod.spider.WeiLai4K
（该类字符串用 C00xx.mNN(short[],off,len,seed) 单字节 XOR 混淆，已全部还原）

站型：苹果 CMS 的 JSON 接口（夸克源 `/provide/vod/from/kl/`）
  列表/搜索/详情：{base}/provide/vod/from/kl/?ac=detail&t=<tid>&pg=<pg>&wd=<key>&ids=<id>
  base 默认 http://110.42.66.100:12678/api.php
  播放：vod_play_url 里可能是 m3u8/mp4 直链、`kl-<base64>` 夸克转码链，
        或需要过一遍解析接口（默认 http://110.42.66.100:5666/api/?key=…&url=）

ext 可覆盖：{"api":"http://x.x.x.x:port/api.php","playUrl":"http://…&url="}
"""

import base64
import json
import re
import ssl
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from base.spider import Spider as BaseSpider

UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36")
DEFAULT_API = "http://110.42.66.100:12678/api.php"
DEFAULT_PARSE = "http://110.42.66.100:5666/api/?key=c31bfd818ac47875ab4922f03834afcc&url="
VIDEO_RE = re.compile(r"\.(m3u8|mp4|flv|mkv|ts|avi)(\?|#|$)", re.I)
TAG_RE = re.compile(r"<[^>]+>")

CATEGORIES = [
    ("2", "电影"), ("1", "电视剧"), ("9", "动漫"), ("10", "综艺"),
    ("13", "少儿"), ("11", "日韩剧"), ("12", "美剧"),
]
URL_KEYS = ("url", "playUrl", "play_url", "video", "m3u8", "src", "link", "data")


class Spider(BaseSpider):
    api = DEFAULT_API
    parse_api = DEFAULT_PARSE
    page_size = 20

    def getName(self):
        return "未来4K"

    def getDependence(self):
        return []

    def setExtendInfo(self, extend):
        return None

    def isVideoFormat(self, url):
        return bool(VIDEO_RE.search(url or ""))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def init(self, extend=""):
        try:
            cfg = {}
            s_ext = extend
            if isinstance(s_ext, dict):
                cfg = s_ext
            elif isinstance(s_ext, str) and s_ext.strip().startswith("{"):
                cfg = json.loads(s_ext)
            elif isinstance(s_ext, str) and s_ext.strip():
                parts = [p.strip() for p in re.split(r"[;\n]+", s_ext) if p.strip()]
                if len(parts) >= 1:
                    cfg["api"] = parts[0]
                if len(parts) >= 2:
                    cfg["playUrl"] = parts[1]
            api = str(cfg.get("api") or "").strip()
            play = str(cfg.get("playUrl") or cfg.get("parse") or "").strip()
            if api:
                self.api = api
            if play:
                self.parse_api = play
        except Exception:
            pass

    # ---------- 网络 ----------
    @staticmethod
    def _http(url, timeout=20):
        req = Request(url, method="GET")
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json, text/plain, */*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        try:
            ctx = ssl.create_default_context()
            with urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except ssl.SSLError:
            with urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
                return r.read()

    _cache = {}

    def _get_json(self, url, timeout=20):
        now = time.time()
        hit = self._cache.get(url)
        if hit and now - hit[0] < 300:
            return hit[1]
        for i in range(6):
            try:
                txt = self._http(url, timeout).decode("utf-8", "ignore").strip()
                if len(txt) > 2 and txt != "null":
                    obj = json.loads(txt)
                    if isinstance(obj, dict):
                        self._cache[url] = (now, obj)
                        return obj
            except Exception:
                pass
            time.sleep(0.6 + 0.5 * i)
        return {}

    def _base(self):
        base = (self.api or DEFAULT_API).strip()
        while base.endswith("/"):
            base = base[:-1]
        if "provide/vod" in base:
            return base + "/"
        if base.endswith("api.php") or base.endswith(".php"):
            return base + "/provide/vod/from/kl/"
        return base + "/api.php/provide/vod/from/kl/"

    def _url(self, ac, tid=None, pg=None, wd=None, ids=None):
        q = [("ac", ac)]
        if tid:
            q.append(("t", tid))
        if pg:
            q.append(("pg", str(pg)))
        if wd:
            q.append(("wd", wd))
        if ids:
            q.append(("ids", ids))
        return self._base() + "?" + urlencode(q, quote_via=quote)

    # ---------- 数据映射 ----------
    @staticmethod
    def _vod(v):
        if not v:
            return None
        vid = str(v.get("vod_id") or "").strip()
        name = (v.get("vod_name") or "").strip()
        if not vid or not name:
            return None
        pic = v.get("vod_pic") or v.get("vod_pic_thumb") or v.get("vod_pic_slide") or ""
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": (v.get("vod_remarks") or "").strip(),
        }

    def _list(self, arr):
        out = []
        for v in arr or []:
            item = self._vod(v)
            if item:
                out.append(item)
        return out

    # ---------- 六方法 ----------
    def homeContent(self, filter):
        data = self._get_json(self._url("detail", pg=1))
        classes = [{"type_id": t, "type_name": n} for t, n in CATEGORIES]
        return {
            "class": classes,
            "filters": {c["type_id"]: [] for c in classes},
            "list": self._list(data.get("list"))[:30],
        }

    def homeVideoContent(self):
        data = self._get_json(self._url("detail", pg=1))
        return {"list": self._list(data.get("list"))[:30]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1
        data = self._get_json(self._url("detail", tid=tid, pg=pg))
        lst = self._list(data.get("list"))
        try:
            pages = int(str(data.get("pagecount") or 0))
        except Exception:
            pages = 0
        if pages <= 0:
            pages = pg + 1 if lst else pg
        try:
            total = int(str(data.get("total") or 0))
        except Exception:
            total = 0
        if total <= 0:
            total = pages * self.page_size
        return {"list": lst, "page": pg, "pagecount": pages,
                "limit": self.page_size, "total": total}

    def detailContent(self, ids):
        try:
            vid = str(ids[0]).strip() if ids else ""
            vid = vid.split(",")[0].strip()
            if not vid:
                return {"list": []}
            data = self._get_json(self._url("detail", ids=vid), timeout=25)
            arr = data.get("list") or []
            if not arr:
                return {"list": []}
            info = arr[0]
            vod = self._vod(info) or {}
            vod["type_name"] = (info.get("type_name") or "").strip()
            vod["vod_year"] = (info.get("vod_year") or "").strip()
            vod["vod_area"] = (info.get("vod_area") or "").strip()
            vod["vod_lang"] = (info.get("vod_lang") or "").strip()
            vod["vod_actor"] = (info.get("vod_actor") or "").strip()
            vod["vod_director"] = (info.get("vod_director") or "").strip()
            vod["vod_remarks"] = vod.get("vod_remarks") or info.get("vod_score") or ""
            content = info.get("vod_content") or info.get("vod_blurb") or ""
            vod["vod_content"] = TAG_RE.sub("", content).strip()

            froms, urls = [], []
            names = str(info.get("vod_play_from") or "").split("$$$")
            for i, group in enumerate(str(info.get("vod_play_url") or "").split("$$$")):
                eps = []
                for seg in str(group).split("#"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    if "$" in seg:
                        ep, url = seg.split("$", 1)
                        ep, url = ep.strip(), url.strip()
                    else:
                        ep, url = "", seg
                    if not url:
                        continue
                    if not ep:
                        ep = "第%d集" % (len(eps) + 1)
                    eps.append("%s$%s" % (ep.replace("$", " "), url))
                if eps:
                    name = names[i].strip() if i < len(names) else ""
                    froms.append((name or ("线路%d" % (len(froms) + 1))).replace("$", " "))
                    urls.append("#".join(eps))
            if not froms:
                return {"list": []}
            vod["vod_play_from"] = "$$$".join(froms)
            vod["vod_play_url"] = "$$$".join(urls)
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        data = self._get_json(self._url("detail", wd=key, pg=page))
        lst = self._list(data.get("list"))
        try:
            pages = int(str(data.get("pagecount") or 0))
        except Exception:
            pages = 0
        res = {"list": lst, "page": page}
        if pages > 0:
            res["pagecount"] = pages
        return res

    # ---------- 播放 ----------
    @staticmethod
    def _decode_kl(url):
        if not url or len(url) <= 3 or not url.lower().startswith("kl-"):
            return ""
        raw = url[3:]
        cut = raw.find("?")
        if cut > 0:
            raw = raw[:cut]
        raw = raw.replace("-", "+").replace("_", "/")
        raw += "=" * ((4 - len(raw) % 4) % 4)
        try:
            txt = base64.b64decode(raw).decode("utf-8", "ignore").strip()
        except Exception:
            return ""
        if txt.startswith("http") or txt.startswith("//"):
            return txt
        return ""

    @staticmethod
    def _pick(obj, depth=0):
        """在解析返回的 JSON 里找第一个 http 地址"""
        if depth > 4 or obj is None:
            return ""
        if isinstance(obj, str):
            s = obj.strip()
            return s if s.startswith("http") or s.startswith("//") else ""
        if isinstance(obj, list):
            for it in obj:
                r = Spider._pick(it, depth + 1)
                if r:
                    return r
            return ""
        if isinstance(obj, dict):
            for k in URL_KEYS:
                if k in obj:
                    r = Spider._pick(obj[k], depth + 1)
                    if r:
                        return r
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    r = Spider._pick(v, depth + 1)
                    if r:
                        return r
        return ""

    def _resolve(self, url):
        api = (self.parse_api or "").strip()
        if not api:
            return ""
        if "url=" not in api:
            if not api.endswith("?") and not api.endswith("&"):
                api += "&" if "?" in api else "?"
            api += "url="
        target = api + quote(url, safe="")
        try:
            txt = self._http(target, timeout=20).decode("utf-8", "ignore").strip()
            if not txt:
                return ""
            try:
                return self._pick(json.loads(txt))
            except Exception:
                m = re.search(r'"url"\s*:\s*"([^"]+)"', txt)
                if m:
                    return m.group(1).replace("\\/", "/")
                if txt.startswith("http"):
                    return txt.split("\n")[0].strip()
        except Exception:
            return ""
        return ""

    def playerContent(self, flag, id, vipFlags):
        pid = (id or "").strip()
        if not pid:
            return {"parse": 1, "url": "", "header": {}}
        low = pid.lower()
        if (low.startswith("http://") or low.startswith("https://") or low.startswith("//")) \
                and VIDEO_RE.search(pid):
            return self._direct(pid)
        kl = self._decode_kl(pid)
        if kl and VIDEO_RE.search(kl):
            return self._direct(kl)
        real = self._resolve(pid)
        if not real and kl:
            real = self._resolve(kl)
        if real and VIDEO_RE.search(real):
            return self._direct(real)
        return {"parse": 1, "url": pid, "header": {"User-Agent": UA}, "jx": 1}

    @staticmethod
    def _direct(url):
        if url.startswith("//"):
            url = "https:" + url
        return {"parse": 0, "url": url, "header": {"User-Agent": UA}}
