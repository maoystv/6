# -*- coding: utf-8 -*-

import ast
import base64
import html as html_module
import json
import re
import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def __init__(self):
            pass
        def getProxyUrl(self):
            return ""


class Spider(BaseSpider):
    DEFAULT_HOST = "http://www.dsxys8.com"
    DEFAULT_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # 主分类列表（补全理论片，ID: 20）
    CLASSES = [
        {"type_name": "电影", "type_id": "1"},
        {"type_name": "连续剧", "type_id": "2"},
        {"type_name": "综艺", "type_id": "3"},
        {"type_name": "动漫", "type_id": "4"},
        {"type_name": "短剧", "type_id": "27"},
    ]

    # 二级子分类筛选字典（基于真实探针萃取数据构建）
    FILTERS = {
        "1": [
            {
                "key": "sub_tid",
                "name": "子分类",
                "value": [
                    {"n": "全部", "v": "1"},
                    {"n": "动作片", "v": "5"},
                    {"n": "喜剧片", "v": "6"},
                    {"n": "爱情片", "v": "7"},
                    {"n": "科幻片", "v": "8"},
                    {"n": "恐怖片", "v": "9"},
                    {"n": "剧情片", "v": "10"},
                    {"n": "战争片", "v": "11"},
                    {"n": "纪录片", "v": "22"},
                    {"n": "动画片", "v": "33"}
                ]
            }
        ],
        "2": [
            {
                "key": "sub_tid",
                "name": "子分类",
                "value": [
                    {"n": "全部", "v": "2"},
                    {"n": "国产剧", "v": "12"},
                    {"n": "香港剧", "v": "13"},
                    {"n": "台湾剧", "v": "14"},
                    {"n": "日本剧", "v": "15"},
                    {"n": "韩国剧", "v": "16"},
                    {"n": "欧美剧", "v": "17"},
                    {"n": "海外剧", "v": "18"},
                    {"n": "泰国剧", "v": "19"}
                ]
            }
        ],
        "3": [
            {
                "key": "sub_tid",
                "name": "子分类",
                "value": [
                    {"n": "全部", "v": "3"},
                    {"n": "内地综艺", "v": "23"},
                    {"n": "港台综艺", "v": "24"},
                    {"n": "日韩综艺", "v": "25"},
                    {"n": "欧美综艺", "v": "26"}
                ]
            }
        ],
        "4": [
            {
                "key": "sub_tid",
                "name": "子分类",
                "value": [
                    {"n": "全部", "v": "4"},
                    {"n": "国产动漫", "v": "28"},
                    {"n": "港台动漫", "v": "29"},
                    {"n": "日韩动漫", "v": "30"},
                    {"n": "欧美动漫", "v": "31"},
                    {"n": "海外动漫", "v": "32"}
                ]
            }
        ]
    }

    DETAIL_RE = re.compile(r"/detail-([^/?#'\"<>]+)/", re.I)
    PLAY_RE = re.compile(r"/play-([^/?#'\"<>]+)-(\d+)-(\d+)/", re.I)
    MEDIA_EXTENSIONS = (".m3u8", ".mp4", ".mkv", ".flv", ".ts", ".webm")
    CF_SIGNS = ("just a moment", "checking your browser", "attention required! | cloudflare")

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.host = self.DEFAULT_HOST
        self.ua = self.DEFAULT_UA
        self.cookie = ""
        self.timeout = 15
        self.use_cffi = False
        self.proxy_enabled = False
        self.tgGroup = "💝分享者在线"
        self.brandActor = "💝分享者在线"
        self.brandDirector = "💝分享者在线"
        self.session = requests.Session()
        self.headers = {}
        self._refresh_headers()

    def init(self, extend=""):
        config = self._parse_extend(extend)
        raw_host = str(config.get("host") or self.DEFAULT_HOST).strip().rstrip("/")
        if raw_host.startswith("https://"):
            raw_host = "http://" + raw_host[len("https://"):]
        self.host = raw_host
        self.ua = str(config.get("ua") or self.DEFAULT_UA).strip()
        self.cookie = str(config.get("cookie") or "").strip()
        self.timeout = self._safe_int(config.get("timeout"), 15, 5, 60)
        self.use_cffi = self._as_bool(config.get("use_cffi"), False)
        self.proxy_enabled = self._as_bool(config.get("proxy"), False)
        self.session = requests.Session()
        self._refresh_headers()
        return True

    def getName(self):
        return "💝分享者在线·大师兄"

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    @staticmethod
    def _safe_int(value, default, minimum=None, maximum=None):
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        if minimum is not None:
            number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    @staticmethod
    def _as_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "是", "开启"}

    @staticmethod
    def _parse_extend(extend):
        if isinstance(extend, dict):
            return dict(extend)
        if not extend:
            return {}
        text = str(extend).strip()
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except Exception:
            pass
        try:
            parsed = parse_qs(text, keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}
        except Exception:
            return {}

    def _refresh_headers(self):
        self.headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if self.cookie:
            self.headers["Cookie"] = self.cookie
        try:
            self.session.headers.clear()
            self.session.headers.update(self.headers)
        except Exception:
            pass

    def _request_raw(self, url, referer="", binary=False):
        if not url:
            return None
        target = self._absolute(url, referer or self.host)
        if target.startswith("https://www.dsxys8.com"):
            target = "http://www.dsxys8.com" + target[len("https://www.dsxys8.com"):]

        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        if binary:
            headers["Accept"] = "*/*"

        if self.use_cffi and cffi_requests is not None:
            try:
                response = cffi_requests.get(
                    target,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                    impersonate="chrome131"
                )
                if getattr(response, "status_code", 200) < 400:
                    if not binary:
                        response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"
                        if not self._is_cloudflare_text(response.text):
                            return response
                    else:
                        return response
            except Exception:
                pass

        for attempt in range(2):
            try:
                response = self.session.get(target, headers=headers, timeout=self.timeout, allow_redirects=True)
                if getattr(response, "status_code", 200) >= 400:
                    raise RuntimeError("HTTP %s" % getattr(response, "status_code", 0))
                if not binary:
                    response.encoding = self._response_encoding(response)
                    if self._is_cloudflare_text(response.text):
                        raise RuntimeError("Cloudflare challenge")
                return response
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
        return None

    @staticmethod
    def _response_encoding(response):
        content = getattr(response, "content", b"")[:3000]
        head = content.decode("ascii", "ignore").lower()
        if "charset=utf-8" in head or "charset=\"utf-8\"" in head or "charset='utf-8'" in head:
            return "utf-8"
        return getattr(response, "apparent_encoding", None) or "utf-8"

    def _get_text(self, url, referer=""):
        response = self._request_raw(url, referer=referer, binary=False)
        if response is None:
            return ""
        try:
            text = response.text or ""
            return "" if self._is_cloudflare_text(text) else text
        except Exception:
            return ""

    @classmethod
    def _is_cloudflare_text(cls, text):
        lower = (text or "")[:100000].lower()
        return any(sign in lower for sign in cls.CF_SIGNS)

    def _absolute(self, url, base):
        if not url:
            return ""
        value = html_module.unescape(str(url).strip()).replace("\\/", "/")
        if value.startswith("//"):
            return "http:" + value
        return urljoin(base, value)

    @staticmethod
    def _clean_text(value):
        if value is None:
            return ""
        text = html_module.unescape(str(value)).replace("\xa0", " ")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip(" \t\r\n/|")

    @staticmethod
    def _attr(attrs, name):
        match = re.search(rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']*)", attrs or "", re.I)
        return html_module.unescape(match.group(1).strip()) if match else ""

    def _parse_video_list(self, source, page_url):
        records = []
        seen = set()
        pattern = re.compile(r"<a\b([^>]*href=[\"']([^\"']*/detail[-/][^\"']+)[\"'][^>]*)>(.*?)</a>", re.I | re.S)
        for match in pattern.finditer(source or ""):
            attrs, href, body = match.groups()
            absolute = self._absolute(href, page_url or self.host)
            path = urlparse(absolute).path
            if path in seen:
                continue
            seen.add(path)
            title = self._attr(attrs, "title")
            if not title:
                found = re.search(r"class=[\"'][^\"']*title[^\"']*[\"'][^>]*>(.*?)</", body, re.I | re.S)
                title = self._clean_text(found.group(1)) if found else ""
            if not title:
                found = re.search(r"alt=[\"']([^\"']+)", body, re.I)
                title = found.group(1) if found else ""
            if not title:
                continue
            pic_match = re.search(r"(?:data-original|data-src|src)=[\"']([^\"']+)", body, re.I)
            pic = self._absolute(pic_match.group(1), absolute) if pic_match else ""
            remark_match = re.search(r"(?:pic-text|text-right|text-muted)[^>]*>(.*?)</(?:span|p|div)>", body, re.I | re.S)
            remark = self._clean_text(remark_match.group(1)) if remark_match else ""
            records.append({
                "vod_id": path,
                "vod_name": self._clean_text(title),
                "vod_pic": pic,
                "vod_remarks": remark or "💝分享者在线",
                "style": {"type": "rect", "ratio": 1.78}
            })
        return records

    def homeContent(self, filter=False):
        return {"class": list(self.CLASSES), "filters": self.FILTERS}

    def homeVideoContent(self):
        source = self._get_text(self.host + "/", referer=self.host + "/")
        return {"list": self._parse_video_list(source, self.host)[:80]}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page = self._safe_int(pg, 1, 1)
        ext = extend or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}

        # 核心联动：若用户点击了筛选栏中的子分类，则使用选中的具体子分类 ID
        target_tid = str(ext.get("sub_tid") or tid or "1").strip()

        paths = [
            f"/sort-{target_tid}/" if page == 1 else f"/sort-{target_tid}-{page}/",
            f"/sort/{target_tid}.html" if page == 1 else f"/sort/{target_tid}-{page}.html"
        ]
        videos, source = self._fetch_list(paths)
        return {
            "list": videos,
            "page": page,
            "pagecount": self._pagecount(source, page),
            "limit": len(videos),
            "total": len(videos)
        }

    def _fetch_list(self, paths):
        last = ""
        for path in paths:
            url = self._absolute(path, self.host)
            source = self._get_text(url, referer=self.host + "/")
            if source:
                last = source
                videos = self._parse_video_list(source, url)
                if videos:
                    return videos, source
        return [], last

    @staticmethod
    def _pagecount(source, page):
        values = [int(x) for x in re.findall(r"/sort-\d+-(\d+)/", source or "", re.I)]
        return max(values + [page])

    def searchContent(self, key, quick, pg="1"):
        page = self._safe_int(pg, 1, 1)
        keyword = quote(unquote(str(key or "").strip()), safe="")
        if not keyword:
            return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}
        path = f"/search--------------/?wd={keyword}"
        if page > 1:
            path += f"&page={page}"
        videos, source = self._fetch_list([path])
        return {"list": videos, "page": page, "pagecount": self._pagecount(source, page), "limit": len(videos), "total": len(videos)}

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        raw_id = str(raw_id or "").strip()
        if not raw_id:
            return {"list": []}
        detail_url = self._absolute(raw_id, self.host)
        source = self._get_text(detail_url, referer=self.host + "/")
        item = self._detail_metadata(source, detail_url)
        play_from, play_url = self._extract_plays(source, detail_url)

        full_desc = (
            "【💝分享者在线: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "%s"
        ) % (self.tgGroup, item.get("vod_content", ""))

        escaped_desc = full_desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        item.update({
            "vod_id": raw_id,
            "vod_actor": self.brandActor if not item.get("vod_actor") else f"{self.brandActor} / {item['vod_actor']}",
            "vod_director": self.brandDirector if not item.get("vod_director") else f"{self.brandDirector} / {item['vod_director']}",
            "vod_content": escaped_desc,
            "vod_play_from": "$$$".join(play_from) if play_from else "💝分享者在线",
            "vod_play_url": "$$$".join(play_url) if play_url else f"立即播放${detail_url}"
        })
        return {"list": [item]}

    def _detail_metadata(self, source, detail_url):
        item = {
            "vod_name": "未知影片",
            "vod_pic": "",
            "type_name": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "💝分享者在线",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": ""
        }
        if not source:
            return item

        title_val = ""
        for pat in (
            r'<h1\b[^>]*>(.*?)</h1>',
            r'<h2\b[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</h2>',
            r'<div\b[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</div>',
            r'<meta\b[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
            r'<meta\b[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\',]+)'
        ):
            m = re.search(pat, source, re.I | re.S)
            if m:
                cand = self._clean_text(m.group(1))
                if cand and cand != "未知影片" and len(cand) < 40:
                    title_val = cand
                    break

        if not title_val:
            m = re.search(r'<title\b[^>]*>(.*?)</title>', source, re.I | re.S)
            if m:
                raw_t = self._clean_text(m.group(1))
                clean_t = re.sub(r'(-|_|\s+)(大师兄影视|海量高清|免费在线观看|在线播放|电视剧|电影|全集).*$', '', raw_t, flags=re.I).strip()
                if clean_t:
                    title_val = clean_t

        if not title_val:
            m = re.search(r'(?:为您提供|提供).*?片\s*([^\s,，。]+?)\s*在线', source)
            if m:
                title_val = self._clean_text(m.group(1))

        if title_val:
            item["vod_name"] = title_val

        pic = re.search(r'<meta\b[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)', source, re.I)
        if not pic:
            pic = re.search(r'(?:data-original|data-src|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp))', source, re.I)
        if pic:
            item["vod_pic"] = self._absolute(pic.group(1), detail_url)

        description = re.search(r'<meta\b[^>]*(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\']([^"\']+)', source, re.I)
        if description:
            item["vod_content"] = self._clean_text(description.group(1))

        plain = self._clean_text(source)
        for label, field in (("类型", "type_name"), ("年份", "vod_year"), ("地区", "vod_area"), ("主演", "vod_actor"), ("导演", "vod_director")):
            found = re.search(label + r"\s*[:：]\s*([^|]{1,120})", plain)
            if found:
                item[field] = self._clean_text(found.group(1))

        year = re.search(r"\b(20\d{2})\b", plain)
        if year and not item["vod_year"]:
            item["vod_year"] = year.group(1)

        return item

    def _extract_plays(self, source, detail_url):
        groups, order = {}, []
        for match in re.finditer(r"<a\b([^>]*href=[\"']([^\"']*/play[-/][^\"']+)[\"'][^>]*)>(.*?)</a>", source or "", re.I | re.S):
            attrs, href, body = match.groups()
            play_match = self.PLAY_RE.search(href)
            sid = play_match.group(2) if play_match else "1"
            absolute = self._absolute(href, detail_url)
            name = self._normalize_episode(self._clean_text(body))
            groups.setdefault(sid, {})
            if sid not in order:
                order.append(sid)
            old = groups[sid].get(absolute)
            if old is None or old == "播放" or "第" in name:
                groups[sid][absolute] = name
        play_from, play_url = [], []
        for sid in sorted(order, key=lambda value: int(value) if value.isdigit() else 1):
            episodes = [f"{name}${url}" for url, name in groups[sid].items()]
            if episodes:
                play_from.append("💝分享者在线" + sid)
                play_url.append("#".join(episodes))
        return play_from, play_url

    @classmethod
    def _normalize_episode(cls, name):
        value = cls._clean_text(name)
        found = re.search(r"第\s*0*(\d+)\s*[集期]", value)
        if found:
            return "第" + str(int(found.group(1))) + "集"
        return value or "播放"

    def playerContent(self, flag, id, vipFlags=None):
        play_url = self._absolute(str(id or ""), self.host)
        headers = self._play_headers(play_url)
        if self._is_media_url(play_url):
            return self._direct_result(play_url, headers)
        source = self._get_text(play_url, referer=self._origin_root(play_url))
        if not source:
            return {"parse": 1, "jx": 0, "url": play_url, "header": headers}
        for variable in ("player_aaaa", "player_data", "MacPlayer"):
            config = self._extract_js_object(source, variable)
            if not config:
                continue
            decoded = self._decode_url(self._find_url(config), config.get("encrypt"), play_url)
            if self._is_media_url(decoded):
                return self._direct_result(decoded, headers)
        direct = self._extract_direct_media(source, play_url)
        if direct:
            return self._direct_result(direct, headers)
        iframe = re.search(r"<iframe\b[^>]*src=[\"']([^\"']+)", source or "", re.I)
        if iframe:
            return {"parse": 1, "jx": 0, "url": self._absolute(iframe.group(1), play_url), "header": headers}
        return {"parse": 1, "jx": 0, "url": play_url, "header": headers}

    @staticmethod
    def _extract_js_object(source, variable):
        match = re.search(rf"(?:var\s+|let\s+|const\s+|window\.)?{re.escape(variable)}\s*=\s*", source or "", re.I)
        if not match:
            return {}
        start = source.find("{", match.end())
        if start < 0:
            return {}
        depth, quote_char, escaped = 0, "", False
        for index in range(start, min(len(source), start + 150000)):
            char = source[index]
            if quote_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    quote_char = ""
            elif char in ("'", '"'):
                quote_char = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    text = source[start:index + 1]
                    try:
                        value = json.loads(text)
                    except Exception:
                        try:
                            value = ast.literal_eval(text)
                        except Exception:
                            value = {}
                    return value if isinstance(value, dict) else {}
        return {}

    @classmethod
    def _find_url(cls, config):
        for key in ("url", "play_url", "playUrl", "src", "m3u8"):
            if config.get(key):
                return str(config[key])
        for value in config.values():
            if isinstance(value, dict):
                found = cls._find_url(value)
                if found:
                    return found
        return ""

    def _decode_url(self, raw_url, encrypt, page_url):
        raw = html_module.unescape(str(raw_url or "")).replace("\\/", "/").strip()
        candidates = [raw, unquote(raw)]
        decoded = self._decode_base64(raw)
        if decoded:
            candidates.extend((decoded, unquote(decoded)))
        for candidate in candidates:
            candidate = html_module.unescape(candidate).replace("\\/", "/").strip()
            if candidate.startswith(("http://", "https://", "//", "/")):
                return self._absolute(candidate, page_url)
        return ""

    @staticmethod
    def _decode_base64(value):
        try:
            text = str(value or "").strip()
            return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8", "ignore")
        except Exception:
            return ""

    def _extract_direct_media(self, source, page_url):
        text = html_module.unescape(source or "").replace("\\/", "/")
        for pattern in (r"https?://[^\"'<>\s]+?\.m3u8(?:\?[^\"'<>\s]*)?", r"https?://[^\"'<>\s]+?\.(?:mp4|flv|mkv|webm)(?:\?[^\"'<>\s]*)?"):
            found = re.search(pattern, text, re.I)
            if found:
                return self._absolute(found.group(0), page_url)
        return ""

    @classmethod
    def _is_media_url(cls, url):
        lower = html_module.unescape(str(url or "")).lower()
        return lower.startswith(("http://", "https://")) and any(ext in lower for ext in cls.MEDIA_EXTENSIONS)

    def _play_headers(self, referer):
        headers = {"User-Agent": self.ua, "Referer": referer}
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _direct_result(self, url, headers):
        return {"parse": 0, "jx": 0, "url": url, "header": headers}

    @staticmethod
    def _origin_root(url):
        parsed = urlparse(url)
        return "%s://%s/" % (parsed.scheme, parsed.netloc) if parsed.scheme and parsed.netloc else url

    def isVideoFormat(self, url):
        return self._is_media_url(url)

    def manualVideoCheck(self):
        return False
