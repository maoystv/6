# -*- coding: utf-8 -*-
# 大米星球 蜘蛛（源自 Hamo 插件 com.butterfly.damixingqiu 的解析逻辑移植）
import base64
import gzip
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse

from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    DEFAULT_HOST = "http://dmxq22.com"
    UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    BAD_PIC_KEYWORDS = ["loading", "load.gif", "icon.png", "frosted.png", "colour-bg", "logo"]
    BAD_SSL_DOMAINS = ["rrcdnbf2.com", "rrcdnbf4.com", "ifznedy1.com", "m3u8.tv", "dmxq"]
    COMMON_BY = [("", "全部排序"), ("time", "时间排序"), ("hits", "人气排序"), ("score", "评分排序")]
    AREA = ["", "大陆", "香港", "台湾", "美国", "日本", "韩国", "英国", "法国", "德国", "印度", "泰国", "丹麦", "瑞典", "巴西", "加拿大", "俄罗斯", "意大利", "比利时", "爱尔兰", "西班牙", "澳大利亚"]
    LANG = ["", "国语", "英语", "粤语", "日语", "韩语", "法语", "德语", "泰语", "俄语", "闽南语", "丹麦语", "波兰语", "瑞典语", "印地语", "挪威语", "意大利语", "西班牙语"]
    YEARS = ["", "2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011", "2010", "2009", "2008", "2007", "2006", "2005", "2004", "2003", "2002", "2001", "2000", "90年代", "80年代", "70年代", "更早"]
    CLASS_MOVIE = ["", "Netflix", "动作", "喜剧", "爱情", "科幻", "剧情", "悬疑", "恐怖", "惊悚", "犯罪", "冒险", "战争", "奇幻", "动画", "古装", "武侠", "家庭", "纪录", "传记", "历史"]
    CLASS_TV = ["", "Netflix", "短剧", "都市", "言情", "古装", "武侠", "悬疑", "罪案", "科幻", "仙侠", "穿越", "动作", "喜剧", "家庭", "战争", "谍战", "历史"]
    CLASSES = [("today", "今日更新"), ("netflix", "Netflix"), ("20", "电影"), ("21", "电视剧"), ("22", "动漫"), ("23", "综艺"), ("36", "短剧")]
    CARD_RE = re.compile(r'<a[^>]+href=["\'][^"\']*voddetail/(\d+)\.html["\'][^>]*>([\s\S]*?<img[\s\S]*?)</a>', re.I)
    EP_RE = re.compile(r'<a[^>]+href=["\'][^"\']*vodplay/(\d+-\d+-\d+)\.html["\'][^>]*>([\s\S]*?)</a>', re.I)

    def getName(self):
        return "大米星球"

    def init(self, extend=""):
        self.host = self.DEFAULT_HOST
        if isinstance(extend, str) and extend.strip().startswith("http"):
            self.host = extend.strip().rstrip("/")

    # ---------- transport ----------
    def _fetch(self, url):
        headers = {"User-Agent": self.UA, "Referer": self.host + "/", "Accept-Encoding": "gzip"}
        for _ in range(2):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                if raw:
                    return raw.decode("utf-8", "replace")
            except Exception:
                pass
            time.sleep(0.5)
        if url.startswith("https://"):
            return self._fetch_http(url)
        return ""

    def _fetch_http(self, url):
        headers = {"User-Agent": self.UA, "Referer": self.host + "/"}
        try:
            req = urllib.request.Request("http://" + url[8:], headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace") if raw else ""
        except Exception:
            return ""

    # ---------- helpers ----------
    def _strip(self, s):
        if not s:
            return ""
        return re.sub(r"<[^>]+>", "", str(s)).strip()

    def _decode_unicode_url(self, s):
        if not s:
            return ""
        clean = str(s).replace("\\/", "/").strip()
        decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), clean)
        try:
            return urllib.parse.quote(urllib.parse.unquote(decoded), safe=";/?:@&=+$,-_.!~*'()#")
        except Exception:
            return decoded

    def _clean_img(self, raw_url):
        if not raw_url:
            return ""
        raw = str(raw_url).strip().replace("&amp;", "&")
        if "baidu.com" in raw:
            sm = re.search(r"src=([^&]+)", raw)
            if sm:
                try:
                    real = urllib.parse.unquote(sm.group(1))
                except Exception:
                    real = sm.group(1)
                if not real.startswith("http"):
                    real = "https://" + real.lstrip("/")
                return "https://gimg0.baidu.com/gimg/app=2001&n=0&g=0n&fmt=jpeg&src=" + urllib.parse.quote(real, safe="")
            return raw
        if raw.startswith("//"):
            full = "https:" + raw
        elif raw.startswith("/"):
            full = self.host + raw
        else:
            full = raw
        if not full.startswith("http"):
            full = "https://" + full
        return "https://gimg0.baidu.com/gimg/app=2001&n=0&g=0n&fmt=jpeg&src=" + urllib.parse.quote(full, safe="")

    def _parse_cards(self, html_text):
        items = []
        seen = set()
        for m in self.CARD_RE.finditer(str(html_text or "")):
            vid, chunk = m.group(1).strip(), m.group(0)
            if not vid or vid in seen:
                continue
            title = ""
            tm = re.search(r'title=["\']([^"\']+)["\']', chunk, re.I)
            if tm and tm.group(1).strip() != "大米星球":
                title = tm.group(1).strip()
            if not title:
                am = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', chunk, re.I)
                if am and am.group(1).strip() != "大米星球":
                    title = am.group(1).strip()
            if not title or title == "大米星球":
                continue
            pic = ""
            pm = (re.search(r'data-original=["\']([^"\']+)["\']', chunk, re.I) or
                  re.search(r'data-src=["\']([^"\']+)["\']', chunk, re.I) or
                  re.search(r'src=["\']([^"\']+)["\']', chunk, re.I))
            if pm:
                p = pm.group(1).strip()
                if not any(k in p.lower() for k in self.BAD_PIC_KEYWORDS):
                    pic = self._clean_img(p)
            remarks = "分享者影视"
            sm = re.search(r"<span[^>]*>([\s\S]*?)</span>", chunk, re.I)
            if sm:
                raw_rem = self._strip(sm.group(1))
                if raw_rem:
                    remarks = "分享者影视" + raw_rem
            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "style": {"type": "rect", "ratio": 0.71},
            })
        return items

    def _filter_rows(self, class_opts):
        def opts(values):
            return [{"n": (v if v else "全部"), "v": v} for v in values]
        return [
            {"key": "class", "name": "类型", "value": opts(class_opts)},
            {"key": "area", "name": "地区", "value": opts(self.AREA)},
            {"key": "lang", "name": "语言", "value": opts(self.LANG)},
            {"key": "year", "name": "年份", "value": opts(self.YEARS)},
            {"key": "by", "name": "排序", "value": [{"n": n, "v": v} for v, n in self.COMMON_BY]},
        ]

    # ---------- entries ----------
    def homeContent(self, filter=False):
        classes = [{"type_id": cid, "type_name": name} for cid, name in self.CLASSES]
        result = {"class": classes}
        if filter:
            result["filters"] = {
                "20": self._filter_rows(self.CLASS_MOVIE),
                "21": self._filter_rows(self.CLASS_TV),
            }
        return result

    def homeVideoContent(self):
        html_text = self._fetch(self.host + "/vodshow/20--------1---.html")
        return {"list": self._parse_cards(html_text)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        ext = extend if isinstance(extend, dict) else {}
        cid = str(tid or "20")
        if cid == "today":
            url = self.host + "/label/week.html"
        elif cid == "netflix":
            url = self.host + "/vodshow/20---Netflix-----" + str(page) + "---.html"
        else:
            c_by = str(ext.get("by") or "")
            c_class = str(ext.get("class") or "")
            c_area = str(ext.get("area") or "")
            url_class = urllib.parse.quote(c_class, safe="") if c_class else ""
            url_area = urllib.parse.quote(c_area, safe="") if c_area else ""
            if not (url_area or url_class or c_by):
                url = self.host + "/vodshow/" + cid + "--------" + str(page) + "---.html"
            else:
                url = self.host + "/vodshow/" + cid + "-" + url_area + "-" + c_by + "-" + url_class + "-----" + str(page) + "---.html"
        html_text = self._fetch(url)
        items = self._parse_cards(html_text)
        return {"list": items, "page": page, "pagecount": page + 1 if items else page, "limit": len(items), "total": len(items)}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        keyword = str(key or "").strip()
        if not keyword:
            return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}
        url = self.host + "/vodsearch/" + urllib.parse.quote(keyword, safe="") + "----------" + str(page) + "---.html"
        html_text = self._fetch(url)
        items = self._parse_cards(html_text)
        return {"list": items, "page": page, "pagecount": page + 1 if items else page, "limit": len(items), "total": len(items)}

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = re.sub(r"\D", "", str(ids[0] or ""))
        if not vid:
            return {"list": []}
        detail_url = self.host + "/voddetail/" + vid + ".html"
        html_text = self._fetch(detail_url)
        h1 = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_text, re.I)
        vod_name = self._strip(h1.group(1)) if h1 else ""
        vod_pic = ""
        pm = (re.search(r'class=["\'][^"\']*detail-pic["\'][\s\S]*?<img[^>]+src=["\']([^"\']+)["\']', html_text, re.I) or
              re.search(r'<img[^>]+class=["\'][^"\']*lazy[^"\']*["\'][^>]+data-original=["\']([^"\']+)["\']', html_text, re.I))
        if pm:
            vod_pic = self._clean_img(pm.group(1).strip())
        desc = ""
        dm = re.search(r'<div[^>]+class=["\'][^"\']*content[^"\']*["\'][^>]*>([\s\S]*?)</div>', html_text, re.I)
        if dm:
            desc = self._strip(dm.group(1))
        tab_names = [self._strip(x) for x in re.findall(r'<div[^>]+class=["\'][^"\']*module-tab-item[^"\']*["\'][^>]*>[\s\S]*?<span>([\s\S]*?)</span>', html_text, re.I)]
        if not tab_names:
            tab_names = [self._strip(x) for x in re.findall(r'<a[^>]+data-toggle=["\']tab["\'][^>]*>([\s\S]*?)</a>', html_text, re.I)]
        play_lists = re.findall(r'<div[^>]+class=["\'][^"\']*module-play-list[^"\']*["\']>([\s\S]*?)</div>', html_text, re.I)
        if not play_lists:
            play_lists = re.findall(r'<ul[^>]+class=["\'][^"\']*playlist[^"\']*["\']>([\s\S]*?)</ul>', html_text, re.I)
        froms = []
        play_urls = []
        for i, plist in enumerate(play_lists):
            line_name = tab_names[i] if i < len(tab_names) and tab_names[i] else ("线路 " + str(i + 1))
            eps = []
            for em in self.EP_RE.finditer(plist):
                play_id = em.group(1).strip()
                ep_name = self._strip(em.group(2)) or ("第 " + str(len(eps) + 1) + " 集")
                val = json.dumps({"playId": play_id}, ensure_ascii=False)
                eps.append(ep_name + "$" + val)
            if eps:
                froms.append(line_name)
                play_urls.append("#".join(eps))
        if not froms:
            froms = ["大米星球"]
            play_urls = ["正片$" + json.dumps({"playId": vid + "-1-1"}, ensure_ascii=False)]
        lines = [
            "分享者在线",
            "导演：分享者在线",
            "当前主站：" + self.host,
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "━━━━━━━",
        ]
        if desc:
            lines.append(desc)
        else:
            lines.append("标题：" + (vod_name or "影视详情"))
            lines.append("片源：大米星球")
            lines.append("编号：" + vid)
        vod = {
            "vod_id": vid,
            "vod_name": vod_name or "影视详情",
            "vod_pic": vod_pic,
            "vod_remarks": "分享者影视",
            "vod_actor": "分享者在线",
            "vod_director": "分享者影视",
            "vod_content": "\n".join(lines),
            "vod_class": "影视专区",
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(play_urls),
            "style": {"type": "rect", "ratio": 0.71},
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        play_id = ""
        try:
            data = json.loads(id)
            if isinstance(data, dict):
                play_id = str(data.get("playId") or "").strip()
        except Exception:
            pass
        if not play_id:
            play_id = str(id or "").strip()
        play_page = self.host + "/vodplay/" + play_id + ".html"
        headers = {"User-Agent": self.UA, "Referer": self.host + "/"}
        html_text = self._fetch(play_page)
        real_url = ""
        um = re.search(r'var\s+player_aaaa\s*=\s*\{[\s\S]*?["\']url["\']\s*:\s*["\']([^"\']+)["\']', html_text, re.I)
        if um:
            real_url = self._decode_unicode_url(um.group(1))
            em = re.search(r'["\']encrypt["\']\s*:\s*(\d+)', html_text, re.I)
            if em:
                enc = em.group(1)
                if enc == "1":
                    try:
                        real_url = urllib.parse.unquote(real_url)
                    except Exception:
                        pass
                elif enc == "2":
                    try:
                        real_url = self._decode_unicode_url(base64.b64decode(real_url).decode("utf-8", "replace"))
                    except Exception:
                        pass
        else:
            jm = re.search(r"var\s+player_aaaa\s*=\s*(\{[\s\S]*?\});", html_text, re.I)
            if jm:
                try:
                    pdata = json.loads(jm.group(1))
                    if isinstance(pdata, dict) and pdata.get("url"):
                        real_url = self._decode_unicode_url(str(pdata["url"]))
                except Exception:
                    pass
        if real_url:
            lower = real_url.lower()
            if ".m3u8" in lower or ".mp4" in lower or ".flv" in lower:
                if any(d in lower for d in self.BAD_SSL_DOMAINS) and real_url.startswith("https://"):
                    real_url = "http://" + real_url[8:]
                if ".m3u8" not in real_url.lower():
                    real_url += ("&" if "?" in real_url else "?") + "format=.m3u8"
                return {"parse": 0, "playUrl": "", "url": real_url, "header": headers}
            return {"parse": 1, "playUrl": "", "url": real_url, "header": headers}
        return {"parse": 1, "playUrl": "", "url": play_page, "header": headers}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

# --- System Signature ---
#‍​​‌‌​‌​‌​​‌‌​‌‌​​​‌‌​​‌​​​‌‌​​‌‌​​‌‌​‌‌​​​‌‌​‌​‌​​‌‌‌​​‌​​‌‌​​​‌​​‌‌​​‌​​​‌‌​​‌​‍
