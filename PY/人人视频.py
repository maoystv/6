# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import random
import re
import string
import time
import urllib.parse
import urllib.request
import uuid
import http.client
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

HOST = '122.228.193.211'
PORT = 18008
PUB1 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCduNEnfxGaLuQRk5ABzXHhPV43zi00sCHjLo8BYc+Wi6xXm2b4v0i28Sq4WlNCKhseft9fz8kO/qLr6/022o1RcuOU7e4GFL3U9WnNODwRBYSYWd+K8nqpI/tAUDmZEBGRWqjrc7x6aMl3A+xpnWkLbPCLsuhbuuUE3tv09oeOpwIDAQAB'
NATIVE = b'ed5fdsgucxumegqa'
DATAIV = b'OC1A06E197EF10CF3F6058CA7A803B5E'
DATAKEY = b'S0VNDTJHOFHHCNMRAW5IV2TOS2PBPQ=='
UA = 'okhttp/3.12.1'
_RSA = PKCS1_v1_5.new(RSA.import_key(base64.b64decode(PUB1)))
UDID = uuid.uuid4().hex.upper()

CATES = [('剧集', '2', 'c'), ('电影', '1', 'c'), ('综艺', '3', 'c'),
         ('动漫', '4', 'c'), ('短剧', '5', 'c'),
         ('4K专区', '117', 't'), ('奈飞专区', '115', 't')]
CATE_BY_ID = {t[1]: (t[0], t[2]) for t in CATES}
DEAD_LINES = ('youku',)
TAG_TYPES = {'117': ('1', '2'), '115': ('2',)}
TAG_MARK = {'117': ('4K',), '115': ('美剧', '韩国', '日本', '欧美', '英剧', '美国')}
RR_API = 'api.rrmj.plus'
RR_SS = b'ES513W0B1CsdUrR13Qk5EgDAKPeeKZY'
RR_DK = b'3b744389882a4067'
RR_IV = b'b1da7878016e4e2b'
RR_REF = 'https://mh.yichengwlkj.com/'
RR_UA = ('Mozilla/5.0 (Linux; Android 16; PJX110) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')
AREA_C = [{'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'},
          {'n': '香港', 'v': '香港'}, {'n': '台湾', 'v': '台湾'},
          {'n': '美国', 'v': '美国'}, {'n': '韩国', 'v': '韩国'},
          {'n': '日本', 'v': '日本'}, {'n': '英国', 'v': '英国'},
          {'n': '泰国', 'v': '泰国'}]
ORDER_C = [{'n': '最新', 'v': '最新'}, {'n': '最热', 'v': '最热'},
           {'n': '评分', 'v': '评分'}]
FILTERS = {}
for _t in CATES:
    if _t[2] == 'c':
        FILTERS[_t[1]] = [{'key': 'area', 'name': '地区', 'value': AREA_C},
                          {'key': 'vodOrderBy', 'name': '排序',
                           'value': ORDER_C}]
FILTERS['117'] = [{'key': 'grp', 'name': '分组',
                   'value': [{'n': '全部', 'v': ''},
                             {'n': '4K大片', 'v': '4K大片'},
                             {'n': '4K好剧', 'v': '4K好剧'}]}]
FILTERS['115'] = [{'key': 'area', 'name': '地区',
                   'value': [{'n': '精选', 'v': ''},
                             {'n': '美剧', 'v': '美国'},
                             {'n': '韩剧', 'v': '韩国'},
                             {'n': '日剧', 'v': '日本'},
                             {'n': '英剧', 'v': '英国'}]},
                  {'key': 'vodOrderBy', 'name': '排序',
                   'value': [{'n': '最新', 'v': '最新'},
                             {'n': '最热', 'v': '最热'}]}]


def _rnd(n):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def _varint(n):
    b = b''
    while True:
        x = n & 0x7f
        n >>= 7
        if n:
            b += bytes([x | 0x80])
        else:
            return b + bytes([x])


def _f(num, wire, payload):
    t = _varint((num << 3) | wire)
    if wire == 2:
        return t + _varint(len(payload)) + payload
    return t + payload


