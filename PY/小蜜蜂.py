# -*- coding: utf-8 -*-
"""
小蜜蜂影院 TVBox Spider
站点: https://www.xmfyy.com/ (小蜜蜂影院 · 服务端直渲染 · 无反爬)
一级分类: 电视剧(1) / 电影(2) / 动漫(3) / 综艺(4) / 短剧(5)
二级分类(filters): 类型 type / 地区 area / 年份 year / 排序 sort
  列表页 /filter?channel={ch}&type={type}&area={area}&year={year}&sort={sort}&page={pg}
  类型对照: 电视剧 7,9-42 · 电影 43-59 · 动漫 60-76 · 综艺 77-91 · 短剧无类型细分
详情页 /detail/{vid}.html: 线路 tab(source-0..n) 与选集 /vodplay/{vid}-{from}-{n}.html 一一对应
播放: GET /api/play-url?vodId={vid}&playFrom={from}&index={n} -> {"code":200,"mode":"native","url":"*.m3u8"}
搜索: /search?keyword={key}&sort=hits&page={pg}
契约: class Spider 无继承 · 14 壳方法全实现 · 位置参数契约 · $/#/$$$ 分隔
      playerContent.header 为 dict · Python 层不调用 setCache/getCache
生成: 2026-10-01 · 结构经真实站点逐页核对(首页/分类/筛选/详情/播放/搜索)
"""
import re
import json
import urllib.request
import urllib.parse
import urllib.error
import html as _html


