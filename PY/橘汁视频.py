# -*- coding: utf-8 -*-
# 橘汁视频 TVBox spider — 华谊同款协议栈移植
import json
import re
import sys
import time
import base64
import string
import random
import hashlib
import urllib.request
import urllib.parse
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5, AES
from Crypto.Util.Padding import pad, unpad

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

PUB1_B64 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB'
NATIVE_K = b'ed5fdsgucxumegqa'
SAFE = b'OC1A06E197EF10CF3F6058CA7A803B5E'
PW_SAFE = b'11GK2we32144LO&hilUITB)FMd1khdaF'
CERT_MD5 = '090DA8F91D3F60CC6CB250D86F06FE12'
CERT_SHA1 = '3DADB42485B7F864E766479ADA6B1176D81D8D73'
PKG = 'com.mxj.wylcjbxyx'
VC = '3023'
HOST = 'https://juziapp.hzhcbkj.cn'
UA = 'okhttp/3.12.1'

_e = base64.b64encode(AES.new(PW_SAFE, AES.MODE_ECB).encrypt(pad(
    (CERT_MD5 + '######' + CERT_SHA1 + '~~~~~~' + PKG + '>>>+++' + VC).encode(), 16))).decode()
_e2 = base64.b64encode(_e.encode()).decode()
SAFECODE = (_e2[:16] + _e2[-16:]).upper()


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
    out = []
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]; fn, wt = b >> 3, b & 7; i += 1
        if wt == 0:
            v = 0; sh = 0
            while i < n:
                x = buf[i]; i += 1
                v |= (x & 0x7f) << sh; sh += 7
                if not x & 0x80:
                    break
            out.append((fn, wt, v))
        elif wt == 2:
            ln = 0; sh = 0
            while i < n:
                x = buf[i]; i += 1
                ln |= (x & 0x7f) << sh; sh += 7
                if not x & 0x80:
                    break
            out.append((fn, wt, buf[i:i + ln])); i += ln
        elif wt == 5:
            out.append((fn, wt, buf[i:i + 4])); i += 4
        elif wt == 1:
            out.append((fn, wt, buf[i:i + 8])); i += 8
        else:
            i += 1
    return out


def _rnd(k):
    CH = string.ascii_letters + string.digits
    return ''.join(random.sample(list(CH), k - 1)) + '='


