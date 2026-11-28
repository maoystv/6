# -*- coding: utf-8 -*-
# 影探4K：鱼壳 webhtv 站点注入用 Python Spider（多源框架保留，可插新源）。
# 用法：把本文件放到手机 /sdcard/py/影探4K.py，站点配置 api 填 file:///sdcard/py/影探4K.py
import base64
import json
import re
import time
import urllib.parse

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
# 同族 CMS 源（同一作者、同一套 AppYs 接口 + lvdou 加密）。
# 2026-11-27 云端实测 4ksj/dytt 两站暂时不可达；不可达的源自动跳过，不拖垮主站。
# 若某站用了独立密钥，在 SOURCE_KEYS 里按域名覆盖即可。
SOURCES = (
    ('影探', 'http://cms.lyyytv.cn'),
)  # 臻彩世界4K(cms4ksj)/电影天堂(cmsdytt) 已实测下线（2026-11-27 用户端验证），移除
SOURCE_KEYS = {}

# 解析接口（fys.lyyytv.cn 放映室）
# 2026-11 实测：老的 parsesId=3 记录已删除，接口直接 500
# （ErrorException in Parses.php line 63: Trying to get property 'url' of non-object）。
# 2026-11-26 复测：5/6 两条也死了（一律 {"code":0,"msg":"解析失败"}），
# 全量扫描 pid1~12 后确认新的活口：
#   7 = 网页线路（腾讯/爱奇艺/芒果/优酷/B站 等页面地址 → m3u8）
#   8 = 4K 直链（ym4kjx.lyyytv.cn 下的 mp4/mkv，源站本体已 404，
#       靠它换成联通云盘 tjdownload.pan.wo.cn / 天翼云 cloudcube.telecomjs.com 直链）
# 4K 兄弟子域（hd4kjx/sd4kjx/mm4kjx/mv4kjx/vk4kjx）全部 403，直连无门。
# 服务商隔段时间就换 pid（3→5/6→7/8），备援级联按序降级试。
PARSE_API = 'http://fys.lyyytv.cn/api/index?appid=10001&videoUrl='
PARSE_ID_WEB = 7
PARSE_ID_4K = 8
# 级联备援：主 pid 失败后依次降级（失败响应很快，代价小）
PARSE_FALLBACK_WEB = (7, 5, 8)
PARSE_FALLBACK_4K = (8, 6, 7)
# 解析口自适应（2026-11-27 起）：不用再人工扫描换号。
# 每次解析给每个 parsesId 记成功/失败并动态排序级联；首选口挂了会自动
# 扫描生成新候选：从 1 往上逐个探测，活口自动入库，编号不设上限
# （超过 20 也能长到），连续 PARSE_SCAN_STOP 个"记录不存在"才收工。
PARSE_PID_MIN = 1
PARSE_PID_MAX = 20          # 仅初始候选池大小，不是扫描上限
PARSE_SCAN_STOP = 5         # 越过已知最高编号后，连续空口几个就停止本轮扫描
PARSE_SCAN_HARD_CAP = 200   # 保险丝，防止异常情况下无限扫
SCAN_COOLDOWN = 600         # 全量扫描冷却（秒），只在级联全败时触发
# appid 换号自愈（10001→10002 之类）：全败时自动向上逐个试，编号无上限。
# 初始基线 = 当前 appid + APPID_SCAN_BASE；每发现一个有效 appid 基线就抬高，
# 越过基线后连续 PARSE_SCAN_STOP 个无效才收工，一轮最多扫 APPID_SCAN_CAP 个。
APPID_SCAN_BASE = 20
APPID_SCAN_STOP = 50   # appid 通常稀疏，连空容忍度给大些
APPID_SCAN_CAP = 300
# 单次播放最多尝试的解析口个数（失败响应都是秒回，代价小）
PARSE_MAX_TRIES = 6
# 解析口成绩的记忆窗口（秒）
_PID_STATS_TTL = 2 * 3600
_pid_stats = {}
HEADERS = {'User-Agent': 'okhttp/4.12.0'}
# 解析请求/回源头：对齐 JS 的 PH，避免 gzip 花屏
PARSE_HEADERS = {'User-Agent': 'okhttp/4.12.0', 'Accept-Encoding': 'identity'}

