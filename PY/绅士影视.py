import json
import re
import sys
import time
import threading

try:
    import requests
except Exception:
    requests = None

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"

SOURCES = [
    {"name": "非凡", "q": "HD", "kind": "direct", "parser": "",
     "api": "https://api.ffzyapi.com/api.php/provide/vod/from/ffm3u8?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://api.ffzyapi.com/api.php/provide/vod/from/ffm3u8?ac=detail&ids=[ID]"},
    {"name": "极速", "q": "HD", "kind": "direct", "parser": "",
     "api": "https://jszyapi.com/api.php/provide/vod/from/jsm3u8?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://jszyapi.com/api.php/provide/vod/from/jsm3u8?ac=detail&ids=[ID]"},
    {"name": "豪华", "q": "HD", "kind": "direct", "parser": "",
     "api": "https://hhzyapi.com/api.php/provide/vod/from/hhm3u8?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://hhzyapi.com/api.php/provide/vod/from/hhm3u8?ac=detail&ids=[ID]"},
    {"name": "速播", "q": "HD", "kind": "direct", "parser": "",
     "api": "https://subocaiji.com/api.php/provide/vod/from/subm3u8?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://subocaiji.com/api.php/provide/vod/from/subm3u8?ac=detail&ids=[ID]"},
    {"name": "天堂", "q": "HD", "kind": "direct", "parser": "",
     "api": "http://caiji.dyttzyapi.com/api.php/provide/vod/from/dyttm3u8?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "http://caiji.dyttzyapi.com/api.php/provide/vod/from/dyttm3u8?ac=detail&ids=[ID]"},
    {"name": "极影4K", "q": "4K", "kind": "parse", "parser": "175.24.181.180", "token": "JYY",
     "api": "http://101.201.171.207:802/api.php/provide/vod/?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "http://101.201.171.207:802/api.php/provide/vod/?ac=detail&ids=[ID]"},
    {"name": "绅士官采", "q": "HD", "kind": "parse", "parser": "", "token": "",
     "api": "https://cj.jusj.top/api.php/provide/vod/?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://cj.jusj.top/api.php/provide/vod/?ac=detail&ids=[ID]"},
    {"name": "绅4K·P", "q": "4K", "kind": "parse", "parser": "jx.meilinvps.com", "token": "",
     "api": "https://cms.meilinvps.com/api.php/provide/vod/?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://cms.meilinvps.com/api.php/provide/vod/?ac=detail&ids=[ID]"},
    {"name": "绅4K·C", "q": "4K", "kind": "parse", "parser": "123jx.vip", "token": "zijian",
     "api": "https://cms.123jx.vip/api.php/provide/vod/?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://cms.123jx.vip/api.php/provide/vod/?ac=detail&ids=[ID]"},
    {"name": "绅2K·P", "q": "2K", "kind": "parse", "parser": "tvapp.eu.org", "token": "co",
     "api": "http://down-hk1.1ljx.com:10800/c_api/co_cj/?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "http://down-hk1.1ljx.com:10800/c_api/co_cj/?ac=detail&ids=[ID]"},
    {"name": "绅4K·E", "q": "4K", "kind": "parse", "parser": "175.24.181.180", "token": "CO4K",
     "api": "https://co4k.1ljx.com:32010/c_api/co4k_cj?ac=detail&pg=[Page]&wd=[Query]",
     "api2": "https://co4k.1ljx.com:32010/c_api/co4k_cj?ac=detail&ids=[ID]"},
    {"name": "灵虎", "q": "HD", "kind": "parse", "parser": "", "token": "",
     "api": "https://app7.555618.xyz/api.php/getappapi.index/searchList",
     "api2": ""},
]

PARSERS = [
    {"name": "组豪富英", "api": "https://coffee-5c93e1f751eb.edge.tvapp.eu.org:31000/api/?key=6f8622b2-8402-43c9-ae29-0adaa292bc71&url="},
    {"name": "组4K·P", "api": "https://jx.meilinvps.com/api/?key=7dba17e4cc9b887faf7afaf9a20fd391&url="},
    {"name": "组4K·C", "api": "https://vip1.123jx.vip/api/?key=f60311e9bc7c1eac9dcaf5e336647b65&url="},
    {"name": "组C4K·E", "api": "http://175.24.181.180:5000/api/jiexi/common?Key=Dg3tqWmzSgcKGlZY2c&url="},
]

RANK = {"4K": 5, "2K": 4, "1080P": 3, "720P": 2, "HD": 1, "": 0}

STANDARD_TABS = [
    {"id": "movie", "name": "电影", "exact": ["电影", "电影片"], "first_subs": ["动作片", "动作", "喜剧片", "剧情片"]},
    {"id": "tv", "name": "电视剧", "exact": ["电视剧", "连续剧", "剧集"], "first_subs": ["国产剧", "国产", "欧美剧", "香港剧"]},
    {"id": "va", "name": "综艺", "exact": ["综艺", "综艺片", "大陆综艺"], "first_subs": ["大陆综艺", "港台综艺", "日韩综艺"]},
    {"id": "ct", "name": "动漫", "exact": ["动漫", "动漫片", "动画片"], "first_subs": ["国产动漫", "日本动漫", "欧美动漫", "番剧"]},
    {"id": "short", "name": "短剧", "exact": ["短剧", "微短剧", "爽剧"], "first_subs": ["微短剧", "古装短剧", "都市短剧"]},
    {"id": "doc", "name": "纪录片", "exact": ["纪录片", "记录片", "纪实"], "first_subs": ["历史", "自然", "人物"]}
]

SUB_CLASSES = {
    "movie": ["全部", "动作片", "喜剧片", "爱情片", "科幻片", "恐怖片", "剧情片", "战争片", "惊悚片", "犯罪片", "悬疑片", "动画片"],
    "tv": ["全部", "国产剧", "香港剧", "台湾剧", "韩国剧", "日本剧", "欧美剧", "泰国剧", "海外剧"],
    "va": ["全部", "大陆综艺", "港台综艺", "日韩综艺", "欧美综艺", "真人秀", "脱口秀"],
    "ct": ["全部", "国产动漫", "日本动漫", "欧美动漫", "海外动漫", "热血", "科幻", "恋爱"],
    "short": ["全部", "微短剧", "爽剧", "古装短剧", "都市短剧", "反转短剧"],
    "doc": ["全部", "历史", "自然", "地理", "人物", "军事", "探索"]
}

AREAS = ["", "大陆", "香港", "台湾", "美国", "韩国", "日本", "泰国", "英国", "法国", "其它"]
YEARS = ["", "2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2010-2016", "更早"]
SORTS = [
    {"n": "按更新", "v": "time"},
    {"n": "按热度", "v": "hits"},
    {"n": "按评分", "v": "score"},
]


def format_remarks(brand="分享者在线", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand


class Spider(object):

    def __init__(self):
        self.s = None
        self.cache = {}
        self.src_class_maps = {}
        self.tgGroup = "分享者在线"
        self.brandActor = "分享者在线"
        self.brandDirector = "分享者在线"
        self.brandName = "分享者在线"
        self.cardStyle = {"type": "rect", "ratio": 1.78}
        self.req_headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
        }

    def getDependence(self):
        return ""

    def init(self, extend=""):
        cfg = {}
        if extend:
            try:
                if isinstance(extend, dict):
                    cfg = extend
                elif isinstance(extend, str):
                    t = extend.strip()
                    if t.startswith("{"):
                        cfg = json.loads(t)
                    else:
                        try:
                            import ast
                            cfg = ast.literal_eval(t)
                        except Exception:
                            cfg = {}
            except Exception:
                cfg = {}
        if isinstance(cfg, dict):
            self._prefer = cfg.get("site") or ""
            self._sort = (cfg.get("sort") or "quality").lower()
        else:
            self._prefer = ""
            self._sort = "quality"
        self.s = self._session()
        return

    def _session(self):
        if requests is None:
            return None
        s = requests.Session()
        s.headers.update(self.req_headers)
        try:
            from requests.adapters import HTTPAdapter
            ad = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=1)
            s.mount("https://", ad)
            s.mount("http://", ad)
        except Exception:
            pass
        return s

    def _get(self, url, timeout=12, headers=None):
        h = dict(self.req_headers)
        if headers:
            h.update(headers)
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=timeout, verify=False)
                r.encoding = "utf-8"
                return r.text
            except Exception:
                return ""
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.read().decode("utf-8", "replace")
        except Exception:
            return ""

    def _json(self, url, timeout=12):
        txt = self._get(url, timeout)
        if not txt:
            return None
        try:
            return json.loads(txt)
        except Exception:
            m = re.search(r"\{.*\}", txt, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return None
            return None

    def _fill(self, tpl, page=1, query="", tid="", area="", year=""):
        u = tpl.replace("[Page]", str(page)).replace("[Query]", query or "").replace("[ID]", str(tid))
        if "[Query]" not in tpl and query:
            u += "&wd=" + query
        return u

    def _fix_pic(self, pic):
        p = (pic or "").strip()
        if not p:
            return "https://dummyimage.com/600x338/222222/ffffff.png&text=NO_COVER"
        if "puui.qpic.cn" in p:
            return "%s@Referer=https://v.qq.com/" % p
        if "hdslb.com" in p:
            return "%s@Referer=https://www.bilibili.com/" % p
        if "hitv.com" in p:
            return "%s@Referer=https://www.mgtv.com/" % p
        if "iqiyipic.com" in p:
            return "%s@Referer=https://www.iqiyi.com/" % p
        if "youku.com" in p:
            return "%s@Referer=https://www.youku.com/" % p
        return p

    def _load_source_classes(self, src):
        src_name = src["name"]
        if src_name in self.src_class_maps:
            return self.src_class_maps[src_name]

        u = src["api"].replace("[Page]", "1").replace("[Query]", "").replace("&wd=", "")
        u = u.replace("ac=detail", "ac=list")
        d = self._json(u, timeout=8)
        classes = d.get("class", []) if d else []

        tab_to_tid = {}
        tab_to_first_sub = {}
        sub_name_to_tid = {}

        if classes:
            for c in classes:
                cid = str(c.get("type_id") or "")
                cname = str(c.get("type_name") or "").strip()
                if not cid or not cname:
                    continue
                sub_name_to_tid[cname] = cid

                for tab in STANDARD_TABS:
                    if tab["id"] not in tab_to_tid:
                        if cname in tab["exact"]:
                            tab_to_tid[tab["id"]] = cid

            for tab in STANDARD_TABS:
                for cand_sub in tab["first_subs"]:
                    for cname, cid in sub_name_to_tid.items():
                        if cand_sub == cname or cand_sub in cname:
                            tab_to_first_sub[tab["id"]] = cid
                            break
                    if tab["id"] in tab_to_first_sub:
                        break

            for tab in STANDARD_TABS:
                if tab["id"] not in tab_to_tid:
                    if tab["id"] in tab_to_first_sub:
                        tab_to_tid[tab["id"]] = tab_to_first_sub[tab["id"]]

        self.src_class_maps[src_name] = (tab_to_tid, tab_to_first_sub, sub_name_to_tid)
        return tab_to_tid, tab_to_first_sub, sub_name_to_tid

    def _vod_dict(self, it, src):
        vid = it.get("vod_id")
        name = (it.get("vod_name") or "").strip()
        raw_pic = it.get("vod_pic") or it.get("vod_pic_thumb") or ""
        remarks = it.get("vod_remarks") or ""
        year = str(it.get("vod_year") or "").strip()

        meta = ("%s %s" % (year, remarks)).strip()
        clean_remarks = format_remarks(self.brandName, meta)

        return {
            "vod_id": "%s@%s" % (src["name"], vid),
            "vod_name": name,
            "vod_pic": self._fix_pic(raw_pic),
            "vod_remarks": clean_remarks,
            "vod_year": year,
            "type_name": it.get("type_name") or "",
            "style": self.cardStyle
        }

    def _split_groups(self, from_s, url_s):
        fs = [x.strip() for x in re.split(r"\$\$\$", from_s or "")]
        us = re.split(r"\$\$\$", url_s or "")
        out = []
        for i, u in enumerate(us):
            if not (u or "").strip():
                continue
            out.append((fs[i] if i < len(fs) else "", u.strip()))
        return out or [("", url_s or "")]

    def _tier(self, src, note, sample):
        best = src.get("q") or "HD"
        hay = "%s %s %s" % (note or "", sample or "", src.get("name") or "")
        up = hay.upper()
        for key, tag in (("4K", "4K"), ("2160P", "4K"), ("2K", "2K"), ("1440P", "2K"),
                         ("1080P", "1080P"), ("720P", "720P"), ("FHD", "1080P"), ("HD", "HD")):
            if key in up and RANK.get(tag, 0) > RANK.get(best, 0):
                best = tag
        return best

    def _is_direct(self, sample):
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", sample or "", re.I))

    def _norm(self, t):
        return re.sub(r"[\s\-_·:：,，.。()（）\[\]【】!！?？'\"]+", "", (t or "")).lower()

    def _score(self, want, got, wy="", gy=""):
        a, b = self._norm(want), self._norm(got)
        if not a or not b:
            return -1
        s = 0
        if a == b:
            s = 100
        elif b.startswith(a) or a.startswith(b):
            s = 85
        elif a in b or b in a:
            s = 70
        else:
            return -1
        if wy and gy:
            try:
                dy = abs(int(wy) - int(gy))
                if dy == 0:
                    s += 8
                elif dy <= 1:
                    s += 4
                else:
                    s -= 25
            except Exception:
                pass
        return s

    def _split_id(self, vid):
        if "@" in str(vid):
            a, b = str(vid).split("@", 1)
            for s in SOURCES:
                if s["name"] == a:
                    return s, b
            return SOURCES[0], b
        return SOURCES[0], vid

    def homeContent(self, filter=False):
        classes = [{"type_id": tab["id"], "type_name": tab["name"]} for tab in STANDARD_TABS]
        site_vals = [{"n": "默认最优", "v": ""}] + [{"n": s["name"], "v": s["name"]} for s in SOURCES]

        filters = {}
        for tab in STANDARD_TABS:
            tid = tab["id"]
            cat_filters = []

            sub_items = SUB_CLASSES.get(tid, ["全部"])
            cat_filters.append({
                "key": "sub",
                "name": "剧情",
                "init": "",
                "value": [{"n": item, "v": ("" if item == "全部" else item)} for item in sub_items]
            })

            cat_filters.append({"key": "site", "name": "线路", "init": "", "value": site_vals})
            cat_filters.append({"key": "area", "name": "地区", "init": "", "value": [{"n": a if a else "全部", "v": a} for a in AREAS]})
            cat_filters.append({"key": "year", "name": "年份", "init": "", "value": [{"n": y if y else "全部", "v": y} for y in YEARS]})
            cat_filters.append({"key": "by", "name": "排序", "init": "time", "value": SORTS})

            filters[tid] = cat_filters

        lst = self.homeVideoContent().get("list", [])
        return {"class": classes, "filters": filters, "list": lst}

    def homeVideoContent(self):
        key = "home"
        if key in self.cache and time.time() - self.cache[key][0] < 600:
            return self.cache[key][1]
        lst = []
        for src in self._ordered():
            d = self._json(self._fill(src["api"], 1, ""), timeout=12)
            if d and d.get("list"):
                for it in d["list"][:20]:
                    lst.append(self._vod_dict(it, src))
                break
        res = {"list": lst}
        self.cache[key] = (time.time(), res)
        return res

    def _ordered(self):
        if getattr(self, "_prefer", ""):
            for i, s in enumerate(SOURCES):
                if s["name"] == self._prefer:
                    return [s] + SOURCES[:i] + SOURCES[i + 1:]
        return SOURCES

    def categoryContent(self, tid, pg, filter=False, extend=None):
        ext = {}
        if extend:
            try:
                ext = json.loads(extend) if isinstance(extend, str) else dict(extend)
            except Exception:
                ext = {}

        try:
            page = int(pg)
        except Exception:
            page = 1

        src = self._ordered()[0]
        want_site = ext.get("site") or ""
        if want_site:
            for s in SOURCES:
                if s["name"] == want_site:
                    src = s
                    break

        tab_to_tid, tab_to_first_sub, sub_name_to_tid = self._load_source_classes(src)

        real_t = ""
        sub_name = ext.get("sub") or ""
        if sub_name:
            if sub_name in sub_name_to_tid:
                real_t = sub_name_to_tid[sub_name]
            else:
                for k, v in sub_name_to_tid.items():
                    if sub_name in k or k in sub_name:
                        real_t = v
                        break
        else:
            real_t = tab_to_tid.get(str(tid), "")

        def _fetch_page(target_t):
            u = self._fill(src["api"], page, "")
            if target_t:
                u += "&t=%s" % target_t
            elif sub_name:
                u += "&class=" + sub_name
            if ext.get("area"):
                u += "&area=" + str(ext["area"])
            if ext.get("year"):
                u += "&year=" + str(ext["year"])
            if ext.get("by"):
                u += "&by=" + str(ext["by"])
            return self._json(u, timeout=12)

        d = _fetch_page(real_t)

        if not (d and d.get("list")):
            fallback_sub_t = tab_to_first_sub.get(str(tid), "")
            if fallback_sub_t and fallback_sub_t != real_t:
                d = _fetch_page(fallback_sub_t)

        if not (d and d.get("list")):
            d = self._json(self._fill(src["api"], page, ""), timeout=12)

        lst = []
        if d and d.get("list"):
            for it in d["list"]:
                lst.append(self._vod_dict(it, src))

        try:
            pc = int(d.get("pagecount") or 1) if d else 1
        except Exception:
            pc = 1

        return {
            "page": page,
            "pagecount": max(pc, page),
            "limit": len(lst) or 20,
            "total": (d or {}).get("total") or len(lst),
            "list": lst
        }

    def _mk_lines(self, s, item, lines=None, score=100):
        if lines is None:
            lines = []
        pu = item.get("vod_play_url") or ""
        pf = item.get("vod_play_from") or ""
        for note, grp in self._split_groups(pf, pu):
            sample = ""
            m = re.search(r"\$([^$#]+)", grp)
            if m:
                sample = m.group(1)
            tier = self._tier(s, note, sample)
            direct = self._is_direct(sample)
            nm = "%s·%s" % (tier, s["name"])
            lines.append((nm, grp, tier, direct, score))
        return lines

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        src, real = self._split_id(vid)
        d = self._json(src["api2"].replace("[ID]", str(real)), timeout=15) if src.get("api2") else None
        if not d or not d.get("list"):
            return {"list": []}
        main = d["list"][0]
        name = main.get("vod_name") or ""
        year = str(main.get("vod_year") or "")
        lines = self._mk_lines(src, main, lines=None)
        lock = threading.Lock()
        got = []

        def worker(s):
            if s["name"] == src["name"] or not s.get("api2"):
                return
            try:
                r = self._json(self._fill(s["api"], 1, name), timeout=11)
                if not r or not r.get("list"):
                    return
                best, bs = None, 0
                for it in r["list"][:20]:
                    sc = self._score(name, it.get("vod_name") or "", year, str(it.get("vod_year") or ""))
                    if sc > bs:
                        bs, best = sc, it
                if best is None or bs < 70:
                    return
                det = self._json(s["api2"].replace("[ID]", str(best.get("vod_id"))), timeout=12)
                if not det or not det.get("list"):
                    return
                pu = det["list"][0].get("vod_play_url") or ""
                if not pu:
                    return
                with lock:
                    got.append((bs, s, pu, det["list"][0].get("vod_play_from") or ""))
            except Exception:
                return

        ths = []
        for s in SOURCES:
            t = threading.Thread(target=worker, args=(s,))
            t.daemon = True
            t.start()
            ths.append(t)
        for t in ths:
            t.join(timeout=13)
        for bs, s0, pu, pf in got:
            lines.extend(self._mk_lines(s0, {"vod_play_from": pf, "vod_play_url": pu}, lines=None, score=bs))

        mode = getattr(self, "_sort", "quality")
        if mode == "playable":
            lines.sort(key=lambda x: (0 if x[3] else 1, -RANK.get(x[2], 0), -x[4]))
        else:
            lines.sort(key=lambda x: (-RANK.get(x[2], 0), 0 if x[3] else 1, -x[4]))

        lines = lines[:9]
        froms, urls = [], []
        for nm, pu, tier, direct, score in lines:
            eps = []
            for seg in (pu or "").split("#"):
                seg = seg.strip()
                if not seg:
                    continue
                if "$" in seg:
                    t, u = seg.split("$", 1)
                else:
                    t, u = "正片", seg
                u = (u or "").strip()
                if not u:
                    continue
                if "#" in u:
                    u = u.replace("#", "%23")
                if "$" in u:
                    u = u.replace("$", "%24")
                eps.append("%s$%s@@%s" % (t.strip() or "正片", nm, u))
            if eps:
                froms.append(nm)
                urls.append("#".join(eps))

        raw_pic = main.get("vod_pic") or ""
        remarks = main.get("vod_remarks") or ""
        meta = ("%s %s" % (year, remarks)).strip()
        clean_remarks = format_remarks(self.brandName, meta)

        raw_content = re.sub(r"<[^>]+>", "", main.get("vod_content") or "").strip()
        full_content = (
            "【分享者在线: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "%s"
        ) % (self.tgGroup, raw_content)

        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._fix_pic(raw_pic),
            "vod_year": year,
            "vod_area": main.get("vod_area") or "",
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": clean_remarks,
            "vod_content": full_content,
            "type_name": main.get("type_name") or "",
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
            "style": self.cardStyle
        }
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        key = (key or "").strip()
        if not key:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}
        try:
            page = int(pg)
        except Exception:
            page = 1
        out = []
        lock = threading.Lock()

        def worker(src):
            try:
                d = self._json(self._fill(src["api"], page, key), timeout=12)
                if not d or not d.get("list"):
                    return
                got = [self._vod_dict(it, src) for it in d["list"]]
                with lock:
                    out.extend(got)
            except Exception:
                return

        ths = []
        for src in SOURCES:
            t = threading.Thread(target=worker, args=(src,))
            t.daemon = True
            t.start()
            ths.append(t)
        for t in ths:
            t.join(timeout=14)

        seen, uniq = set(), []
        for v in out:
            k = (v.get("vod_name") or "") + "|" + (v.get("vod_year") or "")
            if k in seen:
                continue
            seen.add(k)
            uniq.append(v)

        return {"page": page, "pagecount": page + 1, "limit": len(uniq), "total": len(uniq), "list": uniq}

    def _parse_url(self, token_url, prefer=""):
        cands = []
        if prefer:
            for p in PARSERS:
                if prefer in p["api"]:
                    cands.append(p)
        cands += [p for p in PARSERS if p not in cands]
        for p in cands:
            try:
                txt = self._get(p["api"] + token_url, timeout=15)
                if not txt:
                    continue
                for m in re.finditer(r'"(?:url|Url|URL|play_url|data)"\s*:\s*"([^"]+)"', txt):
                    v = m.group(1).replace("\\/", "/")
                    if re.search(r"\.(m3u8|mp4)", v, re.I):
                        return v
                m = re.search(r"https?://[^\"'\s<>]+?\.(?:m3u8|mp4)[^\"'\s<>]*", txt.replace("\\/", "/"))
                if m:
                    return m.group(0)
            except Exception:
                continue
        return ""

    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or "").strip()
        srcname = ""
        if "@@" in raw:
            srcname, raw = raw.split("@@", 1)
            srcname = srcname.strip()
        url = raw.strip()
        head = {"User-Agent": UA}
        try:
            head["Referer"] = "/".join(url.split("/")[:3]) + "/"
        except Exception:
            pass
        direct = bool(re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", url, re.I))
        if direct:
            return {"parse": 0, "jx": 0, "url": url, "header": head,
                    "format": "application/x-mpegURL" if ".m3u8" in url else "video/mp4"}
        prefer = ""
        for s in SOURCES:
            if s["name"] == srcname and s.get("parser"):
                prefer = s["parser"]
                break
        if not prefer:
            for tk, api in (("CO4K", "175.24.181.180"), ("co_egg", "tvapp.eu.org"),
                            ("co_", "tvapp.eu.org"), ("zijian", "123jx.vip"), ("JYY", "175.24.181.180")):
                if url.startswith(tk):
                    prefer = api
                    break
        real = self._parse_url(url, prefer)
        if real:
            return {"parse": 0, "jx": 0, "url": real, "header": head, "format": "application/x-mpegURL"}
        return {"parse": 1, "jx": 1, "url": url, "header": head, "format": "application/x-mpegURL"}

    def localProxy(self, param):
        try:
            raw = param
            if isinstance(param, str):
                try:
                    raw = json.loads(param)
                except Exception:
                    raw = param
            if isinstance(raw, dict):
                url = raw.get("url") or raw.get("u") or ""
            else:
                url = str(raw or "")
            if not url:
                return [404, "text/plain", ""]
            txt = self._get(url, timeout=15)
            if not txt:
                return [404, "text/plain", ""]
            return [200, "application/vnd.apple.mpegurl", txt]
        except Exception:
            return [404, "text/plain", ""]

    def isVideoFormat(self, url):
        u = str(url or "")
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv|ts)(\?|$)", u, re.I))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return ""

    def destroy(self):
        try:
            if self.s is not None:
                self.s.close()
        except Exception:
            pass
        self.cache = {}
        return