def _pb(buf):
    out, i, n = [], 0, len(buf)
    while i < n:
        try:
            tag = 0
            sh = 0
            while True:
                b = buf[i]
                i += 1
                tag |= (b & 0x7f) << sh
                sh += 7
                if not b & 0x80:
                    break
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                v = 0
                sh = 0
                while True:
                    b = buf[i]
                    i += 1
                    v |= (b & 0x7f) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                out.append((fn, wt, v))
            elif wt == 2:
                ln = 0
                sh = 0
                while True:
                    b = buf[i]
                    i += 1
                    ln |= (b & 0x7f) << sh
                    sh += 7
                    if not b & 0x80:
                        break
                out.append((fn, wt, buf[i:i + ln]))
                i += ln
            elif wt == 5:
                out.append((fn, wt, buf[i:i + 4]))
                i += 4
            elif wt == 1:
                out.append((fn, wt, buf[i:i + 8]))
                i += 8
            else:
                break
        except Exception:
            break
    return out


def _txt(b):
    try:
        return b.decode('utf-8', 'replace')
    except Exception:
        return ''


def _flat(g):
    m = {}
    for fn, wt, v in _pb(g):
        if wt == 0:
            m[fn] = v
        elif wt == 2:
            m[fn] = _txt(v)
    return m


def _pics(s):
    return re.findall(r'https?://[^\x00-\x20"\']+', s or '')


def _card(m):
    vid = str(m.get(3, ''))
    if not vid or not m.get(5):
        return None
    p = _pics(m.get(2, ''))
    return {'vod_id': vid, 'vod_name': m.get(5, ''),
            'vod_pic': p[0] if p else '',
            'vod_remarks': m.get(13, '') or m.get(26, '')}