# baidu.con 前缀加密常量（对齐 yt4k.js）
DEC_PREFIX = 'https://baidu.con/'
# 解析重试轮数与退避基数（秒）
PARSE_ROUNDS = 3
PARSE_BACKOFF = 0.35
# 同一原始地址解析结果缓存窗口（秒）
PLAY_CACHE_TTL = 120

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
    try:
        data = object_of(rsp.json())
    except Exception:
        data = {}
    if not data:
        raise Exception('影探4K：接口未返回有效 JSON')
    return data


def cms(path, params=None, src=0, timeout=15):
    params = params or {}
    query = urllib.parse.urlencode(params)
    host = SOURCES[src][1] if 0 <= src < len(SOURCES) else HOST
    data = get_json('%s/api.php/app/%s?%s' % (host, path, query), timeout=timeout)
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


def parse_url(raw, parse_id=PARSE_ID_WEB, api_base=None):
    """把原始地址拼到解析基址后请求，解出真实 URL；parse_id 选解析器编号。"""
    if not raw:
        return ''
    target = '%s%s&parsesId=%d' % (api_base or PARSE_API, urllib.parse.quote(raw, safe="!'()*"), parse_id)
    for rnd in range(PARSE_ROUNDS):
        if rnd > 0:
            time.sleep(rnd * PARSE_BACKOFF)
        try:
            rsp = requests.get(target, headers=PARSE_HEADERS, timeout=30)
            if rsp.status_code == 200 and rsp.text:
                resolved = resolve_parse(rsp.text)
                if resolved and resolved.startswith('http'):
                    return resolved
        except Exception:
            pass
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


def split_src(value):
    """vod_id / type_id 的源前缀：'1:23' → (1, '23')；无前缀默认影探主站。"""
    v = text(value)
    if len(v) > 2 and v[0].isdigit() and v[1] == ':':
        src = int(v[0])
        if 0 <= src < len(SOURCES):
            return src, v[2:]
    return 0, v


def tag_vods(items, src):
    """副源条目：vod_id 加源前缀，备注标来源，主源原样。"""
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if src and item.get('vod_id') is not None:
            item['vod_id'] = '%d:%s' % (src, text(item['vod_id']))
            item['vod_remarks'] = ('%s %s' % (SOURCES[src][0], text(item.get('vod_remarks')))).strip()
        out.append(item)
    return out


def _home_classes(src):
    """拉一个源的分类与筛选；失败抛异常由上层跳过。"""
    data = cms('nav', {'token': ''}, src=src, timeout=8)
    classes = []
    filters = {}
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        if item.get('type_id') is None or not text(item.get('type_name')):
            continue
        tid = '%d:%s' % (src, text(item['type_id']))
        name = text(item['type_name'])
        if src:
            name = '%s·%s' % (SOURCES[src][0], name)
        classes.append({'type_id': tid, 'type_name': name})
        ext = object_of(item.get('type_extend'))
        groups = []
        for key, label in FILTER_NAMES.items():
            values = [v for v in (text(x) for x in text(ext.get(key)).split(',')) if v]
            values = list(dict.fromkeys(values))
            if values:
                groups.append({
                    'key': key, 'name': label, 'init': '',
                    'value': [{'n': '全部', 'v': ''}] + [{'n': v, 'v': v} for v in values],
                })
        if groups:
            filters[tid] = groups
    return classes, filters


def home(extend=''):
    cache_key = '%s_home_%s' % (KEY, text(extend))
    cached = _home_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    classes, filters = [], {}
    for src in range(len(SOURCES)):
        try:
            cls, flt = _home_classes(src)
        except Exception:
            continue  # 死源跳过
        classes.extend(cls)
        filters.update(flt)
    result = {'class': classes, 'filters': filters}
    if classes:
        _home_cache[cache_key] = (time.time() + HOME_CACHE_TTL, result)
    return result


def home_vod():
    vlist = []
    for src in range(len(SOURCES)):
        try:
            data = cms('index_video', {'token': ''}, src=src, timeout=8)
        except Exception:
            continue
        items = []
        for item in list_of(data.get('list')):
            if isinstance(item, dict):
                items.extend(list_of(item.get('vlist')))
        vlist.extend(tag_vods(items[:10], src))
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
    src, real_tid = split_src(tid)
    if not real_tid:
        return paginated({'list': []}, page)
    extend = extend if isinstance(extend, dict) else {}
    params = {'tid': real_tid, 'pg': str(page), 'limit': '18'}
    for key in FILTER_NAMES:
        value = text(extend.get(key))
        if value and value != 'all':
            params[key] = value
    data = paginated(cms('video', params, src=src), page)
    data['list'] = tag_vods(data['list'], src)
    return data


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
        src, real_id = split_src(vid)
        if not real_id:
            continue
        try:
            data = cms('video_detail', {'id': real_id}, src=src).get('data')
        except Exception:
            continue
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
        froms = []
        urls = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            # 官方字段：作者换解析基址时会在这里下发（平时为 null）
            adopt_parse_api(source.get('parse_api'))
            url = playlist(source.get('url'))
            if not url:
                continue
            name = text(source.get('name')) or text(source.get('code')) or '线路%d' % (index + 1)
            froms.append(re.sub(r'[$#]', ' ', name))
            urls.append(url)
        vod['vod_play_from'] = '$$$'.join(froms)
        vod['vod_play_url'] = '$$$'.join(urls)
        vod['vod_id'] = '%d:%s' % (src, real_id)
        lst.append(vod)
    return {'list': lst}


