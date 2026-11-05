# -*- coding: utf-8 -*-
# 橘汁视频 TVBox/AVBox spider
# 修复版：去除第三方加密库硬依赖(纯 Python 实现 AES/RSA)、
#          init 阶段不联网、异常全部就地吞掉、方法签名对齐 AVBox 调用契约。
import json
import re
import sys
import time
import base64
import os
import string
import random
import hashlib
import urllib.request
import urllib.parse

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

# ---------------------------------------------------------------- 加密层
# AVBox 1.3.0 的 pip 只带 lxml/requests/pyquery，没有 pycryptodome。
# 原文件在模块顶层 `from Crypto...` 直接把整个源卡在导入阶段。
# 现在：能用 Crypto 就用（行为与原来完全一致），没有就用内置纯 Python 实现。
try:
    from Crypto.PublicKey import RSA as _CryptoRSA
    from Crypto.Cipher import PKCS1_v1_5 as _CryptoPKCS1
    from Crypto.Cipher import AES as _CryptoAES
    _HAVE_CRYPTO = True
except Exception:
    _HAVE_CRYPTO = False


def _pad(data, block=16):
    """PKCS#7 填充（与 Crypto.Util.Padding.pad 一致）"""
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _unpad(data, block=16):
    n = data[-1]
    if 0 < n <= block and len(data) >= n:
        return data[:-n]
    return data


def _gf_tables():
    alog = [0] * 256
    log = [0] * 256
    x = 1
    for i in range(255):
        alog[i] = x
        log[x] = i
        h = ((x << 1) ^ (0x1B if (x & 0x80) else 0)) & 0xFF
        x = h ^ x
    return alog, log


def _mk_sbox():
    alog, log = _gf_tables()
    sbox = [0] * 256
    for i in range(256):
        if i == 0:
            s = 0
        else:
            s = alog[(255 - log[i]) % 255]
        r = s
        for _ in range(4):
            s = ((s << 1) | (s >> 7)) & 0xFF
            r ^= s
        sbox[i] = r ^ 0x63
    return sbox


_SBOX = _mk_sbox()


def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else (a << 1) & 0xFF


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _key_expansion(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _add_round_key(state, w, rnd):
    for c in range(4):
        kw = w[4 * rnd + c]
        for r in range(4):
            state[r + 4 * c] ^= kw[r]


def _sub_bytes(state):
    for i in range(16):
        state[i] = _SBOX[state[i]]


def _shift_rows(state):
    # AES 行移位：第 r 行循环左移 r 位（state 为列主序 flat 索引 r + 4c）
    for r in range(1, 4):
        row = [state[r + 4 * c] for c in range(4)]
        for c in range(4):
            state[r + 4 * c] = row[(c + r) % 4]


def _mix_columns(state):
    for c in range(4):
        a = [state[r + 4 * c] for r in range(4)]
        state[0 + 4 * c] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
        state[1 + 4 * c] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
        state[2 + 4 * c] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
        state[3 + 4 * c] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)


def _aes_encrypt_block(block, w, nr):
    state = list(block)
    _add_round_key(state, w, 0)
    for rnd in range(1, nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, w, rnd)
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, w, nr)
    return bytes(state)


class _PureAES:
    MODE_ECB = 1
    MODE_CBC = 2

    @classmethod
    def new(cls, key, mode, iv=None):
        return cls(key, mode, iv)

    def __init__(self, key, mode, iv=None):
        if len(key) not in (16, 24, 32):
            raise ValueError('invalid AES key size')
        self.key = bytes(key)
        self.mode = mode
        self.iv = bytes(iv) if iv else b'\x00' * 16
        self._w, self._nr = _key_expansion(self.key)

    def encrypt(self, data):
        out = bytearray()
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            if self.mode == _PureAES.MODE_CBC:
                blk = bytes(a ^ b for a, b in zip(blk, prev))
            enc = _aes_encrypt_block(blk, self._w, self._nr)
            out += enc
            prev = enc
        return bytes(out)


