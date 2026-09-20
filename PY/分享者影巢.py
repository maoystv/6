# -*- coding: utf-8 -*-
"""
影巢影视 Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: https://yc.movie1080.online/

特性:
  - 基于苹果CMS标准API，全JSON数据
  - 多线路播放：直链m3u8 / 电影天堂解析 / 官源BFQ解析
  - 直链优先排序，官源垫后
  - 电影天堂 share URL 自动解析为 m3u8 直链（带重试+嗅探fallback）
  - 官源（腾讯/优酷/爱奇艺等）先BFQ解析直链，失败再交给壳子嗅探
  - 各分类有类型子分类筛选（客户端过滤，API不支持服务端筛选）
  - 详情页3次重试（解决间歇性"未找到数据"）
  - 首页推荐 + 分类浏览 + 全文搜索
  - 全链路短超时，SSL 禁验证
"""

import sys
import json
import re
import time
import base64
import threading

sys.path.append('..')

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r

from urllib.parse import quote, urlencode


# ============================================================
# 常量
# ============================================================

HOST = "https://yc.movie1080.online"
API = HOST + "/api.php/provide/vod/"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

# 线路显示名称映射
LINE_NAMES = {
    "mgtv": "芒果",
    "dytt": "电影天堂",
    "mjzy": "4K蓝光",
    "qq": "腾讯",
    "qiyi": "爱奇艺",
    "youku": "优酷",
    "bilibili": "B站",
    "zuidam3u8": "最大资源",
    "ffzy": "非凡资源",
    "snm3u8": "索尼资源",
    "wjm3u8": "无尽资源",
    "wolong": "卧龙资源",
    "xlm3u8": "新浪资源",
    "tpm3u8": "淘片资源",
    "dbm3u8": "百度资源",
}

# 分类列表（type_id 对应苹果CMS分类ID，父分类返回0条所以用子分类）
CLASSES = [
    {"type_name": "动作片", "type_id": "21"},
    {"type_name": "喜剧片", "type_id": "22"},
    {"type_name": "科幻片", "type_id": "24"},
    {"type_name": "国产剧", "type_id": "38"},
    {"type_name": "港台剧", "type_id": "39"},
    {"type_name": "欧美剧", "type_id": "40"},
    {"type_name": "日韩剧", "type_id": "41"},
    {"type_name": "动漫", "type_id": "44"},
    {"type_name": "综艺", "type_id": "46"},
]

# 通用年份/排序筛选器
_YEAR_FILTER = {"key": "year", "name": "年份", "value": [
    {"n": "全部", "v": ""},
    {"n": "2026", "v": "2026"},
    {"n": "2025", "v": "2025"},
    {"n": "2024", "v": "2024"},
    {"n": "2023", "v": "2023"},
    {"n": "2022", "v": "2022"},
    {"n": "2021", "v": "2021"},
    {"n": "2020", "v": "2020"},
]}
_BY_FILTER = {"key": "by", "name": "排序", "value": [
    {"n": "最新", "v": "time"},
    {"n": "最热", "v": "hits"},
    {"n": "评分", "v": "score"},
]}

