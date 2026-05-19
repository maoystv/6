# coding=utf-8
"""
目标站: 天天影院  首页: https://www.baixiaotangtop.com
接口说明:
- homeContent  : 返回分类(class) + 筛选(filters) + 列表(可为空)
- homeVideoContent : 仅返回首页视频列表(list)
"""
import re
import sys
import json
import urllib.parse
from bs4 import BeautifulSoup

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):

    def init(self, extend=""):
        self.site_url = "https://www.baixiaotangtop.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.site_url,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        self.categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "36", "type_name": "短剧"}
        ]
        # 即使无筛选，也保留空结构，避免客户端报错
        self.filters = {"1":[],"2":[],"3":[],"4":[],"36":[]}

    def _ensure_init(self):
        if not hasattr(self, 'categories'):
            self.init()

    # ==================== 首页分类接口 ====================
    def homeContent(self, filter):
        self._ensure_init()
        # 这里可以返回空列表，分类和筛选由本接口负责
        return {"class": self.categories, "filters": self.filters, "list": []}

    # ==================== 首页视频列表接口 ====================
    def homeVideoContent(self):
        self._ensure_init()
        url = self.site_url + "/"
        resp = self.fetch(url, headers=self.headers)
        video_list = self.parseHtmlForList(resp.text) if resp else []
        # 仅返回 list，不包含 class 和 filters
        return {"list": video_list}

    # ==================== 分类列表 ====================
    def categoryContent(self, tid, pg, filter, extend):
        self._ensure_init()
        page = int(pg) if pg else 1
        url = f"{self.site_url}/vodshow/{tid}--------{page}---.html"
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        video_list = self.parseHtmlForList(resp.text)
        total_pages = self.parseHtmlForTotalPages(resp.text)
        return {
            "list": video_list,
            "page": page,
            "pagecount": total_pages,
            "limit": 20,
            "total": total_pages * 20
        }

    # ==================== 详情 ====================
    def detailContent(self, ids):
        self._ensure_init()
        if not ids:
            return {"list": []}
        vod_id = ids[0]
        resp = self.fetch(vod_id, headers=self.headers)
        if not resp:
            return {"list": []}
        detail = self.parseHtmlForDetail(resp.text, vod_id)
        return {"list": [detail]}

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg="1"):
        self._ensure_init()
        page = int(pg) if pg else 1
        url = f"{self.site_url}/vodsearch/{urllib.parse.quote(key)}----------{page}---.html"
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
        video_list = self.parseHtmlForList(resp.text)
        total_pages = self.parseHtmlForTotalPages(resp.text)
        return {
            "list": video_list,
            "page": page,
            "pagecount": total_pages,
            "limit": 20,
            "total": total_pages * 20
        }

    # ==================== 播放解析 ====================
    def playerContent(self, flag, id, vipFlags):
        self._ensure_init()
        resp = self.fetch(id, headers=self.headers)
        if not resp:
            return {"parse": 1, "url": id, "header": self.headers}
        html = resp.text
        m3u8 = ''
        player_match = re.search(r'var player_aaaa\s*=\s*(\{[\s\S]*?\})\s*(?:;|</script>)', html)
        if player_match:
            try:
                data = json.loads(player_match.group(1))
                if data.get('url'):
                    m3u8 = data['url'].replace('\\/', '/')
            except Exception:
                url_match = re.search(r'"url"\s*:\s*"([^"]*)"', player_match.group(1))
                if url_match:
                    m3u8 = url_match.group(1).replace('\\/', '/')
        if m3u8 and '.m3u8' in m3u8:
            return {"parse": 0, "url": m3u8, "header": self.headers}
        return {"parse": 1, "url": id, "header": self.headers, "extra": {"keyword": ".m3u8|.mp4"}}

    # ==================== 列表解析（正则 + BS4 兜底） ====================
    def parseHtmlForList(self, html):
        vods = []
        # 1. 原JS正则（若网站未改版）
        item_regex = re.compile(r'<li[^>]*class="[^"]*col-md-6[^"]*"[^>]*>([\s\S]*?)</li>', re.I)
        for m in item_regex.finditer(html):
            item = m.group(1)
            link_m = re.search(r'href="([^"]*\/voddetail\/[^"]*)"', item)
            if not link_m: continue
            href = link_m.group(1)
            title_m = re.search(r'title="([^"]*)"', item)
            name = title_m.group(1) if title_m else ''
            if not name:
                alt_m = re.search(r'alt="([^"]*)"', item)
                name = alt_m.group(1) if alt_m else ''
            img_m = re.search(r'data-original="([^"]*)"', item)
            pic = img_m.group(1) if img_m else ''
            remark_m = re.search(r'pic-text[^>]*>([^<]*)<', item)
            remark = remark_m.group(1).strip() if remark_m else ''
            if href and name:
                vods.append({"vod_id": self.site_url+href, "vod_name": name.strip(), "vod_pic": pic, "vod_remarks": remark})
        if vods:
            return vods

        # 2. 正则失效时，BS4 兜底（匹配 /voddetail/ 链接）
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href*="/voddetail/"]'):
            href = a.get('href', '').strip()
            if not href: continue
            name = a.get('title', '').strip()
            if not name:
                name = a.get_text(strip=True)
            if not name:
                parent = a.find_parent('li') or a.find_parent('div')
                if parent:
                    h_tag = parent.select_one('.title, .vodlist_title, h3, h4, strong')
                    if h_tag: name = h_tag.get_text(strip=True)
            pic = ''
            parent_li = a.find_parent('li') or a.find_parent('div', class_=re.compile('item|col'))
            if parent_li:
                img = parent_li.select_one('img')
                if img:
                    pic = img.get('data-original') or img.get('src') or ''
            remark = ''
            if parent_li:
                remark_tag = parent_li.select_one('.pic-text, .remarks, .score, .hint')
                if remark_tag: remark = remark_tag.get_text(strip=True)
            if href and name:
                vods.append({"vod_id": self.site_url+href, "vod_name": name, "vod_pic": pic, "vod_remarks": remark})
        return vods

    # ==================== 详情解析（正则 + BS4 兜底） ====================
    def parseHtmlForDetail(self, html, vod_id):
        # 正则尝试
        title_m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>[\s\S]*?<span[^>]*>([^<]*)</span>', html)
        vod_name = title_m.group(1) if title_m else ''
        img_m = re.search(r'<img[^>]*class="[^"]*lazyload[^"]*"[^>]*data-original="([^"]*)"', html)
        vod_pic = img_m.group(1) if img_m else ''
        desc_m = re.search(r'<div[^>]*id="desc"[^>]*>[\s\S]*?<div[^>]*class="[^"]*col-pd[^"]*"[^>]*>([\s\S]*?)</div>', html)
        vod_content = re.sub(r'<[^>]*>', '', desc_m.group(1)).strip() if desc_m else ''
        dir_m = re.search(r'导演[：:][\s\S]*?<a[^>]*>([^<]*)</a>', html)
        vod_director = dir_m.group(1) if dir_m else ''
        act_m = re.search(r'主演[：:][\s\S]*?<a[^>]*>([^<]*)</a>', html)
        vod_actor = act_m.group(1) if act_m else ''

        play_urls = []
        for m in re.finditer(r'<li[^>]*><a[^>]*href="([^"]*\/vodplay\/[^"]*)"[^>]*>([^<]*)</a></li>', html, re.I):
            if len(play_urls) >= 200: break
            play_urls.append(m.group(2) + '$' + self.site_url + m.group(1))

        # BS4 兜底
        if not vod_name or not play_urls:
            soup = BeautifulSoup(html, 'html.parser')
            if not vod_name:
                h1 = soup.select_one('h1.title, h1, .detail-title')
                if h1: vod_name = h1.get_text(strip=True)
            if not vod_pic:
                img = soup.select_one('img.lazyload[data-original]')
                if img: vod_pic = img['data-original']
            if not vod_content:
                desc_div = soup.select_one('#desc .col-pd, .detail-desc')
                if desc_div: vod_content = desc_div.get_text(strip=True)
            if not play_urls:
                for a in soup.select('a[href*="/vodplay/"]'):
                    if len(play_urls) >= 200: break
                    play_urls.append(a.get_text(strip=True) + '$' + self.site_url + a['href'])

        vod_play_from = '云播资源' if play_urls else ''
        vod_play_url = '#'.join(play_urls)
        return {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content,
            "vod_director": vod_director,
            "vod_actor": vod_actor,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url
        }

    # ==================== 总页数解析 ====================
    def parseHtmlForTotalPages(self, html):
        m = re.search(r'href="[^"]*--------(\d+)---\.html"[^>]*>尾页</', html)
        if m: return int(m.group(1))
        # 备用
        soup = BeautifulSoup(html, 'html.parser')
        max_page = 1
        for a in soup.select('.pagination a, .page-link, .pagelink a'):
            try:
                n = int(a.get_text(strip=True))
                if n > max_page: max_page = n
            except: pass
        return max_page