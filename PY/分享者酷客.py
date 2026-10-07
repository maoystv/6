# -*- coding: utf-8 -*-
import json
import re
import threading
from base64 import b64encode, b64decode
from urllib.parse import quote, unquote, urljoin
import requests
import urllib3
urllib3.disable_warnings()

class Spider:
    def __init__(self):
        self.host = "https://www.8kvod.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
        ]
        self._lock = threading.Lock()
        self._session = None
        self._mcache = {}

    def getName(self):
        return "酷客影院"

    def getDependence(self):
        return []

    def init(self, extend=""):
        ext = {}
        try:
            if isinstance(extend, str) and extend.strip().startswith("{"):
                ext = json.loads(extend)
            elif isinstance(extend, dict):
                ext = extend
        except Exception:
            ext = {}
        if isinstance(ext, dict):
            if ext.get("host"):
                self.host = str(ext.get("host")).rstrip("/")
                self.headers["Referer"] = self.host + "/"
            if ext.get("ua"):
                self.headers["User-Agent"] = str(ext.get("ua"))
        try:
            self._mcache.clear()
        except Exception:
            pass
        return None

    @property
    def session(self):
        if self._session is None:
            with self._lock:
                if self._session is None:
                    s = requests.Session()
                    try:
                        s.headers.clear()
                    except Exception:
                        pass
                    try:
                        ua = ""
                        try:
                            ua = self.headers.get("User-Agent", "")
                        except Exception:
                            ua = ""
                        if not ua:
                            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        s.headers.update({"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9"})
                    except Exception:
                        pass
                    try:
                        s.verify = False
                    except Exception:
                        pass
                    self._session = s
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    @property
    def sess(self):
        return self.session

    @sess.setter
    def sess(self, value):
        self._session = value

    def destroy(self):
        try:
            with self._lock:
                if self._session is not None:
                    try:
                        self._session.close()
                    except Exception:
                        pass
                    self._session = None
        except Exception:
            self._session = None
        try:
            self._mcache.clear()
        except Exception:
            pass
        return None

    def _page_header(self, referer=None):
        try:
            ua = self.headers.get("User-Agent", "")
        except Exception:
            ua = ""
        if not ua:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ref = str(referer or "").strip()
        if not ref.startswith("http"):
            ref = self.host + "/"
        return {"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9", "Referer": ref}

    def _get(self, url, referer=None):
        hd = self._page_header(referer or self.host + "/")
        for _ in range(2):
            try:
                r = self.session.get(url, headers=hd, timeout=20, verify=False)
                if r.status_code == 200:
                    r.encoding = "utf-8"
                    return r.text
            except Exception:
                continue
        return ""

    def _post(self, url, data):
        for _ in range(2):
            try:
                r = self.session.post(url, data=data, headers=self._page_header(self.host + "/"), timeout=20, verify=False)
                if r.status_code == 200:
                    r.encoding = "utf-8"
                    return r.text
            except Exception:
                continue
        return ""

    def _fix(self, u):
        if not u:
            return ""
        u = str(u).strip().replace("&amp;", "&")
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return self.host + u
        return u

    def _pagecount(self, html):
        m = re.search(r'class="num">\s*\d+/(\d+)\s*</span>', html or "")
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return 1
        return 1

    def _split_title(self, title):
        title = str(title or "").strip()
        m = re.search(r'[\s\-]*(高清版|HD国语|HD中字|HD中英|TC国语|蓝光|已完结|更新至第\d+集)$', title)
        if m and m.start() > 0:
            return title[:m.start()].strip(), m.group(1)
        return title, ""

    def _cards(self, html):
        result, seen = [], set()
        blocks = re.findall(r'<li class="col-md-\d[^"]*">(.*?)</li>', html or "", re.S)
        for b in blocks:
            m = re.search(r'<a[^>]+data-original="([^"]*)"[^>]+href="/edu-(\d+)\.html"', b, re.S)
            if not m:
                continue
            pic, vid = m.group(1).strip(), m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            nm = re.search(r'<h4 class="title[^"]*">\s*<a[^>]+title="([^"]*)"', b) or re.search(r'<a[^>]+href="/edu-' + vid + r'\.html"[^>]*title="([^"]*)"', b)
            name = nm.group(1).strip() if nm else ""
            if not name:
                continue
            badges = [x.strip() for x in re.findall(r'<span class="pic-text[^"]*">([^<]*)</span>', b) if x.strip()]
            clean, tail = self._split_title(name)
            result.append({"vod_id": vid, "vod_name": clean or name, "vod_pic": self._fix(pic), "vod_remarks": badges[0] if badges else tail})
        if result:
            return result
        pat = re.compile(r'<a[^>]+data-original="([^"]*)"[^>]+href="/edu-(\d+)\.html"[^>]*title="([^"]*)"', re.S)
        for pic, vid, title in pat.findall(html or ""):
            if vid in seen:
                continue
            seen.add(vid)
            clean, tail = self._split_title(title)
            result.append({"vod_id": vid, "vod_name": clean or title, "vod_pic": self._fix(pic.strip()), "vod_remarks": tail})
        return result

    def _cards_media(self, html):
        result, seen = [], set()
        pat = re.compile(r'<a[^>]+data-original="([^"]*)"[^>]+href="/edu-(\d+)\.html"', re.S)
        namepat = re.compile(r'<h3 class="title">\s*<a href="/edu-\d+\.html">([^<]+)</a>')
        names = namepat.findall(html or "")
        for idx, (pic, vid) in enumerate(pat.findall(html or "")):
            if vid in seen:
                continue
            seen.add(vid)
            name = names[idx].strip() if idx < len(names) else vid
            result.append({"vod_id": vid, "vod_name": name, "vod_pic": self._fix(pic.strip()), "vod_remarks": "搜索"})
        return result

    def _filters(self):
        order = [{"key": "order", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hit"}]}]
        return {c["type_id"]: order for c in self.classes}

    def _proxy_pic_url(self, u):
        u = str(u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("/"):
            u = self.host + u
        if not u.startswith("http"):
            return ""
        return self._proxy_url(u, "img")

    def _wrap_pics(self, vods):
        try:
            for v in (vods or []):
                try:
                    pic = str(v.get("vod_pic") or "").strip()
                    if pic.startswith("http"):
                        v["vod_pic"] = self._proxy_pic_url(pic)
                except Exception:
                    continue
        except Exception:
            pass
        return vods

    def homeContent(self, filter=None):
        html = self._get(self.host + "/")
        vods = self._cards(html)
        if not vods:
            vods = self._cards(self._get(self.host + "/list/1.html"))
        return {"class": self.classes, "list": self._wrap_pics(vods[:20]), "filters": self._filters()}

    def homeVideoContent(self):
        return {"list": self.homeContent({})["list"]}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        tid = str(tid or "1")
        url = self.host + ("/list/%s_%d.html" % (tid, page) if page > 1 else "/list/%s.html" % tid)
        order = ""
        try:
            if isinstance(filter, dict):
                order = str(filter.get("order") or "")
            if not order and isinstance(extend, dict):
                order = str(extend.get("order") or "")
        except Exception:
            order = ""
        if order:
            url += "?order=" + order
        html = self._get(url)
        vods = self._cards(html)
        return {"page": page, "pagecount": self._pagecount(html), "limit": len(vods), "total": 0, "list": self._wrap_pics(vods)}

    def _one_detail(self, vid):
        try:
            vid = str(vid)
            html = self._get(self.host + "/edu-%s.html" % vid)
            if not html:
                return None
            nm = re.search(r'<h1 class="line1">([^<]+)</h1>', html)
            name = nm.group(1).strip() if nm else vid
            pm = re.search(r'<div class="stui-content__thumb">.*?data-original="([^"]*)"', html, re.S) or re.search(r'data-original="([^"]*)"', html)
            pic = self._fix(pm.group(1)) if pm else ""
            badges = [x.strip() for x in re.findall(r'<span class="pic-text[^"]*">([^<]*)</span>', html) if x.strip()]
            yr = re.search(r'/year\.php\?searchword=(\d{4})', html)
            ar = re.search(r'/area\.php\?searchword=([^"&]+)', html)
            tabs = re.findall(r'<a[^>]+href="#(down\d+)"[^>]*>([^<]+)</a>', html)
            sources, episodes = [], []
            for down_id, down_name in tabs:
                block = re.search(r'<div[^>]+id="' + down_id + r'"[^>]*>(.*?)(?=<div[^>]+id="down\d+"|<div class="stui-pannel)', html, re.S)
                if not block:
                    continue
                items = re.findall(r'<a href="(/gov-\d+-\d+-\d+\.html)"[^>]*title="([^"]*)"', block.group(1))
                if not items:
                    continue
                eps = ["%s$%s" % (t.strip(), self._fix(u)) for u, t in items]
                sources.append(down_name.strip())
                episodes.append("#".join(eps))
            if not sources:
                return None
            upd = re.search(r'更新：</span>([0-9\-: ]+)', html)
            vod_pic = self._proxy_pic_url(pic) if pic.startswith("http") else pic
            return {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": vod_pic,
                "vod_remarks": badges[0] if badges else (upd.group(1).strip() if upd else ""),
                "vod_year": yr.group(1) if yr else "",
                "vod_area": ar.group(1) if ar else "",
                "vod_actor": ",".join(re.findall(r'/actor\.php\?searchword=([^"&]+)', html)[:5]),
                "vod_play_from": "$$$".join(sources),
                "vod_play_url": "$$$".join(episodes),
            }
        except Exception:
            return None

    def detailContent(self, ids):
        out = []
        try:
            seq = ids if isinstance(ids, (list, tuple)) else [ids]
        except Exception:
            seq = []
        for i in (seq or []):
            try:
                x = self._one_detail(str(i))
            except Exception:
                x = None
            if x:
                out.append(x)
        return {"list": out}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        html = self._post(self.host + "/search.php", {"searchword": str(key)})
        vods = self._cards_media(html) or self._cards(html)
        return {"list": self._wrap_pics(vods), "page": page, "pagecount": 1, "limit": len(vods), "total": len(vods)}

    def getProxyUrl(self, local=True):
        try:
            from com.github.catvod import Proxy as _CatProxy
            try:
                return str(_CatProxy.getUrl(local)) + "?do=py"
            except Exception:
                return str(_CatProxy.getUrl()) + "?do=py"
        except Exception:
            pass
        return "http://127.0.0.1:9978/proxy?do=py"

    def _proxy_root(self):
        try:
            u = self.getProxyUrl(True)
            if u:
                return str(u)
        except Exception:
            pass
        return "http://127.0.0.1:9978/proxy?do=py"

    def _proxy_url(self, url, kind="media", referer=None):
        root = self._proxy_root()
        sep = "&" if "?" in root else "?"
        u = root + sep + "type=" + kind + "&url=" + quote(str(url or ""), safe="")
        ref = str(referer or "").strip()
        if ref.startswith("http"):
            u += "&referer=" + quote(ref, safe="")
        return u

    def _browser_base(self):
        try:
            ua = self.headers.get("User-Agent", "")
        except Exception:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        if not ua:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        return {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def _media_header(self, url="", referer=""):
        h = self._browser_base()
        try:
            low = str(url or "").lower()
            h.pop("Referer", None)
            if "file.icve.com.cn" in low:
                return dict(h)
            ref = str(referer or "").strip()
            h["Referer"] = ref if ref.startswith("http") else (self.host + "/")
        except Exception:
            pass
        return h

    def _is_media(self, url):
        low = str(url or "").lower().split("?")[0]
        return low.endswith((".m3u8", ".mp4", ".ts", ".m4s", ".key")) or ".m3u8" in low

    def _unescape(self, raw):
        u = str(raw or "")
        try:
            if "\\u" in u:
                u = re.sub(r'\\u([0-9a-fA-F]{4})', lambda g: chr(int(g.group(1), 16)), u)
            u = u.replace("\\/", "/").replace("\\", "")
        except Exception:
            pass
        return u

    def _fetch_bin(self, url, head, timeout=15):
        for _ in range(3):
            try:
                r = self.session.get(url, headers=head, timeout=timeout, verify=False)
                if r.status_code == 200 and r.content:
                    return r
            except Exception:
                continue
        return None

    def _sub_url(self, url, body):
        m = re.search(r'#EXT-X-STREAM-INF[^\n]*\n\s*([^\n#]+)', body or "")
        if not m:
            return ""
        path = m.group(1).strip()
        return path if path.startswith("http") else urljoin(url, path)

    def _playlist(self, url, head):
        r = self._fetch_bin(url, head, 20)
        base = url
        if r is None:
            return url, ""
        try:
            text = r.text
        except Exception:
            text = ""
        if not text or "#EXTINF" not in text:
            try:
                text = self._fetch_m3u8_text(url, head, 20)
            except Exception:
                text = text or ""
            if not text or "#EXTINF" not in text:
                return base, (text or "")
        if "#EXT-X-STREAM-INF" not in text:
            return base, text
        sub = self._sub_url(base, text)
        if not sub:
            return base, text
        r2 = self._fetch_bin(sub, head, 20)
        try:
            t2 = r2.text if r2 is not None else ""
        except Exception:
            t2 = ""
        if r2 is None or "#EXTINF" not in t2:
            try:
                t2 = self._fetch_m3u8_text(sub, head, 20)
            except Exception:
                t2 = t2 or ""
            if not t2 or "#EXTINF" not in t2:
                return base, text
        try:
            self._mcache[url] = sub
            self._mcache[base] = sub
        except Exception:
            pass
        return sub, t2

    def _prewarm(self, text, base, head):
        return text

    def _fetch_m3u8_text(self, url, head, timeout=20):
        last = ""
        for _ in range(3):
            try:
                r = self.session.get(url, headers=dict(head or {}), timeout=timeout, verify=False)
                if r.status_code == 200 and r.text and "#EXTINF" in r.text:
                    return r.text
                if r.status_code == 200 and r.text:
                    last = r.text
            except Exception:
                continue
        return last

    def _rewrite_m3u8(self, text, base, referer=""):
        root = self._proxy_root()
        sep = "&" if "?" in root else "?"
        ref = str(referer or "").strip()
        if not ref.startswith("http"):
            ref = ""
        out = []
        for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line:
                out.append("")
                continue
            if line.startswith("#"):
                if "URI=" in line:
                    def _rp(m):
                        v = m.group(2)
                        if not v.startswith("http"):
                            v = urljoin(base, v)
                        if ref:
                            return m.group(1) + self._proxy_url(v, "media", ref) + m.group(3)
                        return m.group(1) + self._proxy_url(v, "media") + m.group(3)
                    line = re.sub(r'(URI=")([^"]+)(")', _rp, line)
                out.append(line)
                continue
            a = line if line.startswith("http") else urljoin(base, line)
            if ref:
                out.append(root + sep + "type=ts&url=" + quote(a, safe="") + "&referer=" + quote(ref, safe=""))
            else:
                out.append(root + sep + "type=ts&url=" + quote(a, safe=""))
        body = "\n".join(out)
        return body if body.endswith("\n") else body + "\n"

    def playerContent(self, flag, id, vipFlags=None):
        page = self._fix(id)
        html = ""
        for _ in range(3):
            html = self._get(page, self.host + "/")
            if html and re.search(r'<iframe[^>]+src="([^"]+)"', html):
                break
        if not html:
            return {"parse": 0, "url": self._proxy_url(page, "media"), "header": self._media_header()}
        m3u8 = re.search(r'https?://[^\s"\'<>\]]+\.m3u8[^\s"\'<>\]]*', html)
        if m3u8:
            return self._play(m3u8.group(0))
        m = re.search(r'<iframe[^>]+src="([^"]+)"', html)
        depth = 0
        while m and depth < 3:
            cur = self._fix(m.group(1))
            body = ""
            for _ in range(3):
                try:
                    r = self.session.get(cur, headers={"Referer": page}, timeout=20, verify=False)
                    if r.status_code == 200 and r.text:
                        body = r.text
                        break
                except Exception:
                    continue
            if not body:
                break
            m3u8 = re.search(r'https?://[^\s"\'<>\]]+\.m3u8[^\s"\'<>\]]*', body)
            if m3u8:
                return self._play(m3u8.group(0))
            m = re.search(r'<iframe[^>]+src="([^"]+)"', body)
            depth += 1
        if m:
            return {"parse": 1, "url": self._fix(m.group(1)), "header": self._media_header()}
        return {"parse": 0, "url": self._proxy_url(page, "media"), "header": self._media_header()}

    def _play(self, raw):
        real = self._unescape(raw)
        if not self._is_media(real):
            return {"parse": 1, "url": real, "header": self._media_header()}
        return {"parse": 0, "url": self._proxy_url(real, "m3u8"), "header": self._media_header(real), "format": "application/x-mpegURL"}

    def _img_ct(self, data):
        try:
            if not data:
                return "image/jpeg"
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                return "image/png"
            if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                return "image/webp"
            if data[:6] in (b"GIF87a", b"GIF89a"):
                return "image/gif"
            if data[:3] == b"\xff\xd8\xff":
                return "image/jpeg"
            if data[:4] == b"\x00\x00\x00\x18" or (len(data) > 4 and data[4:8] == b"ftyp"):
                return "image/heic"
            if data[:2] == b"BM":
                return "image/bmp"
        except Exception:
            pass
        return "image/jpeg"

    def _img_header(self, referer=""):
        try:
            ua = self.headers.get("User-Agent", "")
        except Exception:
            ua = ""
        if not ua:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        h = {"User-Agent": ua, "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8"}
        ref = str(referer or "").strip()
        if ref.startswith("http"):
            h["Referer"] = ref
        return h

    def _decode_maybe_b64(self, s):
        t = str(s or "").strip()
        if not t or not t.startswith("http"):
            try:
                pad = "=" * (-len(t) % 4)
                raw = b64decode(t + pad)
                txt = raw.decode("utf-8", errors="ignore").strip()
                if txt.startswith("http"):
                    return txt
            except Exception:
                pass
        return t

    def _fetch_img(self, url, referer=""):
        head = self._img_header(referer)
        for _ in range(3):
            try:
                r = self.session.get(url, headers=head, timeout=20, verify=False)
                if r.status_code == 200 and r.content and len(r.content) > 200:
                    return r.content
            except Exception:
                continue
        if referer:
            head2 = self._img_header("")
            for _ in range(2):
                try:
                    r = self.session.get(url, headers=head2, timeout=20, verify=False)
                    if r.status_code == 200 and r.content and len(r.content) > 200:
                        return r.content
                except Exception:
                    continue
        return b""

    def localProxy(self, param):
        try:
            if isinstance(param, str):
                try:
                    param = json.loads(param)
                except Exception:
                    param = dict()
            if not isinstance(param, dict):
                param = dict()
            else:
                param = dict(param)
            kind = param.get("type") or param.get("action") or param.get("do") or ""
            if isinstance(kind, list):
                kind = kind[0] if kind else ""
            kind = str(kind or "").strip().lower()
            url = param.get("url") or ""
            if isinstance(url, list):
                url = url[0] if url else ""
            referer = param.get("referer") or param.get("ref") or ""
            if isinstance(referer, list):
                referer = referer[0] if referer else ""
            try:
                url = unquote(str(url or "")).replace("\\/", "/").strip()
            except Exception:
                url = str(url or "").replace("\\/", "/").strip()
            try:
                referer = unquote(str(referer or "")).strip()
            except Exception:
                referer = str(referer or "").strip()
            if not url:
                return [404, "text/plain", "Not Found"]
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http"):
                return [404, "text/plain", "Unsupported"]
            if not kind or kind in ("py", "proxy", "media"):
                low_all = (url + " " + referer).lower()
                if ".m3u8" in low_all or "m3u8" in low_all:
                    kind = "m3u8"
                elif url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".heic")) or "/260" in url or "imageMogr2" in url or "ykimg.com" in url.lower() or "qpic.cn" in url.lower():
                    kind = "img"
                else:
                    kind = "ts"
            if kind == "img":
                try:
                    raw = self._decode_maybe_b64(url)
                    if raw.startswith("//"):
                        raw = "https:" + raw
                    if not raw.startswith("http"):
                        return [404, "text/plain", "Unsupported"]
                    data = self._fetch_img(raw, referer)
                except Exception:
                    data = b""
                if not data:
                    return [404, "text/plain", "Fetch Failed"]
                return [200, self._img_ct(data), data]
            head = self._media_header(url, referer)
            if kind == "m3u8" or ".m3u8" in url.lower():
                try:
                    base, body = self._playlist(url, head)
                except Exception:
                    base, body = url, ""
                if not body:
                    return [404, "text/plain", "Fetch Failed"]
                try:
                    data = self._rewrite_m3u8(body, base, referer)
                except Exception:
                    try:
                        data = str(body or "")
                    except Exception:
                        data = "Fetch Failed"
                if not data:
                    return [404, "text/plain", "Fetch Failed"]
                return [200, "application/vnd.apple.mpegurl", data]
            try:
                r = self._fetch_bin(url, head, 20)
            except Exception:
                r = None
            if r is None:
                return [404, "text/plain", "Fetch Failed"]
            try:
                body = r.content
            except Exception:
                body = b""
            if not body:
                return [404, "text/plain", "Fetch Failed"]
            mime = "application/octet-stream"
            try:
                if body[:1] == b"\x47":
                    mime = "video/mp2t"
                elif body[:4] == b"\x89PNG":
                    mime = "image/png"
                elif body[:3] == b"\xff\xd8\xff":
                    mime = "image/jpeg"
                elif body[:4] == b"RIFF":
                    mime = "audio/wav"
            except Exception:
                mime = "application/octet-stream"
            try:
                if not isinstance(body, (bytes, bytearray)):
                    body = str(body or "").encode("utf-8")
                else:
                    body = bytes(body)
            except Exception:
                return [404, "text/plain", "Fetch Failed"]
            return [200, mime, body]
        except Exception:
            return [500, "text/plain", "proxy error"]

    def proxy(self, param):
        return self.localProxy(param)

    def isVideoFormat(self, url):
        try:
            return self._is_media(url)
        except Exception:
            return False

    def manualVideoCheck(self):
        return False

    def liveContent(self, url):
        return ""

    def action(self, action):
        return {}