# 各分类的类型子分类（基于 vod_class 字段统计）
_CLASS_FILTERS = {
    "21": [{"n": "全部", "v": ""}, {"n": "动作", "v": "动作"}, {"n": "剧情", "v": "剧情"},
           {"n": "武侠", "v": "武侠"}, {"n": "古装", "v": "古装"}, {"n": "犯罪", "v": "犯罪"},
           {"n": "复仇", "v": "复仇"}],
    "22": [{"n": "全部", "v": ""}, {"n": "喜剧", "v": "喜剧"}, {"n": "剧情", "v": "剧情"},
           {"n": "惊悚", "v": "惊悚"}, {"n": "犯罪", "v": "犯罪"}, {"n": "运动", "v": "运动"}],
    "24": [{"n": "全部", "v": ""}, {"n": "科幻", "v": "科幻"}, {"n": "动作", "v": "动作"},
           {"n": "冒险", "v": "冒险"}, {"n": "剧情", "v": "剧情"}, {"n": "悬疑", "v": "悬疑"},
           {"n": "爱情", "v": "爱情"}, {"n": "战争", "v": "战争"}, {"n": "恐怖", "v": "恐怖"},
           {"n": "灾难", "v": "灾难"}],
    "38": [{"n": "全部", "v": ""}, {"n": "古装", "v": "古装"}, {"n": "剧情", "v": "剧情"},
           {"n": "都市", "v": "都市"}, {"n": "言情", "v": "言情"}, {"n": "悬疑", "v": "悬疑"},
           {"n": "战争", "v": "战争"}, {"n": "犯罪", "v": "犯罪"}, {"n": "民国", "v": "民国"},
           {"n": "穿越", "v": "穿越"}, {"n": "奇幻", "v": "奇幻"}, {"n": "家庭", "v": "家庭"},
           {"n": "网剧", "v": "网剧"}, {"n": "罪案", "v": "罪案"}, {"n": "爱情", "v": "爱情"}],
    "39": [{"n": "全部", "v": ""}, {"n": "港剧", "v": "港剧"}, {"n": "港台", "v": "港台"},
           {"n": "台湾", "v": "台湾"}, {"n": "香港", "v": "香港"}, {"n": "都市", "v": "都市"},
           {"n": "喜剧", "v": "喜剧"}, {"n": "悬疑", "v": "悬疑"}, {"n": "情感", "v": "情感"},
           {"n": "罪案", "v": "罪案"}],
    "40": [{"n": "全部", "v": ""}, {"n": "欧美", "v": "欧美"}, {"n": "美剧", "v": "美剧"}],
    "41": [{"n": "全部", "v": ""}, {"n": "日剧", "v": "日剧"}, {"n": "日本", "v": "日本"},
           {"n": "韩国", "v": "韩国"}, {"n": "剧情", "v": "剧情"}],
    "44": [{"n": "全部", "v": ""}, {"n": "热血", "v": "热血"}, {"n": "搞笑", "v": "搞笑"},
           {"n": "恋爱", "v": "恋爱"}, {"n": "奇幻", "v": "奇幻"}, {"n": "冒险", "v": "冒险"},
           {"n": "古装", "v": "古装"}, {"n": "都市", "v": "都市"}, {"n": "玄幻", "v": "玄幻"},
           {"n": "治愈", "v": "治愈"}, {"n": "日常", "v": "日常"}, {"n": "励志", "v": "励志"},
           {"n": "美食", "v": "美食"}, {"n": "系统", "v": "系统"}, {"n": "脑洞", "v": "脑洞"},
           {"n": "逆袭", "v": "逆袭"}, {"n": "反转", "v": "反转"}, {"n": "异能", "v": "异能"}],
    "46": [{"n": "全部", "v": ""}, {"n": "真人秀", "v": "真人秀"}, {"n": "脱口秀", "v": "脱口秀"},
           {"n": "竞技", "v": "竞技"}, {"n": "音乐", "v": "音乐"}, {"n": "美食", "v": "美食"},
           {"n": "喜剧", "v": "喜剧"}, {"n": "推理", "v": "推理"}, {"n": "生活", "v": "生活"},
           {"n": "明星", "v": "明星"}, {"n": "文化", "v": "文化"}, {"n": "旅游", "v": "旅游"},
           {"n": "游戏", "v": "游戏"}, {"n": "益智", "v": "益智"}, {"n": "相声", "v": "相声"},
           {"n": "访谈", "v": "访谈"}, {"n": "竞演", "v": "竞演"}],
}

