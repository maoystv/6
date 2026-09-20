# coding=utf-8
"""
咕噜电影 (guludyw.com) 爬虫
适配影视仓 / OK影视 / TVBox 等空壳影视APP

接口规范：
- homeContent(filter)       → {"class":[...], "filters":{...}}
- homeVideoContent()        → {"list":[...]}
- categoryContent(tid,pg,filter,extend) → {"list":[...], "page":..., "pagecount":..., ...}
- detailContent(ids)        → {"list":[{...}]}
- playerContent(flag,id,vipFlags) → {"parse":..., "url":..., "header":...}
- searchContent(key,quick,pg) → {"list":[...], ...}
"""

import re
import json
import urllib.parse
import requests
from lxml import etree
from base.spider import Spider


class Spider(Spider):
    def __init__(self):
        self.name = "咕噜电影"
        self.host = "https://www.guludyw.com"
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host
        }
        # 分类映射
        self._cat_map = {
            "1": "1",     # 电影
            "2": "2",     # 电视剧
            "3": "3",     # 动漫
            "4": "4",     # 综艺
            "10": "10",   # 短剧
        }

    def getName(self):
        return self.name

    def init(self, extend=''):
        pass

    def _get(self, url, params=None, allow_redirects=True):
        """发送GET请求"""
        try:
            r = requests.get(url, headers=self.header, params=params,
                             timeout=20, allow_redirects=allow_redirects)
            r.encoding = 'utf-8'
            return r.text
        except Exception as e:
            print(f"请求异常: {e}")
            return ''

    def _fix_url(self, url):
        """修复相对URL为绝对URL"""
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    def _parse_video_card(self, card):
        """解析单个视频卡片 - 兼容多种页面结构"""
        try:
            # 查找链接 - 多种选择器
            a = None
            for selector in [
                './/a[contains(@href, "vod-read")]',
                './/a[contains(@href, "/read/")]',
                './/a[contains(@class, "stui-vodlist__thumb")]',
                './/a[contains(@class, "pic")]',
                './/a'
            ]:
                result = card.xpath(selector)
                if result:
                    a = result[0]
                    break
            
            if not a:
                return None
            
            href = a.get('href', '')
            if not href:
                return None

            # 提取 vod_id
            vod_id = href
            if vod_id.startswith('http'):
                vod_id = vod_id.replace(self.host, '')
            
            # 从href中提取数字ID
            m = re.search(r'vod-read-id-(\d+)', href)
            if m:
                vod_id = '/index.php/vod-read-id-' + m.group(1) + '.html'

            # 图片 - 多种属性
            img = a.xpath('.//img')
            vod_pic = ''
            if img:
                vod_pic = img[0].get('data-original') or img[0].get('data-src') or img[0].get('src', '')
                if vod_pic and not vod_pic.startswith('http'):
                    vod_pic = self.host + vod_pic

            # 标题 - 多种来源
            vod_name = ''
            # 从p标签中的a
            title_a = card.xpath('.//p//a/text()')
            if title_a:
                vod_name = title_a[0].strip()
            # 从a标签的title属性
            if not vod_name:
                title_attr = a.get('title', '')
                if title_attr:
                    vod_name = title_attr.strip()
            # 从h3/h4标签
            if not vod_name:
                title_h = card.xpath('.//h3/text() | .//h4/text()')
                if title_h:
                    vod_name = title_h[0].strip()
            # 从图片alt
            if not vod_name:
                img_alt = a.xpath('.//img/@alt')
                if img_alt:
                    vod_name = img_alt[0].strip()

            # 备注（更新状态/集数）
            vod_remarks = ''
            remarks_selectors = [
                './/span[contains(@class, "remarks")]/text()',
                './/span[contains(@class, "text-red")]/text()',
                './/span[contains(@class, "bg")]/text()',
                './/em/text()',
                './/span/text()'
            ]
            for selector in remarks_selectors:
                remarks = card.xpath(selector)
                if remarks:
                    vod_remarks = remarks[0].strip()
                    if vod_remarks:
                        break

            if not vod_name:
                return None

            return {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks
            }
        except Exception as e:
            print(f"解析卡片异常: {e}")
            return None

    def _parse_video_list(self, html):
        """解析视频列表页"""
        videos = []
        try:
            root = etree.HTML(html)
            
            # 多种选择器匹配视频卡片
            cards = []
            selectors = [
                '//li[contains(@class, "list_yy")]',
                '//div[contains(@class, "stui-vodlist__item")]',
                '//div[contains(@class, "stui-vodlist__box")]',
                '//ul[contains(@class, "stui-vodlist")]/li',
                '//div[contains(@class, "vodlist")]//li',
                '//div[contains(@class, "list")]//li'
            ]
            
            for selector in selectors:
                cards = root.xpath(selector)
                if cards:
                    break
            
            # 如果还是没找到，尝试更宽泛的匹配
            if not cards:
                cards = root.xpath('//li[.//img and .//a]')
            
            print(f"找到 {len(cards)} 个卡片")
            
            for card in cards:
                try:
                    video = self._parse_video_card(card)
                    if video and video.get("vod_name"):
                        videos.append(video)
                except Exception as e:
                    print(f"解析卡片失败: {e}")
                    continue
                    
        except Exception as e:
            print(f"解析列表异常: {e}")
        
        print(f"解析到 {len(videos)} 个视频")
        return videos

    def _parse_pagecount(self, html):
        """解析总页数"""
        total = 1
        try:
            root = etree.HTML(html)
            # 查找分页链接
            page_links = root.xpath('//div[contains(@class, "page")]//a')
            if not page_links:
                page_links = root.xpath('//div[contains(@class, "pages")]//a')
            if not page_links:
                page_links = root.xpath('//a[contains(@href, "-p-")]')
            
            max_page = 0
            for link in page_links:
                href = link.get('href', '')
                m = re.search(r'-p-(\d+)\.html', href)
                if m:
                    max_page = max(max_page, int(m.group(1)))
            
            # 检查是否有"下一页"
            has_next = False
            for link in page_links:
                text = link.text or ''
                if '下一页' in text or '»' in text:
                    has_next = True
                    break
            
            if has_next and max_page > 0:
                total = max_page + 1
            elif max_page > 0:
                total = max_page
            else:
                total = 1
                
        except Exception as e:
            print(f"解析分页异常: {e}")
        return total

    # ==================== 首页接口 ====================

    def homeContent(self, filter):
        result = {"class": []}
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "动漫", "type_id": "3"},
            {"type_name": "综艺", "type_id": "4"},
            {"type_name": "短剧", "type_id": "10"},
        ]
        result["class"] = classes

        # 筛选器
        genre_vals = [
            {"n": "全部", "v": ""},
            {"n": "动作", "v": "动作"},
            {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"},
            {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"},
            {"n": "悬疑", "v": "悬疑"},
            {"n": "惊悚", "v": "惊悚"},
            {"n": "恐怖", "v": "恐怖"},
            {"n": "犯罪", "v": "犯罪"},
            {"n": "警匪", "v": "警匪"},
            {"n": "冒险", "v": "冒险"},
            {"n": "奇幻", "v": "奇幻"},
            {"n": "武侠", "v": "武侠"},
            {"n": "枪战", "v": "枪战"},
            {"n": "动画", "v": "动画"},
            {"n": "战争", "v": "战争"},
            {"n": "经典", "v": "经典"},
            {"n": "青春", "v": "青春"},
            {"n": "文艺", "v": "文艺"},
        ]

        order_vals = [
            {"n": "按人气", "v": "hits"},
            {"n": "按时间", "v": "time"},
        ]

        filters = {}
        for c in classes:
            if c['type_id'] == '10':  # 短剧只有排序
                filters[c['type_id']] = [
                    {"key": "order", "name": "排序", "value": order_vals}
                ]
            else:
                filters[c['type_id']] = [
                    {"key": "genre", "name": "类型", "value": genre_vals},
                    {"key": "order", "name": "排序", "value": order_vals}
                ]
        result["filters"] = filters
        return result

    def homeVideoContent(self):
        """首页推荐列表"""
        videos = []
        try:
            html = self._get(self.host + '/')
            if html:
                videos = self._parse_video_list(html)
        except Exception as e:
            print(f"首页获取异常: {e}")
        return {"list": videos[:30]}

    # ==================== 分类接口 ====================

    def categoryContent(self, tid, pg, filter, extend):
        """分类内容列表"""
        videos = []
        try:
            pg = int(pg) if pg else 1
            
            # 解析筛选参数
            if isinstance(extend, str) and extend:
                try:
                    extend = json.loads(extend)
                except Exception:
                    extend = {}
            elif not extend:
                extend = {}

            genre = extend.get('genre', '')
            order = extend.get('order', 'hits')

            # 构建分类URL
            url = self._build_category_url(tid, pg, genre, order)
            print(f"分类URL: {url}")
            
            html = self._get(url)
            if html:
                videos = self._parse_video_list(html)
                total_pages = self._parse_pagecount(html)
            else:
                total_pages = 1

            return {
                'list': videos,
                'page': pg,
                'pagecount': total_pages,
                'limit': len(videos),
                'total': total_pages * len(videos) if videos else 0
            }
        except Exception as e:
            print(f"分类获取异常: {e}")
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

    def _build_category_url(self, tid, pg, genre='', order='hits'):
        """构建分类URL"""
        # 如果有类型筛选
        if genre:
            url = f"{self.host}/index.php/vod-type-id-{tid}-type-{genre}-area--year--star--state--order-{order}.html"
            if pg > 1:
                url = url.replace('.html', f'-p-{pg}.html')
            return url
        
        # 按时间排序
        if order == 'time':
            url = f"{self.host}/index.php/vod-type-id-{tid}-type--area--year--star--state--order-time.html"
            if pg > 1:
                url = url.replace('.html', f'-p-{pg}.html')
            return url
        
        # 默认按人气排序
        url = f"{self.host}/index.php/vod-show-id-{tid}"
        if pg > 1:
            url += f'-p-{pg}'
        url += '.html'
        return url

    # ==================== 详情接口 ====================

    def detailContent(self, ids):
        """获取视频详情"""
        try:
            vod_id = ids[0]

            # 构建详情URL
            detail_url = self._build_detail_url(vod_id)
            print(f"详情URL: {detail_url}")
            
            html = self._get(detail_url)
            if not html:
                return {'list': []}

            root = etree.HTML(html)

            # ---- 标题 ----
            vod_name = ''
            title_selectors = [
                '//h1/text()',
                '//div[contains(@class, "nei_con")]//h1/text()',
                '//div[contains(@class, "title")]//h1/text()'
            ]
            for selector in title_selectors:
                title = root.xpath(selector)
                if title:
                    vod_name = title[0].strip()
                    break

            # ---- 封面 ----
            vod_pic = ''
            pic_selectors = [
                '//div[contains(@class, "text_img")]//img',
                '//div[contains(@class, "nei_con")]//img',
                '//div[contains(@class, "pic")]//img'
            ]
            for selector in pic_selectors:
                pic_img = root.xpath(selector)
                if pic_img:
                    vod_pic = pic_img[0].get('data-original') or pic_img[0].get('data-src') or pic_img[0].get('src', '')
                    if vod_pic:
                        break

            # ---- 信息字段 ----
            vod_year = vod_area = vod_class = vod_actor = vod_director = vod_remarks = vod_content = ''

            # 解析信息段落
            info_selectors = [
                '//div[contains(@class, "text-sinfo")]/p',
                '//div[contains(@class, "text")]/p',
                '//div[contains(@class, "nei_con")]/p',
                '//div[contains(@class, "info")]/p'
            ]
            
            info_ps = []
            for selector in info_selectors:
                info_ps = root.xpath(selector)
                if info_ps:
                    break

            for p in info_ps:
                text = ''.join(p.xpath('.//text()')).strip()
                
                if '主演' in text:
                    actors = p.xpath('.//a/text()')
                    if actors:
                        vod_actor = ','.join([a.strip() for a in actors if a.strip()])
                elif '导演' in text:
                    directors = p.xpath('.//a/text()')
                    if directors:
                        vod_director = ','.join([d.strip() for d in directors if d.strip()])
                elif '类型' in text:
                    types = p.xpath('.//a/text()')
                    if types:
                        vod_class = ','.join([t.strip() for t in types if t.strip()])
                elif '地区' in text:
                    vod_area = re.sub(r'地区[:：]', '', text).strip()
                elif '年份' in text or '上映' in text:
                    m = re.search(r'(\d{4})', text)
                    if m:
                        vod_year = m.group(1)
                elif '状态' in text:
                    vod_remarks = re.sub(r'状态[:：]', '', text).strip()

            # ---- 简介 ----
            desc_selectors = [
                '//div[contains(@class, "text_content")]//li/text()',
                '//div[contains(@class, "text_content")]/text()',
                '//div[contains(@class, "desc")]/text()'
            ]
            for selector in desc_selectors:
                desc = root.xpath(selector)
                if desc:
                    vod_content = '\n'.join([d.strip() for d in desc if d.strip()])
                    if vod_content:
                        break

            # ---- 播放列表 ----
            vod_play_from = []
            vod_play_url = []

            # 方法1: .show_1 块
            show_blocks = root.xpath('//div[contains(@class, "show_1")]')
            for block in show_blocks:
                line_name = block.xpath('.//h2/text()')
                line_name = line_name[0].strip() if line_name else f'播放源{len(vod_play_from) + 1}'
                
                play_list = []
                for a in block.xpath('.//a[contains(@href, "vod-play")]'):
                    ep_name = a.text or ''
                    ep_name = ep_name.strip()
                    href = a.get('href', '')
                    if ep_name and href:
                        if href.startswith('/'):
                            href = self.host + href
                        play_list.append(f"{ep_name}${href}")
                
                if play_list:
                    vod_play_from.append(line_name)
                    vod_play_url.append("#".join(play_list))

            # 方法2: #play_online
            if not vod_play_from:
                play_online = root.xpath('//*[@id="play_online"]')
                if play_online:
                    play_list = []
                    for a in play_online[0].xpath('.//a[contains(@href, "vod-play")]'):
                        ep_name = a.text or ''
                        ep_name = ep_name.strip()
                        href = a.get('href', '')
                        if ep_name and href:
                            if href.startswith('/'):
                                href = self.host + href
                            play_list.append(f"{ep_name}${href}")
                    if play_list:
                        vod_play_from.append('默认线路')
                        vod_play_url.append("#".join(play_list))

            # 方法3: 全局查找
            if not vod_play_from:
                play_list = []
                seen = set()
                for a in root.xpath('//a[contains(@href, "vod-play")]'):
                    ep_name = a.text or ''
                    ep_name = ep_name.strip()
                    href = a.get('href', '')
                    if ep_name and href and href not in seen:
                        seen.add(href)
                        if href.startswith('/'):
                            href = self.host + href
                        play_list.append(f"{ep_name}${href}")
                if play_list:
                    vod_play_from.append('默认线路')
                    vod_play_url.append("#".join(play_list))

            if not vod_play_from:
                vod_play_from.append('默认线路')
                vod_play_url.append('')

            detail = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_remarks": vod_remarks,
                "vod_year": vod_year,
                "vod_area": vod_area,
                "vod_content": vod_content,
                "vod_class": vod_class,
                "vod_play_from": "$$$".join(vod_play_from),
                "vod_play_url": "$$$".join(vod_play_url)
            }
            return {'list': [detail]}
        except Exception as e:
            print(f"详情解析异常: {e}")
            return {'list': []}

    def _build_detail_url(self, vod_id):
        """构建详情URL"""
        if vod_id.startswith('http'):
            return vod_id
        if vod_id.startswith('/'):
            return self.host + vod_id
        
        # 提取数字ID
        m = re.search(r'(\d+)', vod_id)
        if m:
            num_id = m.group(1)
            return f"{self.host}/index.php/vod-read-id-{num_id}.html"
        
        return self.host + vod_id

    # ==================== 播放接口 ====================

    def _base64_decode(self, s):
        """Base64解码"""
        try:
            import base64
            s = s.replace('-', '+').replace('_', '/')
            while len(s) % 4:
                s += '='
            return base64.b64decode(s).decode('utf-8')
        except Exception:
            return ''

    def playerContent(self, flag, id, vipFlags):
        """解析播放地址"""
        try:
            play_url = id

            # 如果是直链
            if any(play_url.lower().endswith(ext) for ext in ['.m3u8', '.mp4', '.flv', '.ts']):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": play_url,
                    "header": json.dumps({
                        "User-Agent": self.header['User-Agent'],
                        "Referer": self.host + '/'
                    })
                }

            # 统一ID格式
            if '?s=' in play_url:
                m = re.search(r'\?s=/vod-play-id-([^-]+-sid-\d+-pid-\d+)', play_url)
                if m:
                    play_url = f"{self.host}/index.php/vod-play-id-{m.group(1)}.html"

            if not play_url.startswith('http'):
                play_url = self.host + play_url

            html = self._get(play_url)
            if not html:
                return {"parse": 0, "playUrl": "", "url": ""}

            # 提取iframe
            iframe_patterns = [
                r'<iframe[^>]*src=["\']([^"\']+player[^"\']+)["\']',
                r'<iframe[^>]*src=["\']([^"\']+fengniaotv[^"\']+)["\']',
                r'<iframe[^>]*src=["\']([^"\']+)["\']'
            ]

            for pattern in iframe_patterns:
                m = re.search(pattern, html, re.I)
                if m:
                    iframe_url = m.group(1)
                    if iframe_url.startswith('//'):
                        iframe_url = 'https:' + iframe_url

                    # 提取mu参数
                    mu_match = re.search(r'[?&]mu=([^&]+)', iframe_url)
                    if mu_match:
                        mu = mu_match.group(1)
                        decoded_url = self._base64_decode(mu)
                        if decoded_url and any(ext in decoded_url.lower() for ext in ['.m3u8', '.mp4']):
                            return {
                                "parse": 0,
                                "playUrl": "",
                                "url": decoded_url,
                                "header": json.dumps({
                                    "User-Agent": self.header['User-Agent'],
                                    "Referer": self.host + '/'
                                })
                            }

                    # 交给播放器嗅探
                    return {
                        "parse": 1,
                        "playUrl": "",
                        "url": iframe_url,
                        "header": json.dumps({
                            "User-Agent": self.header['User-Agent'],
                            "Referer": self.host + '/'
                        })
                    }

            # 直接匹配m3u8
            m3u8_match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)
            if m3u8_match:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": m3u8_match.group(1),
                    "header": json.dumps({
                        "User-Agent": self.header['User-Agent'],
                        "Referer": self.host + '/'
                    })
                }

            # 直接匹配mp4
            mp4_match = re.search(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html)
            if mp4_match:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": mp4_match.group(1),
                    "header": json.dumps({
                        "User-Agent": self.header['User-Agent'],
                        "Referer": self.host + '/'
                    })
                }

            # 交给播放器处理
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": json.dumps(self.header)
            }
        except Exception as e:
            print(f"播放解析异常: {e}")
            return {"parse": 0, "playUrl": "", "url": ""}

    # ==================== 搜索接口（修复版） ====================

    def searchContent(self, key, quick, pg='1'):
        """搜索 - 修复搜索结果显示问题"""
        videos = []
        try:
            pg = int(pg) if pg else 1
            key = key.strip() if key else ''

            if not key:
                return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

            # 构建搜索URL - 使用标准的搜索路径
            if pg == 1:
                url = f"{self.host}/index.php/vod-search-wd-{urllib.parse.quote(key)}.html"
            else:
                url = f"{self.host}/index.php/vod-search-pg-{pg}-wd-{urllib.parse.quote(key)}.html"

            print(f"搜索URL: {url}")
            html = self._get(url)
            
            if not html:
                print("搜索页面获取失败")
                return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

            # 使用与首页/分类相同的解析逻辑
            videos = self._parse_search_result(html)
            
            # 解析总页数
            total_pages = self._parse_pagecount(html)
            if total_pages < 1:
                total_pages = 1

            print(f"搜索到 {len(videos)} 个结果，共 {total_pages} 页")

            return {
                'list': videos,
                'page': pg,
                'pagecount': total_pages,
                'limit': len(videos),
                'total': len(videos) if pg >= total_pages else len(videos) * total_pages
            }
        except Exception as e:
            print(f"搜索异常: {e}")
            import traceback
            traceback.print_exc()
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

    def _parse_search_result(self, html):
        """专门解析搜索结果页面"""
        videos = []
        try:
            root = etree.HTML(html)
            
            # 搜索结果通常在 list_search 类的 li 中
            cards = []
            
            # 尝试多种选择器
            selectors = [
                '//li[contains(@class, "list_search")]',
                '//li[contains(@class, "search")]',
                '//div[contains(@class, "search-list")]//li',
                '//ul[contains(@class, "search")]/li',
                '//div[contains(@class, "list")]//li[.//a[contains(@href, "vod-read")]]',
                '//li[.//a[contains(@href, "vod-read")]]'
            ]
            
            for selector in selectors:
                cards = root.xpath(selector)
                if cards:
                    print(f"使用选择器 '{selector}' 找到 {len(cards)} 个卡片")
                    break
            
            # 如果还没找到，尝试更宽泛的匹配
            if not cards:
                cards = root.xpath('//li[.//img and .//a[contains(@href, "vod-read")]]')
                if cards:
                    print(f"使用备用选择器找到 {len(cards)} 个卡片")
            
            print(f"搜索结果找到 {len(cards)} 个卡片")
            
            for card in cards:
                try:
                    # 查找链接
                    a = card.xpath('.//a[contains(@href, "vod-read")]')
                    if not a:
                        # 尝试查找任何包含vod-read的链接
                        a = card.xpath('.//a[contains(@href, "vod-read")]')
                    if not a:
                        continue
                    a = a[0]
                    href = a.get('href', '')
                    if not href:
                        continue

                    # 提取 vod_id
                    vod_id = href
                    if vod_id.startswith('http'):
                        vod_id = vod_id.replace(self.host, '')
                    
                    m = re.search(r'vod-read-id-(\d+)', href)
                    if m:
                        vod_id = '/index.php/vod-read-id-' + m.group(1) + '.html'

                    # 标题 - 多种方式获取
                    vod_name = ''
                    
                    # 方式1: 从a标签的title属性
                    title_attr = a.get('title', '')
                    if title_attr:
                        vod_name = title_attr.strip()
                    
                    # 方式2: 从专门的标题元素
                    if not vod_name:
                        title_elem = card.xpath('.//div[contains(@class, "vod-intro-title")]/text()')
                        if title_elem:
                            vod_name = title_elem[0].strip()
                    
                    # 方式3: 从图片alt
                    if not vod_name:
                        img = card.xpath('.//img')
                        if img:
                            vod_name = img[0].get('alt', '').strip()
                    
                    # 方式4: 从a标签文本
                    if not vod_name:
                        a_text = ''.join(a.xpath('.//text()')).strip()
                        if a_text:
                            vod_name = a_text

                    if not vod_name:
                        continue

                    # 图片
                    vod_pic = ''
                    img = card.xpath('.//img')
                    if img:
                        vod_pic = img[0].get('data-original') or img[0].get('data-src') or img[0].get('src', '')
                        if vod_pic and not vod_pic.startswith('http'):
                            if vod_pic.startswith('//'):
                                vod_pic = 'https:' + vod_pic
                            elif not vod_pic.startswith('/'):
                                vod_pic = '/' + vod_pic
                            vod_pic = self.host + vod_pic

                    # 备注（更新状态/集数）
                    vod_remarks = ''
                    remarks_selectors = [
                        './/div[contains(@class, "vod-intro-time")]/text()',
                        './/span[contains(@class, "remarks")]/text()',
                        './/span[contains(@class, "text-red")]/text()',
                        './/span[contains(@class, "bg")]/text()',
                        './/em/text()'
                    ]
                    for selector in remarks_selectors:
                        remarks = card.xpath(selector)
                        if remarks:
                            vod_remarks = remarks[0].strip()
                            if vod_remarks:
                                break

                    videos.append({
                        "vod_id": vod_id,
                        "vod_name": vod_name,
                        "vod_pic": vod_pic,
                        "vod_remarks": vod_remarks
                    })
                except Exception as e:
                    print(f"解析搜索卡片失败: {e}")
                    continue
                    
        except Exception as e:
            print(f"解析搜索结果异常: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"解析到 {len(videos)} 个搜索结果")
        return videos

    # ==================== 辅助方法 ====================

    def isVideoFormat(self, url):
        """判断URL是否为直链视频格式"""
        return any(url.lower().endswith(fmt) for fmt in ['.m3u8', '.mp4', '.flv', '.ts', '.mkv', '.avi', '.mov'])

    def manualVideoCheck(self):
        pass

    def localProxy(self, params):
        return None

    def destroy(self):
        pass