class Spider(_Base):
    HOST_NAME = '橘汁视频'

    def getName(self):
        return '橘汁视频'

    _cur_id = ''

    def init(self, extend=''):
        self.udid = hashlib.md5(str(time.time()).encode()).hexdigest()[:16].upper()
        self._rsa1 = PKCS1_v1_5.new(RSA.import_key(base64.b64decode(PUB1_B64)))
        self._rsa2 = None
        self._token = ''
        self._login()
        self._zone()

    def _http(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        import ssl
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=25, context=ctx).read()

    def _login(self):
        try:
            body = json.dumps({'username': 'tv_%s' % self.udid[:10].lower(),
                               'password': hashlib.md5(('tv' + self.udid).encode()).hexdigest(),
                               'udid': self.udid}).encode()
            try:
                self._http(HOST + '/api/ex/v3/user/register', body, {
                    'User-Agent': UA, 'Content-Type': 'application/json'})
            except Exception:
                pass
            d = self._http(HOST + '/api/ex/v3/user/login', body, {
                'User-Agent': UA, 'Content-Type': 'application/json'})
            data = json.loads(d).get('data') or {}
            self._token = (data.get('token') or (data.get('user') or {}).get('token') or '')
        except Exception:
            self._token = ''

    def _zone(self):
        ts = int(time.time() * 1000)
        rnd = _rnd(16)
        sign = base64.b64encode(self._rsa1.encrypt((str(ts) + rnd).encode())).decode()
        body = (_f(1, 0, _varint(ts)) + _f(2, 2, sign.encode()) +
                _f(3, 2, rnd.encode()) + _f(4, 2, rnd.encode()) + _f(5, 2, rnd.encode()))
        P = {'plat': 'android', 'vOs': '16', '_vOsCode': '36', 'vApp': '3023',
             'vName': '3.0.2.3', 'pkg': PKG,
             'appName': '%E6%A9%98%E6%B1%81',
             'udid': self.udid, 'uuid': self.udid, 'chid': '10000',
             'androidID': self.udid, 'net': '1', 'young': 0, 'tenantId': '*',
             'v': 1, 'device': 0, 'lang': 'zh', 'country': 'CN', 'cpu': 'arm64-v8a'}
        d = self._http(HOST + '/api/v5/find/app/zone', body, {
            'User-Agent': UA, 'Content-Type': 'application/x-protobuf',
            'Accept': 'application/x-protobuf', 'Cache-Control': 'no-cache',
            'publicParams': json.dumps(P, separators=(',', ':'))})
        top = _pb(d)
        inner = [v for fn, wt, v in top if fn == 3 and wt == 2][0]
        strs = {fn: v for fn, wt, v in _pb(inner) if wt == 2}
        self._rsa2 = PKCS1_v1_5.new(RSA.import_key(base64.b64decode(
            strs[2] + strs[3] + strs[4] + strs[5])))

    def _hdr(self):
        ts = int(time.time() * 1000)
        rnd = _rnd(16)
        sig = base64.b64encode(self._rsa2.encrypt((str(ts) + rnd + '3023').encode())).decode()
        ao = base64.b64encode(AES.new(SAFE, AES.MODE_ECB).encrypt(
            pad((str(ts) + rnd).encode(), 16))).decode()
        J = {'country': 'CN', 'vName': '3.0.2.3', 'cpuId': '', 'young': 0,
             'facturer': 'OnePlus', 'pkg': PKG, 'uuid': self.udid,
             'resolution': '1080x2256', 'mac': '02%3A00%3A00%3A00%3A00%3A00',
             'sig': sig, 'abid': '7470', 'model': 'PJX110', 'plat': 'android',
             'udid': self.udid, 'dpi': '480', 'net': '1', 'lang': 'zh',
             'random_str': rnd, 'brand': 'OnePlus', 'timestamp': ts,
             'density': '3.0', 'appName': '%E6%A9%98%E6%B1%81',
             'cpu': 'arm64-v8a', 'chid': '10000', 'carrier': '%E8%81%94%E9%80%9A',
             'sig2': ao[:8], 'v': 1, 'sig3': ao[8:], 'tenantId': '*',
             '_vOsCode': '36', 'vOs': '16', 'vApp': '3023', 'device': 0,
             'androidID': self.udid}
        blob = json.dumps(J, separators=(',', ':'), ensure_ascii=False).encode()
        pd_hex = AES.new(NATIVE_K, AES.MODE_CBC, NATIVE_K).encrypt(pad(blob, 16)).hex()
        h = {'User-Agent': UA, 'Accept': 'application/json',
             'Cache-Control': 'no-cache',
             'publicParams': json.dumps({'paramsData': pd_hex}, separators=(',', ':'))}
        if self._token:
            h['token'] = self._token
        return h

    def _secure(self, mapkv):
        ts = int(time.time() * 1000)
        rnd8 = _rnd(8)
        plain = (mapkv + str(ts)).encode()
        ct = AES.new(SAFECODE.encode(), AES.MODE_ECB).encrypt(pad(plain, 16))
        b64 = base64.b64encode(ct).decode()
        return (_f(1, 2, (rnd8 + b64[:12]).encode()) +
                _f(2, 2, b64[12:].encode()) +
                _f(3, 2, _rnd(20).encode()) + _f(4, 0, _varint(ts)) +
                _f(5, 2, rnd8.encode()))

    def homeContent(self, f):
        cats = []
        try:
            d = self._http(HOST + '/api/v3/drama/getCategory?orderBy=type_id',
                           None, {'User-Agent': UA, 'Accept': 'application/json'})
            for c in (json.loads(d).get('data') or []):
                if str(c.get('id')) != '29':
                    cats.append({'type_id': str(c['id']),
                                 'type_name': c.get('name', '')})
        except Exception:
            pass
        if not cats:
            cats = [{'type_id': '21', 'type_name': '电影'},
                    {'type_id': '22', 'type_name': '剧集'},
                    {'type_id': '25', 'type_name': '动漫'},
                    {'type_id': '26', 'type_name': '综艺'},
                    {'type_id': '27', 'type_name': '短剧'},
                    {'type_id': '28', 'type_name': '漫剧'}]
        cats.append({'type_id': 'history', 'type_name': '最近在看'})
        return {'class': cats}

    def homeVideoContent(self):
        return {'list': self._list('page=1&pagesize=24')}

    def _vodids(self):
        try:
            d = self._http(HOST + '/api/ex/v3/security/tag/list', None, self._hdr())
            tags = json.loads(d).get('data') or []
            ids = []
            for t in tags:
                for sec in (t.get('sections') or []):
                    for v in (sec.get('vodList') or []):
                        ids.append(str(v.get('id')))
            return ','.join(ids[:6])
        except Exception:
            return ''

    def _list(self, qs):
        out = []
        try:
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            d = self._http(HOST + '/api/proto/v5/drama/category',
                           self._secure(qs), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            if (code[0] if code else 0) != 200:
                return out
            data = [v for fn, wt, v in top if fn == 3 and wt == 2][0]
            for fn, wt, v in _pb(data):
                if fn != 1 or wt != 2:
                    continue
                info = {'vod_id': '', 'vod_name': '', 'vod_pic': '', 'vod_remarks': ''}
                for f2, w2, v2 in _pb(v):
                    if f2 == 3 and w2 == 0:
                        info['vod_id'] = str(v2)
                    elif f2 == 5 and w2 == 2:
                        info['vod_name'] = v2.decode('utf-8', 'replace')
                    elif f2 == 2 and w2 == 2:
                        cands = [v3.decode('utf-8', 'replace')
                                 for f3, w3, v3 in _pb(v2)
                                 if w3 == 2 and v3.startswith(b'http')]
                        if cands:
                            info['vod_pic'] = next(
                                (u for u in cands if u.startswith('https')),
                                cands[0])
                    elif f2 == 13 and w2 == 2:
                        info['vod_remarks'] = v2.decode('utf-8', 'replace')
                if info['vod_id']:
                    out.append(info)
        except Exception:
            pass
        return out

    def categoryContent(self, tid, pg, f, ext):
        pg = int(pg or 1)
        if tid == 'history':
            return {'list': self._history_list(), 'page': 1,
                    'pagecount': 1, 'limit': 40, 'total': 40}
        qs = 'page=%d&pagesize=24&typeId1=%s' % (pg, tid)
        return {'list': self._list(qs), 'page': pg,
                'pagecount': 999, 'limit': 24, 'total': 99999}

    def _history_list(self):
        out = []
        try:
            d = self._http(HOST + '/api/ex/v3/user/history?username=fzcrym',
                           None, {'User-Agent': UA, 'Accept': 'application/json'})
            for it in (json.loads(d).get('data') or []):
                vid = it.get('videoId', '')
                if '|' in vid:
                    frm, url = vid.split('|', 1)
                    out.append({
                        'vod_id': 'h$%s$%s' % (frm, url),
                        'vod_name': it.get('videoName', ''),
                        'vod_pic': it.get('videoCover', ''),
                        'vod_remarks': '%s·第%s集' % (frm, it.get('videoPart', '')),
                    })
        except Exception:
            pass
        return out

    def detailContent(self, ids):
        out = {'vod_id': ids[0]}
        self._cur_id = ids[0]
        if ids[0].startswith('h$'):
            _, frm, url = ids[0].split('$', 2)
            return {'list': [dict(out, vod_name='继续观看',
                                   vod_play_from=frm,
                                   vod_play_url='正片$%s' % url,
                                   vod_pic='',
                                   vod_content='播放历史·线路:' + frm)]}
        try:
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            d = self._http(HOST + '/api/proto/v5/drama/getDetail',
                           self._secure('id=' + ids[0]), hh)
            top = _pb(d)
            data = [v for fn, wt, v in top if fn == 3 and wt == 2][0]
            dd = _pb(data)
            for fn, wt, v in dd:
                if fn == 0 or fn > 100:
                    break  # protobuf 错位起点, 之后全是字符串碎片(乱码源)
                if fn == 9 and wt == 2 and 'vod_name' not in out:
                    out['vod_name'] = v.decode('utf-8', 'replace')
                elif fn == 1 and wt == 2 and 'vod_area' not in out:
                    out['vod_area'] = v.decode('utf-8', 'replace')
                elif fn == 12 and wt == 2 and 'vod_director' not in out:
                    out['vod_director'] = v.decode('utf-8', 'replace')
                elif fn == 16 and wt == 2 and 'vod_actor' not in out:
                    out['vod_actor'] = v.decode('utf-8', 'replace').lstrip(' ,')
                elif fn == 25 and wt == 2 and 'vod_actor' not in out:
                    out['vod_actor'] = v.decode('utf-8', 'replace')
                elif fn == 6 and wt == 2 and 'vod_content' not in out:
                    out['vod_content'] = re.sub(
                        r'<[^>]+>', '', v.decode('utf-8', 'replace'))
                elif fn == 2 and wt == 2 and 'vod_pic' not in out:
                    cands = [v3.decode('utf-8', 'replace')
                             for f3, w3, v3 in _pb(v)
                             if w3 == 2 and v3.startswith(b'http')]
                    if cands:
                        out['vod_pic'] = next(
                            (u for u in cands if u.startswith('https')),
                            cands[0])
            # 演员兜底: f16/f25 无值时从错位块的干净中文串提取
            if 'vod_actor' not in out:
                for fn, wt, v in dd:
                    if fn == 0 and wt == 2:
                        txt = v.decode('utf-8', 'replace')
                        names = re.findall(
                            r'[\u4e00-\u9fa5·]{2,12}(?::?,)'
                            r'?[一-龥·]{2,12}', txt)
                        cand = [x for x in names if len(x) >= 4]
                        if cand:
                            out['vod_actor'] = ','.join(cand[:6])
                            break
            # f29 分集: 详情响应 _pb 会错位, 用原始 0xEA01 tag 扫描
            eps = []
            pos = 0
            n = len(data)
            while True:
                j = data.find(b'\xea\x01', pos)
                if j < 0:
                    break
                k = j + 2
                ln = 0
                sh = 0
                while k < n and data[k] & 0x80:
                    ln |= (data[k] & 0x7f) << sh
                    sh += 7
                    k += 1
                if k >= n:
                    break
                ln |= (data[k] & 0x7f) << sh
                k += 1
                if ln <= 0 or k + ln > n:
                    pos = j + 1
                    continue
                entry = data[k:k + ln]
                pos = k + ln
                title = pth = src = src_cn = ''
                for f3_, w3_, v3_ in _pb(entry):
                    if w3_ != 2:
                        continue
                    if f3_ == 2:
                        title = v3_.decode('utf-8', 'replace')
                    elif f3_ == 3:
                        title = v3_.decode('utf-8', 'replace')
                    elif f3_ == 4:
                        pth = v3_.decode('utf-8', 'replace')
                    elif f3_ == 9:
                        src = v3_.decode('utf-8', 'replace')
                    elif f3_ == 10:
                        src_cn = v3_.decode('utf-8', 'replace')
                if not pth:
                    continue
                # 集名归一化: "第01集"/"第01集完结"→"1"
                mm = re.match(r'^第?0*(\d{1,4})[集话期](?:完结)?$', title)
                if mm:
                    title = mm.group(1)
                eps.append((title, pth, src, src_cn))
            lines = {}
            order = []
            for title, pth, src, src_cn in eps:
                line = src_cn or src or '正片'
                if line not in lines:
                    lines[line] = []
                    order.append(line)
                if re.match(r'(?i).*\.(mp4|m3u8|flv|mkv|avi|ts|mov|mpd|m4a|wmv)(\?.*)?$', pth):
                    ep_url = pth
                else:
                    ep_url = base64.b64encode(json.dumps(
                        {'vodPlayFrom': src, 'playUrl': pth},
                        separators=(',', ':')).encode()).decode()
                lines[line].append('%s$%s' % (title or '正片', ep_url))
            # 集名归一化: "第01集"→"1", 纯数字保留, 其他保留原名
            for ln_name in lines:
                norm = []
                for it in lines[ln_name]:
                    t, u = it.split('$', 1)
                    mm = re.match(r'^第?0*(\d{1,4})[集话期]$', t)
                    norm.append('%s$%s' % (mm.group(1) if mm else t, u))
                lines[ln_name] = norm
            # 线路排序: 超高清最前, 蓝光按名, 其余殿后
            def _rank(nm):
                if '超高清' in nm:
                    return 0
                if '蓝光' in nm:
                    return 1
                return 2
            order.sort(key=lambda x: (_rank(x), x))
            out['_lines'] = order
            out['_lines_map'] = lines
            lines = out.pop('_lines', [])
            lmap = out.pop('_lines_map', {})
            if lines:
                out['vod_play_from'] = '$$$'.join(lines)
                out['vod_play_url'] = '$$$'.join(
                    '#'.join(lmap[l]) for l in lines)
            else:
                out['vod_play_from'] = '橘汁'
                out['vod_play_url'] = '暂无片源$http://'
        except Exception:
            out['vod_name'] = ids[0]
            out['vod_play_from'] = '橘汁'
            out['vod_play_url'] = '播放$http://'
        return {'list': [out]}

    def searchContent(self, key, quick, pg=1):
        try:
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            qs = 'page=%s&pagesize=24&searchKeys=%s' % (pg or 1, key)
            d = self._http(HOST + '/api/proto/v5/drama/search',
                           self._secure(qs), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            if (code[0] if code else 0) != 200:
                return {'list': [], 'page': int(pg or 1)}
            datas = [v for fn, wt, v in top if fn == 3 and wt == 2]
            if not datas:
                return {'list': [], 'page': int(pg or 1)}
            out = []
            for fn, wt, v in _pb(datas[0]):
                if wt != 2 or fn == 0 or fn > 100:
                    continue
                item = {'vod_id': '', 'vod_name': '', 'vod_pic': '',
                        'vod_remarks': ''}
                for f3, w3, v3 in _pb(v):
                    if w3 != 2 and not (f3 == 3 and w3 == 0):
                        continue
                    try:
                        if f3 == 3 and w3 == 0:
                            item['vod_id'] = str(v3)
                        elif f3 == 5:
                            item['vod_name'] = v3.decode('utf-8', 'replace')
                        elif f3 == 2:
                            # 海报 b64串: 取内部http
                            cands = [x.decode('utf-8', 'replace')
                                     for _, w4, x in _pb(v3)
                                     if w4 == 2 and x.startswith(b'http')]
                            if cands:
                                item['vod_pic'] = next(
                                    (u for u in cands if u.startswith('https')),
                                    cands[0])
                        elif f3 == 13:
                            item['vod_remarks'] = v3.decode('utf-8', 'replace')
                        elif f3 == 4:
                            item['vod_content'] = v3.decode(
                                'utf-8', 'replace')[:100]
                    except Exception:
                        pass
                if item['vod_id'] and item['vod_name']:
                    out.append(item)
            return {'list': out, 'page': int(pg or 1)}
        except Exception:
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        url = id
        try:
            if id and not id.startswith('http') and not id.startswith('h$'):
                jm = json.loads(base64.b64decode(id))
                pf, pu = jm.get('vodPlayFrom', ''), jm.get('playUrl', '')
                hh = self._hdr()
                hh['Content-Type'] = 'application/x-protobuf'
                hh['Accept'] = 'application/x-protobuf'
                qs = 'vodPlayFrom=%s&playUrl=%s' % (
                    urllib.parse.quote(pf), urllib.parse.quote(pu, safe=''))
                d = self._http(HOST + '/api/proto/v5/videoUsableUrl',
                               self._secure(qs), hh)
                top = _pb(d)
                code = [v for fn, wt, v in top if fn == 1 and wt == 0]
                if (code[0] if code else 0) == 200:
                    data = [v for fn, wt, v in top if fn == 3 and wt == 2]
                    if data:
                        mm = re.search(rb'https?://[\x21-\x7e]+',
                                       data[0])
                        if mm:
                            url = mm.group(0).decode(
                                'utf-8', 'replace')
            elif not url.startswith('http'):
                url = 'http://'
        except Exception:
            pass
        return {'parse': 0, 'playUrl': '', 'url': url,
                'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        return True

    def isTextFormat(self, url):
        return False

    def destroy(self):
        pass
