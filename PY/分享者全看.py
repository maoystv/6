# -*- coding: utf-8 -*-
"""
================================================================================
 全看影院 qkw1.com · 影视仓 hipy Python 源
================================================================================
 站点   : https://www.qkw1.com  (苹果CMS / STUI 模板，无采集 API，按 HTML 抓取)
 接口   : homeContent / homeVideoContent / categoryContent
          searchContent / detailContent / playerContent
 反爬   : 站点对 requests 的 TLS 指纹返回"请用浏览器"假页，改用 urllib + 共享
          cookie 绕过；播放页(/qkwplay)对高频 IP 触发 WAF(403+自跳转JS挑战)，
          短时间封禁，需降低请求频率或等待解封。
 播放   : 播放页 player_aaaa.encrypt 多为 3，url 为「固定混淆前缀
          atHiRa0nccHiM060L3yl9i + base64」，本源暴力扫描对齐偏移正则提取
          真实 m3u8/mp4 直链；解出明文直链时 parse=0 直连。
          无法解出(如 bfzym3u8)或直链失效时，回退到原站解析器 iframe
          (zyz-...xmsu8.top，由 /static/player/{from}.js 指向)，parse=1 交由
          影视仓内置播放器渲染——解析器带 IP 绑定(yonghuip)，影视仓设备
          直接请求时绑定设备 IP，可正常播放；不要在源端代请求解析器。
 边界   : 1) m3u8 CDN 域名(lzcdn28.com / vvvip-plays33.cc 等)为短期轮换，
             常已失效(DoH 无 A 记录)，直连失败请切其它线路。
          2) JP超清源/KK超清源等部分线路对热门剧触发 WAF 403，属站方限制。
          3) BF 高清源(bfzym3u8)用不同加密，暂无法静态解出，走解析器。
================================================================================
"""
import json
import re
import html
import base64
import datetime
import ssl
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

try:
    import requests
except Exception:
    requests = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def init(self, extend=""): pass
        def getName(self): return ""
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False
        def destroy(self): pass
        def localProxy(self, param): return None


HOST = "https://www.qkw1.com"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
_COOKIES = CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_COOKIES),
    urllib.request.HTTPSHandler(context=_SSL),
)
_OPENER.addheaders = list(HEADERS.items())

CATEGORIES = [
    ("dy", "电影"),
    ("tv", "连续剧"),
    ("zy", "综艺"),
    ("dm", "动漫"),
    ("duanju", "短剧"),
]

_LI_RE = re.compile(
    r'<li class="stui-vodlist__item">\s*'
    r'<a class="stui-vodlist__thumb[^"]*"[^>]*?href="(/qkwtv/\d+\.html)"[^>]*?title="([^"]*)"[^>]*?'
    r'data-original="([^"]*)"[^>]*>.*?'
    r'<span class="pic-text[^"]*">([^<]*)</span>.*?'
    r'<h4 class="stui-vodlist__title">.*?title="([^"]*)"',
    re.S,
)
_PAGE_RE = re.compile(r'/qkwlist/([a-z]+)-(\d+)\.html')
_FILTER_KEYS = {"按类型": "type", "按地区": "area", "按年份": "year", "按排序": "sort"}


def _strip(text):
    return re.sub(r'<[^>]+>', '', text or '').replace('&amp;', '&').strip()


def _normalize_pic(url):
    """还原 HTML 实体，并补齐协议相对/站点相对封面地址。"""
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return HOST + url
    return url


def _get(url, referer=None, timeout=20):
    """优先 urllib（该站会按 TLS 指纹拦截 requests），并共享 cookie。"""
    headers = list(HEADERS.items())
    if referer:
        headers.append(("Referer", referer))
    req = urllib.request.Request(url)
    for k, v in headers:
        req.add_header(k, v)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return 0, ""


