#!/usr/bin/python
# -*- coding: utf-8 -*-
import re, json, requests
from urllib.parse import quote
try:
    from lxml import etree
except Exception:
    etree = None
from base.spider import Spider


class Spider(Spider):
    def getName(self): return "袋鼠影视"

    def init(self, extend=""):
        self.host = "https://dsystv.com"
        try: ext = json.loads(extend) if str(extend).strip().startswith("{") else {}
        except Exception: ext = {}
        if ext.get("host"): self.host = ext["host"].rstrip("/")
        self.headers = {"User-Agent": ext.get("ua", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"), "Referer": self.host + "/", "Accept-Language": "zh-CN,zh;q=0.9"}
        self.categories = [{"type_id": "1", "type_name": "电影"}, {"type_id": "2", "type_name": "电视剧"}, {"type_id": "3", "type_name": "综艺"}, {"type_id": "4", "type_name": "动漫"}, {"type_id": "44", "type_name": "短剧"}]
        self.subs = {"1": [["全部", "1"], ["动作片", "5"], ["喜剧片", "10"], ["科幻片", "7"], ["恐怖片", "8"], ["战争片", "9"], ["动画片", "41"], ["剧情片", "12"], ["爱情片", "6"], ["纪录片", "11"]],
                     "2": [["全部", "2"], ["国产剧", "13"], ["港台剧", "14"], ["欧美剧", "15"], ["日韩剧", "16"], ["海外剧", "42"]]}
        self.orders = [["默认", ""], ["最近更新", "time"], ["总排行", "hit"], ["月排行", "monthhit"], ["周排行", "weekhit"], ["豆瓣评分", "douban"]]

    def _fix(self, u):
        if not u: return ""
        if u.startswith("//"): return "https:" + u
        if u.startswith("/"): return self.host + u
        return u

    def _get(self, path):
        url = path if path.startswith("http") else self.host + path
        try:
            r = requests.get(url, headers=self.headers, timeout=15); r.encoding = "utf-8"
            if r.status_code >= 400: print("[WARN] status=%s url=%s" % (r.status_code, url))
            return r.text
        except requests.exceptions.Timeout: print("[ERROR] 请求超时: %s" % url)
        except requests.exceptions.ConnectionError: print("[ERROR] 连接错误: %s" % url)
        except Exception as e: print("[ERROR] 请求失败: %s, %s" % (url, str(e)))
        return None

    def _post(self, path, data):
        try:
            r = requests.post(self.host + path, data=data, headers=self.headers, timeout=15); r.encoding = "utf-8"; return r.text
        except Exception as e: print("[ERROR] POST失败: %s, %s" % (path, str(e))); return None

    def _parse_list(self, html):
        if not html: return []
        if etree is None:
            print("[WARN] lxml 不可用，降级为正则解析")
            out, seen = [], set()
            for vid, title in re.findall(r'href="[^"]*?/movie/index(\d+)\.html"[^>]*?title="([^"]*)"', html):
                if vid in seen: continue
                seen.add(vid); out.append({"vod_id": vid, "vod_name": title, "vod_pic": ""})
            return out
        tree = etree.HTML(html); results, seen = [], set()
        items = tree.xpath('//a[contains(@class,"videopic") and contains(@href,"/movie/index")]') + tree.xpath('//div[contains(@class,"item")]//a[contains(@href,"/movie/index") and .//img]') + tree.xpath('//a[contains(@href,"/movie/index") and .//img]')
        for it in items:
            try:
                m = re.search(r'/movie/index(\d+)\.html', it.get("href", ""))
                if not m or m.group(1) in seen: continue
                name = (it.get("title") or "".join(it.xpath('.//img/@alt')[:1])).strip()
                if not name: continue
                seen.add(m.group(1))
                pic = ""
                for at in ("data-original", "data-src", "data-echo", "data-lazy", "src"):
                    cand = it.xpath('.//img/@%s' % at)
                    if cand and "load.gif" not in cand[0] and "loading" not in cand[0]: pic = cand[0]; break
                note = " ".join(x.strip() for x in it.xpath('.//span//text()') if x.strip())
                results.append({"vod_id": m.group(1), "vod_name": name, "vod_pic": self._fix(pic), "vod_remarks": note[:40]})
            except Exception: continue
        return results

    def _parse_playlist(self, tree, vid):
        groups = {}
        for a in tree.xpath('//a[contains(@href,"/play/")]'):
            m = re.search(r'/play/%s-(\d+)-(\d+)\.html' % vid, a.get("href", ""))
            if not m: continue
            s, e = int(m.group(1)), int(m.group(2))
            nm = (a.get("title") or "".join(a.xpath('.//text()'))).strip()
            groups.setdefault(s, {}).setdefault(e, [])
            if nm: groups[s][e].append(nm)
        froms, urls = [], []
        for s in sorted(groups):
            tab = tree.xpath('//a[@href="#playlist%d"]' % (s + 1))
            name = ((tab[0].get("title") or "".join(tab[0].xpath('.//text()')).strip().split(" ")[0]) if tab else "").strip() or "线路%d" % (s + 1)
            eps = []
            for e in sorted(groups[s]):
                cand = [x for x in groups[s][e] if re.search(r'第.*[集期话]|^\d+$|HD|BD|TS|正片|预告|番外|国语|粤语|中字', x)]
                nm = (cand[0] if cand else "第%d集" % (e + 1)).replace("$", "").replace("#", "")
                eps.append("%s$/play/%s-%d-%d.html" % (nm, vid, s, e))
            froms.append(name); urls.append("#".join(eps))
        return froms, urls

    def _meta(self, tree, prop):
        v = tree.xpath('//meta[@property="%s"]/@content' % prop) or tree.xpath('//meta[@name="%s"]/@content' % prop)
        return v[0].strip() if v else ""

    def _people(self, tree, label):
        v = tree.xpath('//*[contains(text(),"%s")]//a[contains(@href,"searchword=")]/text()' % label)
        return " ".join(x.strip() for x in v[:30] if x.strip())

    def _field(self, text, key):
        m = re.search(r'%s\s*[:：]\s*([^\n]{1,120})' % key, text)
        return m.group(1).strip(" \u3000|/") if m else ""

    def homeContent(self, filter):
        fl = {}
        for c in self.categories:
            f = []
            if c["type_id"] in self.subs:
                f.append({"key": "tid", "name": "类型", "value": [{"n": s[0], "v": s[1]} for s in self.subs[c["type_id"]]]})
            f.append({"key": "order", "name": "排序", "value": [{"n": o[0], "v": o[1]} for o in self.orders]})
            fl[c["type_id"]] = f
        return {"class": self.categories, "list": self._parse_list(self._get("/index.html")), "filters": fl}

    def homeVideoContent(self): return {"list": self._parse_list(self._get("/index.html"))}

    def categoryContent(self, tid, pg, filter, extend):
        pg = str(pg or "1"); ex = extend or {}
        real = ex.get("tid") or tid
        url = "/search.php?searchtype=5&tid=%s&page=%s" % (real, pg)
        if ex.get("order"): url += "&order=" + ex["order"]
        lst = self._parse_list(self._get(url))
        return {"page": int(pg), "pagecount": int(pg) + 1 if lst else int(pg), "limit": 24, "total": 999999, "list": lst}

    def searchContent(self, key, quick, pg="1"):
        pg = str(pg or "1")
        lst = self._parse_list(self._get("/search.php?searchword=%s&page=%s" % (quote(key), pg)))
        if not lst and pg == "1":
            lst = self._parse_list(self._post("/search.php", {"searchword": key, "searchtype": "1"}))
        return {"list": lst, "page": int(pg)}

    def detailContent(self, ids):
        vid = re.sub(r'\D', '', str(ids[0]))
        html = self._get("/movie/index%s.html" % vid)
        if not html or etree is None: return {"list": []}
        tree = etree.HTML(html)
        text = re.sub(r'[ \t\u3000]+', ' ', "\n".join(x.strip() for x in tree.xpath('//text()') if x.strip()))
        froms, urls = self._parse_playlist(tree, vid)
        vod = {"vod_id": vid,
               "vod_name": (self._meta(tree, "og:title") or "".join(tree.xpath('//h1//text()'))).strip().split("《")[-1].split("》")[0] or "".join(tree.xpath('//h1//text()')).strip(),
               "vod_pic": self._fix(self._meta(tree, "og:image")),
               "vod_year": self._field(text, "年份"), "vod_area": self._field(text, "地区"),
               "type_name": self._field(text, "类型"), "vod_lang": self._field(text, "语言"),
               "vod_actor": self._people(tree, "主演") or self._field(text, "主演"),
               "vod_director": self._people(tree, "导演") or self._field(text, "导演"),
               "vod_remarks": self._field(text, "豆瓣"),
               "vod_content": self._meta(tree, "og:description") or self._meta(tree, "description"),
               "vod_play_from": "$$$".join(froms), "vod_play_url": "$$$".join(urls)}
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        pid = id if id.startswith("http") else self._fix(id)
        html = self._get(pid) or ""
        url = ""
        for p in [r'var\s+now\s*=\s*["\']([^"\']+)["\']', r'var\s+player_\w+\s*=\s*(\{.*?\})\s*[;<]', r'"url"\s*:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"', r'url:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', r'(https?://[^\s"\'\\]+\.(?:m3u8|mp4)[^\s"\'\\]*)']:
            m = re.search(p, html.replace("\\/", "/"), re.S)
            if not m: continue
            val = m.group(1)
            if val.startswith("{"):
                try: val = json.loads(val).get("url", "")
                except Exception:
                    m2 = re.search(r'"(https?://[^"]+\.(?:m3u8|mp4)[^"]*)"', val); val = m2.group(1) if m2 else ""
            if val and not val.startswith("#"): url = self._fix(val); break
        if not url: return {"parse": 1, "url": pid, "header": self.headers}
        return {"parse": 0, "url": url, "header": {"User-Agent": self.headers["User-Agent"], "Referer": self.host + "/"}}