def _der_read(buf, i):
    tag = buf[i]
    i += 1
    ln = buf[i]
    i += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[i:i + n], 'big')
        i += n
    return tag, buf[i:i + ln], i + ln


def _rsa_pub_from_der(der):
    """解析 DER：支持 SubjectPublicKeyInfo 与裸 RSAPublicKey"""
    tag, seq, _ = _der_read(der, 0)
    if tag != 0x30:
        raise ValueError('bad rsa key')
    i = 0
    t1, first, i = _der_read(seq, i)
    if i >= len(seq):
        raise ValueError('bad rsa key')
    t2, second, _ = _der_read(seq, i)
    if t2 == 0x03:
        inner = second[1:]
        _, rs, _ = _der_read(inner, 0)
    elif t2 == 0x30:
        rs = second
    else:
        raise ValueError('bad rsa key')
    j = 0
    _, nb, j = _der_read(rs, j)
    _, eb, _ = _der_read(rs, j)
    return int.from_bytes(nb, 'big'), int.from_bytes(eb, 'big')


class _PurePKCS1:
    def __init__(self, key):
        self.n, self.e = key

    def encrypt(self, msg):
        k = (self.n.bit_length() + 7) // 8
        if len(msg) > k - 11:
            raise ValueError('data too long for RSA')
        ps = bytearray()
        while len(ps) < k - len(msg) - 3:
            b = os.urandom(1)
            if b != b'\x00':
                ps += b
        em = b'\x00\x02' + bytes(ps) + b'\x00' + msg
        c = pow(int.from_bytes(em, 'big'), self.e, self.n)
        return c.to_bytes(k, 'big')


if _HAVE_CRYPTO:
    AES = _CryptoAES
    PKCS1_v1_5 = _CryptoPKCS1

    def _rsa_public(der_b64):
        return _CryptoPKCS1.new(_CryptoRSA.import_key(base64.b64decode(der_b64)))
else:
    AES = _PureAES
    PKCS1_v1_5 = _PurePKCS1

    def _rsa_public(der_b64):
        return _PurePKCS1(_rsa_pub_from_der(base64.b64decode(der_b64)))


# ---------------------------------------------------------------- 常量
PUB1_B64 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB'
NATIVE_K = b'ed5fdsgucxumegqa'
SAFE = b'OC1A06E197EF10CF3F6058CA7A803B5E'
PW_SAFE = b'11GK2we32144LO&hilUITB)FMd1khdaF'
CERT_MD5 = '6457E81AF1F6D3BC229E33ED60F248A5'
CERT_SHA1 = '8350E6AAEC7A4D8A174377892B4364CFA2066B85'
PKG = 'com.exxammpea.a1'
VC = '3026'
HOST = 'https://gdsaj.hzhcbkj.cn'
UA = 'okhttp/3.12.1'

_e = base64.b64encode(AES.new(PW_SAFE, AES.MODE_ECB).encrypt(_pad(
    (CERT_MD5 + '######' + CERT_SHA1 + '~~~~~~' + PKG + '>>>+++' + VC).encode(), 16))).decode()
_e2 = base64.b64encode(_e.encode()).decode()
SAFECODE = (_e2[:16] + _e2[-16:]).upper()


# ---------------------------------------------------------------- protobuf 工具
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
    # 正确的 protobuf 解析：字段号 > 15 时 tag 是多字节 varint，
    # 只读一个字节会造成整体错位（老版本源文件就是因此只能按原始字节扫描）
    out = []
    i = 0
    n = len(buf)
    while i < n:
        tag = 0
        sh = 0
        while i < n:
            x = buf[i]; i += 1
            tag |= (x & 0x7f) << sh; sh += 7
            if not x & 0x80:
                break
        fn, wt = tag >> 3, tag & 7
        if fn == 0:
            break
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