def search(key, pg):
    wd = text(key)
    page = page_of(pg)
    if not wd:
        return paginated({'list': []}, page)
    merged = []
    pagecount = page
    total = 0
    for src in range(len(SOURCES)):
        try:
            data = paginated(cms('search', {'text': wd, 'pg': str(page)}, src=src, timeout=10), page)
        except Exception:
            continue  # 死源跳过
        items = [{k: v for k, v in it.items() if k != 'type'}
                 for it in data['list'] if isinstance(it, dict)]
        merged.extend(tag_vods(items, src))
        pagecount = max(pagecount, data.get('pagecount', page))
        total += data.get('total', 0)
    return {'list': merged, 'page': page, 'pagecount': pagecount,
            'limit': PAGE_LIMIT, 'total': total}


# 解析基址池：默认 fys；播放行里发现新解析前缀会自动加入，按成绩排序
_extra_parse_apis = []


def split_embedded_parse(raw):
    """识别播放行自带的解析前缀（…videoUrl= / ?url= / &url= 形式）。
    命中返回 (解析基址, 真实地址)；否则返回 (None, 原地址)。"""
    if not raw or not raw.startswith('http'):
        return None, raw
    for marker in ('videoUrl=', '?url=', '&url='):
        idx = raw.find(marker)
        if idx > 0:
            inner = raw[idx + len(marker):]
            if inner.startswith('http') or '%3a' in inner[:16].lower():
                return raw[:idx + len(marker)], urllib.parse.unquote(inner)
    return None, raw


def adopt_parse_api(base):
    base = text(base)
    if base.startswith('http') and base != PARSE_API and base not in _extra_parse_apis:
        _extra_parse_apis.append(base)


def _ranked_apis():
    now = time.time()
    apis = list(_extra_parse_apis) + [PARSE_API]
    return sorted(apis, key=lambda b: -_pid_score('api:' + b, now))


def _pid_score(pid, now):
    """成绩 = 窗口内 ok/(ok+bad)；未知或过期口给中性分 0.5，排中间。"""
    st = _pid_stats.get(pid)
    if not st:
        return 0.5
    if now - st.get('ts', 0) > _PID_STATS_TTL:
        return 0.5
    tries = st.get('ok', 0) + st.get('bad', 0)
    return st['ok'] / tries if tries else 0.5


_alive_pids = {}   # 自动扫描确认存在的口：pid -> 时间戳
_last_scan = 0.0


def probe_pid(raw, pid, api_base=None):
    """主动探测一个口：ok=解出链接；fail=口存在但没解出这条；missing=口不存在(500/异常)。"""
    target = '%s%s&parsesId=%d' % (api_base or PARSE_API,
                                   urllib.parse.quote(raw, safe="!'()*"), pid)
    try:
        rsp = requests.get(target, headers=PARSE_HEADERS, timeout=20)
        if rsp.status_code != 200:
            return 'missing', ''
        resolved = resolve_parse(rsp.text or '')
        if resolved and resolved.startswith('http'):
            return 'ok', resolved
        return 'fail', ''   # 例如 {"code":0,"msg":"解析失败"}：口在，只是这条没解出来
    except Exception:
        return 'missing', ''