# 构建各分类的完整筛选器
FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "类型", "value": _CLASS_FILTERS.get(tid, [{"n": "全部", "v": ""}])},
        _YEAR_FILTER,
        _BY_FILTER,
    ]


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "影巢影视"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "application/json, text/plain, */*",
        }

        # 首页缓存（5 分钟）
        self._home_cache = []
        self._home_cache_time = 0

    # ===== 网络工具 =====
    def _rsp_text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode('utf-8', 'ignore')
            except Exception:
                return ""

    def _get_json(self, url, timeout=12):
        """GET 请求返回 JSON dict，异常返回 None"""
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            text = self._rsp_text(rsp)
            if not text:
                return None
            return json.loads(text)
        except Exception:
            return None

    def _txt(self, url, referer=None, timeout=12):
        """GET 文本，异常返回空"""
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            return self._rsp_text(rsp)
        except Exception:
            return ""

    def _match(self, pattern, text, flags=0):
        m = re.search(pattern, text, flags)
        return m.group(1) if m else ""

    # ===== 媒体判断 =====
    def _is_direct_media(self, url):
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

    def _is_official_source(self, url):
        url = (url or "").lower()
        keys = (
            "mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
            "v.qq.com", "qq.com", "bilibili.com", "le.com",
            "sohu.com", "pptv.com", "1905.com",
        )
        return any(k in url for k in keys) and not self._is_direct_media(url)

    def _is_dytt_share(self, url):
        """判断是否是电影天堂的 share URL"""
        url = (url or "").lower()
        return "dytt" in url and "/share/" in url and not self._is_direct_media(url)

    def _extract_referer(self, url):
        """从 URL 提取 origin 作为 Referer"""
        try:
            if "://" in url:
                scheme = url.split("://")[0]
                host = url.split("://")[1].split("/")[0]
                return scheme + "://" + host + "/"
        except Exception:
            pass
        return HOST + "/"

    # ===== 电影天堂 share URL 解析 =====
    def _resolve_dytt_share(self, share_url):
        """解析电影天堂 share URL，返回 m3u8 直链（带重试）"""
        if not share_url:
            return ""
        for attempt in range(2):
            try:
                html = self._txt(share_url, referer=HOST + "/", timeout=10)
                if not html:
                    time.sleep(0.5)
                    continue
                # 页面 JS 中: const url = "/path/index.m3u8?sign=xxx";
                m3u8_path = self._match(r'const\s+url\s*=\s*"([^"]+)"', html)
                if m3u8_path and ".m3u8" in m3u8_path:
                    if m3u8_path.startswith("http"):
                        return m3u8_path
                    base = self._extract_referer(share_url).rstrip("/")
                    return base + m3u8_path
            except Exception:
                if attempt == 0:
                    time.sleep(0.5)
        return ""

    # ===== BFQ 官源解析 =====
    def _aes_cbc_decrypt_text(self, cipher_text):
        try:
            from Crypto.Cipher import AES
            key = cipher_text[-32:-16].encode("utf-8")
            iv = cipher_text[-16:].encode("utf-8")
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _resolve_official_to_media(self, src_url):
        """用 bfq.txnp.cn 解析官源地址为 m3u8 直链"""
        if not src_url or not self._is_official_source(src_url):
            return ""
        try:
            page_url = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
            referer = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
            html = self._txt(page_url, referer=referer, timeout=12)
            result = self._match(r'let\s+result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ""
            text = self._aes_cbc_decrypt_text(result)
            if not text:
                return ""
            data = json.loads(text)
            video = ((data.get("video_info") or {}).get("video") or {})
            media = (video.get("url") or "").replace("\\/", "/")
            if media and self._is_direct_media(media):
                return media
        except Exception:
            pass
        return ""

    # ===== 内容字段处理 =====
    def _strip_tags(self, s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    # ===== 卡片格式 =====
    def _card(self, v):
        """API 视频卡片 -> TVBox 格式"""
        vid = v.get("vod_id", "")
        pic = v.get("vod_pic", "") or ""
        if pic.startswith("//"):
            pic = "https:" + pic
        return {
            "vod_id": str(vid),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": pic,
            "vod_remarks": v.get("vod_remarks", "") or v.get("vod_year", "") or "HD",
        }

    # ===== 解析 play_url =====
    def _parse_play(self, play_from_raw, play_url_raw):
        """
        解析苹果CMS的 play_from 和 play_url
        play_from: "mgtv$$$dytt$$$mjzy"
        play_url: "1$url1#2$url2$$$第01集$url3#第02集$url4$$$..."
        返回 (play_from_list, play_url_list)
        """
        if not play_from_raw or not play_url_raw:
            return [], []

        from_list = play_from_raw.split("$$$")
        url_groups = play_url_raw.split("$$$")

        play_from = []
        play_url = []

        for i, from_name in enumerate(from_list):
            if i >= len(url_groups):
                break
            url_group = url_groups[i]
            if not url_group.strip():
                continue

            # 解析每集
            eps = url_group.split("#")
            ep_list = []
            for ep in eps:
                ep = ep.strip()
                if not ep:
                    continue
                if "$" in ep:
                    ep_name, ep_url = ep.split("$", 1)
                    ep_list.append("%s$%s" % (ep_name, ep_url))
                else:
                    # 纯URL无名称
                    ep_list.append("第%s集$%s" % (len(ep_list) + 1, ep))

            if ep_list:
                display_name = LINE_NAMES.get(from_name.strip(), from_name.strip())
                play_from.append(display_name)
                play_url.append("#".join(ep_list))

        return play_from, play_url

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {
            "class": CLASSES,
            "filters": FILTERS,
        }

    def homeVideoContent(self):
        """首页推荐：从API获取最新视频，带5分钟缓存"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache[:72]}

        # 获取最新视频列表
        url = API + "?ac=videolist&pg=1"
        data = self._get_json(url, timeout=10)
        videos = []
        if data and data.get("code") == 1:
            for v in data.get("list", []):
                videos.append(self._card(v))

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ============================================================
    # 分类列表
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            # 解析 extend
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            # 检测是否需要客户端筛选（API 不支持 class/year 筛选）
            need_class_filter = bool(ext.get("class"))
            need_year_filter = bool(ext.get("year"))

            # 构建API参数（虽然API可能忽略class/year，仍然传递）
            params = {
                "ac": "videolist",
                "t": str(tid),
                "pg": str(page),
            }
            if ext.get("by"):
                params["by"] = ext["by"]

            url = API + "?" + urlencode(params)
            data = self._get_json(url, timeout=12)

            if not data or data.get("code") != 1:
                return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}

            raw_list = data.get("list", [])
            pagecount = int(data.get("pagecount", 1))
            total = int(data.get("total", len(raw_list)))

            # 客户端筛选：按 vod_class 和 vod_year 过滤
            if need_class_filter or need_year_filter:
                class_kw = ext.get("class", "")
                year_kw = ext.get("year", "")
                filtered = []
                for v in raw_list:
                    vc = v.get("vod_class", "") or ""
                    vy = str(v.get("vod_year", "") or "")
                    if class_kw and class_kw not in vc:
                        continue
                    if year_kw and year_kw != vy:
                        continue
                    filtered.append(v)
                raw_list = filtered

            vods = [self._card(v) for v in raw_list]

            return {
                "list": vods,
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": total,
            }
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    # ============================================================
    # 详情页
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = str(ids[0])

        url = API + "?ac=detail&ids=" + vod_id

        # 3次重试（解决间歇性"未找到数据"）
        data = None
        for attempt in range(3):
            data = self._get_json(url, timeout=12)
            if data and data.get("code") == 1 and data.get("list"):
                break
            time.sleep(0.5)

        if not data or data.get("code") != 1:
            return {"list": []}

        lst = data.get("list", [])
        if not lst:
            return {"list": []}

        d = lst[0]
        play_from_raw = d.get("vod_play_from", "") or ""
        play_url_raw = d.get("vod_play_url", "") or ""

        play_from, play_url = self._parse_play(play_from_raw, play_url_raw)

        if not play_url:
            return {"list": []}

        # 线路排序：直链 m3u8 优先，电影天堂 share 次之，官源垫后
        direct_from = []
        direct_url = []
        dytt_from = []
        dytt_url = []
        official_from = []
        official_url = []

        for pf, pu in zip(play_from, play_url):
            first_ep = pu.split("#")[0] if pu else ""
            first_url = first_ep.split("$", 1)[1] if "$" in first_ep else ""

            if self._is_direct_media(first_url):
                direct_from.append(pf)
                direct_url.append(pu)
            elif self._is_dytt_share(first_url):
                dytt_from.append(pf)
                dytt_url.append(pu)
            else:
                official_from.append(pf)
                official_url.append(pu)

        # 排序：直链 > 电影天堂 > 官源
        play_from = direct_from + dytt_from + official_from
        play_url = direct_url + dytt_url + official_url

        # 详情内容
        content = self._strip_tags(d.get("vod_content", ""))[:500]

        vod = {
            "vod_id": vod_id,
            "vod_name": d.get("vod_name", ""),
            "vod_pic": d.get("vod_pic", "") or "",
            "type_name": d.get("type_name", ""),
            "vod_year": d.get("vod_year", ""),
            "vod_area": d.get("vod_area", ""),
            "vod_remarks": d.get("vod_remarks", "") or "HD",
            "vod_actor": d.get("vod_actor", ""),
            "vod_director": d.get("vod_director", ""),
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from) if play_from else "影巢影视",
            "vod_play_url": "$$$".join(play_url) if play_url else "",
        }
        return {"list": [vod]}

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            params = {
                "wd": key,
                "pg": str(page),
            }
            url = API + "?" + urlencode(params)
            data = self._get_json(url, timeout=12)

            if data and data.get("code") == 1:
                vods = [self._card(v) for v in data.get("list", [])]
                if vods:
                    return {"list": vods}

            return {"list": []}
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放解析
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = str(id).replace("\\/", "/")

        # 1. 直链媒体（m3u8/mp4）→ 直接播放
        if self._is_direct_media(play_url):
            is_m3u8 = ".m3u8" in play_url.lower()
            media_referer = self._extract_referer(play_url)
            return {
                "parse": 0,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": media_referer,
                },
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. 电影天堂 share URL → 解析为 m3u8 直链
        if self._is_dytt_share(play_url):
            resolved = self._resolve_dytt_share(play_url)
            if resolved and self._is_direct_media(resolved):
                media_referer = self._extract_referer(resolved)
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": resolved,
                    "header": {
                        "User-Agent": UA,
                        "Referer": media_referer,
                    },
                    "format": "application/x-mpegURL",
                    "contentType": "application/x-mpegURL",
                }
            # 解析失败 → 交给壳子嗅探
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                },
            }

        # 3. 官源（iqiyi/youku/qq/mgtv 等）→ BFQ 解析出真实直链
        if self._is_official_source(play_url):
            resolved = self._resolve_official_to_media(play_url)
            if resolved and self._is_direct_media(resolved):
                is_m3u8 = ".m3u8" in resolved.lower()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": resolved,
                    "header": {
                        "User-Agent": UA,
                        "Referer": "https://bfq.txnp.cn/",
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }
            # BFQ 解析失败 → 交给壳子用原始URL嗅探
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                },
            }

        # 4. 其他URL → 返回原URL
        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
        }

    # ===== 本地代理 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        pass

    def close(self):
        self.destroy()
