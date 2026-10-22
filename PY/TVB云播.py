# -*- coding: utf-8 -*-
# ==========================================================
#  TVB云播 (TVB Yunbo)   http://www.viptvb07.com/
#  适配 TVBox / 影视仓 / OK影视 等空壳影视 APP 的 py 源
#
#  站点框架 : MacCMS (苹果CMS) + mytheme 模板
#  反爬机制 (已全过) :
#    1) 直接请求根路径 / 返回 403 滑动验证页 (huadong 人机验证),
#       但只要带上 X-Requested-With: XMLHttpRequest 请求头即放行,
#       全站所有页面均可用该请求头正常访问。
#    2) 响应体不是原始 HTML, 而是把整个 HTML 用 JSON 字符串转义
#       包了一层 (开头是 ", 内部 \n \" \/ 全转义), 直接 json.loads
#       即可还原真实页面; 脚本对 JSON 包裹做了自动探测兼容。
#
#  URL 规则 :
#    首页        /index.php
#    父分类      /index.php/vod/type/id/{tid}.html          tid: 1电影 2剧集 3综艺 4动漫 5短剧
#    子分类      /index.php/vod/type/id/{sub}.html          平级入口, 与父分类同一套解析
#                 电影 -> 6动作 7喜剧 8爱情 9科幻 10剧情 11恐怖 12战争
#                 剧集 -> 13国产 14港台 15日韩 16欧美 20海外
#                 综艺 -> 21大陆综艺 22香港综艺 23日韩综艺
#    筛选        /index.php/vod/show/[class/C/][area/A/].../id/{tid}[/year/Y][/lang/L][/by/B].html
#                 各维度可任意顺序组合, 中文值需 URL 编码 (排序固定 time/hits/score)
#    分页        .../page/{n}.html  (type 页与 show 页通用)
#    总页数      列表页翻页条 "尾页" 链接里的最大页码
#    详情        /index.php/vod/detail/id/{id}.html
#    播放页      /index.php/vod/play/id/{id}/sid/{sid}/nid/{nid}.html
#    搜索        /index.php/vod/search/wd/{kw}.html   (单页, 无翻页)
#
#  播放解析链路 :
#    播放页内 var player_data = {"flag","encrypt","url","from",...}
#      -> encrypt=0 时 url 为明文
#      -> from=mp4 / bfzym3u8 / lzm3u8 等: url 即直链 (.mp4/.m3u8), parse=0 直接播放
#      -> from=vwnet 等: url 为令牌 (vwnet-xxxx), 走站点自带解析器
#         http://jx.hktvyb.top/index3.php?url={令牌} 解出真实 m3u8, parse=0 播放
#      -> 解析失败回退 parse=1 把播放页交给壳处理
#
#  已实现 : 分类 / 每个父分类下的子分类(筛选器, 动态抓取) / 分页 / 详情 / 播放 / 搜索 / 封面
#
#  修复记录 :
#    1) 子分类(筛选器)改为运行时从分类页第一个筛选条动态抓取, 补齐 综艺(欧美综艺)、
#       动漫(25-28)、短剧(29-42) 等此前漏掉的子分类; 静态表仅作兜底。
#    2) 子分类 id 不再被静态白名单拦截 —— 此前 APP 传 24/25/29 等会被静默丢弃,
#       退回父分类全量列表。
#    3) 修正带筛选时的翻页 URL: 旧写法把 '.html' 拼在中间
#       (.../by/time/.html/page/2.html), 站点会当成第 1 页返回, 导致翻页失效。
# ==========================================================

import re
import sys
import json
import time
import urllib.parse

import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def fetch(self, url, headers=None, timeout=20, verify=False, cookies=None):
            s = requests.Session()
            s.trust_env = False
            return s.get(url, headers=headers, timeout=timeout,
                         verify=verify, cookies=cookies)


