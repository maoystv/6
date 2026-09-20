# -*- coding: utf-8 -*-
"""
南瓜影院 Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: https://www.xxcgzh.com/

特性:
  - 基于HTML解析，支持首页、分类、详情、搜索、播放
  - 多线路播放解析，带线路缓存
  - 直链优先排序（m3u8/mp4）
  - 详情页重试机制
  - 首页推荐 + 分类浏览 + 全文搜索
  - 全链路短超时，SSL 禁验证
"""

import sys
import json
import re
import time
import urllib.parse

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

from bs4 import BeautifulSoup


# ============================================================
# 常量
# ============================================================

HOST = "https://www.xxcgzh.com"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

# 分类列表（从网站导航获取，也作为默认值）
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "综艺", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
    {"type_name": "短剧", "type_id": "33"},
]

# 子分类筛选器（用于客户端筛选）
CLASS_FILTERS = {
    "1": [  # 电影
        {"n": "全部", "v": ""},
        {"n": "动作片", "v": "动作片"},
        {"n": "喜剧片", "v": "喜剧片"},
        {"n": "爱情片", "v": "爱情片"},
        {"n": "科幻片", "v": "科幻片"},
        {"n": "恐怖片", "v": "恐怖片"},
        {"n": "剧情片", "v": "剧情片"},
        {"n": "战争片", "v": "战争片"},
        {"n": "动画片", "v": "动画片"},
    ],
    "2": [  # 电视剧
        {"n": "全部", "v": ""},
        {"n": "国产剧", "v": "国产剧"},
        {"n": "香港剧", "v": "香港剧"},
        {"n": "韩国剧", "v": "韩国剧"},
        {"n": "欧美剧", "v": "欧美剧"},
        {"n": "台湾剧", "v": "台湾剧"},
        {"n": "日本剧", "v": "日本剧"},
        {"n": "其它剧", "v": "其它剧"},
    ],
    "3": [  # 综艺
        {"n": "全部", "v": ""},
        {"n": "大陆综艺", "v": "大陆综艺"},
        {"n": "日韩综艺", "v": "日韩综艺"},
        {"n": "港台综艺", "v": "港台综艺"},
        {"n": "欧美综艺", "v": "欧美综艺"},
    ],
    "4": [  # 动漫
        {"n": "全部", "v": ""},
        {"n": "国产动漫", "v": "国产动漫"},
        {"n": "日韩动漫", "v": "日韩动漫"},
        {"n": "欧美动漫", "v": "欧美动漫"},
        {"n": "其它动漫", "v": "其它动漫"},
    ],
    "33": [  # 短剧
        {"n": "全部", "v": ""},
        {"n": "女频恋爱", "v": "女频恋爱"},
        {"n": "反转爽剧", "v": "反转爽剧"},
        {"n": "古装仙侠", "v": "古装仙侠"},
        {"n": "年代穿越", "v": "年代穿越"},
        {"n": "脑洞悬疑", "v": "脑洞悬疑"},
        {"n": "现代都市", "v": "现代都市"},
    ],
}

# 年份筛选器
YEAR_FILTER = {"key": "year", "name": "年份", "value": [
    {"n": "全部", "v": ""},
    {"n": "2026", "v": "2026"},
    {"n": "2025", "v": "2025"},
    {"n": "2024", "v": "2024"},
    {"n": "2023", "v": "2023"},
    {"n": "2022", "v": "2022"},
    {"n": "2021", "v": "2021"},
    {"n": "2020", "v": "2020"},
]}