def _parse_list(html):
    videos = []
    for href, title, pic, remark, name in _LI_RE.findall(html):
        vid = re.search(r'/qkwtv/(\d+)\.html', href).group(1)
        videos.append({
            "vod_id": vid,
            "vod_name": name or title,
            "vod_pic": _normalize_pic(pic),
            "vod_remarks": remark.strip(),
        })
    return videos


def _parse_filters(html):
    """从分类页的 STUI 筛选栏生成影视仓 filters 配置。"""
    filters = []
    for block in re.findall(r'<ul class="stui-screen__list[^>]*>(.*?)</ul>', html or "", re.S):
        label_m = re.search(r'<span class="text-muted">([^<]+)</span>', block)
        if not label_m:
            continue
        key = _FILTER_KEYS.get(label_m.group(1).strip())
        if not key:
            continue
        values = [{"n": "默认" if key == "sort" else "全部", "v": ""}]
        for href, name in re.findall(r'<a[^>]*href="(/qkwshow/[^"]+)"[^>]*>(.*?)</a>', block, re.S):
            parts = re.sub(r"\.html$", "", href.rsplit("/", 1)[-1]).split("-")
            index = {"type": 0, "area": 1, "sort": 2, "year": 11}[key]
            if len(parts) <= index or not parts[index]:
                continue
            value = urllib.parse.unquote(parts[index])
            item = {"n": _strip(name), "v": value}
            if item["n"] and item not in values:
                values.append(item)
        if len(values) > 1:
            filters.append({"key": key, "name": label_m.group(1).strip().replace("按", ""), "value": values})
    # 多数分类的排序在列表导航栏，而不在 stui-screen__list 筛选栏中。
    if not any(item["key"] == "sort" for item in filters):
        nav_m = re.search(r'<ul class="stui-pannel__nav[^>]*>(.*?)</ul>', html or "", re.S)
        values = [{"n": "默认", "v": ""}]
        if nav_m:
            for href, name in re.findall(r'<a[^>]*href="(/qkwshow/[^"]+)"[^>]*>(.*?)</a>', nav_m.group(1), re.S):
                parts = re.sub(r"\.html$", "", href.rsplit("/", 1)[-1]).split("-")
                if len(parts) > 2 and parts[2] in ("time", "hits", "score"):
                    item = {"n": _strip(name).replace("按", ""), "v": parts[2]}
                    if item["n"] and item not in values:
                        values.append(item)
        if len(values) == 1:
            # 综艺/动漫默认页不显示排序栏，但其 qkwshow 路由支持相同排序参数。
            values.extend([{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}])
        filters.append({"key": "sort", "name": "排序", "value": values})
    return filters


def _filter_url(tid, page, extend):
    """苹果CMS qkwshow 路由：地区/排序/页码/年份分别在 1/2/8/11 位。"""
    area = urllib.parse.quote(str(extend.get("area", "")).strip(), safe="")
    sort = str(extend.get("sort", "")).strip()
    year = str(extend.get("year", "")).strip()
    if sort not in ("", "time", "hits", "score"):
        sort = ""
    if year and not re.fullmatch(r"\d{4}", year):
        year = ""
    parts = [tid, area, sort, "", "", "", "", "", str(page) if page > 1 else "", "", "", year]
    return f"{HOST}/qkwshow/{'-'.join(parts)}.html"


def _page_count(html, current):
    pagecount = current
    for href in re.findall(r'href="([^"]*(?:qkwlist|qkwshow)/[^"]+\.html)"', html or ""):
        if "/qkwlist/" in href:
            match = re.search(r'-(\d+)\.html$', href)
            number = int(match.group(1)) if match else 0
        else:
            parts = re.sub(r"\.html$", "", href.rsplit("/", 1)[-1]).split("-")
            number = int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else 0
        pagecount = max(pagecount, number)
    return pagecount