class Spider(BaseSpider):
    name = 'TVB云播'
    host = 'http://www.viptvb07.com'

    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

    # 站点自带解析器路由 (来自 /static/js/playerconfig.js 的 from -> parse 映射)
    # 令牌型线路 (url 不是直链) 按 from 路由到对应解析端点解出真实 m3u8
    JX_HOST = 'http://jx.hktvyb.top'
    JX_PARSE = {
        'zijianm3u8': '/index2.php?url=',
        'vwnet':      '/index3.php?url=',
        'co':         '/index3.php?url=',
        'yunjie':     '/index3.php?url=',
        'NSYS':       '/index3.php?url=',
        'CO4K':       '/index3.php?url=',
        'mp4':        '/index.php?url=',
        'mytvb':      '/index.php?url=',
        '13yun':      '/index.php?url=',
        '189d':       '/index.php?url=',
        'hkm3u8':     '/index.php?url=',
        'mytv':       '/hktvua.php?url=',
        'dbm3u8':     '/indexzy.php?url=',
        'bfzym3u8':   '/indexzy.php?url=',
        '1080zyk':    '/indexzy.php?url=',
        'ffm3u8':     '/indexzy.php?url=',
        'lzm3u8':     '/indexzy.php?url=',
        'xun4k':      '/indexzy.php?url=',
        'wsym3u8':    'http://104.233.148.69:666/xun.php?url=',
    }
    # 未知 from 时的解析端点回退顺序
    JX_FALLBACK = ['/index3.php?url=', '/index.php?url=', '/indexzy.php?url=', '/index2.php?url=']

    # ==================== 父分类 ====================
    CATEGORIES = [
        ('1', '电影'),
        ('2', '剧集'),
        ('3', '综艺'),
        ('4', '动漫'),
        ('5', '短剧'),
    ]

    # ==================== 各父分类下的子分类 ====================
    # 子分类是平级列表入口, 站点形态 /index.php/vod/show/id/{sub}.html。
    # 运行时优先从分类页第一个筛选条动态抓取 (见 _parse_screen 的 sub 维度),
    # 下表只在动态抓取失败时兜底; 已按站点实况补齐:
    #   综艺补上 欧美综艺(24), 动漫(25-28) / 短剧(29-42) 此前被误判为"无子分类"
    SUBS = {
        '1': [('6', '动作片'), ('7', '喜剧片'), ('8', '爱情片'), ('9', '科幻片'),
              ('10', '剧情片'), ('11', '恐怖片'), ('12', '战争片')],
        '2': [('13', '国产剧'), ('14', '港台剧'), ('15', '日韩剧'),
              ('16', '欧美剧'), ('20', '海外剧')],
        '3': [('21', '大陆综艺'), ('22', '香港综艺'), ('23', '日韩综艺'), ('24', '欧美综艺')],
        '4': [('25', '国产动漫'), ('26', '日韩动漫'), ('27', '港台动漫'), ('28', '欧美动漫')],
        '5': [('29', '漫剧'), ('30', '玄幻'), ('31', '剧情'), ('32', '权谋'), ('33', '豪门'),
              ('34', '宫斗'), ('35', '脑洞'), ('36', '科幻'), ('37', '仙侠'), ('38', '悬疑'),
              ('39', '爱情'), ('40', 'AI漫剧'), ('41', '女性成长'), ('42', '旧短剧')],
    }

    # 全部合法 tid (父分类 + 子分类), APP 传任何子分类 id 也能当列表入口
    ALL_TIDS = set(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12',
                    '13', '14', '15', '16', '20', '21', '22', '23', '24', '25', '26',
                    '27', '28', '29', '30', '31', '32', '33', '34', '35', '36', '37',
                    '38', '39', '40', '41', '42'])

    SORTS = [('按时间', 'time'), ('按人气', 'hits'), ('按评分', 'score')]

    # ==================== 生命周期 ====================
    def init(self, extend=''):
        self._session = None
        self._last = {}
        self._filters = {}     # tid -> 筛选器 (动态抓取后缓存)
        self._host = (extend or '').strip() or self.host
        return {}

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        low = (url or '').lower()
        return any(k in low for k in ('.m3u8', '.mp4', '.flv', '.mkv', '.avi', '.ts'))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self._session:
                self._session.close()
        except Exception:
            pass

    def localProxy(self, param):
        return [200, 'text/plain', '']

    # ==================== 基础工具 ====================
    def _log(self, msg):
        try:
            print('[%s] %s' % (self.name, msg))
        except Exception:
            pass

    def _headers(self, referer=None):
        # X-Requested-With 是本站过滑动验证的关键, 缺失即 403
        return {
            'User-Agent': self.UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': referer or (self._host + '/index.php'),
        }

    def _sess(self):
        if getattr(self, '_session', None) is None:
            s = requests.Session()
            s.trust_env = False
            self._session = s
        return self._session

    def _throttle(self, key, gap=0.4):
        now = time.time()
        last = getattr(self, '_last', {}).get(key, 0)
        wait = gap - (now - last)
        if wait > 0:
            time.sleep(wait)
        if not hasattr(self, '_last'):
            self._last = {}
        self._last[key] = time.time()

    @staticmethod
    def _unwrap(text):
        """站点把整个 HTML 用 JSON 字符串包了一层, 解出真实页面; 非 JSON 则原样返回"""
        if not text:
            return ''
        t = text.strip()
        if t.startswith('"'):
            try:
                dec = json.loads(t)
                if isinstance(dec, str) and dec:
                    return dec
            except Exception:
                pass
        return text

    # 搜索限流: 站点对搜索接口限制 "请不要频繁操作, 搜索时间间隔为10秒",
    # 命中时返回 JSON {"code":0,"msg":"请不要频繁操作...","wait":3}, 需等 ~11s 重试。
    RATE_LIMIT_MARK = ('请不要频繁操作', '搜索时间间隔')

    def _is_rate_limited(self, body):
        if not body:
            return False
        return any(k in body for k in self.RATE_LIMIT_MARK)

    def _get(self, url, referer=None, retries=4, timeout=20):
        last = ''
        for i in range(retries):
            try:
                r = self._sess().get(url, headers=self._headers(referer),
                                     timeout=timeout, verify=False)
                if r.status_code == 200:
                    r.encoding = 'utf-8'
                    raw = r.text
                    # 命中搜索限流 -> 等 11 秒重试 (站点硬性间隔 10 秒)
                    if self._is_rate_limited(raw):
                        self._log('rate-limited, wait 11s (%d) %s' % (i + 1, url))
                        time.sleep(11)
                        continue
                    text = self._unwrap(raw)
                    if text and len(text.strip()) > 200:
                        return text
                    last = text
                else:
                    self._log('GET %d -> %d %s' % (i + 1, r.status_code, url))
            except Exception as e:
                self._log('GET fail(%d) %s %s' % (i + 1, type(e).__name__, url))
            time.sleep(1.0 + i * 0.5)
        return last

    @staticmethod
    def _strip(s):
        s = re.sub(r'<[^>]+>', '', s or '')
        s = (s.replace('&nbsp;', ' ').replace('&amp;', '&')
             .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
             .replace('&#39;', "'"))
        return re.sub(r'\s+', ' ', s).strip()

    def _fix(self, u):
        if not u:
            return ''
        u = u.strip()
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http'):
            return u
        if u.startswith('/'):
            return self._host + u
        return self._host + '/' + u

    def _tid(self, tid):
        """APP 传来的 tid 统一成站点 type id"""
        t = str(tid or '').strip().strip('/')
        # 兼容带 /vod/type/id/xx 的完整路径
        m = re.search(r'/vod/(?:type|show)/id/(\d+)', t)
        if m:
            return m.group(1)
        if re.fullmatch(r'\d+', t):
            return t
        return '2'

    # ==================== 列表解析 ====================
    def _parse_list(self, html, container_only=True):
        """解析 myui-vodlist 卡片列表
        container_only=True 时只取主列表 (筛选注释之后第一个 myui-vodlist),
        避开 '猜你喜欢/热播' 等推荐区块 (空结果页会把推荐混进来)"""
        vods = []
        if not html:
            return vods
        seen = set()

        def harvest(seg):
            for block in re.findall(r'<li[^>]*>(.*?)</li>', seg, re.S):
                m = re.search(
                    r'<a class="myui-vodlist__thumb[^"]*"[^>]*'
                    r'href="(/index\.php/vod/detail/id/(\d+)\.html)"[^>]*'
                    r'title="([^"]*)"(?:[^>]*data-original="([^"]*)")?', block)
                if not m:
                    m = re.search(
                        r'href="(/index\.php/vod/detail/id/(\d+)\.html)"[^>]*'
                        r'title="([^"]*)"(?:[^>]*data-original="([^"]*)")?', block)
                if not m:
                    continue
                href, vid, name, pic = m.group(1), m.group(2), m.group(3), (m.group(4) or '')
                if not vid or vid in seen:
                    continue
                name = self._strip(name)
                if not name:
                    continue
                if not pic:
                    mp = re.search(r'data-original="([^"]+)"', block)
                    if not mp:
                        mp = re.search(r'<img[^>]*src="([^"]+)"', block)
                    if mp:
                        pic = mp.group(1)
                # 状态/集数备注 (右上角 tag)
                remark = ''
                rm = re.search(r'class="pic-tag[^"]*">\s*<span class="tag"[^>]*>(.*?)</span>',
                               block, re.S)
                if rm:
                    remark = self._strip(rm.group(1))
                seen.add(vid)
                vods.append({
                    'vod_id': vid,
                    'vod_name': name,
                    'vod_pic': self._fix(pic),
                    'vod_remarks': remark,
                })

        if container_only:
            # 主列表: 筛选注释之后的第一个 <ul class="myui-vodlist clearfix">
            i = html.find('<!-- 筛选 -->')
            seg = html[i:] if i >= 0 else html
            m = re.search(r'<ul class="myui-vodlist clearfix">(.*?)</ul>', seg, re.S)
            harvest(m.group(1) if m else '')
        else:
            for m in re.finditer(r'<ul class="myui-vodlist clearfix">(.*?)</ul>', html, re.S):
                harvest(m.group(1))
        return vods

    @staticmethod
    def _parse_pagecount(html, page):
        """翻页条 '尾页' 链接里的最大页码"""
        page = int(page or 1)
        if not html:
            return page
        nums = [int(n) for n in re.findall(r'/page/(\d+)\.html', html)]
        if nums:
            return max(max(nums), page)
        return page

    # ==================== 筛选器 (动态抓取) ====================
    def _fetch_filters(self, tid):
        """抓分类页, 从筛选条解析 class/area/year/lang/by 五个维度 (带缓存)"""
        tid = str(tid)
        if tid in self._filters:
            return self._filters[tid]
        filters = None
        try:
            html = self._get('%s/index.php/vod/type/id/%s.html' % (self._host, tid))
            filters = self._parse_screen(html, tid)
        except Exception:
            filters = None
        if not filters:
            filters = self._fallback_filters(tid)
        self._filters[tid] = filters
        return filters

    def _parse_screen(self, html, tid):
        """解析筛选条 myui-screen__list 各分组链接, 归类到六个维度
        sub(子分类) / class(类型) / area(地区) / year(年份) / lang(语言) / by(排序)

        站点每个维度是一条独立的 <ul class="myui-screen__list">:
          · 子分类组的链接形如 /vod/show/id/{sub}.html (只有 id, 不带其它维度关键字)
          · 其余各维度链接均带 class|area|year|lang|by 关键字
        每个维度组里都有一条指向 /vod/show/id/{tid}.html 的 "全部" 链接, 它天然
        也符合子分类的 URL 形态, 所以这里先按带关键字的维度判定; 一个分组里连一条
        关键字链接都找不到, 才认定为子分类组 —— 避免 "全部" 把年份/语言等组误判成子分类。
        """
        groups = {}
        if not html:
            return groups
        dim_pats = [
            ('class', r'/vod/show/class/([^/]+)/id/%s\.html$' % tid),
            ('area', r'/vod/show/area/([^/]+)/id/%s\.html$' % tid),
            ('year', r'/vod/show/id/%s/year/([^/]+)\.html$' % tid),
            ('lang', r'/vod/show/id/%s/lang/([^/]+)\.html$' % tid),
            ('by', r'/vod/show/by/([^/]+)/id/%s\.html$' % tid),
        ]
        sub_pat = r'/vod/show/id/(\d+)\.html$'

        for block in re.findall(r'<ul class="myui-screen__list[^"]*"[^>]*>(.*?)</ul>', html, re.S):
            links = re.findall(
                r'href="(/index\.php/vod/show/[^"]+\.html)"[^>]*>(.*?)</a>', block, re.S)
            if not links:
                continue
            dim = None
            vals = []
            sub_vals = []
            for u, t in links:
                t = self._strip(t)
                if not t:
                    continue
                hit = None
                for d, pat in dim_pats:
                    m = re.search(pat, u)
                    if m:
                        hit = (d, m.group(1))
                        break
                if hit:
                    if dim is None:
                        dim = hit[0]
                    if hit[0] == dim:
                        vals.append({'n': t, 'v': hit[1]})
                    continue
                # 只有 id 的链接 -> 子分类 (排除指向父分类自身的 "全部")
                sm = re.search(sub_pat, u)
                if sm and sm.group(1) != str(tid):
                    sub_vals.append({'n': t, 'v': sm.group(1)})
            if dim and vals:
                groups[dim] = vals
            elif sub_vals:
                groups['sub'] = [{'n': '全部', 'v': ''}] + sub_vals
        return groups

    def _fallback_filters(self, tid):
        """动态抓取失败时的兜底筛选器 (从站点各分类页实抄)"""
        tid = str(tid)
        fb = {
            '1': {
                'class': ['儿童', '冒险', '农村', '剧情', '动作', '动画', '历史', '古装', '喜剧',
                          '奇幻', '微电影', '恐怖', '悬疑', '惊悚', '战争', '文艺', '枪战', '武侠',
                          '爱情', '犯罪', '科幻', '经典', '网络电影', '警匪', '运动', '青春'],
                'area': ['其他', '加拿大', '印度', '台湾', '大陆', '德国', '意大利', '日本', '法国',
                         '泰国', '美国', '英国', '西班牙', '韩国', '香港'],
                'lang': ['其它', '国语', '德语', '日语', '法语', '粤语', '英语', '闽南语', '韩语'],
            },
            '2': {
                'class': ['乡村', '其他', '剧情', '动作', '历史', '古装', '商战', '喜剧', '奇幻',
                          '家庭', '情景', '战争', '犯罪', '经典', '网剧', '青春偶像'],
                'area': ['其他', '台湾', '大陆', '新加坡', '日本', '泰国', '美国', '英国', '韩国',
                         '香港'],
                'lang': ['其它', '国语', '日语', '粤语', '英语', '闽南语', '韩语'],
            },
            '3': {
                'class': ['情感', '播报', '旅游', '曲艺', '求职', '游戏互动', '生活', '纪实', '美食',
                          '访谈', '财经', '选秀', '音乐'],
                'area': ['其他', '台湾', '大陆', '新加坡', '日本', '泰国', '美国', '英国', '韩国',
                         '香港'],
                'lang': ['其它', '国语', '日语', '粤语', '英语', '闽南语', '韩语'],
            },
            '4': {
                'class': ['亲子', '其他', '冒险', '动作', '励志', '原创', '少女', '少年', '情感',
                          '战争', '推理', '搞笑', '机战', '校园', '热血', '益智', '社会', '科幻',
                          '萝莉', '运动'],
                'area': ['其他', '国产', '日本', '欧美'],
                'lang': ['其它', '国语', '日语', '粤语', '英语', '闽南语', '韩语'],
            },
            '5': {
                'class': ['儿童', '冒险', '农村', '剧情', '动作', '动画', '历史', '古装', '喜剧',
                          '奇幻', '微电影', '恐怖', '悬疑', '惊悚', '战争', '文艺', '枪战', '武侠',
                          '爱情', '犯罪', '科幻', '经典', '网络电影', '警匪', '运动', '青春'],
                'area': ['其他', '加拿大', '印度', '台湾', '大陆', '德国', '意大利', '日本', '法国',
                         '泰国', '美国', '英国', '西班牙', '韩国', '香港'],
                'lang': ['其它', '国语', '德语', '日语', '法语', '粤语', '英语', '闽南语', '韩语'],
            },
        }
        base = fb.get(tid, fb['1'])
        groups = {}
        for dim in ('class', 'area', 'lang'):
            vals = base.get(dim) or fb['1'][dim]
            groups[dim] = [{'n': '全部', 'v': ''}] + \
                          [{'n': x, 'v': urllib.parse.quote(x)} for x in vals]
        years = [str(y) for y in range(2026, 1999, -1)]
        groups['year'] = [{'n': '全部', 'v': ''}] + [{'n': y, 'v': y} for y in years]
        groups['by'] = [{'n': n, 'v': v} for n, v in self.SORTS]
        return groups

    def _build_filters(self, tid):
        """组装某父分类的完整筛选器 (子分类 + 动态五维)"""
        tid = str(tid)
        groups = []
        dyn = self._fetch_filters(tid)
        # 子分类: 优先用分类页动态抓取结果, 抓不到再退回静态表
        subs = [v for v in (dyn.get('sub') or []) if str(v.get('v', '')).strip()]
        if not subs:
            subs = [{'n': n, 'v': s} for s, n in self.SUBS.get(tid, [])]
        if subs:
            groups.append({
                'key': 'sub', 'name': '子分类',
                'value': [{'n': '全部', 'v': ''}] + subs,
            })
        names = {'class': '类型', 'area': '地区', 'year': '年份',
                 'lang': '语言', 'by': '排序'}
        for dim in ('class', 'area', 'year', 'lang', 'by'):
            vals = dyn.get(dim)
            if not vals:
                if dim == 'by':
                    vals = [{'n': n, 'v': v} for n, v in self.SORTS]
                else:
                    continue
            groups.append({'key': dim, 'name': names[dim], 'value': vals})
        return groups

    # ==================== 首页 ====================
    def homeContent(self, filter=False):
        classes = [{'type_id': tid, 'type_name': name}
                   for tid, name in self.CATEGORIES]
        result = {'class': classes}
        try:
            result['filters'] = {tid: self._build_filters(tid)
                                 for tid, _ in self.CATEGORIES}
        except Exception:
            result['filters'] = {}
        try:
            html = self._get(self._host + '/index.php')
            result['list'] = self._parse_list(html, container_only=False)
        except Exception:
            result['list'] = []
        return result

    def homeVideoContent(self):
        try:
            html = self._get(self._host + '/index.php')
            return {'list': self._parse_list(html, container_only=False)}
        except Exception:
            return {'list': []}

    # ==================== 分类内容 ====================
    def categoryContent(self, tid, pg, filter=False, extend=''):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        if page < 1:
            page = 1

        ext = extend if isinstance(extend, dict) else {}
        if isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}

        base = self._tid(tid)
        # 子分类筛选优先: 子分类是平级列表入口, 站点形态 /vod/show/id/{sub}.html。
        # 只要是纯数字 id 就接受 —— 不再受静态白名单限制 (站点随时可能新增子分类)。
        sub = str(ext.get('sub', '') or '').strip()
        if re.fullmatch(r'\d+', sub):
            base = sub

        cls = (ext.get('class', '') or '').strip()
        area = (ext.get('area', '') or '').strip()
        year = (ext.get('year', '') or '').strip()
        lang = (ext.get('lang', '') or '').strip()
        by = (ext.get('by', '') or '').strip()

        # 无任何筛选 -> /vod/type/id/{tid}.html; 有筛选 -> /vod/show/.../id/{tid}.html
        # 路径段一律用 '/' 连接, 翻页统一追加 '/page/{n}.html';
        # 不能把 '.html' 拼在中间 (旧写法 .../by/time/.html/page/2.html 会被站点当成第 1 页)
        has_filter = bool(cls or area or year or lang or by)
        if has_filter:
            parts = []
            if cls:
                parts.append('class/%s' % cls)
            if area:
                parts.append('area/%s' % area)
            parts.append('id/%s' % base)
            if year:
                parts.append('year/%s' % year)
            if lang:
                parts.append('lang/%s' % lang)
            if by:
                parts.append('by/%s' % by)
            seg = '/index.php/vod/show/' + '/'.join(parts)
        else:
            seg = '/index.php/vod/type/id/%s' % base
        url = self._host + seg + '.html'
        if page > 1:
            url = self._host + seg + '/page/%d.html' % page

        self._throttle('cat', 0.4)
        html = self._get(url)
        vods = self._parse_list(html)
        pagecount = self._parse_pagecount(html, page)
        if not vods and page > 1:
            pagecount = page

        limit = len(vods) or 24
        return {
            'list': vods,
            'page': page,
            'pagecount': pagecount,
            'limit': limit,
            'total': (pagecount * limit) if pagecount else len(vods),
        }

    # ==================== 详情 ====================
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids or '')
        vid = str(vid).strip()
        m = re.search(r'/vod/detail/id/(\d+)', vid)
        if m:
            vid = m.group(1)
        vid = re.sub(r'\D', '', vid)
        if not vid:
            return {'list': []}

        url = '%s/index.php/vod/detail/id/%s.html' % (self._host, vid)
        self._throttle('detail', 0.3)
        html = self._get(url)
        if not html:
            return {'list': [{'vod_id': vid, 'vod_name': vid, 'vod_pic': '',
                              'vod_play_from': '默认', 'vod_play_url': ''}]}

        # 标题
        name = ''
        mt = re.search(r'<h1 class="title">(.*?)</h1>', html, re.S)
        if mt:
            name = self._strip(mt.group(1))
        if not name:
            mt = re.search(r'<title>(.*?)(?:-|_|\|)', html)
            if mt:
                name = self._strip(mt.group(1))
        if not name:
            name = vid

        # 封面
        pic = ''
        mp = re.search(r'class="myui-vodlist__thumb picture"[^>]*>(.*?)</a>', html, re.S)
        if mp:
            pm = re.search(r'data-original="([^"]+)"', mp.group(1))
            if pm:
                pic = pm.group(1)
        if not pic:
            pm = re.search(r'data-original="([^"]+\.(?:jpg|jpeg|png|webp|gif))"', html, re.I)
            if pm:
                pic = pm.group(1)

        # 评分
        score = ''
        ms = re.search(r'<span class="branch">(.*?)</span>', html, re.S)
        if ms:
            score = self._strip(ms.group(1))

        # 元信息行: 分类/地区/年份 (同一 <p class="data"> 里三个 label 各自只取紧跟其后的值)
        area = vclass = year = ''
        for pm in re.finditer(r'<p class="data">(.*?)</p>', html, re.S):
            row = pm.group(1)
            if '地区：' in row:
                am = re.search(r'地区：</span>(?:\s*<a[^>]*>([^<]+)</a>|\s*([^<\n]*?)(?:<|$))', row)
                if am:
                    area = self._strip(am.group(1) if am.group(1) else am.group(2))
            if '分类：' in row:
                cm = re.search(r'分类：</span>\s*<a[^>]*>([^<]+)</a>', row)
                if not cm:
                    cm = re.search(r'分类：</span>\s*([^<\n]*?)(?:<|$)', row)
                if cm:
                    vclass = self._strip(cm.group(1))
            if '年份：' in row:
                ym = re.search(r'年份：</span>\s*(?:<a[^>]*>)?\s*(\d{4})', row)
                if ym:
                    year = ym.group(1)

        # 更新状态
        remark = ''
        mr = re.search(r'<span class="text-muted">更新：</span>(.*?)</p>', html, re.S)
        if mr:
            remark = self._strip(mr.group(1))
        if not remark:
            mr = re.search(r'class="text-red">(.*?)</span>', html, re.S)
            if mr:
                remark = self._strip(mr.group(1))

        # 主演 / 导演
        actor = self._meta_row(html, '主演')
        director = self._meta_row(html, '导演')

        # 语言
        lang = ''
        ml = re.search(r'<span class="text-muted">语言：</span>(.*?)</p>', html, re.S)
        if ml:
            lang = self._strip(ml.group(1))

        # 简介: 优先隐藏的完整简介, 其次 sketch 摘要
        desc = ''
        md = re.search(r'<span class="data"[^>]*>\s*<p>(.*?)</p>', html, re.S)
        if md:
            desc = self._strip(md.group(1))
        if not desc:
            md = re.search(r'<span class="sketch[^"]*">(.*?)</span>', html, re.S)
            if md:
                desc = self._strip(md.group(1))
        if not desc:
            md = re.search(r'<span class="text-muted">简介：</span>(.*?)(?:<a|$)', html, re.S)
            if md:
                desc = self._strip(md.group(1))
        if not desc:
            desc = name

        # 线路 + 集数
        froms, urls = self._parse_play_lines(html, vid)

        vod = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': self._fix(pic),
            'vod_year': year,
            'vod_area': area,
            'type_name': vclass,
            'vod_lang': lang,
            'vod_remarks': remark or score,
            'vod_actor': actor,
            'vod_director': director,
            'vod_content': desc or name,
            'vod_score': score,
            'vod_play_from': '$$$'.join(froms) if froms else '默认',
            'vod_play_url': '$$$'.join(urls) if urls else '',
        }
        return {'list': [vod]}

    def _meta_row(self, html, label):
        m = re.search(r'<span class="text-muted">%s：</span>(.*?)</p>' % re.escape(label),
                      html, re.S)
        if not m:
            return ''
        vals = re.findall(r'<a[^>]*>([^<]+)</a>', m.group(1))
        if vals:
            out = []
            for v in vals:
                v = self._strip(v)
                if v and v not in out:
                    out.append(v)
            return ','.join(out)
        return self._strip(m.group(1))

    def _parse_play_lines(self, html, vid):
        """按 myui-panel__head 切分播放面板, 每个面板取线路名 + 其下集数列表 (sid/nid)"""
        froms, urls = [], []
        if not html:
            return froms, urls
        # 只取播放区域: 第一个播放面板到 "猜你喜欢" 之间, 避开推荐区块
        start = html.find('myui-player')
        if start < 0:
            start = 0
        end = html.find('猜你喜欢', start)
        if end < 0:
            end = html.find('myui-foot', start)
        if end < 0:
            end = len(html)
        body = html[start:end]

        for seg in re.split(r'myui-panel__head', body):
            mt = re.search(r'<h3 class="title">(.*?)</h3>', seg, re.S)
            mu = re.search(r'<ul class="myui-content__list[^"]*"[^>]*>(.*?)</ul>', seg, re.S)
            if not (mt and mu):
                continue
            fname = self._strip(mt.group(1))
            eps = re.findall(
                r'href="/index\.php/vod/play/id/\d+/sid/(\d+)/nid/(\d+)\.html"[^>]*>(.*?)</a>',
                mu.group(1), re.S)
            if not eps:
                continue
            fmt = []
            for sid, nid, label in eps:
                label = self._strip(label) or ('第%s集' % nid)
                # 集名里的 $ # 需转义, 避免破坏 $$$ / # 分隔
                label = label.replace('#', '＃').replace('$', '＄')
                fmt.append('%s$%s-%s-%s' % (label, vid, sid, nid))
            if not fname:
                fname = '线路%s' % (len(froms) + 1)
            froms.append(fname)
            urls.append('#'.join(fmt))
        return froms, urls

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags=None):
        pid = str(id or '').strip().strip('/')
        if pid.startswith('http'):
            return self._play(pid)
        # 形如 {vid}-{sid}-{nid}
        parts = pid.split('-')
        if len(parts) < 3:
            return {'parse': 1, 'url': pid, 'header': self._play_header()}
        en, sid, nid = parts[0], parts[1], parts[2]
        play_url = '%s/index.php/vod/play/id/%s/sid/%s/nid/%s.html' % (
            self._host, en, sid, nid)

        self._throttle('play', 0.3)
        html = self._get(play_url)
        if not html:
            return {'parse': 1, 'url': play_url, 'header': self._play_header()}

        cfg = self._extract_player(html)
        if not cfg:
            return {'parse': 1, 'url': play_url, 'header': self._play_header()}

        enc = str(cfg.get('encrypt', 0))
        raw = cfg.get('url') or ''
        if enc == '1':
            raw = urllib.parse.unquote(raw)
        elif enc == '2':
            try:
                import base64
                raw = urllib.parse.unquote(base64.b64decode(raw).decode('utf-8'))
            except Exception:
                pass
        raw = self._unescape(raw).strip()

        # 直链 (mp4 / m3u8 ...) 直接播
        if raw.startswith('http') and self.isVideoFormat(raw):
            return self._play(raw)

        # 令牌型线路 (vwnet / zijianm3u8 等) -> 按 from 路由到站点自带解析器解出真实 m3u8
        from_src = (cfg.get('from') or '').strip()
        if raw:
            endpoints = []
            if from_src and from_src in self.JX_PARSE:
                endpoints.append(self.JX_PARSE[from_src])
            for ep in self.JX_FALLBACK:
                if ep not in endpoints:
                    endpoints.append(ep)
            for ep in endpoints:
                m3 = self._resolve_jx(raw, ep)
                if m3:
                    return self._play(m3)

        # 兜底: 交给壳解析
        return {'parse': 1, 'url': play_url, 'header': self._play_header()}

    @staticmethod
    def _extract_player(html):
        i = html.find('player_data')
        if i < 0:
            return None
        j = html.find('{', i)
        if j < 0:
            return None
        depth, end = 0, -1
        for k in range(j, len(html)):
            c = html[k]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = k
                    break
        if end < 0:
            return None
        try:
            return json.loads(html[j:end + 1])
        except Exception:
            return None

    @staticmethod
    def _unescape(s):
        """解析器页面里的链接可能带 \\/ \u0026 之类的转义, 统一还原"""
        if not s:
            return ''
        s = s.replace('\\/', '/')
        try:
            return json.loads('"%s"' % s.replace('"', '\\"'))
        except Exception:
            pass
        try:
            s = re.sub(r'\\u([0-9a-fA-F]{4})',
                       lambda m: chr(int(m.group(1), 16)), s)
        except Exception:
            pass
        return s

    def _resolve_jx(self, token, endpoint):
        """站点自带解析器: 令牌 -> 真实 m3u8 直链 (取出的链接必须以 http 开头)
        endpoint 形如 '/index3.php?url=' 或完整 url"""
        if not token or not endpoint:
            return ''
        target = (endpoint if endpoint.startswith('http')
                  else self.JX_HOST + endpoint) + urllib.parse.quote(token, safe='')
        try:
            r = self._sess().get(target, headers=self._headers(self._host + '/'),
                                 timeout=20, verify=False)
            r.encoding = 'utf-8'
            t = r.text
            if 'Warning' in t or 'Undefined' in t:
                return ''
            cands = []
            m = re.search(r'var\s+playUrl\s*=\s*[\'"]([^\'"]+)[\'"]', t)
            if m:
                cands.append(m.group(1))
            for mm in re.finditer(r'[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]', t):
                cands.append(mm.group(1))
            for c in cands:
                c = self._unescape(c).strip()
                if c.startswith('http'):
                    return c
        except Exception as e:
            self._log('jx fail %s %s' % (type(e).__name__, token[:40]))
        return ''

    def _play_header(self):
        return {
            'User-Agent': self.UA,
            'Referer': self._host + '/',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': '*/*',
        }

    def _play(self, url):
        url = (url or '').replace('\\/', '/').strip()
        # 直链必须是 http(s) 开头且为媒体格式, 否则一律交给壳解析 (避免把 JS 片段误判成直链)
        if url.startswith('http') and self.isVideoFormat(url):
            return {'parse': 0, 'jx': 0, 'url': url, 'header': self._play_header()}
        return {'parse': 1, 'jx': 1, 'url': url, 'header': self._play_header()}

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg='1'):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        if page < 1:
            page = 1

        wd = (key or '').strip()
        if not wd:
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': 0, 'total': 0}

        wd_q = urllib.parse.quote(wd)
        url = '%s/index.php/vod/search/wd/%s.html' % (self._host, wd_q)
        if page > 1:
            url = '%s/index.php/vod/search/wd/%s/page/%d.html' % (self._host, wd_q, page)

        # 站点限制搜索间隔 10 秒, throttle 取 11 秒避免命中限流
        self._throttle('search', 11.0)
        html = self._get(url)
        vods = self._parse_search(html)

        return {
            'list': vods,
            'page': page,
            'pagecount': 1 if vods else 0,
            'limit': len(vods) or 10,
            'total': len(vods),
        }

    def _parse_search(self, html):
        """搜索结果在 #searchList 里, 卡片是左图右文的媒体布局"""
        vods = []
        if not html:
            return vods
        i = html.find('id="searchList"')
        seg = html[i:] if i >= 0 else ''
        if not seg:
            return vods
        seen = set()
        for block in re.findall(r'<li class="clearfix">(.*?)</li>', seg, re.S):
            m = re.search(
                r'href="(/index\.php/vod/detail/id/(\d+)\.html)"[^>]*'
                r'title="([^"]*)"[^>]*data-original="([^"]*)"', block)
            if not m:
                m = re.search(
                    r'<h4 class="title">\s*<a[^>]*'
                    r'href="(/index\.php/vod/detail/id/(\d+)\.html)"[^>]*>(.*?)</a>',
                    block, re.S)
            if not m:
                continue
            href, vid, name = m.group(1), m.group(2), m.group(3)
            if not vid or vid in seen:
                continue
            name = self._strip(name)
            if not name:
                continue
            pic = ''
            pm = re.search(r'data-original="([^"]+)"', block)
            if pm:
                pic = pm.group(1)
            remark = ''
            rm = re.search(r'class="tag"[^>]*>(.*?)</span>', block, re.S)
            if rm:
                remark = self._strip(rm.group(1))
            seen.add(vid)
            vods.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': self._fix(pic),
                'vod_remarks': remark,
            })
        return vods


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    home = sp.homeContent(True)
    print('分类:', [c['type_name'] for c in home['class']])
    print('首页推荐:', len(home.get('list') or []))

    # 1) 各父分类的子分类(筛选器)是否齐全
    for tid, cname in sp.CATEGORIES:
        subs = [g for g in home['filters'].get(tid, []) if g['key'] == 'sub']
        names = [v['n'] for v in subs[0]['value']] if subs else []
        print('子分类[%s]:' % cname, names)

    # 2) 子分类逐个可用性 (取各父分类最后一个子分类)
    for tid, cname in sp.CATEGORIES:
        subs = [g for g in home['filters'].get(tid, []) if g['key'] == 'sub']
        if not subs:
            continue
        sv = subs[0]['value'][-1]
        r = sp.categoryContent(tid, 1, True, {'sub': sv['v']})
        print('  %s -> %s(%s): %d 条, 共 %d 页' %
              (cname, sv['n'], sv['v'], len(r['list']), r['pagecount']))

    # 3) 剧集-港台剧 子分类 翻页
    r1 = sp.categoryContent('2', 1, True, {'sub': '14'})
    r2 = sp.categoryContent('2', 2, True, {'sub': '14'})
    print('剧集-港台剧 P1/P2:', len(r1['list']), '/', len(r2['list']),
          '| P1首条:', r1['list'][0]['vod_name'] if r1['list'] else None,
          '| P2首条:', r2['list'][0]['vod_name'] if r2['list'] else None)

    # 4) 筛选组合 + 翻页 (旧版此处会退回第 1 页)
    ext = {'area': urllib.parse.quote('香港'), 'year': '2026', 'by': 'time'}
    r3 = sp.categoryContent('14', 1, True, ext)
    r4 = sp.categoryContent('14', 2, True, ext)
    print('港台剧+香港+2026+time P1/P2:', len(r3['list']), '/', len(r4['list']),
          '| P1首条:', r3['list'][0]['vod_name'] if r3['list'] else None,
          '| P2首条:', r4['list'][0]['vod_name'] if r4['list'] else None)

    # 5) 动漫 / 短剧 子分类 (旧版缺失)
    for tid, sub in [('4', '25'), ('5', '29')]:
        r = sp.categoryContent(tid, 1, True, {'sub': sub})
        print('子分类 tid=%s sub=%s: %d 条, 共 %d 页' %
              (tid, sub, len(r['list']), r['pagecount']))

    # 6) 详情 + 播放 + 搜索
    if r1['list']:
        first = r1['list'][0]
        print('样例:', first['vod_name'], '|', first['vod_remarks'], '|',
              first['vod_pic'][:50])
        v = sp.detailContent([first['vod_id']])['list'][0]
        print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'])
        print('  主演:', v['vod_actor'][:60], '| 地区:', v['vod_area'],
              '| 年份:', v['vod_year'])
        ep = v['vod_play_url'].split('$$$')[0].split('#')[0].split('$')[-1]
        print('播放解析:', sp.playerContent('', ep))

    print('搜索:', [x['vod_name']
                   for x in sp.searchContent('地狱大状', False, '1')['list']][:5])