# 构建各分类的完整筛选器
FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "类型", "value": CLASS_FILTERS.get(tid, [{"n": "全部", "v": ""}])},
        YEAR_FILTER,
    ]


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "南瓜影院"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        # 首页缓存（5 分钟）
        self._home_cache = []
        self._home_cache_time = 0
        
        # 播放地址缓存（避免重复解析）
        self._play_cache = {}
        self._play_cache_time = {}

        # 尝试从网站获取最新分类
        self._update_categories()

    def _update_categories(self):
        """从网站导航更新分类"""
        try:
            resp = self.fetch(HOST, headers=self.header, timeout=10)
            if not resp:
                return
            soup = BeautifulSoup(resp.text, 'html.parser')
            categories = []
            seen = set()
            # 从导航菜单获取
            for a in soup.select('.fed-navs-info .fed-menu-info a, .fed-pops-navbar .fed-pops-list a'):
                href = a.get('href', '')
                match = re.search(r'/type/(\d+)\.html', href)
                if not match:
                    continue
                tid = match.group(1)
                name = a.get_text(strip=True)
                if not name or tid in seen or name in ['首页', '导航', '留言']:
                    continue
                seen.add(tid)
                categories.append({"type_name": name, "type_id": tid})
            if categories:
                global CLASSES
                CLASSES = categories
                # 更新FILTERS
                for c in CLASSES:
                    tid = c["type_id"]
                    if tid not in FILTERS:
                        FILTERS[tid] = [
                            {"key": "class", "name": "类型", "value": [{"n": "全部", "v": ""}]},
                            YEAR_FILTER,
                        ]
        except Exception as e:
            print(f"[南瓜影院] 更新分类失败: {e}")

    # ===== 网络工具 =====
    def _rsp_text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode('utf-8', 'ignore')
            except Exception:
                return ""

    def _fetch_html(self, url, timeout=12, headers=None):
        """GET 请求返回 HTML 文本，异常返回空"""
        try:
            req_headers = self.header.copy()
            if headers:
                req_headers.update(headers)
            rsp = self.fetch(url, headers=req_headers, timeout=timeout)
            return self._rsp_text(rsp)
        except Exception as e:
            print(f"[南瓜影院] 请求失败: {url}, {e}")
            return ""

    def _fix_url(self, url):
        """修复URL"""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(HOST + "/", url)
        return url

    def _is_direct_media(self, url):
        """判断是否是直链媒体"""
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

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

    # ===== 解析视频列表 =====
    def _parse_video_list(self, html):
        """解析视频列表"""
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        for item in soup.select('.fed-list-item'):
            a = item.select_one('a.fed-list-pics')
            if not a:
                continue
            
            href = a.get('href', '')
            vod_id = re.search(r'/voddetail/(\d+)\.html', href)
            if not vod_id:
                continue
            
            vid = vod_id.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            
            # 标题
            title_elem = item.select_one('.fed-list-title')
            title = title_elem.get_text(strip=True) if title_elem else ''
            
            # 图片
            pic = a.get('data-original') or a.get('src', '')
            if not pic:
                img = a.select_one('img')
                if img:
                    pic = img.get('data-original') or img.get('src', '')
            pic = self._fix_url(pic)
            
            # 备注（集数/状态）
            remark = ''
            remark_elem = item.select_one('.fed-list-score')
            if remark_elem:
                remark = remark_elem.get_text(strip=True)
            
            results.append({
                "vod_id": str(vid),
                "vod_name": title.strip(),
                "vod_pic": pic,
                "vod_remarks": remark,
            })
        
        return results

    # ===== 解析播放列表 =====
    def _parse_play_list(self, html):
        """从详情页解析播放列表"""
        soup = BeautifulSoup(html, 'html.parser')
        play_from_list = []
        play_url_list = []
        
        # 查找播放列表 - 多种选择器
        play_blocks = []
        
        # 方法1: fed-play-item
        blocks1 = soup.select('.fed-play-item')
        if blocks1:
            play_blocks = blocks1
        else:
            # 方法2: 其他常见选择器
            blocks2 = soup.select('.play-list, .vod-play-list, .episode-list, .playlist')
            if blocks2:
                play_blocks = blocks2
            else:
                # 方法3: 查找所有包含播放链接的ul
                blocks3 = soup.select('ul[class*="play"], ul[class*="list"]')
                if blocks3:
                    play_blocks = blocks3
        
        if not play_blocks:
            # 兜底：查找所有播放链接
            all_links = soup.select('a[href*="/vodplay/"]')
            if all_links:
                episodes = []
                for a in all_links[:100]:
                    href = a.get('href', '')
                    if not href or 'javascript:' in href:
                        continue
                    ep_name = a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    episodes.append(f"{ep_name}${full_url}")
                if episodes:
                    play_from_list.append('默认线路')
                    play_url_list.append('#'.join(episodes))
            return play_from_list, play_url_list
        
        for idx, block in enumerate(play_blocks):
            # 线路名称
            line_name = f"线路{idx+1}"
            name_elem = block.select_one('.fed-play-title, .play-title, .line-name, .fed-part-eone')
            if name_elem:
                name_text = name_elem.get_text(strip=True)
                if name_text and len(name_text) < 20:
                    line_name = name_text
            
            episodes = []
            for a in block.select('a'):
                href = a.get('href', '')
                if not href or 'javascript:' in href or '#' in href:
                    continue
                ep_name = a.get_text(strip=True) or f"第{len(episodes)+1}集"
                # 过滤掉太长的名称（可能是描述而非集数）
                if len(ep_name) > 50:
                    ep_name = f"第{len(episodes)+1}集"
                full_url = self._fix_url(href)
                episodes.append(f"{ep_name}${full_url}")
            
            if episodes:
                play_from_list.append(line_name)
                play_url_list.append('#'.join(episodes))
        
        return play_from_list, play_url_list

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {
            "class": CLASSES,
            "filters": FILTERS,
        }

    def homeVideoContent(self):
        """首页推荐，带5分钟缓存"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache[:72]}
        
        html = self._fetch_html(HOST, timeout=10)
        videos = []
        if html:
            videos = self._parse_video_list(html)[:72]
        
        self._home_cache = videos
        self._home_cache_time = now
        return {"list": videos}

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
            
            # 构建URL
            if page == 1:
                url = f"{HOST}/type/{tid}.html"
            else:
                url = f"{HOST}/type/{tid}-{page}.html"
            
            html = self._fetch_html(url, timeout=12)
            if not html:
                return {"page": page, "pagecount": 1, "limit": 24, "total": 0, "list": []}
            
            raw_list = self._parse_video_list(html)
            
            # 获取总页数
            pagecount = page
            soup = BeautifulSoup(html, 'html.parser')
            pagination = soup.select('.fed-page a, .page a, .pagination a')
            if pagination:
                nums = []
                for a in pagination:
                    text = a.get_text(strip=True)
                    if text.isdigit():
                        nums.append(int(text))
                if nums:
                    pagecount = max(nums)
            
            return {
                "list": raw_list,
                "page": page,
                "pagecount": pagecount,
                "limit": 24,
                "total": len(raw_list) * pagecount,
            }
        except Exception as e:
            print(f"[南瓜影院] 分类获取失败: {e}")
            return {"page": 1, "pagecount": 1, "limit": 24, "total": 0, "list": []}

    # ============================================================
    # 详情页
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = str(ids[0])
        
        url = f"{HOST}/voddetail/{vod_id}.html"
        
        # 3次重试
        html = ""
        for attempt in range(3):
            html = self._fetch_html(url, timeout=12)
            if html and 'voddetail' in html:
                break
            time.sleep(0.5)
        
        if not html:
            return {"list": []}
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 标题
        title_elem = soup.select_one('.fed-deta-title, h1, .vod-title, .fed-part-eone')
        vod_name = title_elem.get_text(strip=True) if title_elem else vod_id
        
        # 图片
        vod_pic = ''
        pic_elem = soup.select_one('.fed-list-pics img, .detail-pic img, .vod-pic img, .fed-lazy')
        if pic_elem:
            vod_pic = pic_elem.get('data-original') or pic_elem.get('src', '')
            vod_pic = self._fix_url(vod_pic)
        
        # 简介
        vod_content = ''
        content_elem = soup.select_one('.fed-deta-content, .vod-content, .detail-content')
        if content_elem:
            vod_content = content_elem.get_text(' ', strip=True)[:500]
        
        # 演员
        vod_actor = ''
        actor_elem = soup.select_one('.fed-deta-actor, .vod-actor, .actor')
        if actor_elem:
            text = actor_elem.get_text(strip=True)
            match = re.search(r'主演[：:]\s*(.+)', text)
            if match:
                vod_actor = match.group(1).strip()
            else:
                vod_actor = text.replace('主演：', '').replace('演员：', '').strip()
        
        # 导演
        vod_director = ''
        director_elem = soup.select_one('.fed-deta-director, .vod-director, .director')
        if director_elem:
            text = director_elem.get_text(strip=True)
            match = re.search(r'导演[：:]\s*(.+)', text)
            if match:
                vod_director = match.group(1).strip()
            else:
                vod_director = text.replace('导演：', '').strip()
        
        # 年份
        vod_year = ''
        year_elem = soup.select_one('.fed-deta-year, .vod-year, .year')
        if year_elem:
            text = year_elem.get_text(strip=True)
            match = re.search(r'(\d{4})', text)
            if match:
                vod_year = match.group(1)
        
        # 类型
        vod_area = ''
        area_elem = soup.select_one('.fed-deta-area, .vod-area, .area')
        if area_elem:
            vod_area = area_elem.get_text(strip=True).replace('地区：', '').strip()
        
        # 解析播放列表
        play_from, play_url = self._parse_play_list(html)
        
        # 如果没解析到播放列表，尝试另一种方式
        if not play_url:
            # 直接找所有播放链接
            all_links = soup.select('a[href*="/vodplay/"]')
            if all_links:
                episodes = []
                for a in all_links[:100]:
                    href = a.get('href', '')
                    if not href or 'javascript:' in href:
                        continue
                    ep_name = a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    episodes.append(f"{ep_name}${full_url}")
                if episodes:
                    play_from = ['默认线路']
                    play_url = ['#'.join(episodes)]
        
        if not play_url:
            # 如果还是没有播放地址，返回一个默认播放链接
            default_play = soup.select_one('a[href*="/vodplay/"]')
            if default_play:
                href = default_play.get('href', '')
                full_url = self._fix_url(href)
                play_from = ['默认线路']
                play_url = [f"播放${full_url}"]
            else:
                return {"list": []}
        
        vod = {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "type_name": "",
            "vod_year": vod_year,
            "vod_area": vod_area,
            "vod_remarks": "",
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_content": vod_content,
            "vod_play_from": "$$$".join(play_from) if play_from else "默认源",
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
            
            encoded_key = urllib.parse.quote(key)
            if page == 1:
                url = f"{HOST}/search/{encoded_key}-------------.html"
            else:
                url = f"{HOST}/search/{encoded_key}----------{page}---.html"
            
            html = self._fetch_html(url, timeout=12)
            if not html:
                return {"list": []}
            
            videos = self._parse_video_list(html)
            return {"list": videos}
        except Exception as e:
            print(f"[南瓜影院] 搜索失败: {e}")
            return {"list": []}

    # ============================================================
    # 播放解析（核心修复）
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        """
        解析播放地址
        flag: 线路名称
        id: 播放URL
        """
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}
        
        play_url = str(id).replace("\\/", "/")
        print(f"[南瓜影院] 开始解析播放地址: {play_url}")
        
        # 检查缓存（5分钟有效）
        cache_key = play_url
        now = int(time.time())
        if cache_key in self._play_cache and now - self._play_cache_time.get(cache_key, 0) < 300:
            cached = self._play_cache[cache_key]
            print(f"[南瓜影院] 使用缓存: {cached}")
            return cached
        
        # 1. 直链媒体 → 直接播放
        if self._is_direct_media(play_url):
            result = self._build_media_response(play_url)
            self._play_cache[cache_key] = result
            self._play_cache_time[cache_key] = now
            return result
        
        # 2. 尝试从播放页面提取真实地址
        resolved = self._extract_play_url(play_url)
        
        if resolved and self._is_direct_media(resolved):
            print(f"[南瓜影院] 解析成功: {resolved}")
            result = self._build_media_response(resolved)
            self._play_cache[cache_key] = result
            self._play_cache_time[cache_key] = now
            return result
        
        # 3. 解析失败，返回原始URL让客户端尝试
        print(f"[南瓜影院] 解析失败，返回原始URL: {play_url}")
        result = {
            "parse": 1,  # 让客户端自己解析
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
        }
        self._play_cache[cache_key] = result
        self._play_cache_time[cache_key] = now
        return result

    def _build_media_response(self, url):
        """构建媒体播放响应"""
        is_m3u8 = ".m3u8" in url.lower()
        referer = self._extract_referer(url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": UA,
                "Referer": referer,
            },
            "format": "application/x-mpegURL" if is_m3u8 else "",
            "contentType": "application/x-mpegURL" if is_m3u8 else "",
        }

    def _extract_play_url(self, url, depth=0, max_depth=5):
        """递归解析播放地址"""
        if depth > max_depth:
            return None
        
        print(f"[南瓜影院] 深度 {depth}: 请求 {url}")
        
        # 如果是直链，直接返回
        if self._is_direct_media(url):
            return url
        
        # 请求播放页面
        headers = {
            "User-Agent": UA,
            "Referer": HOST + "/",
        }
        html = self._fetch_html(url, timeout=15, headers=headers)
        if not html:
            return None
        
        # 方法1: 查找 iframe 并递归
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if iframe_match:
            iframe_url = self._fix_url(iframe_match.group(1))
            if iframe_url and iframe_url != url:
                return self._extract_play_url(iframe_url, depth + 1, max_depth)
        
        # 方法2: 查找 player_aaaa 变量（南瓜影院常用）
        player_match = re.search(r'var\s+player_aaaa\s*=\s*({[^;]+});', html, re.DOTALL)
        if player_match:
            try:
                data = json.loads(player_match.group(1))
                # 优先使用 link
                link = data.get('link', '')
                if link:
                    next_url = self._fix_url(link)
                    if next_url and next_url != url:
                        return self._extract_play_url(next_url, depth + 1, max_depth)
                # 其次使用 url
                url_val = data.get('url', '')
                if url_val:
                    if self._is_direct_media(url_val):
                        return url_val
                    next_url = self._fix_url(url_val)
                    if next_url and next_url != url:
                        return self._extract_play_url(next_url, depth + 1, max_depth)
            except Exception as e:
                print(f"[南瓜影院] 解析 player_aaaa 失败: {e}")
        
        # 方法3: 查找 video 标签
        video_match = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if video_match:
            video_url = self._fix_url(video_match.group(1))
            if self._is_direct_media(video_url):
                return video_url
        
        # 方法4: 查找 source 标签
        source_match = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if source_match:
            source_url = self._fix_url(source_match.group(1))
            if self._is_direct_media(source_url):
                return source_url
        
        # 方法5: 直接查找 m3u8 链接
        m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html, re.I)
        if m3u8_match:
            return m3u8_match.group(1)
        
        # 方法6: 直接查找 mp4 链接
        mp4_match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html, re.I)
        if mp4_match:
            return mp4_match.group(1)
        
        # 方法7: 查找常见的播放变量
        var_patterns = [
            r'var\s+playurl\s*=\s*["\']([^"\']+)["\']',
            r'var\s+url\s*=\s*["\']([^"\']+)["\']',
            r'var\s+video\s*=\s*["\']([^"\']+)["\']',
            r'var\s+src\s*=\s*["\']([^"\']+)["\']',
            r'var\s+playUrl\s*=\s*["\']([^"\']+)["\']',
        ]
        for pattern in var_patterns:
            var_match = re.search(pattern, html, re.I)
            if var_match:
                var_url = var_match.group(1)
                if self._is_direct_media(var_url):
                    return var_url
                # 可能是相对路径
                full_url = self._fix_url(var_url)
                if full_url != var_url:
                    return self._extract_play_url(full_url, depth + 1, max_depth)
        
        # 方法8: 查找页面中的播放链接
        play_links = re.findall(r'<a[^>]+href=["\']([^"\']*\/vodplay\/[^"\']+)["\']', html, re.I)
        for pl in play_links[:3]:
            next_url = self._fix_url(pl)
            if next_url and next_url != url:
                result = self._extract_play_url(next_url, depth + 1, max_depth)
                if result:
                    return result
        
        return None

    # ===== 本地代理 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        self._play_cache.clear()
        self._play_cache_time.clear()

    def close(self):
        self.destroy()