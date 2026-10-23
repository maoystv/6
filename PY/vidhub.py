#!/usr/bin/env python
#coding=utf-8
"""
VidHub视频库 爬虫脚本
目标站点: https://vidhub2.top/
框架: maccms V10 + mxone 模板 (HTML解析, API已关闭)
适配: 影视仓 / OK影视 / TVBox

功能:
  1. 分类 - 父分类4个 + 子分类完整筛选器
  2. 分页 - 12段伪静态URL分页
  3. 详情 - 标题/又名/年份/地区/类型/导演/主演/简介/评分/备注
  4. 播放 - iframe播放器页面 var config JSON 提取m3u8
  5. 搜索 - /index.php/ajax/suggest?mid=1&wd= JSON接口
  6. 封面 - img data-src 属性
"""

import re
import json
from html import unescape
from urllib.parse import quote
from base.spider import Spider


class Spider(Spider):

    HOST = "https://vidhub2.top"

    # 父分类
    CATEGORIES = [
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "连续剧"},
        {"type_id": "3", "type_name": "综艺"},
        {"type_id": "4", "type_name": "动漫"},
    ]

    # 类型标签 (class 筛选器值, 从网站筛选页面提取)
    CLASS_TAGS = {
        "1": ["动作", "喜剧", "爱情", "科幻", "恐怖", "剧情", "战争", "警匪",
              "犯罪", "动画", "奇幻", "武侠", "冒险", "枪战", "悬疑", "惊悚",
              "经典", "青春", "文艺", "微电影", "古装", "历史", "运动", "农村",
              "儿童", "网络电影"],
        "2": ["剧情", "动作", "喜剧", "奇幻", "战争", "犯罪", "经典", "网剧",
              "青春偶像", "古装", "历史", "家庭", "情景", "商战", "乡村"],
        "3": ["情感", "播报", "旅游", "曲艺", "求职", "游戏互动", "生活",
              "纪实", "美食", "访谈", "财经", "选秀", "音乐"],
        "4": ["亲子", "冒险", "动作", "励志", "原创", "少女", "少年", "情感",
              "战争", "推理", "搞笑", "机战", "校园", "热血", "益智", "社会",
              "科幻", "萝莉", "运动", "其他"],
    }

    # ========================
    #  框架接口
    # ========================

    def getName(self):
        return "VidHub视频库"

    def isVideo(self):
        return False

    def init(self, extend=""):
        self.extend = extend
        self.host = self.HOST
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;"
                      "q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
        }

    # ========================
    #  工具方法
    # ========================

    def _get(self, path):
        """请求页面并返回 HTML 文本"""
        url = self.host + path if path.startswith("/") else path
        r = self.fetch(url, headers=self.headers, timeout=15, verify=False)
        return r.text

    def _build_vodshow_url(self, tid, page, extend):
        """
        构建 12 段分类列表 URL
        格式: /vodshow/{tid}-{area}-{by}-{class}-{lang}-{letter}----{page}---{year}.html
        段位:  1     2      3    4      5      6     7 8   9     10 11   12
        """
        ext = extend or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        area = quote(ext.get("area", ""), safe="")
        by   = ext.get("by", "")
        cls  = quote(ext.get("class", ""), safe="")
        lang = quote(ext.get("lang", ""), safe="")
        year = ext.get("year", "")
        parts = [str(tid), area, by, cls, lang, "", "", "", str(page), "", "", year]
        return "/vodshow/" + "-".join(parts) + ".html"

    def _parse_card(self, item):
        """解析单个 div.module-item 卡片, 返回 vod dict 或 None"""
        links = item.xpath('.//a[contains(@href,"/voddetail/")]')
        if not links:
            return None
        href = links[0].get("href", "")
        m = re.search(r'/voddetail/(\d+)\.html', href)
        if not m:
            return None
        vid = m.group(1)

        # 标题: 优先 title 属性, 其次内部文本
        title = ""
        for link in links:
            t = (link.get("title") or "").strip()
            if t:
                title = t
                break
        if not title:
            for link in links:
                texts = link.xpath('.//text()')
                for txt in texts:
                    txt = txt.strip()
                    if txt:
                        title = txt
                        break
                if title:
                    break

        # 封面
        pic = item.xpath('.//img/@data-src')
        if not pic:
            pic = item.xpath('.//img/@src')
        pic = pic[0].strip() if pic else ""

        # 备注
        remark = item.xpath('.//div[contains(@class,"module-item-text")]//text()')
        remark = remark[0].strip() if remark else ""

        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": remark,
        }

    def _parse_list_page(self, html):
        """解析列表页, 返回 (videos, page_count)"""
        videos = []
        seen = set()

        # 总页数 (从尾页链接提取, 兼容筛选后的 URL 和带年份的页码)
        page_count = 0
        pages = re.findall(r'/vodshow/\d+-[^"]*?-(\d+)---[^"]*?\.html', html)
        if pages:
            page_count = max(int(p) for p in pages)

        tree = self.html(html)
        items = tree.xpath('//div[@class="module-item"]')
        for item in items:
            vod = self._parse_card(item)
            if vod and vod["vod_id"] not in seen:
                seen.add(vod["vod_id"])
                videos.append(vod)

        return videos, page_count

    def _extract_meta(self, html, label):
        """
        从详情页 HTML 中提取 <span>标签：</span> 后面的值
        支持多个 <a> 链接或纯文本
        """
        pat = re.escape(label) + r'\s*</span>'
        m = re.search(pat, html)
        if not m:
            return ""
        rest = html[m.end():]
        # 截取到下一个 <span>...：</span> 或 </div>
        end_m = re.search(r'<span[^>]*>[^<]*\uff1a\s*</span>|</div>', rest)
        if end_m:
            rest = rest[:end_m.start()]
        # 优先提取 <a> 标签文本
        texts = re.findall(r'<a[^>]*>([^<]+)</a>', rest)
        if texts:
            return ",".join([t.strip() for t in texts])
        # 降级提取纯文本
        text = re.sub(r'<[^>]+>', '', rest).strip()
        if text and text != "/":
            return text
        return ""

    # ========================
    #  首页
    # ========================

    def homeContent(self, filter=False):
        result = {}
        result["class"] = [
            {"type_id": c["type_id"], "type_name": c["type_name"]}
            for c in self.CATEGORIES
        ]
        result["filters"] = self._all_filters() if filter else {}
        # 首页推荐: 电影最新
        try:
            html = self._get("/vodshow/1--------1---.html")
            videos, _ = self._parse_list_page(html)
            result["list"] = videos
        except Exception:
            result["list"] = []
        result["parse"] = 0
        result["jx"] = 0
        return result

    def homeVideoContent(self):
        try:
            html = self._get("/vodshow/1--------1---.html")
            videos, _ = self._parse_list_page(html)
        except Exception:
            videos = []
        return {"list": videos, "parse": 0, "jx": 0}

    # ========================
    #  分类列表 + 分页
    # ========================

    def categoryContent(self, tid, pg, filter=False, extend=''):
        page = int(pg) if str(pg).isdigit() else 1
        url = self._build_vodshow_url(tid, page, extend)
        try:
            html = self._get(url)
            videos, page_count = self._parse_list_page(html)
        except Exception:
            videos, page_count = [], 0
        return {
            "list": videos,
            "page": page,
            "pagecount": page_count if page_count else 999,
            "limit": len(videos),
            "total": page_count * len(videos) if page_count else 9999,
            "parse": 0,
            "jx": 0,
        }

    # ========================
    #  筛选器
    # ========================

    def _all_filters(self):
        filters = {}
        for cat in self.CATEGORIES:
            tid = cat["type_id"]
            filters[tid] = self._default_filters(tid)
        return filters

    def _default_filters(self, tid):
        filters = []

        # 类型 (class 标签, 值为类型名)
        class_opts = [{"n": "全部", "v": ""}]
        for tag in self.CLASS_TAGS.get(tid, []):
            class_opts.append({"n": tag, "v": tag})
        if len(class_opts) > 1:
            filters.append({"key": "class", "name": "类型", "value": class_opts})

        # 地区
        filters.append({"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "中国大陆", "v": "中国大陆"},
            {"n": "中国香港", "v": "中国香港"},
            {"n": "中国台湾", "v": "中国台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
            {"n": "英国", "v": "英国"},
            {"n": "法国", "v": "法国"},
            {"n": "德国", "v": "德国"},
            {"n": "泰国", "v": "泰国"},
            {"n": "印度", "v": "印度"},
            {"n": "其它", "v": "其它"},
        ]})

        # 语言
        filters.append({"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "汉语普通话", "v": "汉语普通话"},
            {"n": "闽南语", "v": "闽南语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "法语", "v": "法语"},
            {"n": "德语", "v": "德语"},
            {"n": "其它", "v": "其它"},
        ]})

        # 年份
        filters.append({"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
            {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"},
            {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"},
            {"n": "2013", "v": "2013"},
            {"n": "2012", "v": "2012"},
            {"n": "2011", "v": "2011"},
            {"n": "2010", "v": "2010"},
            {"n": "更早", "v": "2009"},
        ]})

        # 排序
        filters.append({"key": "by", "name": "排序", "value": [
            {"n": "最新", "v": "time"},
            {"n": "最热", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]})

        return filters

    # ========================
    #  详情页
    # ========================

    def detailContent(self, ids):
        # 兼容 list/tuple/str 传入, 正则提取数字 ID
        raw = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        raw = str(raw)
        m = re.search(r'(\d+)', raw)
        vod_id = m.group(1) if m else raw
        try:
            html = self._get("/voddetail/" + vod_id + ".html")
        except Exception:
            return {"list": [], "parse": 0, "jx": 0}
        tree = self.html(html)

        # ---- 标题 ----
        title = tree.xpath('//h1[contains(@class,"page-title")]/text()')
        title = title[0].strip() if title else ""

        # ---- 又名 ----
        subtitle = tree.xpath('//h2[contains(@class,"video-subtitle")]/text()')
        subtitle = subtitle[0].strip() if subtitle else ""

        # ---- 元数据 (正则提取) ----
        director = self._extract_meta(html, "\u5bfc\u6f14\uff1a")   # 导演：
        actor    = self._extract_meta(html, "\u4e3b\u6f14\uff1a")   # 主演：
        release  = self._extract_meta(html, "\u4e0a\u6620\uff1a")   # 上映：
        remark   = self._extract_meta(html, "\u5907\u6ce8\uff1a")   # 备注：
        score    = self._extract_meta(html, "\u8bc4\u5206\uff1a")   # 评分：

        # 年份: 从上映信息提取 4 位数字
        year = ""
        if release:
            m = re.search(r'(\d{4})', release)
            if m:
                year = m.group(1)

        # 地区: 从 info_links 中匹配
        area = ""
        info_links = tree.xpath('//div[contains(@class,"video-info")]//a/text()')
        for link in info_links:
            link = link.strip()
            if any(k in link for k in [
                "\u4e2d\u56fd", "\u7f8e\u56fd", "\u65e5\u672c",
                "\u97e9\u56fd", "\u82f1\u56fd", "\u6cd5\u56fd",
                "\u5fb7\u56fd", "\u6cf0\u56fd", "\u5370\u5ea6",
            ]):  # 中国 美国 日本 韩国 英国 法国 德国 泰国 印度
                area = link
                break

        # 如果年份仍未找到, 从 info_links 提取
        if not year:
            for link in info_links:
                link = link.strip()
                if re.match(r'^\d{4}$', link):
                    year = link
                    break

        # 类型: 从 video-info 下的 /vodshow/ 链接提取 (排除年份和地区)
        type_name = ""
        type_as = tree.xpath(
            '//div[contains(@class,"video-info")]//a[contains(@href,"/vodshow/")]'
        )
        types = []
        for a in type_as:
            text = (a.text or "").strip()
            if not text:
                continue
            if re.match(r'^\d{4}$', text):
                continue  # 跳过年份
            if "," in text or "\uff0c" in text:
                continue  # 跳过地区(含逗号)
            if any(k in text for k in [
                "\u4e2d\u56fd", "\u7f8e\u56fd", "\u65e5\u672c",
                "\u97e9\u56fd", "\u82f1\u56fd", "\u6cd5\u56fd",
                "\u5fb7\u56fd", "\u6cf0\u56fd", "\u5370\u5ea6",
                "\u9999\u6e2f", "\u53f0\u6e7e", "\u5176\u4ed6",
            ]):  # 中国 美国 日本 韩国 英国 法国 德国 泰国 印度 香港 台湾 其他
                continue
            types.append(text)
        type_name = ",".join(types)

        # ---- 简介 ----
        content = ""
        m = re.search(
            r'\u5267\u60c5\uff1a\s*</span>\s*([\s\S]*?)(?:</div>|</p>|\s*\u6536\u8d77)',
            html  # 剧情： ... 收起
        )
        if m:
            content = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not content:
            m = re.search(r'class="[^"]*content[^"]*"[^>]*>([\s\S]*?)</p>', html)
            if m:
                content = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        # ---- 封面 ----
        pic = ""
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if m:
            pic = m.group(1)
        if not pic:
            pics = tree.xpath('//div[contains(@class,"module-item-pic")]//img/@data-src')
            if pics:
                pic = pics[0]
        if not pic:
            pics = tree.xpath('//div[contains(@class,"video-pic")]//img/@src')
            if pics:
                pic = pics[0]

        # ---- 播放源 ----
        # 播放源名称 (data-dropdown-value)
        play_from_names = re.findall(r'data-dropdown-value="([^"]+)"', html)

        # 播放链接: /vodplay/{vodId}-{source}-{episode}.html
        play_matches = re.findall(
            r'href="(/vodplay/(\d+)-(\d+)-(\d+)\.html)"[^>]*>([\s\S]*?)</a>',
            html
        )

        # 按播放源分组, 去重
        sources = {}
        for full_path, vid, src_idx, ep_idx, inner in play_matches:
            text = re.sub(r'<[^>]+>', '', inner).strip()
            if not text or text == "\u7acb\u5373\u64ad\u653e":  # 跳过"立即播放"
                continue
            if src_idx not in sources:
                sources[src_idx] = {}
            if ep_idx not in sources[src_idx]:
                sources[src_idx][ep_idx] = (
                    text, "%s-%s-%s" % (vid, src_idx, ep_idx)
                )

        # 构建 vod_play_from / vod_play_url
        play_from_list = []
        play_url_list = []
        for src_idx in sorted(sources.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            eps = sources[src_idx]
            if not eps:
                continue
            src_num = int(src_idx) if src_idx.isdigit() else 1
            if src_num <= len(play_from_names):
                name = play_from_names[src_num - 1]
            else:
                name = "\u7ebf\u8def%d" % src_num  # 线路N
            play_from_list.append(name)
            ep_strs = []
            for ep_idx in sorted(eps.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                ep_text, ep_id = eps[ep_idx]
                ep_strs.append("%s$%s" % (ep_text, ep_id))
            play_url_list.append("#".join(ep_strs))

        vod_play_from = "$$$".join(play_from_list)
        vod_play_url  = "$$$".join(play_url_list)

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": actor,
            "vod_director": director,
            "vod_area": area,
            "vod_year": year,
            "vod_remarks": remark,
            "vod_score": score,
            "vod_content": content,
            "type_name": type_name,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
        }

        return {"list": [vod], "parse": 0, "jx": 0}

    # ========================
    #  搜索
    # ========================

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        if page > 1:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 0, "total": 0, "parse": 0, "jx": 0}

        # /vodsearch/ 伪静态被验证码拦截
        # /index.php?m=vod-search 返回首页内容, 非搜索结果
        # 使用 AJAX suggest JSON 接口: /index.php/ajax/suggest?mid=1&wd=
        path = "/index.php/ajax/suggest?mid=1&wd=" + quote(key)
        try:
            r = self.fetch(
                self.host + path, headers=self.headers, timeout=15, verify=False
            )
        except Exception:
            return {"list": [], "page": 1, "pagecount": 1,
                    "limit": 0, "total": 0, "parse": 0, "jx": 0}

        videos = []
        try:
            data = json.loads(r.text)
            for item in data.get("list", []):
                videos.append({
                    "vod_id": str(item.get("id", "")),
                    "vod_name": item.get("name", ""),
                    "vod_pic": item.get("pic", ""),
                    "vod_remarks": "",
                })
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "list": videos,
            "page": 1,
            "pagecount": 1,
            "limit": len(videos),
            "total": len(videos),
            "parse": 0,
            "jx": 0,
        }

    def searchContentPage(self, key, quick, page):
        """搜索分页接口, 委托给 searchContent"""
        return self.searchContent(key, quick, str(page))

    # ========================
    #  播放
    # ========================

    def playerContent(self, flag, id, vipFlags=None):
        """
        提取播放地址流程:
        1. 请求播放页 /vodplay/{id}.html
        2. 提取 iframe src (/player/?u=...&i=...&s=...)
        3. 请求 iframe 页面, 提取 var config = {...} JSON
        4. 从 config.url 获取 m3u8 地址

        id 格式: {vodId}-{sourceIdx}-{episodeIdx}
        """
        play_page_url = self.host + "/vodplay/" + id + ".html"

        # Step 1: 获取播放页
        try:
            html = self._get("/vodplay/" + id + ".html")
        except Exception:
            return {"parse": 1, "playUrl": "", "url": play_page_url,
                    "header": {}, "jx": 0}

        # Step 2: 提取 iframe src
        iframe_m = re.search(r'<iframe[^>]*src="(/player/\?[^"]+)"', html)
        if not iframe_m:
            iframe_m = re.search(r'src="(/player/\?[^"]+)"', html)

        if iframe_m:
            iframe_path = unescape(iframe_m.group(1))

            # Step 3: 请求 iframe 播放器页面
            try:
                iframe_html = self._get(iframe_path)
            except Exception:
                iframe_html = ""

            # Step 4: 提取 var config JSON
            if iframe_html:
                pos = iframe_html.find('var config')
                if pos == -1:
                    pos = iframe_html.find('config = {')
                if pos != -1:
                    brace_start = iframe_html.find('{', pos)
                    if brace_start != -1:
                        try:
                            decoder = json.JSONDecoder()
                            config, _ = decoder.raw_decode(
                                iframe_html[brace_start:]
                            )
                            m3u8_url = config.get("url", "")
                            if m3u8_url and m3u8_url.startswith("http"):
                                return {
                                    "parse": 0,
                                    "playUrl": "",
                                    "url": m3u8_url,
                                    "header": {
                                        "User-Agent": self.headers["User-Agent"],
                                        "Referer": self.host + "/",
                                    },
                                    "jx": 0,
                                }
                        except (json.JSONDecodeError, ValueError):
                            pass

        # 降级方案1: 检查 player_aaaa 变量
        player_m = re.search(r'player_aaaa\s*=\s*(\{.*?\})', html, re.S)
        if player_m:
            try:
                player_data = json.loads(player_m.group(1))
                play_url = player_data.get("url", "")
                if play_url and play_url.startswith("http"):
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": play_url,
                        "header": {
                            "User-Agent": self.headers["User-Agent"],
                            "Referer": self.host + "/",
                        },
                        "jx": 0,
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # 降级方案2: 返回播放页 URL, 由 APP 内置解析
        return {
            "parse": 1,
            "playUrl": "",
            "url": play_page_url,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.host + "/",
            },
            "jx": 0,
        }

    # ========================
    #  其他框架接口
    # ========================

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return any(x in u for x in (
            '.m3u8', '.mp4', '.flv', '.ts', '.mkv', '.avi',
            '.webm', '.m3u', '.mpd', 'm3u8?',
        ))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None
