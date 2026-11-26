# -*- coding: utf-8 -*-
# 南瓜影视：由 南瓜影视.js 移植的 TVBox / 鱼壳 webhtv Python 插件。
# 用法：本文件放到手机 /sdcard/py/南瓜影视.py，站点配置 api 填 file:///sdcard/py/南瓜影视.py
# 对接站点：nangua.tv（接口 api.apinangua.com），只做接口读取与解析，不在本地存任何片源。
import json
import re
import time
import urllib.parse

import requests

try:
    from base.spider import Spider
except ImportError:
    import sys

    sys.path.append('..')
    from base.spider import Spider

# ---------------------------------------------------------------- 基础配置
BASE = 'https://api.apinangua.com'
SITE_URL = 'https://nangua.tv'
# 与 JS 版保持一致的客户端标识（站点按 UA 区分接口）
UA = ('jqtfgshv.gwmzbj.ymfxzmmrhh/47 (Linux; U; Android 16; zh_CN; '
      'Xiaomi 17 Ultra; Build/BP2A.250605.031.A3; Cronet/143.0.7445.0)')
HDR = {
    'User-Agent': UA,
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/plain, */*',
}
PLAY_HDR = {'User-Agent': 'ExoPlayer'}

PAGE_SIZE = 30
SEARCH_SIZE = 30
TIMEOUT = 12
RETRY = 2
RETRY_BACKOFF = 0.4

HOME_TTL = 6 * 3600
CONFIG_TTL = 6 * 3600
SEARCH_TTL = 120
DETAIL_TTL = 300
CATEGORY_TTL = 60

SORT_OPTS = [
    {'n': '最新', 'v': 'new'},
    {'n': '最热', 'v': 'hot'},
    {'n': '评分', 'v': 'rating'},
]

# 图片 CDN 前缀，由 /api/config 的 storageBases 填充
_img_bases = []
_cache = {}


# ---------------------------------------------------------------- 小工具
def text(value):
    return '' if value is None else str(value).strip()


def page_of(value):
    m = re.match(r'\s*[+-]?\d+', '' if value is None else str(value))
    return max(1, int(m.group(0))) if m else 1


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_items(data):
    """接口的 data 有时是数组，有时是 {list: [...]}，统一成列表。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('list', 'items', 'videos'):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def cached(key, ttl, loader):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = loader()
    if value:
        _cache[key] = (now + ttl, value)
    return value


def build_url(path, params=None):
    url = BASE + path
    if params:
        pairs = []
        for k, v in params.items():
            if v is None or v == '':
                continue
            pairs.append('%s=%s' % (urllib.parse.quote(str(k), safe=''),
                                    urllib.parse.quote(str(v), safe='')))
        if pairs:
            url += '?' + '&'.join(pairs)
    return url


def get_data(path, params=None, timeout=TIMEOUT, tries=RETRY):
    """打接口取 data。站点会间歇性抽风（HTTP 200 但 code!=0 / 空 body），所以带退避重试。"""
    url = build_url(path, params)
    last = None
    for attempt in range(tries + 1):
        try:
            resp = requests.get(url, headers=HDR, timeout=timeout)
            if resp.status_code != 200:
                last = 'http %s' % resp.status_code
            else:
                body = resp.json()
                code = str(body.get('code')) if isinstance(body, dict) else ''
                if code in ('0', '200', 'ok', 'success') and 'data' in body:
                    return body['data']
                last = 'code %s' % code
        except Exception as exc:  # 网络抖动 / JSON 损坏都算可重试
            last = str(exc)
        if attempt < tries:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


def img_of(path):
    url = text(path)
    if not url:
        return ''
    if not re.match(r'^https?://', url, re.I) and _img_bases:
        return _img_bases[0].rstrip('/') + '/' + url.lstrip('/')
    return url


# ---------------------------------------------------------------- 数据映射
def vod_item(row):
    if not isinstance(row, dict) or row.get('id') is None:
        return None
    item = {
        'vod_id': str(row.get('id')),
        'vod_name': text(row.get('title')),
        'vod_pic': img_of(row.get('cover') or row.get('wide')),
        'vod_remarks': text(row.get('latest') or row.get('category')),
        'vod_year': text(row.get('year')),
        'vod_area': text(row.get('region')),
        'vod_lang': text(row.get('language')),
        'vod_director': text(row.get('director')),
    }
    actors = row.get('actors')
    if isinstance(actors, list) and actors:
        item['vod_actor'] = ','.join([text(a) for a in actors if text(a)])
    if row.get('rating') is not None:
        item['vod_score'] = text(row.get('rating'))
    return item


def uniq_options(names, first_all=True):
    out = [{'n': '全部', 'v': 'all'}] if first_all else []
    seen = set()
    for raw in names:
        name = text(raw)
        if name and name not in seen:
            seen.add(name)
            out.append({'n': name, 'v': name})
    return out


# ---------------------------------------------------------------- 站点数据装配
def load_config():
    def fetch():
        data = get_data('/api/config', tries=1)
        if not isinstance(data, dict):
            return None
        bases = data.get('storageBases')
        if isinstance(bases, list):
            global _img_bases
            _img_bases = [text(b).rstrip('/') for b in bases
                          if re.match(r'^https?://', text(b), re.I)]
        return data

    data = cached('config', CONFIG_TTL, fetch)
    site = (data or {}).get('site') if isinstance(data, dict) else None
    if isinstance(site, dict) and site.get('url'):
        global SITE_URL
        SITE_URL = text(site.get('url'))
    return data or {}


def load_home():
    """拉 /api/home 并整理成：分类 + 每个分类的筛选项 + 首页推荐列表。"""

    def fetch():
        data = get_data('/api/home', tries=RETRY)
        if not isinstance(data, dict):
            return None
        return parse_home(data)

    home = cached('home', HOME_TTL, fetch)
    if home:
        return home
    # 首页接口挂了时的兜底：直接拿电影频道热门，至少不空
    rows = as_items(get_data('/api/channel/movie', {'sort': 'hot', 'size': PAGE_SIZE, 'page': 1})) or []
    items = [x for x in (vod_item(r) for r in rows) if x]
    return {'classes': [{'type_id': 'movie', 'type_name': '电影'}],
            'filters': {}, 'list': items, 'regions': [], 'years': [], 'genres': {}}


def parse_home(data):
    classes, class_seen = [], set()
    rows = data.get('rows') if isinstance(data.get('rows'), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel = text(row.get('channel'))
        if channel and channel not in class_seen:
            class_seen.add(channel)
            classes.append({'type_id': channel, 'type_name': text(row.get('name')) or channel})

    tiles = data.get('tv_tiles') if isinstance(data.get('tv_tiles'), list) else []
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = text(tile.get('key'))
        if key and key != 'featured' and key not in class_seen:
            class_seen.add(key)
            classes.append({'type_id': key, 'type_name': text(tile.get('title')) or key})

    picks, pick_seen = [], set()

    def collect(row):
        item = vod_item(row)
        if item and item['vod_id'] not in pick_seen and item['vod_name']:
            pick_seen.add(item['vod_id'])
            picks.append(item)

    hero = data.get('hero') if isinstance(data.get('hero'), list) else []
    for row in hero:
        collect(row)

    genres, regions, years = {}, [], []
    region_seen, year_seen = set(), set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        channel = text(row.get('channel'))
        bucket = genres.setdefault(channel, [])
        genre_seen = set(bucket)
        videos = []
        if isinstance(row.get('videos'), list):
            videos += row['videos']
        if isinstance(row.get('ranking'), list):
            videos += row['ranking']
        for video in videos:
            if not isinstance(video, dict):
                continue
            collect(video)
            category = text(video.get('category'))
            if category and category not in genre_seen:
                genre_seen.add(category)
                bucket.append(category)
            region = text(video.get('region'))
            if region and region != '其它' and not re.search(r'[/\s]', region) and region not in region_seen:
                region_seen.add(region)
                regions.append(region)
            year = text(video.get('year'))
            if re.match(r'^\d{4}$', year) and year not in year_seen:
                year_seen.add(year)
                years.append(year)

    for row in hero:
        if not isinstance(row, dict):
            continue
        region = text(row.get('region'))
        if region and region != '其它' and not re.search(r'[/\s]', region) and region not in region_seen:
            region_seen.add(region)
            regions.append(region)
        year = text(row.get('year'))
        if re.match(r'^\d{4}$', year) and year not in year_seen:
            year_seen.add(year)
            years.append(year)

    years.sort(reverse=True)
    filters = dict((c['type_id'], filters_of_from(genres, regions, years)) for c in classes)
    return {'classes': classes, 'filters': filters, 'list': picks,
            'regions': regions, 'years': years, 'genres': genres}


def filters_of_from(genres, regions, years, tid=None):
    return [
        {'key': 'genre', 'name': '类型', 'init': 'all', 'value': uniq_options(genres.get(tid) or [])},
        {'key': 'region', 'name': '地区', 'init': 'all', 'value': uniq_options(regions)},
        {'key': 'year', 'name': '年份', 'init': 'all', 'value': uniq_options(years)},
        {'key': 'sort', 'name': '排序', 'init': 'new', 'value': SORT_OPTS},
    ]


# ---------------------------------------------------------------- 对外动作
def home_content(extend=''):
    load_config()
    home = load_home()
    classes = list(home.get('classes') or [])
    if classes:
        classes.insert(0, {'type_id': 'home', 'type_name': '首页'})
    filters = {}
    for cls in classes:
        tid = cls['type_id']
        if tid == 'home':
            continue
        filters[tid] = filters_of_from(home.get('genres') or {},
                                       home.get('regions') or [],
                                       home.get('years') or [],
                                       tid)
    return {'class': classes, 'filters': filters}


def home_vod():
    return {'list': load_home().get('list') or []}


def parse_extend(extend):
    if isinstance(extend, dict):
        return extend
    if isinstance(extend, str) and extend.strip():
        try:
            value = json.loads(extend)
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}
    return {}


def category_content(tid, pg, extend=None):
    tid = text(tid) or 'movie'
    page = page_of(pg)
    if tid == 'home':
        home = load_home()
        return {'list': home.get('list') or [], 'page': 1, 'pagecount': 1, 'limit': len(home.get('list') or []), 'total': len(home.get('list') or [])}

    ext = parse_extend(extend)
    params = {'page': page, 'size': PAGE_SIZE}
    for key in ('genre', 'region', 'year'):
        value = text(ext.get(key))
        if value and value != 'all':
            params[key] = value
    sort = text(ext.get('sort'))
    params['sort'] = sort if sort and sort != 'all' else 'new'

    key = 'cat:%s:%s:%s' % (tid, page, json.dumps(params, sort_keys=True))
    data = cached(key, CATEGORY_TTL, lambda: get_data('/api/channel/' + urllib.parse.quote(tid, safe=''), params))

    items = [x for x in (vod_item(r) for r in as_items(data)) if x]
    pagecount = page
    if isinstance(data, dict):
        total = to_int(data.get('total'))
        size = to_int(data.get('size')) or PAGE_SIZE
        if total > 0:
            pagecount = max(1, (total + size - 1) // size)
    if len(items) < PAGE_SIZE:
        pagecount = page
    return {'list': items, 'page': page, 'pagecount': pagecount, 'limit': PAGE_SIZE, 'total': len(items)}


def search_content(key, pg='1'):
    word = text(key)
    page = page_of(pg)
    if not word:
        return {'list': [], 'page': page, 'pagecount': page, 'limit': SEARCH_SIZE, 'total': 0}

    def fetch():
        return get_data('/api/search', {'q': word, 'page': page, 'size': SEARCH_SIZE})

    data = cached('search:%s:%s' % (word, page), SEARCH_TTL, fetch)
    items = [x for x in (vod_item(r) for r in as_items(data)) if x]
    pagecount = page
    if isinstance(data, dict):
        total = to_int(data.get('total'))
        size = to_int(data.get('size')) or SEARCH_SIZE
        if total > 0:
            pagecount = max(1, (total + size - 1) // size)
    if len(items) < SEARCH_SIZE:
        pagecount = page
    return {'list': items, 'page': page, 'pagecount': pagecount, 'limit': SEARCH_SIZE, 'total': len(items)}


def clean_html(value):
    raw = text(value)
    if not raw:
        return ''
    raw = re.sub(r'<[^>]*>', '', raw)
    for src, dst in (('&nbsp;', ' '), ('&amp;', '&'), ('&quot;', '"'),
                     ('&#39;', "'"), ('&lt;', '<'), ('&gt;', '>'), ('&ldquo;', '“'), ('&rdquo;', '”')):
        raw = raw.replace(src, dst)
    return re.sub(r'[ \t]+', ' ', raw).strip()


def detail_content(ids):
    vod_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
    vod_id = text(vod_id)
    if not vod_id:
        return {'list': []}

    def fetch():
        return get_data('/api/video/' + urllib.parse.quote(vod_id, safe=''))

    data = cached('detail:%s' % vod_id, DETAIL_TTL, fetch)
    if not isinstance(data, dict):
        return {'list': []}

    item = {
        'vod_id': text(data.get('id')) or vod_id,
        'vod_name': text(data.get('title')),
        'vod_pic': img_of(data.get('cover') or data.get('wide')),
        'vod_year': text(data.get('year')),
        'vod_remarks': text(data.get('latest') or data.get('category')),
        'vod_content': clean_html(data.get('description')),
        'vod_area': text(data.get('region')),
        'vod_lang': text(data.get('language')),
        'vod_director': text(data.get('director')),
        'vod_actor': ','.join([text(a) for a in (data.get('actors') or []) if text(a)]),
        'type_name': text(data.get('category')),
    }
    if data.get('rating') is not None:
        item['vod_score'] = text(data.get('rating'))

    froms, urls, used = [], [], {}
    sources = data.get('sources') if isinstance(data.get('sources'), list) else []
    for src in sources:
        if not isinstance(src, dict):
            continue
        episodes = src.get('episodes') if isinstance(src.get('episodes'), list) else []
        if not episodes:
            continue
        name = text(src.get('name')) or '线路'
        if name in used:
            used[name] += 1
            name = '%s%d' % (name, used[name])
        else:
            used[name] = 1

        parts = []
        for idx, ep in enumerate(episodes):
            if not isinstance(ep, dict):
                continue
            url = text(ep.get('url'))
            if not url:
                continue
            ep_name = text(ep.get('name')) or ('第%d集' % (idx + 1))
            parts.append('%s$%s' % (ep_name, url))
        if not parts:
            continue
        froms.append(name)
        urls.append('#'.join(parts))

    item['vod_play_from'] = '$$$'.join(froms)
    item['vod_play_url'] = '$$$'.join(urls)
    return {'list': [item]}


def is_media_url(url):
    return bool(re.search(r'\.(?:m3u8|mp4|mkv|flv|avi|ts|mov|webm|m4v|mpd)(?:\?|$)', text(url), re.I))


def play_content(flag, play_id):
    url = text(play_id)
    if not url:
        return {'parse': 0, 'url': '', 'header': dict(PLAY_HDR)}
    # 站点给的本来就是可直连的 m3u8（少数是 mp4），直接交播放器；别丢 UA，部分 CDN 会挑。
    return {'parse': 0, 'url': url, 'header': dict(PLAY_HDR)}


# ---------------------------------------------------------------- TVBox 入口
class Spider(Spider):
    extend = ''

    def getName(self):
        return '🎃 南瓜影视'

    def init(self, extend=''):
        self.extend = extend or ''
        # ext 里可以覆盖接口域名：{"host": "https://api.apinangua.com", "site": "https://nangua.tv"}
        global BASE, SITE_URL
        conf = parse_extend(extend)
        host = text(conf.get('host'))
        if host and re.match(r'^https?://', host, re.I):
            BASE = host.rstrip('/')
        site = text(conf.get('site'))
        if site:
            SITE_URL = site

    def isVideoFormat(self, url):
        return is_media_url(url)

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        return home_content(self.extend)

    def homeVideoContent(self):
        return home_vod()

    def categoryContent(self, tid, pg, filter, extend):
        return category_content(tid, pg, extend)

    def detailContent(self, ids):
        return detail_content(ids)

    def searchContent(self, key, quick, pg='1'):
        return search_content(key, pg)

    def playerContent(self, flag, id, vipFlags=None):
        return play_content(flag, id)

    def localProxy(self, param):
        return None

    def destroy(self):
        pass