def auto_discover(raw, api_base=None):
    """自动测试、自动生成候选口（级联全败时才触发，有冷却）：
    从 1 号往上顺序探测，'口存在'就抬高基线继续往上长，编号无上限；
    越过基线后连续 PARSE_SCAN_STOP 个空口停止。解出的第一条链接直接返回。"""
    global _last_scan
    now = time.time()
    if now - _last_scan < SCAN_COOLDOWN:
        return ''
    _last_scan = now
    baseline = max([PARSE_PID_MAX] + list(_alive_pids))
    misses = 0
    found = ''
    pid = 1
    while pid <= PARSE_SCAN_HARD_CAP:
        if pid > baseline and misses >= PARSE_SCAN_STOP:
            break
        if pid in _alive_pids and now - _alive_pids[pid] < _PID_STATS_TTL:
            pid += 1
            continue  # 已知活口跳过请求，排序时自然置顶
        status, resolved = probe_pid(raw, pid, api_base)
        st = _pid_stats.setdefault(pid, {'ok': 0, 'bad': 0, 'ts': now})
        st['ts'] = now
        if status == 'ok':
            st['ok'] += 1
            _alive_pids[pid] = now
            baseline = max(baseline, pid)
            misses = 0
            if not found:
                found = resolved
        elif status == 'fail':
            st['bad'] += 1
            baseline = max(baseline, pid)  # 口存在就继续往上探
            misses = 0
        else:
            st['bad'] += 1
            if pid > baseline:
                misses += 1
        pid += 1
    return found


_last_appid_scan = 0.0
_alive_appids = {}   # 自动确认有效的 appid：appid -> 时间戳


def auto_discover_appid(raw):
    """appid 自动测试自动生成（无上限）：从当前 appid 往后逐个试，
    用已知活口 pid 探测；有效（出链接或口存在）就接管新基址并抬高基线，
    越过基线后连续 APPID_SCAN_STOP 个无效停止。"""
    global _last_appid_scan
    now = time.time()
    m = re.search(r'appid=(\d+)', PARSE_API)
    if not m or now - _last_appid_scan < SCAN_COOLDOWN:
        return ''
    _last_appid_scan = now
    current = int(m.group(1))
    baseline = max([current + APPID_SCAN_BASE] + list(_alive_appids))
    pids = sorted(_alive_pids) or [PARSE_ID_WEB, PARSE_ID_4K]
    misses = 0
    appid = current
    while appid - current <= APPID_SCAN_CAP:
        if appid > baseline and misses >= APPID_SCAN_STOP:
            break
        candidate = re.sub(r'appid=\d+', 'appid=%d' % appid, PARSE_API)
        if appid == current or (appid in _alive_appids
                                and now - _alive_appids[appid] < _PID_STATS_TTL):
            appid += 1
            continue
        for pid in pids[:3]:
            status, resolved = probe_pid(raw, pid, candidate)
            if status == 'missing':
                break  # 这个 appid 无效
            adopt_parse_api(candidate)
            _alive_appids[appid] = now
            baseline = max(baseline, appid)
            misses = 0
            st = _pid_stats.setdefault('api:' + candidate, {'ok': 0, 'bad': 0, 'ts': now})
            st['ts'] = now
            if status == 'ok':
                st['ok'] += 1
                _alive_pids[pid] = now
                return resolved
            st['bad'] += 1  # fail：appid 有效但这条没解出，继续试别的 pid
        else:
            # 内层没 break（不会到这）占位防御
            pass
        if appid > baseline:
            misses += 1
        appid += 1
    return ''


def _ranked_pids(primary):
    """原级联顺序打底 + 全量 1~N 候选，按最近成绩从高到低排序。"""
    now = time.time()
    seen = list(primary)
    extra = list(_alive_pids) + [k for k in _pid_stats if isinstance(k, int)]
    extra += list(range(PARSE_PID_MIN, PARSE_PID_MAX + 1))
    for pid in sorted(set(extra)):
        if pid not in seen:
            seen.append(pid)
    return sorted(seen, key=lambda p: -_pid_score(p, now))


def _try_pid(raw, pid, now, api_base=None):
    """试一个解析口并记成绩（pid 与基址分别记），成功返回链接。"""
    st = _pid_stats.setdefault(pid, {'ok': 0, 'bad': 0, 'ts': 0.0})
    ast = _pid_stats.setdefault('api:' + (api_base or PARSE_API),
                                {'ok': 0, 'bad': 0, 'ts': 0.0})
    resolved = parse_url(raw, pid, api_base)
    st['ts'] = ast['ts'] = now
    if resolved:
        st['ok'] += 1
        ast['ok'] += 1
        return resolved
    st['bad'] += 1
    ast['bad'] += 1
    return ''


