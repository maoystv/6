# -*- coding: utf-8 -*-
# 华视影院

import hashlib
import json
import re
import time
from urllib.parse import quote

import requests
from base.spider import Spider as BaseSpider

DEFAULT_HOST = "https://www.lwdys.com"
SITE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
SIGN_KEY = "cb808529bae6b6be45ecfab29a4889bc"
BRAND = "分享者影视"
LINE_NAME = "分享者专线"
POSTER_RATIO = 0.67
PAGE_SIZE = 48
SEARCH_PAGE_SIZE = 12
TIMEOUT = 8
DETAIL_FAIL_TEXT = "未找到该影片"
NO_SOURCE_TEXT = "未找到可播放片源"
FILTER_ORDER = ["type", "class", "area", "year", "lang", "by"]

CATEGORIES_DATA = [{'type_id': '1', 'type_name': '电影', 'filters': [{'key': 'type', 'name': '类型', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '喜剧', 'v': '/type/22'}, {'n': '动作', 'v': '/type/23'}, {'n': '科幻', 'v': '/type/30'}, {'n': '爱情', 'v': '/type/26'}, {'n': '悬疑', 'v': '/type/27'}, {'n': '奇幻', 'v': '/type/87'}, {'n': '剧情', 'v': '/type/37'}, {'n': '恐怖', 'v': '/type/36'}, {'n': '犯罪', 'v': '/type/35'}, {'n': '动画', 'v': '/type/33'}, {'n': '惊悚', 'v': '/type/34'}, {'n': '战争', 'v': '/type/25'}, {'n': '冒险', 'v': '/type/31'}, {'n': '灾难', 'v': '/type/81'}, {'n': '伦理', 'v': '/type/83'}, {'n': '其他', 'v': '/type/43'}]}, {'key': 'area', 'name': '地区', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '中国大陆', 'v': '/area/中国大陆'}, {'n': '中国香港', 'v': '/area/中国香港'}, {'n': '中国台湾', 'v': '/area/中国台湾'}, {'n': '美国', 'v': '/area/美国'}, {'n': '日本', 'v': '/area/日本'}, {'n': '韩国', 'v': '/area/韩国'}, {'n': '印度', 'v': '/area/印度'}, {'n': '泰国', 'v': '/area/泰国'}, {'n': '其他', 'v': '/area/其他'}]}, {'key': 'year', 'name': '年份', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '2026', 'v': '/year/2026'}, {'n': '2025', 'v': '/year/2025'}, {'n': '2024', 'v': '/year/2024'}, {'n': '2023', 'v': '/year/2023'}, {'n': '2022', 'v': '/year/2022'}, {'n': '2021', 'v': '/year/2021'}, {'n': '2020', 'v': '/year/2020'}, {'n': '2019', 'v': '/year/2019'}, {'n': '2018', 'v': '/year/2018'}, {'n': '2017', 'v': '/year/2017'}, {'n': '2016', 'v': '/year/2016'}, {'n': '2015', 'v': '/year/2015'}, {'n': '2014', 'v': '/year/2014'}, {'n': '2013', 'v': '/year/2013'}, {'n': '2012', 'v': '/year/2012'}, {'n': '2011', 'v': '/year/2011'}, {'n': '2010', 'v': '/year/2010'}, {'n': '2009~2000', 'v': '/year/2009~2000'}]}, {'key': 'lang', 'name': '语言', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国语', 'v': '/lang/国语'}, {'n': '英语', 'v': '/lang/英语'}, {'n': '粤语', 'v': '/lang/粤语'}, {'n': '韩语', 'v': '/lang/韩语'}, {'n': '日语', 'v': '/lang/日语'}, {'n': '其他', 'v': '/lang/其他'}]}, {'key': 'by', 'name': '排序', 'init': '/sortType/1/sortOrder/0', 'value': [{'n': '上映时间', 'v': '/sortType/1/sortOrder/0'}, {'n': '人气高低', 'v': '/sortType/3/sortOrder/0'}, {'n': '评分高低', 'v': '/sortType/4/sortOrder/0'}]}]}, {'type_id': '2', 'type_name': '电视剧', 'filters': [{'key': 'type', 'name': '类型', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国产剧', 'v': '/type/14'}, {'n': '欧美剧', 'v': '/type/15'}, {'n': '港台剧', 'v': '/type/16'}, {'n': '日韩剧', 'v': '/type/62'}, {'n': '其他剧', 'v': '/type/68'}]}, {'key': 'class', 'name': '剧情', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '古装', 'v': '/class/古装'}, {'n': '战争', 'v': '/class/战争'}, {'n': '喜剧', 'v': '/class/喜剧'}, {'n': '家庭', 'v': '/class/家庭'}, {'n': '犯罪', 'v': '/class/犯罪'}, {'n': '动作', 'v': '/class/动作'}, {'n': '奇幻', 'v': '/class/奇幻'}, {'n': '剧情', 'v': '/class/剧情'}, {'n': '历史', 'v': '/class/历史'}, {'n': '短片', 'v': '/class/短片'}]}, {'key': 'area', 'name': '地区', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '中国大陆', 'v': '/area/中国大陆'}, {'n': '中国香港', 'v': '/area/中国香港'}, {'n': '中国台湾', 'v': '/area/中国台湾'}, {'n': '日本', 'v': '/area/日本'}, {'n': '韩国', 'v': '/area/韩国'}, {'n': '美国', 'v': '/area/美国'}, {'n': '泰国', 'v': '/area/泰国'}, {'n': '其他', 'v': '/area/其他'}]}, {'key': 'year', 'name': '时间', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '2026', 'v': '/year/2026'}, {'n': '2025', 'v': '/year/2025'}, {'n': '2024', 'v': '/year/2024'}, {'n': '2023', 'v': '/year/2023'}, {'n': '2022', 'v': '/year/2022'}, {'n': '2021', 'v': '/year/2021'}, {'n': '2020', 'v': '/year/2020'}, {'n': '2019', 'v': '/year/2019'}, {'n': '2018', 'v': '/year/2018'}, {'n': '2017', 'v': '/year/2017'}, {'n': '2016', 'v': '/year/2016'}, {'n': '2015', 'v': '/year/2015'}, {'n': '2014', 'v': '/year/2014'}, {'n': '2013', 'v': '/year/2013'}, {'n': '2012', 'v': '/year/2012'}, {'n': '2011', 'v': '/year/2011'}, {'n': '2010', 'v': '/year/2010'}]}, {'key': 'lang', 'name': '语言', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '普通话', 'v': '/lang/普通话'}, {'n': '英语', 'v': '/lang/英语'}, {'n': '粤语', 'v': '/lang/粤语'}, {'n': '韩语', 'v': '/lang/韩语'}, {'n': '日语', 'v': '/lang/日语'}, {'n': '泰语', 'v': '/lang/泰语'}, {'n': '其他', 'v': '/lang/其他'}]}, {'key': 'by', 'name': '排序', 'init': '/sortType/1/sortOrder/0', 'value': [{'n': '最近更新', 'v': '/sortType/1/sortOrder/0'}, {'n': '添加时间', 'v': '/sortType/2/sortOrder/0'}, {'n': '人气高低', 'v': '/sortType/3/sortOrder/0'}, {'n': '评分高低', 'v': '/sortType/4/sortOrder/0'}]}]}, {'type_id': '3', 'type_name': '综艺', 'filters': [{'key': 'type', 'name': '类型', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国产综艺', 'v': '/type/69'}, {'n': '港台综艺', 'v': '/type/70'}, {'n': '日韩综艺', 'v': '/type/72'}, {'n': '欧美综艺', 'v': '/type/73'}]}, {'key': 'class', 'name': '剧情', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '真人秀', 'v': '/class/真人秀'}, {'n': '音乐', 'v': '/class/音乐'}, {'n': '脱口秀', 'v': '/class/脱口秀'}]}, {'key': 'area', 'name': '地区', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '中国大陆', 'v': '/area/中国大陆'}, {'n': '中国香港', 'v': '/area/中国香港'}, {'n': '中国台湾', 'v': '/area/中国台湾'}, {'n': '日本', 'v': '/area/日本'}, {'n': '韩国', 'v': '/area/韩国'}, {'n': '美国', 'v': '/area/美国'}, {'n': '其他', 'v': '/area/其他'}]}, {'key': 'year', 'name': '时间', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '2026', 'v': '/year/2026'}, {'n': '2025', 'v': '/year/2025'}, {'n': '2024', 'v': '/year/2024'}, {'n': '2023', 'v': '/year/2023'}, {'n': '2022', 'v': '/year/2022'}, {'n': '2021', 'v': '/year/2021'}, {'n': '2020', 'v': '/year/2020'}]}, {'key': 'lang', 'name': '语言', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国语', 'v': '/lang/国语'}, {'n': '英语', 'v': '/lang/英语'}, {'n': '粤语', 'v': '/lang/粤语'}, {'n': '韩语', 'v': '/lang/韩语'}, {'n': '日语', 'v': '/lang/日语'}, {'n': '其他', 'v': '/lang/其他'}]}, {'key': 'by', 'name': '排序', 'init': '/sortType/1/sortOrder/0', 'value': [{'n': '最近更新', 'v': '/sortType/1/sortOrder/0'}, {'n': '添加时间', 'v': '/sortType/2/sortOrder/0'}, {'n': '人气高低', 'v': '/sortType/3/sortOrder/0'}, {'n': '评分高低', 'v': '/sortType/4/sortOrder/0'}]}]}, {'type_id': '4', 'type_name': '动漫', 'filters': [{'key': 'type', 'name': '类型', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国产动漫', 'v': '/type/75'}, {'n': '日韩动漫', 'v': '/type/76'}, {'n': '欧美动漫', 'v': '/type/77'}]}, {'key': 'class', 'name': '剧情', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '喜剧', 'v': '/class/喜剧'}, {'n': '科幻', 'v': '/class/科幻'}, {'n': '热血', 'v': '/class/热血'}, {'n': '冒险', 'v': '/class/冒险'}, {'n': '动作', 'v': '/class/动作'}, {'n': '运动', 'v': '/class/运动'}, {'n': '战争', 'v': '/class/战争'}, {'n': '儿童', 'v': '/class/儿童'}]}, {'key': 'area', 'name': '地区', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '中国大陆', 'v': '/area/中国大陆'}, {'n': '日本', 'v': '/area/日本'}, {'n': '美国', 'v': '/area/美国'}, {'n': '其他', 'v': '/area/其他'}]}, {'key': 'year', 'name': '时间', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '2026', 'v': '/year/2026'}, {'n': '2025', 'v': '/year/2025'}, {'n': '2024', 'v': '/year/2024'}, {'n': '2023', 'v': '/year/2023'}, {'n': '2022', 'v': '/year/2022'}, {'n': '2021', 'v': '/year/2021'}, {'n': '2020', 'v': '/year/2020'}, {'n': '2019', 'v': '/year/2019'}, {'n': '2018', 'v': '/year/2018'}, {'n': '2017', 'v': '/year/2017'}, {'n': '2016', 'v': '/year/2016'}, {'n': '2015', 'v': '/year/2015'}, {'n': '2014', 'v': '/year/2014'}, {'n': '2013', 'v': '/year/2013'}, {'n': '2012', 'v': '/year/2012'}, {'n': '2011', 'v': '/year/2011'}, {'n': '2010', 'v': '/year/2010'}]}, {'key': 'lang', 'name': '语言', 'init': '', 'value': [{'n': '全部', 'v': ''}, {'n': '国语', 'v': '/lang/国语'}, {'n': '英语', 'v': '/lang/英语'}, {'n': '日语', 'v': '/lang/日语'}, {'n': '其他', 'v': '/lang/其他'}]}, {'key': 'by', 'name': '排序', 'init': '/sortType/1/sortOrder/0', 'value': [{'n': '最近更新', 'v': '/sortType/1/sortOrder/0'}, {'n': '添加时间', 'v': '/sortType/2/sortOrder/0'}, {'n': '人气高低', 'v': '/sortType/3/sortOrder/0'}, {'n': '评分高低', 'v': '/sortType/4/sortOrder/0'}]}]}]


def _md5_hex(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _sha1_hex(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _clean_text(raw):
    if raw is None:
        return ""
    return re.sub(r"[\r\n\t]+", " ", str(raw)).strip()


def _split_tags(raw):
    if raw is None:
        return []
    s = str(raw)
    for ch in ("，", "、", ";", "；"):
        s = s.replace(ch, ",")
    out = []
    for part in s.split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out


def _format_status(meta):
    clean = _clean_text(meta)
    if clean:
        return BRAND + " | " + clean
    return BRAND


def _status_raw(row):
    try:
        is_movie = int(row.get("typeId1")) == 1
    except Exception:
        is_movie = False
    if is_movie:
        return row.get("vodVersion")
    return row.get("vodRemarks")


def _quote_path(value):
    parts = str(value).split("/")
    return "/".join(quote(part, safe="!*'()") for part in parts)


def _extract_rsc_list(html_text):
    if not html_text:
        return []
    for marker in ('\\"list\\":[', '"list":['):
        start = 0
        while True:
            idx = html_text.find(marker, start)
            if idx == -1:
                break
            bracket_pos = idx + len(marker) - 1
            depth = 0
            end_pos = -1
            limit = min(len(html_text), bracket_pos + 150000)
            for i in range(bracket_pos, limit):
                c = html_text[i]
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break
            if end_pos != -1:
                chunk = html_text[bracket_pos:end_pos]
                if "vodId" in chunk:
                    clean = chunk.replace('\\"', '"').replace('\\\\', '\\')
                    try:
                        data = json.loads(clean)
                    except Exception:
                        data = None
                    if isinstance(data, list) and data and isinstance(data[0], dict) and "vodId" in data[0]:
                        return data
            start = idx + len(marker)
    return []


def _episode_name(name):
    return str(name or "").replace("$", "_").replace("#", "_")


class Spider(BaseSpider):
    def __init__(self):
        self.host = DEFAULT_HOST

    def init(self, extend=""):
        cfg = {}
        if isinstance(extend, dict):
            cfg = extend
        elif isinstance(extend, str) and extend:
            try:
                cfg = json.loads(extend)
            except Exception:
                cfg = {}
        custom = ""
        if isinstance(cfg, dict):
            custom = str(cfg.get("host", "") or "").strip()
        if custom and custom.startswith("http"):
            self.host = custom.rstrip("/")
        else:
            self.host = DEFAULT_HOST
        return True

    def getName(self):
        return "华视影院"

    def isVideoFormat(self, url):
        low = str(url or "").lower()
        return (".m3u8" in low) or (".mp4" in low) or (".flv" in low) or (".mpd" in low)

    def manualVideoCheck(self):
        return False

    def _base_headers(self):
        return {
            "User-Agent": SITE_UA,
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _sign(self, params_str):
        t = str(int(time.time() * 1000))
        if params_str:
            data = params_str + "&key=" + SIGN_KEY + "&t=" + t
        else:
            data = "key=" + SIGN_KEY + "&t=" + t
        return t, _sha1_hex(_md5_hex(data))

    def _fetch_json(self, path, params_str):
        headers = self._base_headers()
        t, sign = self._sign(params_str)
        headers["t"] = t
        headers["sign"] = sign
        try:
            resp = requests.get(self.host + path, headers=headers, timeout=TIMEOUT)
            if resp.status_code < 200 or resp.status_code >= 300:
                return None
            return resp.json()
        except Exception:
            return None

    def _fetch_text(self, url):
        try:
            resp = requests.get(url, headers=self._base_headers(), timeout=TIMEOUT)
            if resp.status_code < 200 or resp.status_code >= 300:
                return ""
            return resp.text or ""
        except Exception:
            return ""

    def _to_page(self, pg):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        return page

    def _card(self, row):
        card = {
            "vod_id": str(row.get("vodId")),
            "vod_name": str(row.get("vodName") or ""),
            "vod_pic": str(row.get("vodPic") or ""),
            "vod_remarks": _format_status(_status_raw(row)),
            "style": {"type": "rect", "ratio": POSTER_RATIO},
        }
        genres = _split_tags(row.get("vodClass"))
        if genres:
            card["vod_class"] = ",".join(genres)
        return card

    def _rows_to_cards(self, rows):
        cards = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("vodId") is not None and str(row.get("vodId")) != "":
                    cards.append(self._card(row))
        return cards

    def _page_form(self, page, cards, limit):
        if cards:
            return {"page": page, "pagecount": page + 1, "limit": limit, "total": (page + 1) * limit, "list": cards}
        return {"page": page, "pagecount": page, "limit": 1, "total": 0, "list": []}

    def homeContent(self, filter):
        classes = [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in CATEGORIES_DATA]
        result = {"class": classes}
        if filter:
            filters = {}
            for c in CATEGORIES_DATA:
                rows = []
                for row in c["filters"]:
                    rows.append({
                        "key": row["key"],
                        "name": row["name"],
                        "init": row["init"],
                        "value": [dict(o) for o in row["value"]],
                    })
                filters[c["type_id"]] = rows
            result["filters"] = filters
        return result

    def homeVideoContent(self):
        data = self._fetch_json("/api/mw-movie/anonymous/home/hotSearch", "")
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return {"list": []}
        return {"list": self._rows_to_cards(rows)}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._to_page(pg)
        category_id = str(tid or "").strip() or "1"
        ext = extend if isinstance(extend, dict) else {}
        sub = ""
        for key in FILTER_ORDER:
            val = ext.get(key)
            if val:
                sub += str(val)
        url = self.host + "/vod/show/id/" + category_id + _quote_path(sub) + "/page/" + str(page)
        html = self._fetch_text(url)
        rows = _extract_rsc_list(html)
        return self._page_form(page, self._rows_to_cards(rows), PAGE_SIZE)

    def searchContent(self, key, quick, pg="1"):
        page = self._to_page(pg)
        keyword = str(key or "")
        params_str = "keyword=" + keyword + "&pageNum=" + str(page) + "&pageSize=" + str(SEARCH_PAGE_SIZE)
        path = "/api/mw-movie/anonymous/video/searchByWord?keyword=" + quote(keyword, safe="!*'()") + "&pageNum=" + str(page) + "&pageSize=" + str(SEARCH_PAGE_SIZE)
        data = self._fetch_json(path, params_str)
        rows = None
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                result = inner.get("result")
                if isinstance(result, dict):
                    rows = result.get("list")
        if not isinstance(rows, list):
            return self._page_form(page, [], SEARCH_PAGE_SIZE)
        return self._page_form(page, self._rows_to_cards(rows), SEARCH_PAGE_SIZE)

    def _brand_block(self):
        lines = [
            "分享者在线",
            "导演：分享者",
            "当前主站：" + self.host,
            "━" * 28,
            "━" * 7,
        ]
        return "\n".join(lines)

    def _summary(self, data, genres, item_id):
        lines = [self._brand_block()]
        content = data.get("vodContent")
        content = "" if content is None else str(content).strip()
        if content:
            lines.append(content)
        else:
            lines.append("标题：" + str(data.get("vodName") or ""))
            cat_text = "、".join(genres) if genres else str(data.get("typeName") or "")
            lines.append("分类：" + cat_text)
            lines.append("片源：华视影院")
            lines.append("编号：" + item_id)
        return "\n".join(lines)

    def detailContent(self, ids):
        raw = ""
        if isinstance(ids, (list, tuple)) and ids:
            raw = str(ids[0])
        elif ids:
            raw = str(ids)
        if not raw:
            return {"list": [], "msg": DETAIL_FAIL_TEXT}
        data = self._fetch_json("/api/mw-movie/anonymous/video/detail?id=" + raw, "id=" + raw)
        inner = data.get("data") if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            return {"list": [], "msg": DETAIL_FAIL_TEXT}
        item_id = raw
        genres = _split_tags(inner.get("vodClass"))
        actors = _split_tags(inner.get("vodActor"))
        if not actors:
            actors = ["分享者在线"]
        pic = str(inner.get("vodPic") or "")
        episodes = []
        play_list = inner.get("episodeList")
        if not isinstance(play_list, list):
            play_list = []
        for i, ep in enumerate(play_list):
            if not isinstance(ep, dict) or ep.get("nid") is None:
                continue
            nm = ep.get("name")
            nm = "" if nm is None else str(nm)
            nm = _episode_name(nm)
            if not nm:
                sort_val = ep.get("sort")
                nm = str(sort_val) if sort_val is not None else str(i + 1)
            env = {"vodId": item_id, "nid": str(ep.get("nid"))}
            episodes.append(nm + "$" + json.dumps(env, ensure_ascii=False))
        content = self._summary(inner, genres, item_id)
        remarks = _format_status(_status_raw(inner))
        if episodes:
            play_url = "#".join(episodes)
        else:
            content = content + "\n" + NO_SOURCE_TEXT
            play_url = "暂无播放源$" + json.dumps({"notice": NO_SOURCE_TEXT}, ensure_ascii=False)
            remarks = NO_SOURCE_TEXT
        year = inner.get("vodYear")
        year_text = "" if year is None else str(year)
        vod = {
            "vod_id": raw,
            "vod_name": str(inner.get("vodName") or ""),
            "vod_pic": pic,
            "vod_bg": pic,
            "vod_background": pic,
            "vod_banner": pic,
            "vod_year": year_text if (year_text and year_text != "0") else "",
            "vod_remarks": remarks,
            "vod_actor": ",".join(actors),
            "vod_director": "分享者影视",
            "vod_content": content,
            "vod_play_from": LINE_NAME,
            "vod_play_url": play_url,
        }
        if genres:
            vod["vod_class"] = ",".join(genres)
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "").strip()
        env = None
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                if obj.get("notice"):
                    return {"parse": 0, "msg": str(obj["notice"])}
                env = obj
        if env is None:
            return {"parse": 0, "jx": 0, "url": "", "msg": "缺少播放标识"}
        vod_id = str(env.get("vodId") or "")
        nid = str(env.get("nid") or "")
        if not vod_id or not nid:
            return {"parse": 0, "jx": 0, "url": "", "msg": "缺少播放标识"}
        params_str = "id=" + vod_id + "&nid=" + nid
        data = self._fetch_json("/api/mw-movie/anonymous/v2/video/episode/url?id=" + vod_id + "&nid=" + nid, params_str)
        play_url = ""
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                lst = inner.get("list")
                if isinstance(lst, list) and lst and isinstance(lst[0], dict) and lst[0].get("url"):
                    play_url = str(lst[0]["url"])
        if not play_url:
            return {"parse": 0, "jx": 0, "url": "", "msg": "未能提取到播放地址"}
        headers = {"User-Agent": SITE_UA, "Referer": self.host + "/"}
        return {"parse": 0, "jx": 0, "url": play_url, "header": headers}

    def liveContent(self, url):
        return ""

# --- System Signature ---
#‍​​‌‌​‌​‌​​‌‌​‌‌​​​‌‌​​‌​​​‌‌​​‌‌​​‌‌​‌‌​​​‌‌​‌​‌​​‌‌‌​​‌​​‌‌​​​‌​​‌‌​​‌​​​‌‌​​‌​‍
