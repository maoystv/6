# 看看鸭 Python蜘蛛
import base64
import http.cookiejar
import json
import random
import re
import threading
import time
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        pass


BRAND_NAME = "分享者影视"
BRAND_ACTOR = "分享者在线"
BRAND_DIRECTOR = "分享者影视"
TG_GROUP = "分享者在线"
SYNOPSIS_GROUP = "分享者影视"
DIVIDER_THIN = "────────────────────"
DIVIDER_THICK = "━━━━━━━━━━━━━━"
MARKER = "〔影片简介〕"
LINE_NAME = "分享者专线"
NODE_LINE = "当前节点：https://www.kankanya.me"

BASE = "https://www.kankanya.me"
HOST = "www.kankanya.me"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_1_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Mobile/15E148 Safari/604.1"
VERIFY_CHARS = "PXhw7UT1B0a9kQDKZsjIASmOezxYG4CHo5Jyfg2b8FLpEvRr3WtVnlqMidu6cN"
PAGE_SIZE = 40

CLASSES = [
    {"type_id": "dianying", "type_name": "电影"},
    {"type_id": "juji", "type_name": "剧集"},
    {"type_id": "zongyi", "type_name": "综艺"},
    {"type_id": "dongman", "type_name": "动漫"},
]

FILTER_DATA = {
    "dianying": {
        "area": ["大陆", "香港", "台湾", "美国", "日本", "韩国", "英国", "法国", "德国", "泰国", "印度", "意大利", "西班牙", "加拿大", "其他"],
        "class": ["剧情", "喜剧", "动作", "爱情", "科幻", "悬疑", "惊悚", "恐怖", "犯罪", "古装", "武侠", "战争", "历史", "奇幻", "动画", "冒险", "儿童", "文艺", "青春", "运动", "农村", "警匪", "枪战", "网络电影", "微电影", "经典"],
        "lang": ["国语", "粤语", "英语", "日语", "韩语", "法语", "德语", "闽南语", "其它"],
        "year": ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010"],
    },
    "juji": {
        "area": ["内地", "香港", "台湾", "新加坡", "日本", "泰国", "美国", "英国", "韩国", "其他"],
        "class": ["剧情", "喜剧", "古装", "动作", "奇幻", "犯罪", "家庭", "战争", "历史", "商战", "情景", "乡村", "网剧", "青春偶像", "经典", "其他"],
        "lang": ["国语", "粤语", "英语", "日语", "韩语", "闽南语", "其它"],
        "year": ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010", "2009", "2008", "2006", "2005", "2004"],
    },
    "zongyi": {
        "area": ["内地", "港台", "日韩", "欧美"],
        "class": ["音乐", "选秀", "访谈", "纪实", "美食", "旅游", "生活", "游戏互动", "求职", "情感", "财经", "曲艺", "播报"],
        "lang": ["国语", "粤语", "英语", "日语", "韩语", "闽南语", "其它"],
        "year": ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010", "2009", "2008", "2007", "2006", "2005", "2004"],
    },
    "dongman": {
        "area": ["国产", "日本", "欧美", "其他"],
        "class": ["热血", "科幻", "搞笑", "校园", "少年", "少女", "冒险", "动作", "推理", "机战", "战争", "情感", "励志", "亲子", "益智", "运动", "社会", "原创", "萝莉", "其他"],
        "lang": ["国语", "粤语", "英语", "日语", "韩语", "闽南语", "其它"],
        "year": ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010", "2009", "2008", "2007", "2006", "2005", "2004"],
    },
}

SLOT_OF = {"area": 1, "by": 2, "class": 3, "lang": 4, "year": 11}
FILTER_TITLES = {"class": "类型", "area": "地区", "lang": "语言", "year": "年份", "by": "排序"}
BY_OPTIONS = [("", "默认"), ("time", "最新"), ("hits", "人气"), ("score", "评分")]


def _encrypt(text):
    out = []
    for ch in text:
        idx = VERIFY_CHARS.find(ch)
        code = VERIFY_CHARS[(idx + 3) % 62] if idx >= 0 else ch
        out.append(VERIFY_CHARS[random.randrange(62)] + code + VERIFY_CHARS[random.randrange(62)])
    return base64.b64encode("".join(out).encode("utf-8")).decode("utf-8")


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"\s+", " ", text).strip()


