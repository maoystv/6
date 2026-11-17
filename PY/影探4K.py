# -*- coding: utf-8 -*-
# 影探4K：由 影探4k.js 移植到鱼壳 webhtv 站点注入使用的 Python Spider。
# 用法：把本文件放到手机 /sdcard/py/影探4K.py，站点配置 api 填 file:///sdcard/py/影探4K.py
import base64
import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

try:
    from base.spider import Spider
except ImportError:
    import sys
    sys.path.append('..')
    from base.spider import Spider

KEY = 'yingtan4k'
HOST = 'http://cms.lyyytv.cn'
CMS_KEY = 'wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy'

# 解析接口（fys.lyyytv.cn 放映室）
# 2026-11 实测：老的 parsesId=3 记录已删除，接口直接 500
# （ErrorException in Parses.php line 63: Trying to get property 'url' of non-object）。
# 现存可用的只有两条，按线路类型分流：
#   5 = 网页线路（腾讯/爱奇艺/芒果/优酷/B站 等页面地址）
#   6 = 4K 直链（ym4kjx.lyyytv.cn 下的 mp4/mkv，站点本身返回 404，必须靠它换链）
PARSE_API = 'http://fys.lyyytv.cn/api/index?appid=10001&videoUrl='
PARSE_ID_WEB = 5
PARSE_ID_4K = 6
HEADERS = {'User-Agent': 'okhttp/4.12.0'}
# 解析请求/回源头：对齐 JS 的 PH，避免 gzip 花屏
PARSE_HEADERS = {'User-Agent': 'okhttp/4.12.0', 'Accept-Encoding': 'identity'}

# baidu.con 前缀加密常量（对齐 yt4k.js）
DEC_PREFIX = 'https://baidu.con/'
# 解析重试轮数与退避基数（秒）
# 2026-11-17 实测：站点解析接口（parsesId 5/6/7）全部返回「解析失败」，单次耗时 10~13 秒，
# 硬等会把播放器卡死，所以轮数降到 2、单次超时压到 8 秒，连续失败后短暂熔断。
PARSE_ROUNDS = 1
PARSE_BACKOFF = 0.35
PARSE_TIMEOUT = 6
# 解析接口连续失败后的熔断窗口（秒）：期间不再硬打，直接走兜底
PARSE_TRIP_TTL = 300
PARSE_TRIP_LIMIT = 2
# 同一原始地址解析结果缓存窗口（秒）
PLAY_CACHE_TTL = 120
# 直链探活超时（秒）与结果缓存窗口
PROBE_TIMEOUT = 3
PROBE_CACHE_TTL = 180

# 兜底采集源：站点自身播放通道（fys 解析 + ym4kjx 直链）整批失效时，
# 用这些源按片名换出可直接播放的 m3u8/mp4 地址，保证有片能看。
# 关掉兜底把 ENABLE_BACKUP 改成 False 即可。
ENABLE_BACKUP = True
BACKUP_TIMEOUT = 6
BACKUP_TTL = 900
# 原生线路地址 → 兜底地址的映射缓存窗口
PLAY_MAP_TTL = 6 * 3600
BACKUP_SOURCES = [
    {'name': '备用①', 'api': 'https://bfzyapi.com/api.php/provide/vod/'},
    {'name': '备用②', 'api': 'https://ikunzyapi.com/api.php/provide/vod/'},
    {'name': '备用③', 'api': 'https://api.ukuapi.com/api.php/provide/vod/'},
    {'name': '备用④', 'api': 'https://cj.lziapi.com/api.php/provide/vod/'},
]
BACKUP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36'}


PAGE_LIMIT = 20
FILTER_NAMES = {
    'class': '类型', 'area': '地区', 'lang': '语言', 'year': '年份',
    'letter': '字母', 'by': '排序', 'sort': '顺序',
}
HOME_CACHE_TTL = 6 * 3600

