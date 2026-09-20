"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '皮克网',
  lang: 'hipy',
})
"""
# -*- coding: utf-8 -*-
# 皮克网 (pdy0.com) TVBox 解析器 —— hipy 格式
# 逆向要点:
#   列表/首页  : <li class="col-..."> 卡片, 链接 /mv/{vid}.html, 海报 data-original, 备注 .item-status
#   详情       : /mv/{vid}.html, 片名取自 <title>《...》, 选集按线路分 #ewave-playlist-N 区块
#   选集链接   : /py/{vid}-{line}-{ep}.html (line=线路号, ep=选集号)
#   播放       : 播放页 <script> 内 JSON 含 "url":"...m3u8/mp4" 即真实直链, 无需签名
#   搜索       : /index.php/ajax/suggest?mid={分类}&wd={关键词}  (绕开 /vs/ 路径的 WAF 安全验证)
import re
import json
import requests
from urllib.parse import quote
from base.spider import Spider as BaseSpider

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://www.pdy0.com"
        if extend and extend.startswith("http"):
            self.host = extend.rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def getName(self):
        return "皮克网"

    # ==================== 网络 ====================
    def _fetch(self, path, ref=None):
        url = path if path.startswith("http") else self.host + path
        try:
            r = self.session.get(
                url, timeout=20,
                headers={"Referer": ref or (self.host + "/")},
            )
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        return ""

    # ==================== 列表解析 ====================
    def _parse_video_list(self, html):
        if not html:
            return []
        items = []
        for card in re.findall(r'<li class="col-[^"]*">.*?</li>', html, re.S):
            m = re.search(r'/mv/(\d+)\.html', card)
            if not m:
                continue
            vid = m.group(1)
            t = re.search(r'title="([^"]+)"', card)
            name = t.group(1).strip() if t else ""
            p = re.search(r'data-original="([^"]+)"', card)
            pic = p.group(1) if p else ""
            remark = ""
            s1 = re.search(r'class="s1"[^>]*>(?:<[^>]+>[^<]*</[^>]+>)?\s*([^<]*)', card)
            if s1 and s1.group(1).strip():
                remark = s1.group(1).strip()
            st = re.search(r'class="[^"]*item-status[^"]*">([^<]+)</p>', card)
            if st and not remark:
                remark = st.group(1).strip()
            items.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark,
            })
        return items

    # ==================== 首页 ====================
    def homeContent(self, filter):
        return {"class": [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "剧集"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "30", "type_name": "短剧"},
        ]}

    def homeVideoContent(self):
        html = self._fetch("/")
        return {"list": self._parse_video_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        url = "/vt/%s.html" % tid if pg <= 1 else "/vt/%s-%s.html" % (tid, pg)
        html = self._fetch(url)
        items = self._parse_video_list(html)
        pagecount = pg + 1 if len(items) >= 24 else pg
        return {"list": items, "page": pg, "pagecount": pagecount, "limit": 24, "total": 99999}

    # ==================== 详情 ====================
    def detailContent(self, ids):
        vid = ids[0]
        html = self._fetch("/mv/%s.html" % vid)
        if not html:
            return {"list": []}
        vod = {}

        # 片名: <title>《片名》高清在线观看 - ...</title>
        mt = re.search(r'<title>([^<]+)</title>', html)
        name = ""
        if mt:
            tm = re.search(r'《([^》]+)》', mt.group(1))
            name = tm.group(1).strip() if tm else mt.group(1).split("-")[0].strip()
        vod["vod_name"] = name

        # 海报
        pic = re.search(r'data-original="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', html)
        vod["vod_pic"] = pic.group(1) if pic else ""

        # 年份 / 地区 / 类型 / 语言  (格式: 2026 / 美国 / 悬疑,恐怖 / 英语)
        st = re.search(r'class="[^"]*item-status[^"]*">([^<]+)</p>', html)
        if st:
            parts = [x.strip() for x in st.group(1).split("/")]
            if len(parts) >= 1:
                vod["vod_year"] = parts[0]
            if len(parts) >= 2:
                vod["vod_area"] = parts[1]
            if len(parts) >= 3:
                vod["vod_class"] = parts[2]
            if len(parts) >= 4:
                vod["vod_lang"] = parts[3]
            vod["vod_remarks"] = st.group(1).strip()

        # 简介
        dc = re.search(r'class="[^"]*content[^"]*"[^>]*>(.*?)</(?:div|p|span)>', html, re.S)
        if dc:
            vod["vod_content"] = re.sub(r'<[^>]+>', "", dc.group(1)).strip()

        # 选集 (多线路: 每条线路对应 #ewave-playlist-N 区块)
        froms, urls, seen = [], [], set()
        for n, ln in re.findall(r'data-target="#ewave-playlist-(\d+)"[^>]*>([^<]+)<span', html):
            if n in seen:
                continue
            seen.add(n)
            blk = re.search(r'id="ewave-playlist-%s"[^>]*>(.*?)</ul>' % n, html, re.S)
            if not blk:
                continue
            eps = re.findall(r'<a\b[^>]*href="/py/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]*)</a>', blk.group(1))
            if not eps:
                continue
            froms.append(ln.strip())
            ep_items = []
            for _, _, ep, txt in eps:
                label = txt.strip() or ("第%s集" % ep)
                ep_items.append("%s$/py/%s-%s-%s.html" % (label, vid, n, ep))
            urls.append("#".join(ep_items))

        if froms:
            vod["vod_play_from"] = "$$$".join(froms)
            vod["vod_play_url"] = "$$$".join(urls)

        return {"list": [vod]}

    # ==================== 搜索 (ajax/suggest 绕过 WAF) ====================
    def searchContent(self, key, quick, pg=1):
        items, seen = [], set()
        for mid in ["1", "2", "3", "4", "30"]:
            try:
                r = self.session.get(
                    "%s/index.php/ajax/suggest?mid=%s&wd=%s&limit=30" % (self.host, mid, quote(key)),
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": self.host + "/"},
                    timeout=20,
                )
                data = r.json()
            except Exception:
                continue
            if data.get("code") != 1:
                continue
            for it in data.get("list", []):
                vid = str(it.get("id", ""))
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                items.append({
                    "vod_id": vid,
                    "vod_name": it.get("name", ""),
                    "vod_pic": it.get("pic", ""),
                    "vod_remarks": "",
                })
        return {"list": items}

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        pid = str(id).strip()
        if pid.startswith("http"):
            url = pid
        elif pid.startswith("/"):
            url = self.host + pid
        else:
            url = self.host + "/" + pid
        html = self._fetch(url)
        if not html:
            return {"parse": 1, "playUrl": "", "url": url, "header": self.headers}
        m = re.search(r'"url"\s*:\s*"((?:\\/|[^"])+?\.m3u8[^"]*)"', html) or \
            re.search(r'"url"\s*:\s*"((?:\\/|[^"])+?\.mp4[^"]*)"', html)
        if not m:
            return {"parse": 1, "playUrl": "", "url": url, "header": self.headers}
        real = m.group(1).replace("\\/", "/")
        return {"parse": 0, "playUrl": "", "url": real, "header": self.headers}