class Spider(BaseSpider):
    def __init__(self):
        self.opener = None
        self.timeout = 8
        self._cache = {}
        self._lock = threading.Lock()
        self.extend = ""

    def init(self, extend=""):
        self.extend = extend

    def getName(self):
        return BRAND_NAME

    def _session(self):
        if self.opener is None:
            jar = http.cookiejar.CookieJar()
            self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        return self.opener

    def _raw(self, url, data=None, referer=None):
        headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"}
        if referer:
            headers["Referer"] = referer
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        with self._session().open(req, timeout=self.timeout) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")

    def _is_verify(self, text):
        return "robot.php" in text and bool(re.findall(r'encrypt\("([^"]+)"\)', text))

    def _fetch(self, url):
        try:
            status, final, text = self._raw(url)
        except Exception:
            status, final, text = self._raw(url)
        if self._is_verify(text):
            seeds = re.findall(r'encrypt\("([^"]+)"\)', text)
            payload = urllib.parse.urlencode({"value": _encrypt(final), "token": _encrypt(seeds[-1])}).encode("utf-8")
            self._raw(BASE + "/robot.php", data=payload, referer=final)
            status, final, text = self._raw(url)
            if self._is_verify(text):
                raise RuntimeError("站点人机验证未通过")
        return status, final, text

    def _cached(self, url, ttl):
        now = time.time()
        with self._lock:
            hit = self._cache.get(url)
            if hit and now - hit[1] < ttl:
                return hit[0], hit[2], hit[3]
        status, final, text = self._fetch(url)
        with self._lock:
            self._cache[url] = (status, now, final, text)
        return status, final, text

    def _parse_cards(self, text):
        items = []
        seen = set()
        for m in re.finditer(r'<a[^>]+href="(/detail/[^"]+\.html)"[^>]*>(.*?)</a>', text, re.S):
            path, block = m.group(1), m.group(2)
            if path in seen:
                continue
            img = re.search(r'data-original="([^"]+)"', block)
            if not img:
                continue
            seen.add(path)
            anchor = m.group(0)
            title = re.search(r'title="([^"]+)"', anchor)
            name = title.group(1) if title else ""
            if not name:
                alt = re.search(r'alt="([^"]+)"', block)
                name = alt.group(1) if alt else ""
            note = re.search(r'module-item-note">([^<]*)<', block)
            items.append({
                "vod_id": path,
                "vod_name": name,
                "vod_pic": img.group(1),
                "vod_remarks": note.group(1).strip() if note else "",
            })
        return items

    def _filters_for(self, slug):
        data = FILTER_DATA.get(slug)
        if not data:
            return []
        groups = []
        for key in ("class", "area", "lang", "year"):
            values = [{"n": "全部", "v": ""}]
            for v in data[key]:
                values.append({"n": v, "v": v})
            groups.append({"key": key, "name": FILTER_TITLES[key], "value": values})
        by_values = [{"n": n, "v": v} for v, n in BY_OPTIONS]
        groups.append({"key": "by", "name": FILTER_TITLES["by"], "value": by_values})
        return groups

    def homeContent(self, filter):
        filters = {}
        for cls in CLASSES:
            filters[cls["type_id"]] = self._filters_for(cls["type_id"])
        return {"class": [dict(c) for c in CLASSES], "filters": filters}

    def homeVideoContent(self):
        try:
            status, final, text = self._fetch(BASE + "/")
            return {"list": self._parse_cards(text)[:36]}
        except Exception as err:
            return {"list": [], "msg": "首页加载失败：%s" % err}

    def _clean_filter(self, slug, filt):
        data = FILTER_DATA.get(slug) or {}
        allowed = {}
        for key in ("class", "area", "lang", "year"):
            allowed[key] = set(data.get(key) or [])
        allowed["by"] = set(v for v, n in BY_OPTIONS)
        name2value = {}
        for v, n in BY_OPTIONS:
            name2value[("by", n)] = v
        clean = {}
        for key, value in (filt or {}).items():
            value = str(value or "")
            if not value:
                continue
            if value in allowed.get(key, set()):
                clean[key] = value
            elif (key, value) in name2value:
                clean[key] = name2value[(key, value)]
        return clean

    def _show_url(self, slug, page, filt):
        parts = [slug] + [""] * 11
        for key, slot in SLOT_OF.items():
            value = str((filt or {}).get(key) or "")
            if value:
                parts[slot] = value
        if int(page or 1) > 1:
            parts[8] = str(page)
        return BASE + "/show/" + "-".join(urllib.parse.quote(p, safe="") for p in parts) + ".html"

    def _pagecount(self, text, slug):
        best = 1
        for href in re.findall(r'href="(/show/[^"]+)"', text):
            parts = urllib.parse.unquote(href)[len("/show/"):-len(".html")].split("-")
            if len(parts) == 12 and parts[0] == slug and parts[8].isdigit():
                best = max(best, int(parts[8]))
        return best

    def categoryContent(self, tid, pg, filter, extend):
        slug = str(tid or "")
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        ext = extend if isinstance(extend, dict) else {}
        merged = dict(ext) if ext else (filter if isinstance(filter, dict) else {})
        try:
            status, final, text = self._cached(self._show_url(slug, page, self._clean_filter(slug, merged)), 300)
            items = self._parse_cards(text)
            pagecount = self._pagecount(text, slug)
            if page > pagecount:
                pagecount = page
            return {"list": items, "page": page, "pagecount": pagecount, "limit": len(items), "total": pagecount * PAGE_SIZE}
        except Exception as err:
            return {"list": [], "page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 0, "msg": "分类加载失败：%s" % err}

    def searchContent(self, key, quick, pg="1"):
        keyword = str(key or "").strip()
        if not keyword:
            return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": 0}
        try:
            url = BASE + "/search/" + urllib.parse.quote(keyword) + "-" * 13 + ".html"
            status, final, text = self._fetch(url)
            items = self._parse_cards(text)
            return {"list": items, "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": len(items)}
        except Exception as err:
            return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": 0, "msg": "搜索失败：%s" % err}

    def detailContent(self, ids):
        cid = str(ids[0] if ids else "").strip()
        if not cid:
            return {"list": [], "msg": "内容标识无效"}
        url = cid if cid.startswith("http") else BASE + (cid if cid.startswith("/") else "/" + cid)
        try:
            status, final, text = self._cached(url, 600)
        except Exception as err:
            return {"list": [], "msg": "详情加载失败：%s" % err}
        h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", text)
        if h1:
            name = h1.group(1).strip()
        else:
            t = re.search(r"<title>([^<]+)</title>", text)
            name = re.split(r"详情介绍|在线观看|[-_]", t.group(1))[0].strip() if t else ""
        poster = ""
        pm = re.search(r'module-info-poster.*?<img[^>]+data-original="([^"]+)"', text, re.S)
        if pm:
            poster = pm.group(1)
        meta = {}
        for m in re.finditer(r'module-info-item-title">([^<]+)</span>\s*<div class="module-info-item-content">(.*?)</div>', text, re.S):
            meta[m.group(1).replace("：", "").strip()] = _clean(m.group(2)).rstrip("/").strip()
        synopsis = ""
        for m in re.finditer(r'<div class="module-info-content">(.*?)</div>', text, re.S):
            block = _clean(m.group(1))
            if len(block) > len(synopsis):
                synopsis = block
        groups = {}
        order = []
        for m in re.finditer(r'<a[^>]+href="(/play/[^"]+\.html)"[^>]*>(.*?)</a>', text, re.S):
            path, inner = m.group(1), m.group(2)
            seg = re.search(r'-(\d+)-(\d+)\.html$', path)
            if not seg:
                continue
            sid = seg.group(1)
            ep_name = _clean(inner) or ("第%s集" % seg.group(2))
            if sid not in groups:
                groups[sid] = []
                order.append(sid)
            if not any(e["id"] == path for e in groups[sid]):
                groups[sid].append({"name": ep_name, "id": path})
        froms = []
        urls = []
        for sid in order:
            froms.append("线路%s" % sid)
            urls.append("#".join("%s$%s" % (e["name"], e["id"]) for e in groups[sid]))
        content_parts = [NODE_LINE, BRAND_NAME]
        for label in ("导演", "主演", "编剧", "上映", "集数", "片长", "更新"):
            if meta.get(label):
                content_parts.append("%s：%s" % (label, meta[label]))
        content_parts.append(DIVIDER_THIN)
        content_parts.append(MARKER)
        content_parts.append(synopsis or "暂无简介")
        content_parts.append(DIVIDER_THIN)
        content_parts.append(SYNOPSIS_GROUP)
        vod = {
            "vod_id": cid,
            "vod_name": name,
            "vod_pic": poster,
            "vod_remarks": meta.get("集数", ""),
            "type_name": meta.get("类型", ""),
            "vod_actor": BRAND_ACTOR,
            "vod_director": BRAND_DIRECTOR,
            "vod_content": "\n".join(content_parts),
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        pid = str(id or "").strip()
        if not pid:
            return {"parse": 0, "url": "", "msg": "播放标识无效"}
        url = pid if pid.startswith("http") else BASE + (pid if pid.startswith("/") else "/" + pid)
        try:
            status, final, text = self._fetch(url)
        except Exception as err:
            return {"parse": 0, "url": "", "msg": "播放页加载失败：%s" % err}
        m = re.search(r"player_aaaa\s*=\s*(\{.*?\})\s*</script>", text, re.S)
        if not m:
            return {"parse": 0, "url": "", "msg": "未找到播放数据"}
        try:
            data = json.loads(m.group(1))
        except Exception as err:
            return {"parse": 0, "url": "", "msg": "播放数据解析失败：%s" % err}
        raw = str(data.get("url") or "")
        if not raw:
            return {"parse": 0, "url": "", "msg": "播放地址为空"}
        if raw.startswith("http") and (".m3u8" in raw or ".mp4" in raw):
            return {"parse": 0, "url": raw, "header": {"User-Agent": UA, "Referer": BASE + "/"}}
        real = self._decode_vid(raw)
        if "baidu.com/404" in real or real.endswith("/404.mp4"):
            real = ""
        if real.startswith("http"):
            return {"parse": 0, "url": real, "header": {"User-Agent": UA, "Referer": BASE + "/"}}
        play_url = BASE + "/kkyplayer/index.php?vid=" + urllib.parse.quote(raw, safe="")
        return {"parse": 1, "url": play_url, "header": {"User-Agent": UA, "Referer": final}}

    def _decode_vid(self, enc):
        key = "vid:" + str(enc)
        with self._lock:
            hit = self._cache.get(key)
            if hit:
                return hit[0]
        for attempt in range(3):
            real = self._decode_once(enc)
            if real.startswith("http"):
                with self._lock:
                    self._cache[key] = (real, time.time(), real, real)
                return real
            time.sleep(0.25)
        return ""

    def _decode_once(self, enc):
        try:
            payload = urllib.parse.urlencode({"vid": enc}).encode("utf-8")
            req = urllib.request.Request(BASE + "/kkyplayer/api.php", data=payload, headers={"User-Agent": UA, "Referer": BASE + "/"})
            with self._session().open(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            text = str((data.get("data") or {}).get("url") or "")
            if not text:
                return ""
            raw = base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf-8", "replace")
            out = []
            for i in range(0, len(raw) - 2, 3):
                ch = raw[i + 1]
                idx = VERIFY_CHARS.find(ch)
                out.append(VERIFY_CHARS[(idx - 3) % 62] if idx >= 0 else ch)
            return "".join(out)
        except Exception:
            return ""

    def localProxy(self, param):
        return [404, "text/plain", ""]

# --- System Signature ---
#‍​​‌‌​‌​‌​​‌‌​‌‌​​​‌‌​​‌​​​‌‌​​‌‌​​‌‌​‌‌​​​‌‌​‌​‌​​‌‌‌​​‌​​‌‌​​​‌​​‌‌​​‌​​​‌‌​​‌​‍