class Spider(_Base):
    def getName(self):
        return '小苹果'

    def init(self, extend=''):
        return

    def _pd(self, ts):
        r16 = base64.b64encode(_rnd(12).encode()).decode()
        sig = base64.b64encode(_RSA.encrypt((str(ts) + r16 + '1003').encode())).decode()
        b = base64.b64encode(AES.new(DATAIV, AES.MODE_ECB).encrypt(
            pad((str(ts) + r16).encode(), 16))).decode()
        J = {'country': 'CN', 'vName': '1.0.0.3', 'cpuId': '', 'young': 0,
             'facturer': 'OnePlus', 'pkg': 'com.juechufsh.android.xpg1',
             'uuid': UDID, 'resolution': '1080x2256',
             'mac': '02%3A00%3A00%3A00%3A00%3A00', 'sig': sig, 'abid': '2557',
             'model': 'PJX110', 'plat': 'android', 'udid': UDID, 'dpi': '480',
             'net': '1', 'lang': 'zh', 'random_str': r16, 'brand': 'OnePlus',
             'timestamp': ts, 'density': '3.0',
             'appName': '%E5%B0%8F%E8%8B%B9%E6%9E%9C%E5%BD%B1%E8%A7%86',
             'cpu': 'arm64-v8a', 'chid': '10000', 'carrier': '%E8%81%94%E9%80%9A',
             'sig2': b[:8], 'v': 1, 'sig3': b[8:], 'tenantId': 'xpg',
             '_vOsCode': '36', 'vOs': '16', 'vApp': '1003', 'device': 0,
             'androidID': UDID[:16].lower()}
        return AES.new(NATIVE, AES.MODE_CBC, NATIVE).encrypt(
            pad(json.dumps(J, separators=(',', ':')).encode(), 16)).hex()

    def _headers(self, ts):
        return {'User-Agent': UA, 'Cache-Control': 'no-cache',
                'Accept': 'application/x-protobuf',
                'Content-Type': 'application/x-protobuf',
                'publicParams': json.dumps({'paramsData': self._pd(ts)},
                                           separators=(',', ':'))}

    def _body(self, kvs, ts):
        f8 = _rnd(8)
        sb = '&'.join('%s=%s' % (k, v) for k, v in kvs.items() if str(v))
        aes = f8 + base64.b64encode(AES.new(DATAKEY, AES.MODE_ECB).encrypt(
            pad((sb + str(ts)).encode(), 16))).decode()
        return (_f(1, 2, aes[:20].encode()) + _f(2, 2, aes[20:].encode()) +
                _f(3, 2, _rnd(20).encode()) + _f(4, 0, _varint(ts)) +
                _f(5, 2, f8.encode()))

    def _req(self, method, ep, body=None):
        try:
            ts = int(time.time() * 1000)
            conn = http.client.HTTPConnection(HOST, PORT, timeout=20)
            conn.request(method, ep, body=body, headers=self._headers(ts))
            r = conn.getresponse()
            d = r.read()
            conn.close()
            return d
        except Exception:
            return b''

    def _get(self, ep):
        return self._req('GET', ep)

    def _post(self, ep, kvs):
        return self._req('POST', ep, self._body(kvs, int(time.time() * 1000)))

    def _data(self, raw):
        for fn, wt, v in _pb(raw):
            if fn == 3 and wt == 2:
                return v
        return b''

    def _v5list(self, raw):
        vids = []
        seen = set()
        for fn, wt, g in _pb(self._data(raw)):
            if fn == 1 and wt == 2:
                c = _card(_flat(g))
                if c and c['vod_id'] not in seen:
                    seen.add(c['vod_id'])
                    vids.append(c)
        return vids

    def _v4list(self, raw, grp=''):
        vids = []
        seen = set()
        for fn, wt, g in _pb(self._data(raw)):
            if fn == 31 and wt == 2:
                gname = ''
                items = []
                for f2, w2, item in _pb(g):
                    if f2 == 1 and w2 == 2:
                        gname = _txt(item)
                    elif f2 == 5 and w2 == 2:
                        items.append(item)
                if grp and gname != grp:
                    continue
                for item in items:
                    c = _card(_flat(item))
                    if c and c['vod_id'] not in seen:
                        seen.add(c['vod_id'])
                        vids.append(c)
        return vids

    def homeContent(self, filter):
        return {'class': [{'type_id': t[1], 'type_name': t[0]} for t in CATES],
                'filters': FILTERS}

    def homeVideoContent(self):
        return {'list': self._v4list(
            self._get('/api/proto/v4/tag/list/detail?pagesize=21&id=117&page=1'))}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        mode = CATE_BY_ID.get(str(tid), ('', 'c'))[1]
        ex = extend or {}
        if isinstance(ex, str):
            ex = dict(urllib.parse.parse_qsl(ex))
        try:
            if mode == 't':
                if str(tid) == '117':
                    vids = self._v4list(self._get(
                        '/api/proto/v4/tag/list/detail?pagesize=21&id=%s&page=1'
                        % tid), ex.get('grp', ''))
                elif str(tid) == '115':
                    area = ex.get('area', '')
                    if area:
                        r = self._post('/api/proto/v5/drama/category',
                                       {'pagesize': '21', 'typeId1': '2',
                                        'page': str(page), 'vodArea': area,
                                        'vodOrderBy': ex.get('vodOrderBy', '最新')})
                        vids = self._v5list(r)
                    elif page == 1:
                        vids = self._v4list(self._get(
                            '/api/proto/v4/tag/list/detail?pagesize=21&id=%s&page=1'
                            % tid))
                    else:
                        areas = ('美国', '韩国', '日本', '英国')
                        a = areas[(page - 2) % len(areas)]
                        p2 = (page - 2) // len(areas) + 1
                        r = self._post('/api/proto/v5/drama/category',
                                       {'pagesize': '21', 'typeId1': '2',
                                        'page': str(p2), 'vodArea': a,
                                        'vodOrderBy': '最新'})
                        vids = self._v5list(r)
                else:
                    vids = self._v4list(self._get(
                        '/api/proto/v4/tag/list/detail?pagesize=21&id=%s&page=%d'
                        % (tid, page)))
            else:
                kvs = {'pagesize': '21', 'typeId1': str(tid), 'page': str(page),
                       'vodOrderBy': ex.get('vodOrderBy', '最新')}
                area = ex.get('area', '')
                if area:
                    kvs['vodArea'] = area
                vids = self._v5list(self._post('/api/proto/v5/drama/category', kvs))
            pc = 1 if str(tid) == '117' else 9999
            return {'list': vids, 'page': page, 'pagecount': pc, 'limit': 21,
                    'total': len(vids) if pc == 1 else 999999}
        except Exception:
            return {'list': [], 'page': page, 'pagecount': 0, 'limit': 21,
                    'total': 0}

    def searchContent(self, key, quick, pg='1'):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            vids = self._v5list(self._post('/api/proto/v5/drama/search',
                                           {'searchKeys': key, 'page': str(page),
                                            'pagesize': '21'}))
            return {'list': vids, 'page': page, 'pagecount': 9999, 'limit': 21,
                    'total': 999999}
        except Exception:
            return {'list': [], 'page': page, 'pagecount': 0, 'limit': 21,
                    'total': 0}

    def detailContent(self, ids):
        try:
            data = self._data(self._post('/api/proto/v5/drama/getDetail',
                                         {'id': ids[0]}))
            if not data:
                return {'list': []}
            head = {}
            eps = []
            pic = ''
            for fn, wt, v in _pb(data):
                if fn == 29 and wt == 2:
                    eps.append(_flat(v))
                elif wt == 2:
                    if fn == 2:
                        p = _pics(_txt(v))
                        pic = p[1] if len(p) > 1 else (p[0] if p else '')
                    elif fn in (5, 6, 9, 12, 15, 25, 26):
                        head[fn] = _txt(v)
                elif wt == 0 and fn == 18:
                    head[18] = str(v)
            line = {}
            order = []
            for e in eps:
                src = e.get(9) or 'Ksvideo'
                if any(d in src for d in DEAD_LINES):
                    continue
                tok = e.get(4) or ''
                if not tok:
                    continue
                q = e.get(10) or ''
                nm = ('%s·%s' % (src, q)) if q else src
                if nm not in line:
                    line[nm] = []
                    order.append(nm)
                b64 = base64.b64encode(json.dumps(
                    {'f': src, 'u': tok}, separators=(',', ':')).encode()).decode()
                line[nm].append('%s$%s' % (e.get(3) or str(len(line[nm]) + 1), b64))
            if not order:
                return {'list': []}
            return {'list': [{'vod_id': ids[0], 'vod_name': head.get(9, ''),
                              'vod_pic': pic, 'vod_year': head.get(18, ''),
                              'vod_area': head.get(5, ''),
                              'vod_remarks': head.get(26, ''),
                              'vod_actor': head.get(25, ''),
                              'vod_director': head.get(12, ''),
                              'vod_content': head.get(6, ''),
                              'vod_play_from': '$$$'.join(order),
                              'vod_play_url': '$$$'.join(
                                  '#'.join(line[k]) for k in order)}]}
        except Exception:
            return {'list': []}

    def _vuu(self, pf, pu):
        raw = self._post('/api/proto/v5/videoUsableUrl',
                         {'vodPlayFrom': urllib.parse.quote(pf),
                          'playUrl': urllib.parse.quote(pu, safe='')})
        data = self._data(raw)
        if not data:
            return ''
        m = re.search(rb'https?://[^\x00-\x20"\']+', data)
        return m.group(0).decode('utf-8', 'replace') if m else ''

    def _rr_call(self, path, params):
        try:
            ts = int(time.time() * 1000)
            dev = uuid.uuid4().hex
            qs = '&'.join('%s=%s' % (k, params[k]) for k in sorted(params))
            s = 'GET\naliId:%s\nct:web_applet\ncv:1.0.0\nt:%s\n%s?%s' % (
                dev, ts, path, qs)
            sg = base64.b64encode(hmac.new(RR_SS, s.encode(),
                                           hashlib.sha256).digest()).decode()
            req = urllib.request.Request(
                'https://%s%s?%s' % (RR_API, path, qs),
                headers={'x-ca-sign': sg, 't': str(ts), 'aliId': dev,
                         'umid': dev, 'deviceId': dev, 'clientVersion': '1.0.0',
                         'cv': '1.0.0', 'clientType': 'web_applet',
                         'ct': 'web_applet', 'uet': '9', 'User-Agent': RR_UA,
                         'Origin': RR_REF[:-1], 'Referer': RR_REF})
            body = urllib.request.urlopen(req, timeout=20).read()
            try:
                return json.loads(unpad(AES.new(RR_DK, AES.MODE_ECB).decrypt(
                    base64.b64decode(body)), 16).decode())
            except Exception:
                return json.loads(body.decode('utf-8', 'replace'))
        except Exception:
            return {}

    def _rrsp(self, pu):
        try:
            did = re.search(r'/drama/(\d+)', pu).group(1)
            mm = re.search(r'episodeNo=(\d+)', pu)
            eno = int(mm.group(1)) if mm else 1
            pg = self._rr_call('/m-station/drama/page',
                               {'hsdrOpen': 0, 'isAgeLimit': 0, 'dramaId': did,
                                'pageNum': 1, 'pageSize': 200})
            eps = ((pg.get('data') or {}).get('episodeList') or [])
            sid = ''
            for e in eps:
                if int(e.get('episodeNo') or 0) == eno:
                    sid = e.get('sid')
                    break
            if not sid and eps:
                sid = eps[0].get('sid')
            if not sid:
                return ''
            last = ''
            for _ in range(8):
                for q in ('HD', 'SD'):
                    pl = self._rr_call('/m-station/drama/play',
                                       {'hsdrOpen': 0, 'dramaId': did,
                                        'episodeSid': sid, 'quality': q,
                                        'hevcOpen': 0, 'tria4k': 0})
                    pd = pl.get('data') or {}
                    m3 = pd.get('m3u8') or {}
                    ns = pd.get('newSign') or ''
                    if not m3.get('url') or len(ns) < 20:
                        continue
                    u = unpad(AES.new(ns[4:20].encode(), AES.MODE_CBC,
                                      RR_IV).decrypt(
                        base64.b64decode(m3['url'])), 16).decode()
                    if 'auth_key=' in u:
                        return u
                    last = u
            return last
        except Exception:
            return ''

    def playerContent(self, flag, id, vipFlags):
        hdr = {'User-Agent': UA}
        try:
            j = json.loads(base64.b64decode(id + '=' * (-len(id) % 4)).decode())
            pf, pu = j.get('f', ''), j.get('u', '')
            if pf == 'RRSP' or 'yichengwlkj.com' in pu:
                u = self._rrsp(pu)
                if u:
                    return {'parse': 0, 'url': u,
                            'header': {'User-Agent': RR_UA, 'Referer': RR_REF}}
                return {'parse': 0, 'url': '', 'header': hdr}
            url = self._vuu(pf, pu) or pu
            if not url.startswith('http'):
                return {'parse': 0, 'url': '', 'header': hdr}
            if 'response-content-disposition' in url or '.mp4?' in url:
                return {'parse': 0, 'url': url, 'header': hdr}
            if re.search(r'\.(m3u8|mp4|mkv|flv|ts|m4s)(\?|$)|\.mp4', url):
                return {'parse': 0, 'url': url, 'header': hdr}
            if re.search(r'/m3u8/|/hls/|m3u8\?|/api/(banyun|gongyou)', url):
                sep = '&' if '?' in url else '?'
                return {'parse': 0, 'url': url + sep + 'ext=.m3u8',
                        'header': hdr}
            return {'parse': 1, 'url': url, 'header': hdr}
        except Exception:
            return {'parse': 0, 'url': '', 'header': hdr}

    def isVideoFormat(self, url):
        u = url or ''
        if re.search(r'\.(m3u8|mp4|mkv|flv|ts|m4s|avi|mov)(\?|$)', u):
            return True
        return bool(re.search(r'/m3u8/|/hls/|\.mp4|m3u8\?', u))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [200, 'text/plain', '']

# --- System Signature ---
#‍​​‌‌​‌​‌​​‌‌​‌‌​​​‌‌​​‌​​​‌‌​​‌‌​​‌‌​‌‌​​​‌‌​‌​‌​​‌‌‌​​‌​​‌‌​​​‌​​‌‌​​‌​​​‌‌​​‌​‍