class Spider(BaseSpider):

    def getName(self):
        return "全看影院"

    def init(self, extend=""):
        self.host = HOST
        self._filters = None
        return ""

    # ---- 首页分类 ----
    def homeContent(self, filter):
        classes = [{"type_id": tid, "type_name": name} for tid, name in CATEGORIES]
        result = {"class": classes}
        if self._filters is None:
            self._filters = {}
            for tid, _ in CATEGORIES:
                # 默认分类页提供类型等选项，qkwshow 页还藏有地区/年份等完整选项。
                status, list_html = _get(f"{HOST}/qkwlist/{tid}.html", referer=HOST + "/")
                show_status, show_html = _get(
                    f"{HOST}/qkwshow/{tid}--time---------.html",
                    referer=f"{HOST}/qkwlist/{tid}.html",
                )
                groups = (_parse_filters(list_html) if status == 200 else []) + \
                    (_parse_filters(show_html) if show_status == 200 else [])
                items = []
                for group in groups:
                    current = next((x for x in items if x["key"] == group["key"]), None)
                    if current is None:
                        items.append(group)
                    else:
                        for value in group["value"]:
                            if value not in current["value"]:
                                current["value"].append(value)
                # 模板年份列表停留在 2025，但路由已支持当前年份（2026 已实测）。
                current_year = str(datetime.datetime.now().year)
                for group in items:
                    if group["key"] == "year" and not any(x["v"] == current_year for x in group["value"]):
                        group["value"].insert(1, {"n": current_year, "v": current_year})
                order = {"type": 0, "area": 1, "year": 2, "sort": 3}
                items.sort(key=lambda x: order.get(x["key"], 99))
                if items:
                    self._filters[tid] = items
        result["filters"] = self._filters
        try:
            result["list"] = self.homeVideoContent().get("list", [])
        except Exception:
            result["list"] = []
        return result

    def homeVideoContent(self):
        status, html = _get(HOST + "/")
        return {"list": _parse_list(html)} if status == 200 else {"list": []}

    # ---- 分类列表 ----
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        extend = extend if isinstance(extend, dict) else {}
        selected_type = str(extend.get("type", "")).strip()
        if selected_type and not re.fullmatch(r"[A-Za-z0-9]+", selected_type):
            selected_type = ""
        has_filter = any(str(extend.get(key, "")).strip() for key in ("type", "area", "year", "sort"))
        if has_filter:
            url = _filter_url(selected_type or tid, page, extend)
        else:
            url = f"{HOST}/qkwlist/{tid}-{page}.html" if page > 1 else f"{HOST}/qkwlist/{tid}.html"
        status, html = _get(url, referer=HOST + "/")
        videos = _parse_list(html) if status == 200 else []
        pagecount = _page_count(html, page)
        if not videos:
            pagecount = page - 1 if page > 1 else 1
        elif len(videos) >= 30 and pagecount <= page:
            pagecount = page + 1
        return {
            "page": page,
            "pagecount": pagecount,
            "limit": len(videos),
            "total": pagecount * 36,
            "list": videos,
        }

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        kw = urllib.parse.quote(key)
        url = f"{HOST}/qkwsearch/-------------.html?wd={kw}"
        if page > 1:
            url += f"&page={page}"
        status, html = _get(url, referer=HOST + "/")
        if status != 200:
            return {"list": []}
        return {"list": _parse_list(html), "page": page}

    # ---- 详情 ----
    def detailContent(self, ids):
        vid = str(ids[0])
        url = f"{HOST}/qkwtv/{vid}.html"
        status, html = _get(url, referer=HOST + "/")
        if status != 200:
            return {"list": []}
        m_title = re.search(r'<h3 class="title">\s*<strong>([^<]+)</strong>', html)
        m_pic = re.search(r'data-original="([^"]+)"[^>]*>\s*<span class="pic-text', html) or \
            re.search(r'<img[^>]*data-original="([^"]+)"', html)
        info = {}
        for key, val in re.findall(r'<p class="data">\s*<span>([^：：]+)[：:](.*?)</p>', html, re.S):
            info[key.strip()] = _strip(val)
        mtype = info.get("类型", "")
        area = year = ""
        mm = re.search(r'地区[:：]?\s*([^\s年]+)\s*年份[:：]?\s*(\d+)', mtype)
        if mm:
            area, year = mm.group(1), mm.group(2)
        else:
            my = re.search(r'(\d{4})', mtype)
            if my:
                year = my.group(1)
        content = ""
        mc = re.search(r'<div class="stui-content__desc">(.*?)</div>', html, re.S)
        if mc:
            content = _strip(mc.group(1))
            content = re.sub(r'详细\s*>.*$', '', content).strip()
        # 线路 + 剧集（线路 h3 在 stui-pannel__head 内，紧邻 ul；详情标题 h3 含 strong，不会匹配）
        play_from, play_url = [], []
        for m in re.finditer(
            r'<h3 class="title">([^<]+)</h3>\s*</div>\s*'
            r'<ul class="stui-content__playlist[^"]*">(.*?)</ul>', html, re.S):
            line = m.group(1).strip()
            eps = []
            for em in re.finditer(r'<li[^>]*>(.*?)</li>', m.group(2), re.S):
                seg = em.group(1)
                href_m = re.search(r'href="(/qkwplay/\d+-\d+-\d+\.html)"', seg)
                name = _strip(seg)
                if href_m:
                    eps.append(name + "$" + href_m.group(1))
            if eps:
                play_from.append(line)
                play_url.append("#".join(eps))
        vod = {
            "vod_id": vid,
            "vod_name": m_title.group(1) if m_title else "",
            "vod_pic": _normalize_pic(m_pic.group(1)) if m_pic else "",
            "type_name": _strip(info.get("类型", "")),
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": _strip(info.get("状态", "")),
            "vod_actor": _strip(info.get("主演", "")),
            "vod_director": _strip(info.get("导演", "")),
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    # ---- 播放 ----
    def _parse_player(self, html):
        m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
        if not m:
            m = re.search(r'player_aaaa\s*=\s*(\{.*\})', html, re.S)
        if not m:
            return None
        raw = m.group(1)
        raw = re.sub(r'(\{|\,)\s*([A-Za-z_]+)\s*:', r'\1"\2":', raw)
        raw = raw.replace("'", '"')
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _decode_url(self, obj):
        u = obj.get("url", "")
        enc = str(obj.get("encrypt", "0"))
        try:
            if enc == "1":
                return urllib.parse.unquote(u)
            if enc == "2":
                return urllib.parse.unquote(base64.b64decode(u).decode("utf-8", errors="ignore"))
            # enc=3：全看网为「混淆前缀+base64」加密的 m3u8，但其 CDN 域名短期轮换
            # 多已失效，解出直链也无法直连，故不解直链，交由 playerContent 走解析器。
            if enc == "3":
                return u
        except Exception:
            pass
        return u

    @staticmethod
    def _decode3(u):
        best = ""
        for start in range(0, 24):
            s = u[start:]
            if len(s) < 8:
                continue
            pad = "=" * ((4 - len(s) % 4) % 4)
            try:
                raw = base64.b64decode(s + pad)
            except Exception:
                continue
            txt = raw.decode("utf-8", errors="ignore")
            # 命中完整 http 直链
            m = re.search(r'https?://[^\s\'"<>]+?\.(?:m3u8|mp4|flv)(?:\?[^\s\'"<>]*)?', txt)
            if m and len(m.group(0)) > len(best):
                best = m.group(0)
            # 无协议头但有 host+m3u8 路径：补 https://（host 以字母数字开头，排除前导伪字节）
            m2 = re.search(r'([a-zA-Z0-9][a-zA-Z0-9._-]*\.[a-zA-Z]{2,}(?:/[^\s\x00-\x1f<>\'"&]*)?\.m3u8)', txt)
            if m2:
                cand = "https://" + m2.group(1)
                if len(cand) > len(best):
                    best = cand
        return best

    def _player_parse_url(self, frm, play_url, play_data):
        """从 /static/player/{from}.js 还原原站解析器 iframe 地址。"""
        status, js = _get(f"{HOST}/static/player/{frm}.js?ver=20260821", referer=HOST + "/")
        if status != 200 or not js:
            return ""
        base_m = re.search(r'src="(https?://[^"]+?url=)"\s*\+\s*MacPlayer\.PlayUrl', js)
        if not base_m:
            base_m = re.search(r'src="(https?://[^"]+url=)', js)
        if not base_m:
            return ""
        base = base_m.group(1)
        extra = ""
        type_m = re.search(r'&type=([A-Za-z0-9]+)', js)
        if type_m:
            extra += "&type=" + type_m.group(1)
        if play_data:
            extra += "&data=" + play_data
        return base + play_url + extra

    def playerContent(self, flag, id, vipFlags=None):
        play_path = id if str(id).startswith("/qkwplay/") else f"/qkwplay/{id}.html"
        play_url = HOST + play_path
        vid_m = re.search(r'/qkwplay/(\d+)-', play_path)
        referer = HOST + f"/qkwtv/{vid_m.group(1)}.html" if vid_m else HOST + "/"
        header = {"User-Agent": UA, "Referer": referer}
        status, html = _get(play_url, referer=referer)
        # —— 403 + 自跳转 JS：站点 WAF 挑战，urllib 无法执行 JS 绕过。
        # 此时不再返回播放页让影视仓空嗅探（只跑流量），改回退到详情页，避免无效流量。
        if status == 403 or not html or "location.href" in (html or "")[:300]:
            return {"parse": 1, "url": play_url, "header": header}
        obj = self._parse_player(html)
        if not obj:
            return {"parse": 1, "url": play_url, "header": header}
        frm = obj.get("from", "")
        play_data = obj.get("play_data", "")
        enc = str(obj.get("encrypt", "0"))
        raw_url = self._decode_url(obj)
        # enc=0/1/2 本身为明文直链时直接播放（qkw1 主流是 enc=3，不走此分支）。
        if enc in ("0", "1", "2") and re.match(r'https?://.*\.(m3u8|mp4|flv)(\?|$)', raw_url, re.I):
            return {"parse": 0, "url": raw_url, "header": header}
        # enc=3：直链 CDN 域名多已失效，不解直链，统一走原站解析器 iframe
        # （zyz-...xmsu8.top，由 /static/player/{from}.js 指向）。
        # 解析器带 IP 绑定(yonghuip)，影视仓设备直接请求时绑定设备 IP，可正常播放。
        parse_page = self._player_parse_url(frm, obj.get("url", ""), play_data)
        if parse_page:
            return {"parse": 1, "url": parse_page, "header": {"User-Agent": UA, "Referer": HOST + "/"}}
        return {"parse": 1, "url": play_url, "header": header}


if __name__ == "__main__":
    s = Spider()
    s.init("")
    print("名称:", s.getName())
    h = s.homeContent(False)
    print("分类:", [(c["type_id"], c["type_name"]) for c in h["class"]], "推荐", len(h["list"]))
    c = s.categoryContent("dy", 1, False, {})
    print("电影列表:", len(c["list"]), "页数", c["pagecount"])
    if c["list"]:
        print("  首条:", c["list"][0])
    sc = s.searchContent("兰香", False)
    print("搜索兰香:", len(sc["list"]), sc["list"][:1])
    if sc["list"]:
        d = s.detailContent([sc["list"][0]["vod_id"]])
        if d["list"]:
            v = d["list"][0]
            print("详情:", v["vod_name"], "| 线路", v["vod_play_from"].split("$$$"))
            lines = v["vod_play_from"].split("$$$")
            urls = v["vod_play_url"].split("$$$")
            for i, line in enumerate(lines):
                eps = urls[i].split("#")
                ep_name, ep_id = eps[0].split("$")
                p = s.playerContent(line, ep_id)
                kind = ("直链" if p.get("parse") == 0 else "解析器" if "xmsu8" in p.get("url", "") else "播放页/受限")
                print(f"  [{i}] {line} {ep_name}: parse={p.get('parse')} {kind} -> {p.get('url')[:90]}")