def parse_with_fallback(raw, primary):
    """基址 × parsesId 双层级联：每个基址按成绩试 pid；
    第一个基址做全量 pid 发现（换 pid 自愈），后续基址只试前几个。
    基址整个换域名时靠播放行内嵌前缀自动接管（split_embedded_parse）。"""
    now = time.time()
    ranked = _ranked_pids(primary)
    for ai, base in enumerate(_ranked_apis()):
        limit = len(ranked) if ai == 0 else PARSE_MAX_TRIES
        for pid in ranked[:limit]:
            resolved = _try_pid(raw, pid, now, base)
            if resolved:
                return resolved
    # 已知口全败：先自动扫 pid（编号无上限），再自动换 appid 试新基址
    resolved = auto_discover(raw, _ranked_apis()[0])
    if resolved:
        return resolved
    return auto_discover_appid(raw)


# 第二梯队：影探官方 yt.json 配置自带的公共 JSON 解析（网页线路兜底）。
# 这类解析生死很快，同样交给成绩排序自适应，不用人工维护。
PUBLIC_JSON_PARSES = (
    ('网络', 'https://jx.bhs6.com/api/?key=3b0f9783d81fb21a99db6bf161fac26d&url='),
    ('推荐', 'https://jxjson.icu/neibu.php?url='),
    ('臻享', 'https://jk.123zy.cool/jx/jx.php?url='),
    ('1080解析', 'https://zy.qiaoji8.com/gouzi.php?url='),
    ('反弹', 'http://110.40.85.39:81/jxxx/api.php?url='),
    ('优选', 'http://1.94.221.189:88/algorithm.php?url='),
    ('皮皮虾', 'http://jiexi.52ppx.top/lxjson.php?url='),
)


def parse_public_url(raw, base):
    """走一个公共 JSON 解析，解出真实 URL（m3u8/mp4），失败返回空。"""
    target = base + urllib.parse.quote(raw, safe="!'()*")
    for _ in range(2):
        try:
            r = requests.get(target, headers=HEADERS, timeout=20)
            body = r.text or ''
            resolved = resolve_parse(body)
            if resolved and is_http_url(resolved):
                return resolved
        except Exception:
            pass
    return ''


def parse_public(raw):
    """公共解析池级联，与 parsesId 共用成绩表，活的自动置顶。"""
    now = time.time()
    for name, base in sorted(PUBLIC_JSON_PARSES,
                             key=lambda kv: -_pid_score(kv[0], now)):
        st = _pid_stats.setdefault(name, {'ok': 0, 'bad': 0, 'ts': 0.0})
        resolved = parse_public_url(raw, base)
        st['ts'] = now
        if resolved:
            st['ok'] += 1
            return resolved
        st['bad'] += 1
    return ''


def play(play_id):
    """
    按线路类型分流解析（2026-11-27 起自适应，pid 换号免维护）：
      - 4K 直链（ym4kjx 的 mp4/mkv，源站已 404）→ 按成绩动态级联换链到
        联通云盘/天翼云直链；全败退回原直链（兼容源站还活着的网络）。
      - m3u8/mpd 直链 → 原样交给播放器，不解析。
      - 网页线路（腾讯/爱奇艺/芒果…）→ 按成绩动态级联解析出 m3u8。
    """
    original = decrypt_lvdou(play_id)
    if not original:
        return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS)}

    # 兼容老加密：ldmax 前缀先本地解密
    if is_ldmax_url(original):
        decrypted = decrypt_ldmax(original)
        if decrypted:
            original = decrypted

    # 播放行自带解析前缀（作者换解析域名时的形态）→ 接管新基址
    new_base, original = split_embedded_parse(original)
    if new_base:
        adopt_parse_api(new_base)
    if not original:
        return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS)}

    # 解析结果缓存
    now = time.time()
    cached = _play_cache.get(original)
    if cached and cached[0] > now:
        return {'parse': 0, 'url': cached[1], 'header': dict(PARSE_HEADERS)}

    if is_4k_source(original):
        # 4K 换链：按成绩动态级联；全败退回原直链（网络内源站还活着的兜底）
        resolved = parse_with_fallback(original, PARSE_FALLBACK_4K)
        if not resolved:
            resolved = original
    elif is_stream_url(original):
        resolved = original
    else:
        # 网页线路：fys 按成绩动态级联 → 公共解析池兜底；再败且是媒体直链就原样交播放器
        resolved = parse_with_fallback(original, PARSE_FALLBACK_WEB)
        if not resolved:
            resolved = parse_public(original)
        if not resolved and is_media_url(original):
            resolved = original

    if resolved:
        _play_cache[original] = (now + PLAY_CACHE_TTL, resolved)

    return {'parse': 0, 'url': resolved or '', 'header': dict(PARSE_HEADERS)}


class Spider(Spider):
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