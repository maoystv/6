#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import time
import base64
import ssl
import hmac
import hashlib
import urllib.request
import urllib.parse
from urllib.parse import urlparse, quote, unquote

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

def format_remarks(brand="分享者在线", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.siteName = "蓝光资源"
        self.host = "https://lgzyz.xyz"
        self.apiUrl = "https://lgapi.xyz"
        self.parse_host = "https://vv00.xyz"
        self.demo_host = "https://yanshi.lgzyz.xyz"
        self.tgGroup = "https://t.me/tvshare23"
        self.brandActor = "分享者在线"
        self.brandDirector = "分享者在线"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.options = {}
        self.play_cache = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self._parent_to_first_sub = {
            "2": "13",
            "47": "53",
            "48": "57",
            "49": "61",
            "50": "65"
        }

        self._classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "13", "type_name": "连续剧"},
            {"type_id": "53", "type_name": "动漫"},
            {"type_id": "57", "type_name": "综艺"},
            {"type_id": "61", "type_name": "体育赛事"},
            {"type_id": "65", "type_name": "短剧"},
            {"type_id": "51", "type_name": "电影解说"},
            {"type_id": "52", "type_name": "预告片"}
        ]

        self._filters = {
            "1": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "1",
                    "value": [
                        {"n": "全部电影", "v": "1"},
                        {"n": "动作片", "v": "6"},
                        {"n": "喜剧片", "v": "7"},
                        {"n": "科幻片", "v": "8"},
                        {"n": "恐怖片", "v": "9"},
                        {"n": "爱情片", "v": "10"},
                        {"n": "剧情片", "v": "11"},
                        {"n": "战争片", "v": "12"},
                        {"n": "惊悚片", "v": "36"},
                        {"n": "悬疑片", "v": "37"},
                        {"n": "家庭片", "v": "38"},
                        {"n": "犯罪片", "v": "39"},
                        {"n": "灾难片", "v": "40"},
                        {"n": "古装片", "v": "41"},
                        {"n": "历史片", "v": "42"},
                        {"n": "纪录片", "v": "20"},
                        {"n": "动画片", "v": "21"}
                    ]
                }
            ],
            "13": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "13",
                    "value": [
                        {"n": "国产剧", "v": "13"},
                        {"n": "欧美剧", "v": "14"},
                        {"n": "香港剧", "v": "15"},
                        {"n": "韩国剧", "v": "16"},
                        {"n": "台湾剧", "v": "22"},
                        {"n": "日本剧", "v": "23"},
                        {"n": "海外剧", "v": "24"},
                        {"n": "泰国剧", "v": "25"}
                    ]
                }
            ],
            "53": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "53",
                    "value": [
                        {"n": "国产动漫", "v": "53"},
                        {"n": "日韩动漫", "v": "54"},
                        {"n": "欧美动漫", "v": "55"},
                        {"n": "海外动漫", "v": "56"},
                        {"n": "港台动漫", "v": "73"},
                        {"n": "动漫电影", "v": "75"}
                    ]
                }
            ],
            "57": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "57",
                    "value": [
                        {"n": "大陆综艺", "v": "57"},
                        {"n": "港台综艺", "v": "58"},
                        {"n": "日韩综艺", "v": "59"},
                        {"n": "欧美综艺", "v": "60"}
                    ]
                }
            ],
            "61": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "61",
                    "value": [
                        {"n": "足球赛事", "v": "61"},
                        {"n": "篮球赛事", "v": "62"},
                        {"n": "斯诺克", "v": "63"},
                        {"n": "网球赛事", "v": "64"}
                    ]
                }
            ],
            "65": [
                {
                    "key": "class_sub",
                    "name": "分类",
                    "init": "65",
                    "value": [
                        {"n": "重生民国", "v": "65"},
                        {"n": "穿越年代", "v": "66"},
                        {"n": "反转爽剧", "v": "67"},
                        {"n": "女恋总裁", "v": "70"},
                        {"n": "闪婚离婚", "v": "69"},
                        {"n": "都市脑洞", "v": "71"},
                        {"n": "古装仙侠", "v": "72"},
                        {"n": "现代言情", "v": "74"}
                    ]
                }
            ]
        }

    def init(self, extend=""):
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict):
                    if cfg.get("host"):
                        self.host = cfg["host"].rstrip("/")
                    if cfg.get("api"):
                        self.apiUrl = cfg["api"].rstrip("/")
                    if cfg.get("parse_host"):
                        self.parse_host = cfg["parse_host"].rstrip("/")
                    if cfg.get("demo_host"):
                        self.demo_host = cfg["demo_host"].rstrip("/")
            except Exception:
                pass
        return True

    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        if not url:
            return False
        clean = url.split("?")[0].lower()
        return any(clean.endswith(ext) for ext in [".m3u8", ".mp4", ".ts"])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.play_cache = {}

    def _http_get(self, url, headers=None, timeout=8):
        h = {
            "User-Agent": self._ua,
            "Accept-Encoding": "identity"
        }
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                pass
        return ""

    def _http_post_json(self, url, data_dict, headers=None, timeout=8):
        h = {
            "User-Agent": self._ua,
            "Content-Type": "application/json",
            "Accept-Encoding": "identity"
        }
        if headers:
            h.update(headers)
        body = json.dumps(data_dict, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=h)
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                pass
        return ""

    def homeContent(self, filter):
        result = {
            "class": self._classes
        }
        if filter:
            result["filters"] = self._filters
        return result

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1

        raw_tid = str(tid).strip()
        if raw_tid in self._parent_to_first_sub:
            target_tid = self._parent_to_first_sub[raw_tid]
        else:
            target_tid = raw_tid

        if isinstance(extend, dict) and extend.get("class_sub"):
            selected_sub = str(extend.get("class_sub")).strip()
            if selected_sub:
                target_tid = selected_sub

        url = "%s/api.php/provide/vod/?ac=detail&t=%s&pg=%d" % (self.apiUrl, target_tid, page)
        txt = self._http_get(url)

        cards = []
        pagecount = page
        total = 0

        try:
            data = json.loads(txt)
            raw_list = data.get("list", [])
            pagecount = int(data.get("pagecount", page))
            total = int(data.get("total", 0))

            for it in raw_list:
                v_id = str(it.get("vod_id", ""))
                v_name = str(it.get("vod_name", ""))
                if not v_id or not v_name:
                    continue

                cards.append({
                    "vod_id": v_id,
                    "vod_name": v_name,
                    "vod_pic": str(it.get("vod_pic", "")),
                    "vod_remarks": format_remarks(self.brandDirector, it.get("vod_remarks", "")),
                    "style": {"type": "rect", "ratio": 0.75}
                })
        except Exception:
            cards = []

        if not cards:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

        return {
            "list": cards,
            "page": page,
            "pagecount": pagecount if pagecount >= 1 else 1,
            "limit": len(cards),
            "total": total if total > 0 else (page * len(cards) + 100)
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        url = "%s/api.php/provide/vod/?ac=detail&ids=%s" % (self.apiUrl, str(raw_id).strip())
        txt = self._http_get(url)

        item = {}
        try:
            data = json.loads(txt)
            item = (data.get("list", []) or [{}])[0]
        except Exception:
            item = {}

        v_name = str(item.get("vod_name", "超清正片"))
        v_pic = str(item.get("vod_pic", ""))
        v_remarks = format_remarks(self.brandDirector, item.get("vod_remarks", "正片"))

        desc_raw = str(item.get("vod_content", "")).strip()
        if desc_raw and desc_raw != "暂无简介":
            v_content = "分享者在线 | %s | 分享者在线" % desc_raw
        else:
            v_content = "分享者在线 | 分享者在线 | 4K高清原生极速画质"

        raw_from = str(item.get("vod_play_from", "lgzym3u8")).strip()
        from_list = raw_from.split("$$$") if raw_from else ["lgzym3u8"]

        brand_from_list = []
        for f in from_list:
            if "lgzym3u8" in f.lower():
                brand_from_list.append("分享者专线")
            else:
                brand_from_list.append(f)

        final_play_from = "$$$".join(brand_from_list)
        final_play_url = str(item.get("vod_play_url", "")).strip()

        vod = {
            "vod_id": str(raw_id),
            "vod_name": v_name,
            "vod_pic": v_pic,
            "vod_bg": v_pic,
            "vod_background": v_pic,
            "vod_banner": v_pic,
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": v_remarks,
            "vod_content": v_content,
            "vod_play_from": final_play_from,
            "vod_play_url": final_play_url
        }
        return {"list": [vod]}

    def _resolve_stream(self, target_url):
        now = time.time()
        if target_url in self.play_cache:
            cache_url, exp = self.play_cache[target_url]
            if now < exp:
                return cache_url

        page_url = "%s?url=%s" % (self.parse_host, quote(target_url, safe=""))
        html = self._http_get(page_url, headers={"Referer": "%s/" % self.demo_host}, timeout=8)
        if not html:
            return ""

        sess_m = re.search(r"hishow\.php\?session=([a-f0-9]+)", html)
        if not sess_m:
            return ""
        sess = sess_m.group(1)

        js_url = "%s/godoo/hishow.php?session=%s" % (self.parse_host, sess)
        js_txt = self._http_get(js_url, headers={"Referer": page_url}, timeout=8)
        if not js_txt:
            return ""

        sec_m = re.search(r"var SECRET\s*=\s*['\"]([a-f0-9]+)['\"]", js_txt)
        if not sec_m:
            return ""
        secret = sec_m.group(1)

        rand_m = re.search(r"var RANDOM_INDICATORS\s*=\s*(\[[^\]]+\])", js_txt)
        rand_keys = json.loads(rand_m.group(1)) if rand_m else []

        getters = {
            "plugins": "Chrome PDF Viewer",
            "mimeTypes": 2,
            "timezone": -480,
            "language": "zh-CN",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "platform": "Win32",
            "audioFingerprint": "audio_placeholder",
            "fontList": "fonts_placeholder",
            "canvasNoise": "canvas_noise",
            "webglVendor": "Google Inc. (NVIDIA)"
        }
        random_data = {k: getters.get(k, "") for k in rand_keys}

        payload = {
            "sessionId": sess,
            "isTop": True,
            "isRealBrowser": True,
            "isTrusted": False,
            "deviceId": "-1827491203",
            "domain": "yanshi.lgzyz.xyz",
            "randomIndicators": random_data
        }
        payload_str = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        boom_url = "%s/godoo/boom.php" % self.parse_host
        self._http_post_json(boom_url, {"payload": payload, "signature": sig}, headers={
            "Referer": page_url,
            "Origin": self.parse_host
        }, timeout=8)

        vurl_m = re.search(r'videoUrl:\s*"([^"]+)"', html)
        if not vurl_m:
            return ""
        playback_url = "%s%s" % (self.parse_host, vurl_m.group(1))

        pb_html = self._http_get(playback_url, headers={"Referer": page_url}, timeout=8)
        if not pb_html:
            return ""

        spec_m = re.search(r"window\.specialPlayConfig\s*=\s*(\{[\s\S]*?\});", pb_html)
        if spec_m:
            spec_txt = spec_m.group(1)
            ps_m = re.search(r"playSources:\s*(\[[^\]]+\])", spec_txt)
            play_sources = json.loads(ps_m.group(1)) if ps_m else []
            for src in play_sources:
                mac_src = src.get("mac_play_source", "")
                if not mac_src:
                    continue
                if mac_src == "dujia":
                    res_url = "%s&resolve_dujia_plain=1" % playback_url
                else:
                    res_url = "%s&resolve_special_plain=1&resolve_source=%s" % (playback_url, mac_src)
                res_txt = self._http_get(res_url, headers={
                    "Referer": playback_url,
                    "Accept": "application/json"
                }, timeout=8)
                if res_txt:
                    try:
                        res_json = json.loads(res_txt)
                        stream_url = res_json.get("url", "")
                        if stream_url and stream_url.startswith("http"):
                            self.play_cache[target_url] = (stream_url, now + 1800)
                            return stream_url
                    except Exception:
                        pass

        norm_m = re.search(r"normalPlayUrl:\s*['\"]([^'\"]+)['\"]", pb_html)
        if norm_m:
            norm_url = norm_m.group(1).strip()
            if norm_url and norm_url.startswith("http"):
                self.play_cache[target_url] = (norm_url, now + 1800)
                return norm_url

        return ""

    def playerContent(self, flag, id, vipFlags):
        raw_url = str(id).strip()
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            if "lgvideo.xyz" in raw_url:
                try:
                    resolved = self._resolve_stream(raw_url)
                    if resolved:
                        return {
                            "parse": 0,
                            "playUrl": "",
                            "url": resolved,
                            "header": {
                                "User-Agent": self._ua
                            }
                        }
                except Exception:
                    pass
            elif ".m3u8" in raw_url.lower() or ".mp4" in raw_url.lower():
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": raw_url,
                    "header": {
                        "User-Agent": self._ua
                    }
                }

        return {
            "parse": 1,
            "playUrl": "",
            "url": raw_url,
            "header": {
                "User-Agent": self._ua
            }
        }

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1

        url = "%s/api.php/provide/vod/?ac=detail&wd=%s&pg=%d" % (self.apiUrl, quote(str(key)), page)
        txt = self._http_get(url)

        cards = []
        pagecount = page
        total = 0

        try:
            data = json.loads(txt)
            raw_list = data.get("list", [])
            pagecount = int(data.get("pagecount", page))
            total = int(data.get("total", 0))

            for it in raw_list:
                v_id = str(it.get("vod_id", ""))
                v_name = str(it.get("vod_name", ""))
                if not v_id or not v_name:
                    continue

                cards.append({
                    "vod_id": v_id,
                    "vod_name": v_name,
                    "vod_pic": str(it.get("vod_pic", "")),
                    "vod_remarks": format_remarks(self.brandDirector, it.get("vod_remarks", "")),
                    "style": {"type": "rect", "ratio": 0.75}
                })
        except Exception:
            cards = []

        if not cards:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

        return {
            "list": cards,
            "page": page,
            "pagecount": pagecount if pagecount >= 1 else 1,
            "limit": len(cards),
            "total": total if total > 0 else (page * len(cards) + 100)
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]