# -*- coding: utf-8 -*-
# 新视讯影视：由 分享者新视讯.js 移植的 TVBox / 鱼壳 webhtv Python 插件。
# 用法：本文件放到手机 /sdcard/py/分享者新视讯.py，站点配置 api 填 file:///sdcard/py/分享者新视讯.py
# 对接站点：m.sunnafh.com（/api/mw-movie/anonymous/* 接口），只做接口读取与解析，不存任何片源。
#
# 移植说明：
#   原版是 TVBox 的 JS 爬虫（var rule = {...} + js: 代码块），这里改成标准 Python Spider，
#   列表 / 搜索 / 详情 / 播放四条链路的参数、签名、字段映射与原版一一对应。
#   签名算法：sign = SHA1( MD5( "参数串&key=xxx&t=毫秒时间戳" ).hexdigest() )，与原版一致。
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    from base.spider import Spider
except ImportError:
    sys.path.append('..')
    from base.spider import Spider

# ---------------------------------------------------------------- 基础配置
BASE = 'https://m.sunnafh.com'
SIGN_KEY = 'cb808529bae6b6be45ecfab29a4889bc'
DEVICE_ID = '63ffad23-a598-4f96-85d7-7bf5f3e4a0a2'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

LIST_API = '/api/mw-movie/anonymous/video/list'
SEARCH_API = '/api/mw-movie/anonymous/video/searchByWordPageable'
DETAIL_API = '/api/mw-movie/anonymous/video/detail'
PLAY_API = '/api/mw-movie/anonymous/v2/video/episode/url'

PAGE_SIZE = 30
SEARCH_SIZE = 12
TIMEOUT = 15
RETRY = 3
RETRY_BACKOFF = 0.4

HOME_TTL = 300
CATEGORY_TTL = 60
SEARCH_TTL = 120
DETAIL_TTL = 300
PLAY_TTL = 20          # 播放地址带时效签名，只缓存极短时间

CLASSES = [
    {'type_id': '1', 'type_name': '电影'},
    {'type_id': '2', 'type_name': '电视剧'},
    {'type_id': '3', 'type_name': '综艺'},
    {'type_id': '4', 'type_name': '动漫'},
]

SORT_OPTS = [
    {'n': '最新', 'v': '1'},
    {'n': '最热', 'v': '2'},
    {'n': '好评', 'v': '3'},
]

# 直链正则：能直接丢给播放器的地址
VIDEO_RE = re.compile(r'\.(m3u8|mp4|flv|mkv|ts|mov)(\?|$)', re.I)
M3U8_RE = re.compile(r'\.m3u8(\?|$)', re.I)

_cache = {}


# ---------------------------------------------------------------- 小工具
def text(value):
    return '' if value is None else str(value).strip()


def page_of(value):
    m = re.match(r'\s*[+-]?\d+', text(value))
    return max(1, int(m.group(0))) if m else 1


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_list(value):
    return value if isinstance(value, list) else []


def clean_html(value):
    s = text(value)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
    return re.sub(r'\s+', ' ', s).strip()


def cached(key, ttl, loader):
    """带 TTL 的轻量缓存，避免边翻页边搜把接口打爆。"""
    now = time.time()
    item = _cache.get(key)
    if item and item[0] > now:
        return item[1]
    value = loader()
    if len(_cache) > 300:
        _cache.clear()
    _cache[key] = (now + ttl, value)
    return value


def sign_of(pairs, ts):
    """与原版一致：SHA1( MD5(参数串 + key + t) 的十六进制字符串 )"""
    raw = '&'.join('%s=%s' % (k, v) for k, v in pairs) + '&key=' + SIGN_KEY + '&t=' + ts
    return hashlib.sha1(hashlib.md5(raw.encode('utf-8')).hexdigest().encode('utf-8')).hexdigest()