_BASE64_RE = re.compile(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?')
_LDMAX_RE = re.compile(r'^https?://ldmax\.cooom/', re.I)
_MEDIA_RE = re.compile(r'\.(?:mp4|m3u8?|flv|avi|mkv|ts|mov|wmv|webm|m4v|mpd)$', re.I)
# HLS/DASH 直链：本身就能播，不需要走解析
_STREAM_RE = re.compile(r'\.(?:m3u8?|mpd)$', re.I)
# 4K 片源主机（ym4kjx 是主站，其余子域为历史/备用）
_4K_HOST_RE = re.compile(r'(?:^|\.)(?:ym4kjx|hd4kjx|sd4kjx|mm4kjx|mv4kjx|vk4kjx)\.lyyytv\.cn$', re.I)

_home_cache = {}
_play_cache = {}
_backup_cache = {}
_play_map = {}
_probe_cache = {}
_host_dead = {}
_parse_trip = {'until': 0, 'fails': 0}


def text(value):
    return '' if value is None else str(value).strip()


def page_of(value):
    m = re.match(r'\s*[+-]?\d+', '' if value is None else str(value))
    n = int(m.group(0)) if m else 0
    return max(1, n) if n else 1


def list_of(value):
    return value if isinstance(value, list) else []


def object_of(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def get_json(url, headers=None, timeout=15):
    headers = HEADERS if headers is None else headers
    rsp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if rsp.status_code >= 400:
        raise Exception('影探4K：接口返回 %s' % rsp.status_code)
    try:
        data = object_of(rsp.json())
    except Exception:
        data = {}
    if not data:
        raise Exception('影探4K：接口未返回有效 JSON')
    return data


def cms(path, params=None):
    params = params or {}
    query = urllib.parse.urlencode(params)
    data = get_json('%s/api.php/app/%s?%s' % (HOST, path, query))
    code = data.get('code')
    if code is not None:
        try:
            ok = int(code) in (1, 200)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise Exception('影探4K：CMS 请求失败')
    return data


def decode_base64(value):
    clean = re.sub(r'\s+', '', text(value))
    if not clean or not _BASE64_RE.fullmatch(clean):
        return None
    try:
        return base64.b64decode(clean)
    except Exception:
        return None


def decrypt_lvdou(value):
    """对齐 JS decUrlOne：lvdou+ → 前16 key/后16 iv AES/CBC/PKCS7"""
    original = text(value)
    if not original.startswith('lvdou+'):
        return original
    if not CMS_KEY:
        return original
    try:
        encrypted = decode_base64(original[6:])
        if not encrypted:
            return original
        key = CMS_KEY[:16].encode('utf-8')
        iv = CMS_KEY[16:32].encode('utf-8') if len(CMS_KEY) >= 32 else key
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plain = unpad(cipher.decrypt(encrypted), AES.block_size)
        result = plain.decode('utf-8', errors='replace').strip()
        if result.startswith('http'):
            return result
    except Exception:
        pass
    return original


def is_http_url(value):
    try:
        parsed = urllib.parse.urlparse(text(value))
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


def is_site_url(value):
    if not is_http_url(value):
        return False
    host = (urllib.parse.urlparse(text(value)).hostname or '').lower()
    return host == 'lyyytv.cn' or host.endswith('.lyyytv.cn')


def is_ldmax_url(value):
    return bool(_LDMAX_RE.match(text(value)))


def decrypt_ldmax(value, depth=0):
    """兼容老加密：ldmax.cooom 前缀"""
    if depth > 5:
        return ''
    url = text(value)
    decoded = decode_base64(url)
    if decoded:
        url = re.sub(r'\s+', '', decoded.decode('utf-8', errors='replace'))
    if not is_ldmax_url(url):
        return url
    path = _LDMAX_RE.sub('', url)
    if len(path) <= 16:
        return ''
    try:
        key = path[:16][::-1].encode('utf-8')
        encrypted = decode_base64(path[16:])
        if not encrypted or len(encrypted) % 16:
            return ''
        cipher = AES.new(key, AES.MODE_CBC, key)
        plain = bytearray(cipher.decrypt(encrypted))
        pad = plain[-1]
        if 0 < pad <= 16:
            del plain[-pad:]
        result = bytes(plain).decode('utf-8', errors='replace').strip()
        return decrypt_ldmax(result, depth + 1) if is_ldmax_url(result) else result
    except Exception:
        return ''


def find_url(value):
    """对齐 JS findUrl：从解析响应 JSON 中挑出 url/playUrl/link/data.url"""
    if not isinstance(value, dict):
        return ''
    for key in ('url', 'playUrl', 'link'):
        v = value.get(key)
        if v:
            return text(v)
    return find_url(value.get('data'))


def resolve_parse(body):
    """
    对齐 JS resolveParse：
      1) JSON 包裹 → 取出 url
      2) https://baidu.con/ 前缀 → 前16位 key=iv，余下 base64 密文 AES/CBC/PKCS7
      3) 明文 URL
    """
    body = text(body)
    if not body:
        return ''

    candidate = body
    if body.startswith('{'):
        try:
            parsed = json.loads(body)
            found = find_url(parsed)
            if found:
                candidate = found
        except Exception:
            pass

    if candidate.startswith(DEC_PREFIX):
        rest = candidate[len(DEC_PREFIX):]
        if len(rest) <= 16:
            return ''
        key = rest[:16].encode('utf-8')
        cipher_b64 = rest[16:]
        # 优先按 base64 密文解密
        try:
            encrypted = base64.b64decode(cipher_b64, validate=False)
            cipher = AES.new(key, AES.MODE_CBC, key)
            plain = unpad(cipher.decrypt(encrypted), AES.block_size)
            result = plain.decode('utf-8', errors='replace').strip()
            if result.startswith('http'):
                return result
        except Exception:
            pass
        # 兜底：密文本身是 raw bytes
        try:
            raw = cipher_b64.encode('latin-1', errors='ignore')
            if raw and len(raw) % 16 == 0:
                cipher = AES.new(key, AES.MODE_CBC, key)
                plain = unpad(cipher.decrypt(raw), AES.block_size)
                result = plain.decode('utf-8', errors='replace').strip()
                if result.startswith('http'):
                    return result
        except Exception:
            pass
        return ''

    return candidate


def parse_url(raw, parse_id=PARSE_ID_WEB):
    """把原始地址拼到解析基址后请求，解出真实 URL；parse_id 选解析器（5 网页 / 6 4K 直链）。"""
    if not raw:
        return ''
    now = time.time()
    if _parse_trip['until'] > now:
        return ''
    target = '%s%s&parsesId=%d' % (PARSE_API, urllib.parse.quote(raw, safe="!'()*"), parse_id)
    for rnd in range(PARSE_ROUNDS):
        if rnd > 0:
            time.sleep(rnd * PARSE_BACKOFF)
        try:
            rsp = requests.get(target, headers=PARSE_HEADERS, timeout=PARSE_TIMEOUT)
            if rsp.status_code == 200 and rsp.text:
                resolved = resolve_parse(rsp.text)
                if resolved and resolved.startswith('http'):
                    _parse_trip['fails'] = 0
                    return resolved
        except Exception:
            pass
    _parse_trip['fails'] += 1
    if _parse_trip['fails'] >= PARSE_TRIP_LIMIT:
        _parse_trip['until'] = time.time() + PARSE_TRIP_TTL
        _parse_trip['fails'] = 0
    return ''


def is_media_url(url):
    if not is_http_url(url):
        return False
    return bool(_MEDIA_RE.search(urllib.parse.urlparse(text(url)).path))


def is_stream_url(url):
    """已经是 m3u8/mpd 的直链，播放器能直接拉，无需解析。"""
    if not is_http_url(url):
        return False
    return bool(_STREAM_RE.search(urllib.parse.urlparse(text(url)).path))


def is_4k_source(url):
    """4K 线路：ym4kjx 下的 mp4/mkv 直链（站点本身 404，要走 parsesId=6 换链）。"""
    if not is_http_url(url):
        return False
    host = (urllib.parse.urlparse(text(url)).hostname or '').lower()
    if host and _4K_HOST_RE.search(host):
        return True
    # 主机名变了也能认：非 HLS 的直链媒体文件一律当 4K 片源
    return is_media_url(url) and not is_stream_url(url)


def parse_episodes(value):
    """'第01集$url#第02集$url' → [(集名, 地址)]"""
    out = []
    for entry in text(value).split('#'):
        sep = entry.find('$')
        if sep <= 0:
            continue
        name = text(entry[:sep])
        url = text(entry[sep + 1:])
        if not url:
            continue
        out.append((name or '第%d集' % (len(out) + 1), url))
    return out


def join_episodes(items):
    return '#'.join('%s$%s' % (name, url) for name, url in items)


def norm_name(value):
    s = text(value).lower()
    return re.sub(r'[\s\u3000·:：,，.。!！?？\-_/\\()（）\[\]【】《》"\'“”‘’]', '', s)


def name_score(key, title):
    """片名相似度：同名 100，前后缀 80，包含 60，去季数/版本尾巴后再比 40。"""
    a = norm_name(key)
    b = norm_name(title)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if b.startswith(a):
        # 「流浪地球」不该认成「流浪地球2」：续集尾巴单独降级
        rest = b[len(a):]
        if re.match(r'^(\d+|ii|iii|ⅱ|ⅲ|第.{1,2}[季部])$', rest):
            return 50
        return 80
    if a.startswith(b):
        rest = a[len(b):]
        if re.match(r'^(\d+|ii|iii|ⅱ|ⅲ|第.{1,2}[季部])$', rest):
            return 50
        return 80
    if a in b:
        return 60
    if b in a:
        return 50
    core = re.sub(r'(第.{1,2}季|第.{1,2}部|完整版|国语|粤语|高清|4k|在线观看|全集)$', '', a)
    if core and core != a and (core in b or b in core):
        return 40
    return 0


def pick_streams(item):
    """从采集数据里挑一条全是直链的线路，返回 '集名$地址#集名$地址'。"""
    for line in text(item.get('vod_play_url')).split('$$$'):
        parts = []
        for entry in line.split('#'):
            sep = entry.find('$')
            if sep <= 0:
                continue
            name = text(entry[:sep])
            url = text(entry[sep + 1:])
            if not is_http_url(url):
                continue
            if not (is_stream_url(url) or is_media_url(url)):
                continue
            parts.append('%s$%s' % (name or ('第%d集' % (len(parts) + 1)), url))
        if parts:
            return '#'.join(parts)
    return ''


def backup_one(source, key):
    url = '%s?ac=detail&wd=%s' % (source['api'], urllib.parse.quote(key))
    data = get_json(url, headers=BACKUP_HEADERS, timeout=BACKUP_TIMEOUT)
    best = ''
    best_score = 0
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        score = name_score(key, item.get('vod_name'))
        if score < 60 or score <= best_score:
            continue
        line = pick_streams(item)
        if not line:
            continue
        best_score = score
        best = line
    if not best:
        return None
    eps = parse_episodes(best)
    if not eps:
        return None
    return {'name': source['name'], 'eps': eps}


def backup_episodes(name):
    """按片名去兜底源取可播地址，返回 [{'name': 线路名, 'eps': [(集名, 地址)]}]。"""
    key = text(name)
    if not ENABLE_BACKUP or not key:
        return []
    cached = _backup_cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]
    found = []
    collected = {}
    try:
        with ThreadPoolExecutor(max_workers=len(BACKUP_SOURCES)) as pool:
            jobs = {pool.submit(backup_one, src, key): i for i, src in enumerate(BACKUP_SOURCES)}
            for job in as_completed(jobs):
                try:
                    item = job.result()
                except Exception:
                    item = None
                if item:
                    collected[jobs[job]] = item
        found = [collected[i] for i in sorted(collected)]
    except Exception:
        found = []
    # 空结果也短缓存一会儿，省得反复打几个源
    _backup_cache[key] = (time.time() + (BACKUP_TTL if found else 300), found)
    return found


def probe_url(url, timeout=PROBE_TIMEOUT):
    """短超时探活：拿到 4xx/5xx 或连不上就判死，结果缓存几分钟。"""
    url = text(url)
    if not is_http_url(url):
        return False
    now = time.time()
    cached = _probe_cache.get(url)
    if cached and cached[0] > now:
        return cached[1]
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    dead_until = _host_dead.get(host, 0)
    if host and dead_until > now:
        # 同一片源主机整批失效时，别再一条条白等
        _probe_cache[url] = (now + PROBE_CACHE_TTL, False)
        return False
    ok = False
    rsp = None
    code = 0
    try:
        rsp = requests.get(url, headers=dict(PARSE_HEADERS, Range='bytes=0-2047'),
                           timeout=timeout, stream=True, allow_redirects=True)
        code = rsp.status_code
        ok = code < 400
    except Exception:
        ok = False
    finally:
        try:
            if rsp is not None:
                rsp.close()
        except Exception:
            pass
    if host and code in (404, 410):
        _host_dead[host] = now + 120
    _probe_cache[url] = (now + PROBE_CACHE_TTL, ok)
    return ok


def remember_play(origin, target):
    if origin and target and origin != target:
        if len(_play_map) > 5000:
            _play_map.clear()
        _play_map[origin] = (time.time() + PLAY_MAP_TTL, target)


def recall_play(origin):
    item = _play_map.get(text(origin))
    if item and item[0] > time.time():
        return item[1]
    return ''


def probe_many(urls):
    """并发探活一批地址，返回 {地址: 是否可播}。"""
    result = {}
    targets = []
    for u in urls:
        if is_http_url(u) and u not in targets:
            targets.append(u)
    if not targets:
        return result
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            jobs = {pool.submit(probe_url, u): u for u in targets}
            for job in as_completed(jobs):
                u = jobs[job]
                try:
                    result[u] = job.result()
                except Exception:
                    result[u] = False
    except Exception:
        for u in targets:
            result[u] = True
    return result


def direct_probe_url(line):
    """纯直链线路取第一集做探活目标；需要解析的网页线路不参与探活。"""
    eps = parse_episodes(line.get('url'))
    if eps and all(is_stream_url(u) or is_media_url(u) for _, u in eps):
        return eps[0][1]
    return ''


def mark_dead_lines(lines, alive=None):
    """直链线路先探活：活的原位保留，死的挪到末尾并标注，免得播放器拿到 404 死链。"""
    if not lines:
        return lines
    if alive is None:
        alive = probe_many([u for u in (direct_probe_url(l) for l in lines) if u])
    good = []
    dead = []
    for line in lines:
        target = direct_probe_url(line)
        if target and alive.get(target) is False:
            dead.append({'name': line['name'] + '(已失效)', 'url': line['url']})
        else:
            good.append(line)
    return good + dead



def home(extend=''):
    cache_key = '%s_home_%s' % (KEY, text(extend))
    cached = _home_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    data = cms('nav', {'token': ''})
    classes = []
    filters = {}
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        if item.get('type_id') is None or not text(item.get('type_name')):
            continue
        tid = text(item['type_id'])
        classes.append({'type_id': tid, 'type_name': text(item['type_name'])})
        ext = object_of(item.get('type_extend'))
        groups = []
        for key, name in FILTER_NAMES.items():
            values = [v for v in (text(x) for x in text(ext.get(key)).split(',')) if v]
            values = list(dict.fromkeys(values))
            if values:
                groups.append({
                    'key': key,
                    'name': name,
                    'init': '',
                    'value': [{'n': '全部', 'v': ''}] + [{'n': v, 'v': v} for v in values],
                })
        if groups:
            filters[tid] = groups
    result = {'class': classes, 'filters': filters}
    if classes:
        _home_cache[cache_key] = (time.time() + HOME_CACHE_TTL, result)
    return result


def home_vod():
    data = cms('index_video', {'token': ''})
    vlist = []
    for item in list_of(data.get('list')):
        if isinstance(item, dict):
            vlist.extend(list_of(item.get('vlist')))
    return {'list': vlist}


def paginated(data, requested_page):
    lst = list_of(data.get('list'))
    raw_page = data.get('page')
    page = page_of(raw_page if raw_page is not None else requested_page)
    try:
        limit = int(data.get('limit') or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        limit = PAGE_LIMIT
    try:
        raw_pagecount = int(data.get('pagecount') or 0)
    except (TypeError, ValueError):
        raw_pagecount = 0
    has_pagecount = raw_pagecount > 0
    pagecount = raw_pagecount if has_pagecount else page + (1 if len(lst) >= limit else 0)
    try:
        raw_total = data.get('total')
        has_total = raw_total is not None and int(raw_total) >= 0
    except (TypeError, ValueError):
        has_total = False
    if has_pagecount and has_total:
        total = int(data.get('total'))
    else:
        total = (page - 1) * limit + len(lst) + (1 if pagecount > page else 0)
    data['page'] = page
    data['pagecount'] = pagecount
    data['limit'] = limit
    data['total'] = total
    data['list'] = lst
    return data


def category(tid, pg, extend):
    page = page_of(pg)
    tid = text(tid)
    if not tid:
        return paginated({'list': []}, page)
    extend = extend if isinstance(extend, dict) else {}
    params = {'tid': tid, 'pg': str(page), 'limit': '18'}
    for key in FILTER_NAMES:
        value = text(extend.get(key))
        if value and value != 'all':
            params[key] = value
    return paginated(cms('video', params), page)


def playlist(value):
    parts = []
    for entry in text(value).split('#'):
        sep = entry.find('$')
        if sep <= 0 or not text(entry[sep + 1:]):
            continue
        parts.append('%s$%s' % (text(entry[:sep]), decrypt_lvdou(entry[sep + 1:])))
    return '#'.join(parts)


def detail(ids):
    if not isinstance(ids, (list, tuple)):
        ids = [ids]
    lst = []
    for vid in ids:
        vid = text(vid)
        if not vid:
            continue
        data = cms('video_detail', {'id': vid}).get('data')
        if not isinstance(data, dict):
            continue
        players = data.get('vod_url_with_player')
        vod = {k: v for k, v in data.items() if k != 'vod_url_with_player'}
        names = text(vod.get('vod_play_from')).split('$$$')
        if isinstance(players, list):
            sources = players
        else:
            sources = [
                {'name': names[i] if i < len(names) else '', 'url': u}
                for i, u in enumerate(text(vod.get('vod_play_url')).split('$$$'))
            ]
        lines = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            url = playlist(source.get('url'))
            if not url:
                continue
            name = text(source.get('name')) or text(source.get('code')) or '线路%d' % (index + 1)
            lines.append({'name': re.sub(r'[$#]', ' ', name), 'url': url})

        # 直链线路先探活：站点 4K 直链已整批 404，死的排到后面并标注，别让用户点了黑屏
        # 兜底线路：站点自身解析/直链失效时，用备用源按片名换出可直接播放的地址
        heads_raw = []
        for item in backup_episodes(vod.get('vod_name')):
            eps = item['eps']
            if eps:
                heads_raw.append({'name': item['name'], 'url': join_episodes(eps), 'eps': eps})

        # 原生直链和兜底线路一起并发探活，只留真能拿到数据的
        targets = [u for u in (direct_probe_url(l) for l in lines) if u]
        targets.extend(h['eps'][0][1] for h in heads_raw)
        alive = probe_many(targets)

        lines = mark_dead_lines(lines, alive)
        heads = [h for h in heads_raw if alive.get(h['eps'][0][1], False)][:3]

        # 原生每一集的地址映射到兜底源同一集，用户点原来那几条线路也能播
        if heads:
            eps = heads[0]['eps']
            for line in lines:
                line_eps = parse_episodes(line['url'])
                # 集数差太多就不映射了，免得第 3 集跳到对面第 30 集
                if abs(len(line_eps) - len(eps)) > 1:
                    continue
                for i, (_, origin_url) in enumerate(line_eps):
                    if i < len(eps):
                        remember_play(origin_url, eps[i][1])

        all_lines = [{'name': h['name'], 'url': h['url']} for h in heads] + lines
        vod['vod_play_from'] = '$$$'.join(line['name'] for line in all_lines)
        vod['vod_play_url'] = '$$$'.join(line['url'] for line in all_lines)
        lst.append(vod)
    return {'list': lst}


def search(key, pg):
    wd = text(key)
    page = page_of(pg)
    if not wd:
        return paginated({'list': []}, page)
    data = cms('search', {'text': wd, 'pg': str(page)})
    lst = []
    for item in list_of(data.get('list')):
        if isinstance(item, dict):
            lst.append({k: v for k, v in item.items() if k != 'type'})
    data['list'] = lst
    return paginated(data, page)


def play(play_id):
    """
    按线路类型分流解析：
      - 兜底映射命中 → 直接用已换好的直链（站点解析/直链失效时靠这条能播）
      - m3u8/mpd 直链 → 原样交给播放器，不解析
      - 4K 直链（ym4kjx 的 mp4/mkv）→ 先探活，活着直接播；死了再试 parsesId=6
      - 网页线路（腾讯/爱奇艺/芒果…）→ parsesId=5
    """
    original = decrypt_lvdou(play_id)
    if not original:
        return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS)}

    # 兼容老加密：ldmax 前缀先本地解密
    if is_ldmax_url(original):
        decrypted = decrypt_ldmax(original)
        if decrypted:
            original = decrypted

    # 详情页已经换好的可播地址：优先用，别再去硬打失效的解析接口
    mapped = recall_play(original)
    if mapped:
        return {'parse': 0, 'url': mapped, 'header': dict(PARSE_HEADERS)}

    # 解析结果缓存
    now = time.time()
    cached = _play_cache.get(original)
    if cached and cached[0] > now:
        return {'parse': 0, 'url': cached[1], 'header': dict(PARSE_HEADERS)}

    resolved = ''
    if is_stream_url(original):
        resolved = original
    elif is_media_url(original):
        # 直链先探活：404 的死链不再直接甩给播放器
        if probe_url(original):
            resolved = original
        else:
            resolved = parse_url(original, PARSE_ID_4K)
    else:
        resolved = parse_url(original, PARSE_ID_WEB)
        if not resolved and is_media_url(original):
            resolved = original

    _play_cache[original] = (now + PLAY_CACHE_TTL, resolved)

    return {'parse': 0, 'url': resolved or '', 'header': dict(PARSE_HEADERS)}


class Spider(Spider):
    extend = ''

    def getName(self):
        return '🎬 影探4K'

    def init(self, extend=''):
        self.extend = extend or ''

    def isVideoFormat(self, url):
        return is_media_url(url)

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        return home(self.extend)

    def homeVideoContent(self):
        return home_vod()

    def categoryContent(self, tid, pg, filter, extend):
        return category(tid, pg, extend)

    def detailContent(self, ids):
        return detail(ids)

    def searchContent(self, key, quick, pg='1'):
        return search(key, pg)

    def playerContent(self, flag, id, vipFlags):
        return play(id)

    def localProxy(self, param):
        return None

    def destroy(self):
        pass