class Spider:
    def __init__(self):
        self.host = 'https://www.xmfyy.com'
        self.ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        self.headers = {
            'User-Agent': self.ua,
            'Referer': self.host + '/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        # 一级分类: (名称, channel)
        self.classes = [
            ('电视剧', '1'), ('电影', '2'), ('动漫', '3'),
            ('综艺', '4'), ('短剧', '5'),
        ]
        # 二级分类 - 类型(type id -> 名称)，与站点 /filter 链接逐一核对
        self.type_map = {
            '1': [('7', '剧情'), ('9', '古装'), ('10', '战争'), ('11', '谍战'),
                  ('12', '爱情'), ('13', '罪案'), ('14', '悬疑'), ('15', '家庭'),
                  ('16', '军旅'), ('17', '喜剧'), ('18', '都市'), ('19', '武侠'),
                  ('20', '言情'), ('21', '偶像'), ('22', '青春'), ('23', '农村'),
                  ('24', '穿越'), ('25', '奇幻'), ('26', '历史'), ('27', '年代'),
                  ('28', '科幻'), ('29', '生活'), ('30', '剧情'), ('31', '励志'),
                  ('32', '婚姻'), ('33', '警匪'), ('34', '犯罪'), ('35', '推理'),
                  ('36', '商战'), ('37', '宫廷'), ('38', '仙侠'), ('39', '神话'),
                  ('40', '动作'), ('41', '复仇'), ('42', '惊悚')],
            '2': [('43', '动作'), ('44', '喜剧'), ('45', '爱情'), ('46', '科幻'),
                  ('47', '恐怖'), ('48', '剧情'), ('49', '战争'), ('50', '犯罪'),
                  ('51', '惊悚'), ('52', '冒险'), ('53', '悬疑'), ('54', '动画'),
                  ('55', '武侠'), ('56', '古装'), ('57', '历史'), ('58', '传记'),
                  ('59', '纪录片')],
            '3': [('60', '热血'), ('61', '恋爱'), ('62', '校园'), ('63', '搞笑'),
                  ('64', '机甲'), ('65', '神魔'), ('66', '竞技'), ('67', '冒险'),
                  ('68', '治愈'), ('69', '百合'), ('70', '萝莉'), ('71', '后宫'),
                  ('72', '励志'), ('73', '泡面番'), ('74', '国产动漫'),
                  ('75', '日本动漫'), ('76', '欧美动漫')],
            '4': [('77', '选秀'), ('78', '情感'), ('79', '访谈'), ('80', '播报'),
                  ('81', '旅游'), ('82', '音乐'), ('83', '美食'), ('84', '纪实'),
                  ('85', '曲艺'), ('86', '游戏'), ('87', '亲子'), ('88', '职场'),
                  ('89', '脱口秀'), ('90', '真人秀'), ('91', '晚会')],
            '5': [],
        }
        self.areas = ['大陆', '香港', '台湾', '韩国', '日本', '美国',
                      '泰国', '法国', '英国', '德国', '印度', '其他']
        self.years = ['2026', '2025', '2024', '2023', '2022', '2021',
                      '2020', '2019', '2018']
        self.sorts = [('hot', '热度排序'), ('time', '上映时间'), ('score', '评分排序')]

    # ================= 内部工具 =================
    def _fetch(self, url, referer=None, timeout=20):
        h = dict(self.headers)
        if referer:
            h['Referer'] = referer
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                return data.decode(enc)
            except Exception:
                continue
        return data.decode('utf-8', 'ignore')

    def _clean(self, s):
        if not s:
            return ''
        s = _html.unescape(s)
        s = re.sub(r'<[^>]+>', '', s)
        return s.strip()

    def _parse_cards(self, html):
        """解析视频卡片: 首页/分类/筛选页 .vod-card 与搜索页 .search-item 通用。
        以 /detail/{id}.html 锚点切块, 就近取封面/标题/备注, 按 vid 去重保序。"""
        items = []
        seen = set()
        for m in re.finditer(r'href="/detail/(\d+)\.html"', html):
            vid = m.group(1)
            if vid in seen:
                continue
            chunk = html[m.start():m.start() + 1600]
            pic = ''
            pm = re.search(r'<img[^>]+src="(https?://[^"]+)"', chunk)
            if pm:
                pic = pm.group(1)
            title = ''
            tm = re.search(r'class="vod-title[^"]*"[^>]*>([^<]+)<', chunk)
            if not tm:
                tm = re.search(r'class="search-item-title[^"]*"[^>]*>([^<]+)<', chunk)
            if tm:
                title = self._clean(tm.group(1))
            if not title and pm:
                am = re.search(r'alt="([^"]+?)(?:封面图片|海报)?"', chunk)
                if am:
                    title = self._clean(am.group(1))
            if not title:
                continue
            remark = ''
            rm = re.search(r'vod-badge[^"]*"[^>]*>([^<]+)<', chunk)
            if rm:
                remark = self._clean(rm.group(1))[:20]
            if not remark:
                sm = re.search(r'class="vod-subtitle[^"]*"[^>]*>([^<]+)<', chunk)
                if sm:
                    remark = self._clean(sm.group(1))[:30]
            seen.add(vid)
            items.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })
        return items

    def _parse_pagecount(self, html, pg):
        # 筛选页分页链接是 &amp;page=N 转义形态, 先还原再取最大页码
        pages = [int(x) for x in re.findall(r'page=(\d+)', html.replace('&amp;', '&'))]
        pc = max(pages) if pages else int(pg)
        if pc < int(pg):
            pc = int(pg)
        return str(pg), str(pc)

    def _filters(self):
        """构造二级分类筛选: 每个一级分类 -> [类型, 地区, 年份, 排序] 四组"""
        out = {}
        for _, ch in self.classes:
            groups = []
            types = self.type_map.get(ch, [])
            if types:
                groups.append({
                    'key': 'type', 'name': '类型',
                    'value': [{'n': '全部', 'v': ''}] +
                             [{'n': n, 'v': v} for v, n in types],
                })
            groups.append({
                'key': 'area', 'name': '地区',
                'value': [{'n': '全部', 'v': ''}] +
                         [{'n': a, 'v': a} for a in self.areas],
            })
            groups.append({
                'key': 'year', 'name': '年份',
                'value': [{'n': '全部', 'v': ''}] +
                         [{'n': y, 'v': y} for y in self.years] +
                         [{'n': '其他', 'v': '-1'}],
            })
            groups.append({
                'key': 'sort', 'name': '排序',
                'value': [{'n': n, 'v': v} for v, n in self.sorts],
            })
            out[ch] = groups
        return out

    def _first_id(self, ids):
        """detailContent 入参兼容: list / JSON 字符串 / 纯字符串 / dict"""
        if isinstance(ids, (list, tuple)):
            return str(ids[0]) if ids else ''
        if isinstance(ids, dict):
            for k in ('id', 'vod_id', 'value'):
                if ids.get(k):
                    return str(ids[k])
            return ''
        s = str(ids or '').strip()
        if s.startswith('['):
            try:
                arr = json.loads(s)
                if isinstance(arr, list) and arr:
                    return str(arr[0])
            except Exception:
                pass
        m = re.search(r'\d+', s)
        return m.group(0) if m else s

    # ================= 壳接口(位置参数契约) =================
    def getName(self):
        return '小蜜蜂影院'

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        u = (url or '').lower()
        return u.endswith('.m3u8') or u.endswith('.mp4') or '.m3u8?' in u or '.mp4?' in u

    def manualVideoCheck(self):
        return False

    def init(self, extend):
        return None

    def destroy(self):
        return None

    def homeContent(self, filter):
        classes = [{'type_id': tid, 'type_name': name} for name, tid in self.classes]
        items = []
        try:
            html = self._fetch(self.host + '/')
            items = self._parse_cards(html)
        except Exception:
            items = []
        return {'class': classes, 'list': items, 'filters': self._filters()}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        ext = extend if isinstance(extend, dict) else {}
        if isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}
        ftype = str(ext.get('type') or '')
        area = str(ext.get('area') or '')
        year = str(ext.get('year') or '')
        sort = str(ext.get('sort') or 'hot')
        q = urllib.parse.urlencode({
            'channel': tid, 'type': ftype, 'area': area,
            'year': year, 'sort': sort, 'page': pg,
        })
        url = '{0}/filter?{1}'.format(self.host, q)
        html = self._fetch(url)
        items = self._parse_cards(html)
        page, pagecount = self._parse_pagecount(html, pg)
        return {
            'list': items,
            'page': page,
            'pagecount': pagecount,
            'limit': 90,
            'total': 999999,
        }

    def detailContent(self, ids):
        vid = self._first_id(ids)
        url = '{0}/detail/{1}.html'.format(self.host, vid)
        html = self._fetch(url)
        title = ''
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            title = self._clean(m.group(1))
        if not title:
            m2 = re.search(r'og:title" content="《([^》]+)》', html)
            title = self._clean(m2.group(1)) if m2 else vid
        pic = ''
        pm = re.search(r'og:image" content="([^"]+)"', html)
        if pm:
            pic = pm.group(1)
        meta = {}
        for k, v in re.findall(
                r'meta-label">([^<]+)</span>\s*<span class="meta-value">([^<]*)</span>', html):
            meta[self._clean(k).rstrip('：:')] = self._clean(v)
        content = ''
        cm = re.search(r'class="synopsis-content"[^>]*>(.*?)</div>', html, re.S)
        if cm:
            content = self._clean(cm.group(1))
        # 线路名(与 source-panel 顺序一一对应) + 各线路选集
        from_names = re.findall(r'data-target="source-\d+"[^>]*>([^<]+)</button>', html)
        panels = re.split(r'<div class="source-panel"', html)[1:]
        play_from, play_url = [], []
        for i, panel in enumerate(panels):
            eps = re.findall(r'href="(/vodplay/[^"]+)"[^>]*>([^<]+)</a>', panel)
            # 相关推荐等后续区块不属于本线路, 截到下一个 section 前
            eps = [(u, t) for u, t in eps if '/vodplay/{0}-'.format(vid) in u]
            if not eps:
                continue
            # 普通线路二(bfzym3u8 -> fengbao12.com)整站已下线: API 照发地址但 m3u8 恒 404,
            # 站内播放器同样播不了, 详情里直接剔除避免用户点到死线路
            fm = re.search(r'/vodplay/\d+-(.+)-\d+\.html', eps[0][0])
            if fm and fm.group(1) == 'bfzym3u8':
                continue
            name = self._clean(from_names[i]) if i < len(from_names) else '线路{0}'.format(i + 1)
            play_from.append(name)
            play_url.append('#'.join(
                '{0}${1}{2}'.format(self._clean(t), self.host, u) for u, t in eps))
        vod = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': pic,
            'type_name': meta.get('类型', ''),
            'vod_year': meta.get('年份', ''),
            'vod_area': meta.get('地区', ''),
            'vod_actor': meta.get('主演', ''),
            'vod_director': meta.get('导演', ''),
            'vod_remarks': meta.get('备注', ''),
            'vod_content': content,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg):
        pg = int(pg) if str(pg).isdigit() else 1
        q = urllib.parse.urlencode({'keyword': key, 'sort': 'hits', 'page': pg})
        url = '{0}/search?{1}'.format(self.host, q)
        html = self._fetch(url)
        items = self._parse_cards(html)
        page, pagecount = self._parse_pagecount(html, pg)
        return {
            'list': items,
            'page': page,
            'pagecount': pagecount,
            'limit': 90,
            'total': 999999,
        }

    def playerContent(self, flag, id, vipFlags):
        header = {'User-Agent': self.ua, 'Referer': self.host + '/'}
        play_page = id if str(id).startswith('http') else self.host + str(id)
        m = re.search(r'/vodplay/(\d+)-(.+)-(\d+)\.html', play_page)
        if m:
            api = '{0}/api/play-url?vodId={1}&playFrom={2}&index={3}'.format(
                self.host, m.group(1),
                urllib.parse.quote(m.group(2)), m.group(3))
            try:
                text = self._fetch(api, referer=play_page)
                data = json.loads(text)
                if data.get('code') == 200 and data.get('url'):
                    if data.get('mode') == 'iframe':
                        return {'parse': 1, 'url': data['url'], 'header': header}
                    return {'parse': 0, 'url': data['url'], 'header': header}
            except Exception:
                pass
        # 解析失败兜底: 交给壳嗅探播放页
        return {'parse': 1, 'url': play_page, 'header': header}

    def localProxy(self, param):
        return [404, 'text/plain', b'not found', {}]

    def action(self, action):
        return None