def http_json(path, pairs, retry=RETRY, timeout=TIMEOUT):
    """带签名的匿名接口请求，网络抖动时退避重试。"""
    last = None
    for i in range(max(1, retry)):
        try:
            ts = str(int(time.time() * 1000))
            query = urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)
            headers = {
                'User-Agent': UA,
                'Accept': 'application/json, text/plain, */*',
                'deviceId': DEVICE_ID,
                'sign': sign_of(pairs, ts),
                't': ts,
            }
            req = urllib.request.Request(BASE + path + '?' + query, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
            data = json.loads(body.decode('utf-8', 'replace'))
            code = data.get('code')
            if code not in (0, 200):
                raise RuntimeError('接口返回 code=%s msg=%s' % (code, data.get('msg')))
            return data
        except Exception as exc:                     # 网络/解析/接口抖动统一重试
            last = exc
            if i + 1 < retry:
                time.sleep(RETRY_BACKOFF * (i + 1))
    raise last


def img_of(url):
    """源站海报是 webp，部分 TVBox 版本认不出；走它的图片处理参数转成 jpg。"""
    url = text(url)
    if not url:
        return ''
    if '.webp' in url.lower() and 'x-oss-process' not in url:
        url += ('&' if '?' in url else '?') + 'x-oss-process=image/format,jpg'
    return url


def year_of(row):
    year = text(row.get('vodYear'))
    if year:
        return year
    m = re.match(r'(\d{4})', text(row.get('vodPubdate')))
    return m.group(1) if m else ''


def vod_item(row):
    """列表 / 搜索共用的条目映射（字段来自原版一级与搜索代码块）。"""
    return {
        'vod_id': text(row.get('vodId')),
        'vod_name': text(row.get('vodName')),
        'vod_pic': img_of(row.get('vodPic')),
        'vod_remarks': text(row.get('vodRemarks')) or text(row.get('vodVersion')),
        'vod_year': year_of(row),
    }


def rank_by_keyword(rows, kw):
    """站方搜索是分词模糊匹配，把片名真正含关键词的排前面（不删结果，避免误杀）。"""
    key = text(kw).lower()
    if not key:
        return rows
    hit = [x for x in rows if key in text(x.get('vodName')).lower()]
    if not hit:
        return rows
    rest = [x for x in rows if key not in text(x.get('vodName')).lower()]
    return hit + rest


def split_play_id(value):
    """播放 id 兼容三种写法：'剧id|集id'、新视讯原始播放页 URL、'剧id_集id'。"""
    s = text(value)
    m = re.search(r'/sid/(\d+)', s)
    if m:
        nid = m.group(1)
        m2 = re.search(r'/play/(\d+)', s)
        return (m2.group(1) if m2 else ''), nid
    if '|' in s:
        parts = s.split('|')
        if len(parts) >= 2:
            return parts[0].strip(), parts[-1].strip()
    if '_' in s:
        parts = s.split('_')
        if len(parts) >= 2 and parts[0].isdigit() and parts[-1].isdigit():
            return parts[0], parts[-1]
    return '', ''


def pick_play_url(items):
    """一条剧集通常返回多档清晰度，优先挑能直接播的 m3u8，其次分辨率最高的。"""
    best, best_score = '', -1
    for it in items:
        url = text(it.get('url'))
        if not url or not VIDEO_RE.search(url):
            continue
        res = to_int(it.get('resolution'), 0)
        score = res + (1000 if M3U8_RE.search(url) else 0)
        if score > best_score:
            best, best_score = url, score
    if not best:
        for it in items:
            url = text(it.get('url'))
            if url:
                return url
    return best


# ---------------------------------------------------------------- 插件主体
class Spider(Spider):

    def getName(self):
        return '新视讯影视'

    def init(self, extend=''):
        # 站点换域名时，可在配置里传 {"host": "https://新域名"}，不用改文件
        global BASE
        cfg = text(extend)
        if cfg.startswith('{'):
            try:
                data = json.loads(cfg)
                host = text(data.get('host') or data.get('site') or data.get('base'))
                if host:
                    BASE = host.rstrip('/')
            except Exception:
                pass
        return

    def isVideoFormat(self, url):
        return bool(VIDEO_RE.search(text(url)))

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        result = {'class': CLASSES}
        if filter:
            result['filters'] = {
                c['type_id']: [{'key': 'sort', 'name': '排序', 'value': SORT_OPTS}]
                for c in CLASSES
            }
        return result

    def homeVideoContent(self):
        try:
            return {'list': self.categoryContent('1', 1, False, {}).get('list', [])}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        tid = text(tid) or '1'
        pg = page_of(pg)
        sort = '1'
        if isinstance(extend, dict) and text(extend.get('sort')):
            sort = text(extend.get('sort'))
        pairs = [
            ('pageNum', pg),
            ('pageSize', PAGE_SIZE),
            ('sort', sort),
            ('sortBy', '1'),
            ('type1', tid),
        ]
        try:
            data = cached('cat:%s:%s:%s' % (tid, sort, pg), CATEGORY_TTL,
                          lambda: http_json(LIST_API, pairs))
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': pg, 'limit': PAGE_SIZE, 'total': 0}
        body = data.get('data') or {}
        rows = as_list(body.get('list'))
        return {
            'list': [vod_item(x) for x in rows],
            'page': pg,
            'pagecount': to_int(body.get('totalPage'), pg) or pg,
            'limit': PAGE_SIZE,
            'total': to_int(body.get('totalCount'), len(rows)),
        }

    def detailContent(self, ids):
        tid = text(ids[0] if ids else '')
        tid = tid.split('|')[0].strip()
        if not tid:
            return {'list': []}
        try:
            data = cached('detail:' + tid, DETAIL_TTL,
                          lambda: http_json(DETAIL_API, [('id', tid)]))
        except Exception:
            return {'list': []}
        info = data.get('data') or {}

        plays = []
        for idx, ep in enumerate(as_list(info.get('episodeList'))):
            nid = text(ep.get('nid'))
            if not nid:
                continue
            name = text(ep.get('name')).replace('$', ' ').replace('#', ' ')
            if not name:
                name = '第%d集' % (idx + 1)
            plays.append('%s$%s|%s' % (name, tid, nid))

        vod = {
            'vod_id': tid,
            'vod_name': text(info.get('vodName')),
            'vod_pic': img_of(info.get('vodPic')),
            'type_name': text(info.get('vodClass')),
            'vod_year': text(info.get('vodYear')),
            'vod_area': text(info.get('vodArea')),
            'vod_lang': text(info.get('vodLang')),
            'vod_remarks': text(info.get('vodRemarks')),
            'vod_actor': text(info.get('vodActor')),
            'vod_director': text(info.get('vodDirector')),
            'vod_content': clean_html(info.get('vodContent')),
            'vod_play_from': '分享者在线',
            'vod_play_url': '#'.join(plays),
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        kw = text(key)
        page = page_of(pg)
        if not kw:
            return {'list': [], 'page': page, 'pagecount': 0, 'limit': SEARCH_SIZE, 'total': 0}
        pairs = [
            ('keyword', kw),
            ('pageNum', page),
            ('pageSize', SEARCH_SIZE),
            ('type', 'false'),
        ]
        try:
            data = cached('search:%s:%s' % (kw, page), SEARCH_TTL,
                          lambda: http_json(SEARCH_API, pairs))
        except Exception:
            return {'list': [], 'page': page, 'pagecount': page, 'limit': SEARCH_SIZE, 'total': 0}
        body = data.get('data') or {}
        rows = rank_by_keyword(as_list(body.get('list')), kw)
        return {
            'list': [vod_item(x) for x in rows],
            'page': page,
            'pagecount': to_int(body.get('totalPage'), page) or page,
            'limit': SEARCH_SIZE,
            'total': to_int(body.get('totalCount'), len(rows)),
        }

    def playerContent(self, flag, id, vipFlags=None):
        pid, nid = split_play_id(id)
        url = ''
        if pid and nid:
            pairs = [('clientType', '1'), ('id', pid), ('nid', nid)]
            try:
                data = cached('play:%s:%s' % (pid, nid), PLAY_TTL,
                              lambda: http_json(PLAY_API, pairs, retry=2))
                items = as_list((data.get('data') or {}).get('list'))
                url = pick_play_url(items)
            except Exception:
                url = ''

        header = {'User-Agent': UA}
        if url:
            if VIDEO_RE.search(url):
                return {'parse': 0, 'playUrl': '', 'url': url, 'header': header}
            # 不是直链，交给客户端嗅探 / 解析
            return {'parse': 1, 'playUrl': '', 'url': url, 'header': header}

        # 接口没给地址时，退回原版播放页，让客户端自己去探
        fallback = '%s/vod/play/%s/sid/%s' % (BASE, pid, nid) if pid and nid else text(id)
        return {'parse': 1, 'playUrl': '', 'url': fallback, 'header': header}

    def localProxy(self, param):
        return None

    def destroy(self):
        _cache.clear()