# ---------------------------------------------------------------- Spider
class Spider(_Base):
    HOST_NAME = '橘汁视频'

    def getName(self):
        return '橘汁视频'

    _cur_id = ''

    # init 只做本地初始化，绝不联网、绝不抛异常。
    # 原版在这里做 _login()/_zone()，_zone() 里 [..][0] 在服务端返回异常结构时
    # 会抛 IndexError，客户端实例化失败 → 首页直接显示「加载失败，请检查网络」。
    def init(self, extend=''):
        try:
            self.extend = extend or ''
            self.udid = hashlib.md5(str(time.time()).encode()).hexdigest()[:16].upper()
            self._rsa1 = _rsa_public(PUB1_B64)
            self._rsa2 = None
            self._token = ''
            self._ready = False
            self._tried = False
            self._last_try = 0
        except Exception:
            self.udid = '0000000000000000'
            self._rsa1 = None
            self._rsa2 = None
            self._token = ''
            self._ready = False
            self._tried = True
            self._last_try = 0

    # 懒加载：真正要用数据时再去登录 + 取二级公钥，失败也不抛给客户端。
    # 服务端/网络偶发抖动（代理 403 等）不应把整个源永久锁死，
    # 所以这里带内部重试，且失败后隔 60 秒还允许再次尝试。
    def _ensure(self):
        try:
            if self._ready:
                return True
            now = int(time.time())
            if self._tried and now - self._last_try < 60:
                return False
            self._tried = True
            self._last_try = now
            for _ in range(3):
                try:
                    self._login()
                    self._zone()
                    if self._rsa2 is not None:
                        self._ready = True
                        break
                except Exception:
                    pass
                time.sleep(2)
        except Exception:
            self._ready = False
        return bool(self._ready)

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
        try:
            ts = int(time.time() * 1000)
            rnd = _rnd(16)
            sign = base64.b64encode(self._rsa1.encrypt((str(ts) + rnd).encode())).decode()
            body = (_f(1, 0, _varint(ts)) + _f(2, 2, sign.encode()) +
                    _f(3, 2, rnd.encode()) + _f(4, 2, rnd.encode()) + _f(5, 2, rnd.encode()))
            P = {'plat': 'tv', 'vOs': '16', '_vOsCode': '36', 'vApp': VC,
                 'vName': '3.0.2.6', 'pkg': PKG,
                 'appName': '%E6%A9%98%E6%B1%81',
                 'udid': self.udid, 'uuid': self.udid, 'chid': '10000',
                 'androidID': self.udid, 'net': '1', 'young': 0, 'tenantId': '*',
                 'v': 1, 'device': 0, 'lang': 'zh', 'country': 'CN', 'cpu': 'arm64-v8a'}
            d = self._http(HOST + '/api/v5/find/app/zone', body, {
                'User-Agent': UA, 'Content-Type': 'application/x-protobuf',
                'Accept': 'application/x-protobuf', 'Cache-Control': 'no-cache',
                'publicParams': json.dumps(P, separators=(',', ':'))})
            top = _pb(d)
            inner = [v for fn, wt, v in top if fn == 3 and wt == 2]
            if not inner:
                raise ValueError('no secondary key')
            strs = {fn: v for fn, wt, v in _pb(inner[0]) if wt == 2}
            self._rsa2 = _rsa_public(
                (strs[1] + strs[2] + strs[4] + strs[5]).decode())
        except Exception:
            self._rsa2 = None

    def _hdr(self):
        ts = int(time.time() * 1000)
        rnd = _rnd(16)
        sig = base64.b64encode(self._rsa2.encrypt((str(ts) + rnd + VC).encode())).decode()
        ao = base64.b64encode(AES.new(SAFE, AES.MODE_ECB).encrypt(
            _pad((str(ts) + rnd).encode(), 16))).decode()
        J = {'country': 'CN', 'vName': '3.0.2.6', 'cpuId': '', 'young': 0,
             'facturer': 'OnePlus', 'pkg': PKG, 'uuid': self.udid,
             'resolution': '1080x2256', 'mac': '02%3A00%3A00%3A00%3A00',
             'sig': sig, 'abid': '7470', 'model': 'PJX110', 'plat': 'tv',
             'udid': self.udid, 'dpi': '480', 'net': '1', 'lang': 'zh',
             'random_str': rnd, 'brand': 'OnePlus', 'timestamp': ts,
             'density': '3.0', 'appName': '%E6%A9%98%E6%B1%81',
             'cpu': 'arm64-v8a', 'chid': '10000', 'carrier': '%E8%81%94%E9%80%9A',
             'sig2': ao[:8], 'v': 1, 'sig3': ao[8:], 'tenantId': '*',
             '_vOsCode': '36', 'vOs': '16', 'vApp': VC, 'device': 0,
             'androidID': self.udid}
        # 当前官方 APK 的格式：publicParams 直接是明文 J JSON
        # （BaseStatisticsParamsUtils.a() 统计参数 + NetSecurityParamsHelper.a()
        #  追加 timestamp/random_str/sig/sig2/sig3），token 单独走请求头
        h = {'User-Agent': UA, 'Accept': 'application/json',
             'Cache-Control': 'no-cache',
             'publicParams': json.dumps(J, separators=(',', ':'),
                                       ensure_ascii=False)}
        if self._token:
            h['token'] = self._token
        return h

    # ex/v3 响应的 data 字段为双层 AES 加密串：先 SAFECODE 解，再 SAFE 解
    def _dec_data(self, data):
        try:
            if not data or not isinstance(data, str):
                return data
            r1 = _unpad(AES.new(SAFECODE.encode(), AES.MODE_ECB).decrypt(
                base64.b64decode(data)))
            r2 = _unpad(AES.new(SAFE, AES.MODE_ECB).decrypt(
                base64.b64decode(r1)))
            return json.loads(r2.decode('utf-8', 'replace'))
        except Exception:
            return None

    # 详情/播放走的是「map 直传」通道：NetSecurityParamsHelper.g(map) 只做
    # 'k=v&k2=v2' 拼接（不做 query= 封装、不做双层 AES），
    # 再由 h() 追加时间戳后单层 AES(SAFECODE) 加密。
    def _secure_map(self, param):
        ts = int(time.time() * 1000)
        rnd = _rnd(16)
        plain = (param + str(ts)).encode()
        ct = AES.new(SAFECODE.encode(), AES.MODE_ECB).encrypt(_pad(plain, 16))
        b64 = base64.b64encode(ct).decode()
        return (_f(1, 2, (rnd + b64[:4]).encode()) +
                _f(2, 2, b64[4:].encode()) +
                _f(3, 2, _rnd(20).encode()) + _f(4, 0, _varint(ts)) +
                _f(5, 2, rnd.encode()))

    def _secure(self, mapkv):
        # proto/v5 载荷需双层 AES 编码后包成 query= 参数（见当前官方 APK
        # ExtendUtilsKt.getRequestVideoListParams + ResponseDecodeManager.encodeQuery）
        e1 = base64.b64encode(AES.new(SAFE, AES.MODE_ECB).encrypt(
            _pad(mapkv.encode(), 16))).decode()
        e2 = base64.b64encode(AES.new(SAFECODE.encode(), AES.MODE_ECB).encrypt(
            _pad(e1.encode(), 16))).decode()
        payload = 'query=' + e2
        ts = int(time.time() * 1000)
        rnd16 = _rnd(16)
        plain = (payload + str(ts)).encode()
        ct = AES.new(SAFECODE.encode(), AES.MODE_ECB).encrypt(_pad(plain, 16))
        b64 = base64.b64encode(ct).decode()
        return (_f(1, 2, (rnd16 + b64[:4]).encode()) +
                _f(2, 2, b64[4:].encode()) +
                _f(3, 2, _rnd(20).encode()) + _f(4, 0, _varint(ts)) +
                _f(5, 2, rnd16.encode()))

    # ---- AVBox 调用约定：homeContent(ru, filter) → ru.homeContent(filter)
    def homeContent(self, filter=False):
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
        try:
            return {'list': self._list('page=1&pagesize=24')}
        except Exception:
            return {'list': []}

    def _vodids(self):
        try:
            d = self._http(HOST + '/api/ex/v3/security/tag/list', None, self._hdr())
            tags = self._dec_data(json.loads(d).get('data')) or []
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
            if not self._ensure():
                return out
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            d = self._http(HOST + '/api/proto/v5/drama/category',
                           self._secure_map(qs), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            if (code[0] if code else 0) != 200:
                return out
            data = [v for fn, wt, v in top if fn == 3 and wt == 2]
            if not data:
                return out
            for fn, wt, v in _pb(data[0]):
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

    # ---- AVBox 调用约定：categoryContent 的 extend 传 dict
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            if str(tid) == 'history':
                return {'list': self._history_list(), 'page': 1,
                        'pagecount': 1, 'limit': 40, 'total': 40}
            qs = 'page=%d&pagesize=24&typeId1=%s' % (pg, tid)
            return {'list': self._list(qs), 'page': pg,
                    'pagecount': 999, 'limit': 24, 'total': 99999}
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 24, 'total': 0}

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

    # ---- AVBox 调用约定：detailContent 的 ids 传 list
    def detailContent(self, ids):
        try:
            ids = list(ids or [])
            if not ids:
                return {'list': []}
        except Exception:
            return {'list': []}
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
            if not self._ensure():
                raise ValueError('secondary key unavailable')
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            d = self._http(HOST + '/api/proto/v5/drama/getDetail',
                           self._secure_map('id=' + ids[0]), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            if (code[0] if code else 0) != 200:
                return {'list': []}
            data = [v for fn, wt, v in top if fn == 3 and wt == 2]
            if not data:
                return {'list': []}
            dd = _pb(data[0])
            eps = []
            for fn, wt, v in dd:
                if wt == 2 and fn == 29:
                    ep = {}
                    for f3, w3, v3 in _pb(v):
                        if w3 == 2:
                            ep[f3] = v3.decode('utf-8', 'replace')
                    if ep.get(4):
                        eps.append(ep)
                    continue
                if wt != 2:
                    if fn == 18 and 'vod_year' not in out:
                        out['vod_year'] = str(v)
                    continue
                if fn == 9 and 'vod_name' not in out:
                    out['vod_name'] = v.decode('utf-8', 'replace')
                elif fn == 1 and 'vod_area' not in out:
                    out['vod_area'] = v.decode('utf-8', 'replace')
                elif fn == 2 and 'vod_pic' not in out:
                    cands = []
                    for f3, w3, v3 in _pb(v):
                        if w3 == 2:
                            t = v3.decode('utf-8', 'replace')
                            if t.startswith('http'):
                                cands.append(t)
                    if cands:
                        out['vod_pic'] = next((u for u in cands
                                                if u.startswith('https')), cands[0])
                elif fn == 6 and 'vod_content' not in out:
                    out['vod_content'] = re.sub(
                        r'<[^>]+>', '', v.decode('utf-8', 'replace'))
                elif fn == 12 and 'vod_director' not in out:
                    out['vod_director'] = v.decode('utf-8', 'replace')
                elif fn == 25 and 'vod_actor' not in out:
                    out['vod_actor'] = v.decode('utf-8', 'replace')
                elif fn == 26 and 'vod_remarks' not in out:
                    out['vod_remarks'] = v.decode('utf-8', 'replace')
                elif fn == 28 and 'vod_note' not in out:
                    out['vod_note'] = v.decode('utf-8', 'replace')
            # 分集 -> 线路
            lines = {}
            order = []
            for ep in eps:
                title = ep.get(2) or ep.get(3) or ''
                pth = ep.get(4) or ''
                src = ep.get(9) or ''
                src_cn = ep.get(10) or ''
                line = src_cn or src or '正片'
                if line not in lines:
                    lines[line] = []
                    order.append(line)
                if re.match(r'(?i).*\.(mp4|m3u8|flv|mkv|avi|ts|mov|mpd|m4a|wmv)'
                            r'(\?.*)?$', pth):
                    ep_url = pth
                else:
                    ep_url = base64.b64encode(json.dumps(
                        {'vodPlayFrom': src, 'playUrl': pth},
                        separators=(',', ':')).encode()).decode()
                mm = re.match(r'^第?0*(\d{1,4})[集话期](?:完结)?$', title)
                if mm:
                    title = mm.group(1)
                lines[line].append('%s$%s' % (title or '正片', ep_url))
            # 线路排序（2026-10-31 用户要求）：
            # 把 自建4K-2 / 自建4K-3 / 自建4K-4 排到最前面，JD4K 紧随其后，
            # 其余线路（超高清 / 蓝光 / 其他）保持原有相对顺序不变。
            def _line_rank(nm):
                if nm.startswith('自建4K'):
                    return (0, nm)
                if nm == '蓝光':
                    return (1, nm)
                return (2, 0 if 'JD4K' in nm else
                        1 if '超高清' in nm else 2, nm)
            order.sort(key=_line_rank)
            if lines:
                out['vod_play_from'] = '$$$'.join(order)
                out['vod_play_url'] = '$$$'.join('#'.join(lines[nm])
                                               for nm in order)
                out['vod_remarks'] = out.get('vod_remarks') or (
                    '全集' if eps else '')
            out.setdefault('vod_name', '')
            out.setdefault('vod_pic', '')
            return {'list': [out]}
        except Exception:
            return {'list': [out] if out.get('vod_name') else []}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            if not self._ensure():
                return {'list': [], 'page': pg}
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            qs = 'page=%s&pagesize=24&searchKeys=%s' % (pg, key)
            d = self._http(HOST + '/api/proto/v5/drama/search',
                           self._secure_map(qs), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            if (code[0] if code else 0) != 200:
                return {'list': [], 'page': pg}
            datas = [v for fn, wt, v in top if fn == 3 and wt == 2]
            if not datas:
                return {'list': [], 'page': pg}
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
            return {'list': out, 'page': pg}
        except Exception:
            return {'list': [], 'page': 1}

    # ---- AVBox 调用约定：playerContent 的 vipFlags 传 list
    def playerContent(self, flag, id, vipFlags=None):
        url = id or ''
        try:
            if id and not id.startswith('http') and not id.startswith('h$'):
                jm = json.loads(base64.b64decode(id))
                pf = jm.get('vodPlayFrom', '')
                pu = jm.get('playUrl', '')
                if not self._ensure():
                    raise ValueError('secondary key unavailable')
                hh = self._hdr()
                hh['Content-Type'] = 'application/x-protobuf'
                hh['Accept'] = 'application/x-protobuf'
                qs = 'vodPlayFrom=%s&playUrl=%s' % (
                    urllib.parse.quote(pf), urllib.parse.quote(pu, safe=''))
                d = self._http(HOST + '/api/proto/v5/videoUsableUrl',
                               self._secure_map(qs), hh)
                top = _pb(d)
                code = [v for fn, wt, v in top if fn == 1 and wt == 0]
                if (code[0] if code else 0) == 200:
                    data = [v for fn, wt, v in top if fn == 3 and wt == 2]
                    if data:
                        got = ''
                        for fn, wt, v in _pb(data[0]):
                            if fn == 1 and wt == 2:
                                t = v.decode('utf-8', 'replace')
                                if t.startswith('http'):
                                    got = t
                                    break
                        if not got:
                            mm = re.search(rb'https?://[\x21-\x7e]+', data[0])
                            if mm:
                                got = mm.group(0).decode('utf-8', 'replace')
                        if got:
                            url = got
            elif not url.startswith('http'):
                url = 'http://'
        except Exception:
            pass
        return {'parse': 0, 'playUrl': '', 'url': url,
                'header': {'User-Agent': UA}}

    def localProxy(self, url):
        try:
            return url
        except Exception:
            return None

    def liveContent(self, filter=False):
        try:
            return {'list': []}
        except Exception:
            return {'list': []}

    def isVideoFormat(self, url):
        return True

    def isTextFormat(self, url):
        return False

    def destroy(self):
        try:
            self._ready = False
            self._tried = True
        except Exception:
            pass
