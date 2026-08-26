#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# TVBox Python 爬虫 · 咕噜咕噜 (glgl.tv) — 修复版
# 修复内容:
#   1. searchContent 签名改为 (self, key, quick, pg="1") 兼容 TVBox 三参数调用
#   2. homeContent 返回 filters 配置，使 TVBox 显示年份/排序筛选器
#   3. categoryContent 继续使用 m=66 真正分类接口，避免内容重复
# ============================================================
import sys
import json, os, re, time, zlib, base64, hashlib, hmac, secrets
import urllib.request, urllib.parse

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

BASE = "http://103.45.132.22:19987/app/bn"
UA = "Dalvik/2.1.0 (Linux; U; Android 11; Pixel 4)"

# ============ 加密后端 (三级降级) ============
_BACKEND = None
try:
    from Crypto.Cipher import AES as _PAES
    _BACKEND = "pycryptodome"
except Exception:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        _BACKEND = "cryptography"
    except Exception:
        _BACKEND = "pure"

# ---------- 纯 Python AES + GCM (仅当无库时) ----------
if _BACKEND == "pure":
    _SBOX = None
    def _init_sbox():
        global _SBOX, _INV_SBOX, _MUL2, _MUL3, _MUL9, _MUL11, _MUL13, _MUL14
        if _SBOX is not None: return
        p = q = 1
        sb = [0]*256
        while True:
            p = (p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0))
            q ^= q << 1; q ^= q << 2; q ^= q << 4
            q &= 0xFF
            if q & 0x80: q ^= 0x09
            x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
            sb[p] = x & 0xFF ^ 0x63
            if p == 1: break
        sb[0] = 0x63
        _SBOX = sb
        _INV_SBOX = [0]*256
        for i in range(256): _INV_SBOX[sb[i]] = i
        def xt(a):
            a <<= 1
            return (a ^ 0x1B) & 0xFF if a & 0x100 else a
        _MUL2 = [xt(i) for i in range(256)]
        _MUL3 = [_MUL2[i] ^ i for i in range(256)]
        _MUL9 = [0]*256; _MUL11 = [0]*256; _MUL13 = [0]*256; _MUL14 = [0]*256
        for i in range(256):
            m2 = _MUL2[i]; m4 = _MUL2[m2]; m8 = _MUL2[m4]
            _MUL9[i] = m8 ^ i; _MUL11[i] = m8 ^ m2 ^ i
            _MUL13[i] = m8 ^ m4 ^ i; _MUL14[i] = m8 ^ m4 ^ m2

    def _xtime(a):
        a <<= 1
        return (a ^ 0x1B) & 0xFF if a & 0x100 else a

    _RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36,0x6C,0xD8,0xAB,0x4D]

    def _aes128_key_expand(key):
        _init_sbox()
        w = [list(key[i*4:i*4+4]) for i in range(4)]
        for i in range(4, 44):
            t = list(w[i-1])
            if i % 4 == 0:
                t = t[1:] + t[:1]
                t = [_SBOX[b] for b in t]
                t[0] ^= _RCON[i//4-1]
            w.append([w[i-4][j] ^ t[j] for j in range(4)])
        return w

    def _aes256_key_expand(key):
        _init_sbox()
        w = [list(key[i*4:i*4+4]) for i in range(8)]
        for i in range(8, 60):
            t = list(w[i-1])
            if i % 8 == 0:
                t = t[1:] + t[:1]
                t = [_SBOX[b] for b in t]
                t[0] ^= _RCON[i//8-1]
            elif i % 8 == 4:
                t = [_SBOX[b] for b in t]
            w.append([w[i-8][j] ^ t[j] for j in range(4)])
        return w

    def _aes_encrypt_block(w, block):
        s = [[block[r + 4*c] for c in range(4)] for r in range(4)]
        def add_round_key(rnd):
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= w[rnd*4 + c][r]
        def sub_shift():
            for r in range(4):
                row = [_SBOX[s[r][(c + r) % 4]] for c in range(4)]
                for c in range(4): s[r][c] = row[c]
        def mix():
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _MUL2[a[0]] ^ _MUL3[a[1]] ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ _MUL2[a[1]] ^ _MUL3[a[2]] ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ _MUL2[a[2]] ^ _MUL3[a[3]]
                s[3][c] = _MUL3[a[0]] ^ a[1] ^ a[2] ^ _MUL2[a[3]]
        nr = len(w)//4 - 1
        add_round_key(0)
        for rnd in range(1, nr):
            sub_shift(); mix(); add_round_key(rnd)
        sub_shift(); add_round_key(nr)
        out = bytearray(16)
        for c in range(4):
            for r in range(4): out[r + 4*c] = s[r][c]
        return bytes(out)

    def _aes_ecb_encrypt(w, data):
        return b"".join(_aes_encrypt_block(w, data[i:i+16]) for i in range(0, len(data), 16))

    def _pkcs7_pad(d):
        n = 16 - len(d) % 16
        return d + bytes([n])*n

    def _pkcs7_unpad(d):
        return d[:-d[-1]] if d and 1 <= d[-1] <= 16 else d

    def _cbc_encrypt(key, iv, data):
        w = _aes128_key_expand(key) if len(key) == 16 else _aes256_key_expand(key)
        data = _pkcs7_pad(data)
        out = bytearray(); prev = iv
        for i in range(0, len(data), 16):
            blk = bytes(a ^ b for a, b in zip(data[i:i+16], prev))
            prev = _aes_ecb_encrypt(w, blk)
            out += prev
        return bytes(out)

    def _cbc_decrypt(key, iv, data):
        _init_sbox()
        w = _aes128_key_expand(key) if len(key) == 16 else _aes256_key_expand(key)
        nr = len(w)//4 - 1
        inv_sbox = _INV_SBOX
        def dec_block(blk):
            s = [[blk[r + 4*c] for c in range(4)] for r in range(4)]
            def inv_shift():
                for r in range(4):
                    row = [s[r][(c - r) % 4] for c in range(4)]
                    for c in range(4): s[r][c] = row[c]
            def add_rk(rnd):
                for c in range(4):
                    for r in range(4): s[r][c] ^= w[rnd*4 + c][r]
            def inv_sub():
                for r in range(4):
                    for c in range(4): s[r][c] = inv_sbox[s[r][c]]
            def inv_mix():
                for c in range(4):
                    a = [s[r][c] for r in range(4)]
                    s[0][c] = _MUL14[a[0]] ^ _MUL11[a[1]] ^ _MUL13[a[2]] ^ _MUL9[a[3]]
                    s[1][c] = _MUL9[a[0]] ^ _MUL14[a[1]] ^ _MUL11[a[2]] ^ _MUL13[a[3]]
                    s[2][c] = _MUL13[a[0]] ^ _MUL9[a[1]] ^ _MUL14[a[2]] ^ _MUL11[a[3]]
                    s[3][c] = _MUL11[a[0]] ^ _MUL13[a[1]] ^ _MUL9[a[2]] ^ _MUL14[a[3]]
            add_rk(nr)
            for rnd in range(nr-1, 0, -1):
                inv_shift(); inv_sub(); add_rk(rnd); inv_mix()
            inv_shift(); inv_sub(); add_rk(0)
            out = bytearray(16)
            for c in range(4):
                for r in range(4): out[r + 4*c] = s[r][c]
            return bytes(out)
        out = bytearray(); prev = iv
        for i in range(0, len(data), 16):
            blk = data[i:i+16]
            out += bytes(a ^ b for a, b in zip(dec_block(blk), prev))
            prev = blk
        return bytes(out)

    def _ghash(h, data):
        def gmul(a, b):
            r = 0; v = b
            for i in range(127, -1, -1):
                if (a >> i) & 1: r ^= v
                v = (v >> 1) ^ (0xE1 << 120 if v & 1 else 0)
            return r
        def b2i(b): return int.from_bytes(b, "big")
        def i2b(i): return i.to_bytes(16, "big")
        y = 0
        for i in range(0, len(data), 16):
            blk = data[i:i+16]
            if len(blk) < 16: blk = blk + b"\x00" * (16 - len(blk))
            y = gmul(y ^ b2i(blk), b2i(h))
        return i2b(y)

    def _gcm_encrypt(key, nonce, plain):
        w = _aes256_key_expand(key)
        h = _aes_ecb_encrypt(w, b"\x00"*16)
        j0 = nonce + b"\x00\x00\x00\x01"
        ct = bytearray(); counter = 2
        for i in range(0, len(plain), 16):
            ctr_blk = nonce + counter.to_bytes(4, "big")
            ks = _aes_ecb_encrypt(w, ctr_blk)
            blk = plain[i:i+16]
            ct += bytes(a ^ b for a, b in zip(blk, ks[:len(blk)]))
            counter += 1
        pad_ct = ct + b"\x00" * ((16 - len(ct) % 16) % 16)
        lenblk = (0).to_bytes(8, "big") + (len(plain) * 8).to_bytes(8, "big")
        s = _ghash(h, pad_ct + lenblk)
        ekj0 = _aes_ecb_encrypt(w, j0)
        tag = bytes(a ^ b for a, b in zip(s, ekj0))
        return bytes(ct), tag

    def _gcm_decrypt(key, nonce, ct_tag):
        nonce = ct_tag[:12] if nonce is None else nonce
        w = _aes256_key_expand(key)
        ct = ct_tag[:-16] if len(ct_tag) > 16 else ct_tag
        pt = bytearray(); counter = 2
        for i in range(0, len(ct), 16):
            ctr_blk = nonce + counter.to_bytes(4, "big")
            ks = _aes_ecb_encrypt(w, ctr_blk)
            blk = ct[i:i+16]
            pt += bytes(a ^ b for a, b in zip(blk, ks[:len(blk)]))
            counter += 1
        return bytes(pt)

# ---------- 统一加密接口 ----------
def aes_cbc_encrypt(key, iv, data):
    if _BACKEND == "pycryptodome":
        return _PAES.new(key, _PAES.MODE_CBC, iv).encrypt(
            data + bytes([16 - len(data) % 16]) * (16 - len(data) % 16))
    if _BACKEND == "cryptography":
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        pad = 16 - len(data) % 16
        return enc.update(data + bytes([pad])*pad) + enc.finalize()
    return _cbc_encrypt(key, iv, data)

def aes_cbc_decrypt(key, iv, data):
    if _BACKEND == "pycryptodome":
        return _PAES.new(key, _PAES.MODE_CBC, iv).decrypt(data)
    if _BACKEND == "cryptography":
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return dec.update(data) + dec.finalize()
    return _cbc_decrypt(key, iv, data)

def pkcs7_unpad(d):
    return d[:-d[-1]] if d and 1 <= d[-1] <= 16 else d

def aes_gcm_encrypt(key, nonce, data):
    if _BACKEND == "pycryptodome":
        ci = _PAES.new(key, _PAES.MODE_GCM, nonce, mac_len=16)
        ct = ci.encrypt(data)
        return nonce + ct + ci.digest()
    if _BACKEND == "cryptography":
        ct = AESGCM(key).encrypt(nonce, data, None)
        return nonce + ct
    ct, tag = _gcm_encrypt(key, nonce, data)
    return nonce + ct + tag

def aes_gcm_decrypt(key, nonce, ct):
    if _BACKEND == "pycryptodome":
        return _PAES.new(key, _PAES.MODE_GCM, nonce, mac_len=16).decrypt(ct)
    if _BACKEND == "cryptography":
        return AESGCM(key).decrypt(nonce, ct, None)
    return _gcm_decrypt(key, nonce, ct)

# ---------- 纯 Python secp256r1 ECDH ----------
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = P_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

def _pt_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1; x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % _P == 0: return None
        lam = (3 * x1 * x1 + _A) * pow(2 * y1, _P - 2, _P) % _P
    else:
        lam = (y2 - y1) * pow((x2 - x1) % _P, _P - 2, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)

def _pt_mul(k, pt):
    r = None
    while k:
        if k & 1: r = _pt_add(r, pt)
        pt = _pt_add(pt, pt)
        k >>= 1
    return r

def ecdh_keypair():
    priv = secrets.randbelow(_N - 1) + 1
    pub = _pt_mul(priv, (_GX, _GY))
    pub65 = b"\x04" + pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big")
    return priv, pub65

def ecdh_shared(priv, server_pub65):
    sx = int.from_bytes(server_pub65[1:33], "big")
    sy = int.from_bytes(server_pub65[33:65], "big")
    shared = _pt_mul(priv, (sx, sy))
    return shared[0].to_bytes(32, "big")

# ============ protobuf 裸编解码 ============
def pb_varint(n):
    out = b""
    while True:
        b = n & 0x7F; n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n: return out

def pb_read_varint(data, i):
    r, s = 0, 0
    while True:
        b = data[i]; i += 1
        r |= (b & 0x7F) << s
        if not (b & 0x80): return r, i
        s += 7

def pb_field(fnum, wire, payload):
    tag = pb_varint((fnum << 3) | wire)
    if wire == 0: return tag + pb_varint(payload)
    if wire == 2: return tag + pb_varint(len(payload)) + payload
    raise ValueError("wire")

def pb_var(fnum, val):  return pb_field(fnum, 0, val)
def pb_bytes(fnum, b):  return pb_field(fnum, 2, b)
def pb_str(fnum, s):    return pb_field(fnum, 2, s.encode("utf-8") if isinstance(s, str) else s)

def pb_decode(data):
    out, i, n = [], 0, len(data)
    while i < n:
        try:
            tag, i = pb_read_varint(data, i)
            fnum, wire = tag >> 3, tag & 7
            if wire == 0:
                val, i = pb_read_varint(data, i)
                out.append((fnum, 0, val))
            elif wire == 2:
                ln, i = pb_read_varint(data, i)
                out.append((fnum, 2, data[i:i+ln])); i += ln
            elif wire == 1:
                out.append((fnum, 1, data[i:i+8])); i += 8
            elif wire == 5:
                out.append((fnum, 5, data[i:i+4])); i += 4
            else:
                break
        except (IndexError, ValueError):
            break
    return out

def deflate_raw(data, level=6):
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()

def inflate_raw(data):
    return zlib.decompressobj(-15).decompress(data)

# ============ 协议客户端 ============
class GuluClient:
    def __init__(self):
        self.session_id = None
        self.key = None
        self.android_id = secrets.token_hex(8).encode()
        self._booted = False
        self._last_search = 0
        self.parse_apis = {}

    def _post(self, body, session_id="", handshake_key=""):
        req = urllib.request.Request(BASE + "/v2", data=body, method="POST")
        req.add_header("Content-Type", "application/x-protobuf")
        req.add_header("User-Agent", UA)
        req.add_header("X-Player-Page-Protection", "1")
        if session_id: req.add_header("X-Session-Id", session_id)
        if handshake_key: req.add_header("X-Handshake-Key", handshake_key)
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()

    def ensure(self):
        if self.key is not None and self._booted:
            return True
        if not self.handshake():
            return False
        return self.boot()

    def handshake(self):
        priv, pub65 = ecdh_keypair()
        inner = pb_var(1, 1) + pb_var(2, 1) + pb_var(3, 1)
        outer = pb_bytes(1, pub65) + pb_str(2, "1.0.0") + pb_bytes(3, inner)
        hex_key = secrets.token_hex(16)
        iv = os.urandom(16)
        ct = aes_cbc_encrypt(hex_key.encode(), iv, zlib.compress(outer, 5))
        body = base64.b64encode(iv + ct)
        try:
            resp = self._post(body, handshake_key=hex_key)
        except Exception:
            return False
        raw = base64.b64decode(resp)
        plain = pkcs7_unpad(aes_cbc_decrypt(hex_key.encode(), raw[:16], raw[16:]))
        data = zlib.decompress(plain)
        fields = {}
        for f, w, v in pb_decode(data):
            fields.setdefault(f, v)
        if 1 not in fields or 2 not in fields: return False
        self.session_id = fields[1].decode()
        spub = fields[2]
        shared = ecdh_shared(priv, spub)
        prk = hmac.new(self.session_id.encode(), shared, hashlib.sha256).digest()
        okm = b""; t = b""; i = 1
        while len(okm) < 32:
            t = hmac.new(prk, t + b"v2-session" + bytes([i]), hashlib.sha256).digest()
            okm += t; i += 1
        self.key = okm[:32]
        return True

    def boot(self):
        aid = self.android_id.decode()
        device_info = pb_str(1, "咕噜咕噜") + pb_str(2, "2.1.2") \
                    + pb_str(3, "com.jymqfh.xee") + pb_str(4, aid) + pb_str(5, "212")
        device_state = pb_str(1, aid) + pb_var(2, 0) + pb_str(3, "11") \
                     + pb_str(4, "Pixel 4") + pb_str(5, "google/redfin/redfin:11/RQ3A.211001.001") \
                     + pb_str(6, "google") + pb_str(7, "redfin") + pb_var(8, 0) \
                     + pb_str(9, "unknown") + pb_str(10, "unknown") + pb_var(11, 0) \
                     + pb_var(12, 30)
        boot_body = pb_str(1, "v1") + pb_str(2, "Android 11") + pb_str(3, "gulu") \
                  + pb_bytes(4, device_info) + pb_bytes(5, device_state)
        r = self.api(1, 0, boot_body)
        self._booted = r is not None
        if r and r.get("payload"):
            try:
                self.parse_apis = {}
                for f, w, v in pb_decode(r["payload"]):
                    if f == 7 and w == 2:
                        name = url = None
                        for sf, sw, sv in pb_decode(v):
                            if sf == 2 and sw == 2: name = _safe_str(sv)
                            elif sf == 3 and sw == 2: url = _safe_str(sv)
                        if name and url:
                            self.parse_apis[name] = url
            except Exception:
                pass
        return self._booted

    def api(self, service, method, body=b""):
        if self.key is None: return None
        req_id = int(time.time() * 1000)
        ts = req_id
        inner = pb_var(1, req_id) + pb_var(2, service) + pb_var(3, method) \
              + pb_bytes(4, self.android_id) + pb_bytes(5, b"") \
              + pb_bytes(6, body) + pb_var(7, ts)
        compressed = deflate_raw(inner, 6)
        blob = aes_gcm_encrypt(self.key, os.urandom(12), compressed)
        outer = pb_var(1, ts) + pb_bytes(2, blob)
        try:
            resp = self._post(outer, session_id=self.session_id)
        except Exception:
            return None
        fields = pb_decode(resp)
        enc = next((v for f, w, v in fields if f == 2 and w == 2), None)
        if enc is None or len(enc) < 28: return None
        plain = aes_gcm_decrypt(self.key, enc[:12], enc[12:])
        try:
            data = inflate_raw(plain)
        except Exception:
            return None
        out = pb_decode(data)
        code = next((v for f, w, v in out if f == 2 and w == 0), None)
        msg = next((v for f, w, v in out if f == 3 and w == 2), None)
        payload = next((v for f, w, v in out if f == 4 and w == 2), None)
        return {"code": code, "msg": msg, "payload": payload}

# ============ 业务解析 ============
LINE_NAMES = {"dyttm3u8": "电影天堂", "bfzym3u8": "暴风资源",
              "lzm3u8": "量子资源", "ffm3u8": "非凡资源",
              "qq": "腾讯视频", "qiyi": "爱奇艺", "youku": "优酷",
              "newxfyun": "咕噜4K", "xfyun": "咕噜4K二线",
              "CO4K": "咖啡4K超清", "jplink": "金牌极速",
              "rose": "玫瑰4K", "NBY": "蚂蚁资源",
              "qsvip": "旋风VIP", "qingshan": "青山资源"}

CIPHER_API = {
    "CO4K_":     "咖啡4K",
    "rose_":     "咖啡4K",
    "NBY-":      "蚂蚁",
    "qsvip-":    "熊出没",
    "qingshan-": "熊出没",
    "JP-":       "旋风金牌",
    "xfy-":      "新咕噜4K",
}

API_FALLBACK = {
    "咖啡4K":   "https://co4k.1ljx.com:32010/api/?key=6db7285d-c228-4cee-918e-67a01ef7c3f8&url=",
    "蚂蚁":     "https://api.nbyjson.top:7788/api/?key=8LJohkjTZHC2F9ct48&url=",
    "熊出没":   "https://jf.hxx2023.cc/api?key=Uw5rZokFSAywqcLN&url=",
    "旋风金牌": "http://111.170.58.215:4470/api.php?id=",
    "咕噜金牌": "http://111.170.58.215:4470/api.php?id=",
    "新咕噜4K": "http://172.247.189.48:7788/dsxt/api.php?user=xt&key=969632c8da19b3ef8c56e5b51011d5e0&j=19227eae77225a30&url=",
    "咕噜4K":   "http://172.247.189.48:7788/dsxt/api.php?user=xt&key=e1234a9df0358c6d78f20721a1b7b055&j=b8582063bca37121&url=",
}

def _cipher_prefix(url):
    for p in CIPHER_API:
        if url.startswith(p):
            return p
    return None

CATEGORIES = [
    {"type_id": "movie",    "type_name": "电影"},
    {"type_id": "tv",       "type_name": "电视剧"},
    {"type_id": "variety",  "type_name": "综艺"},
    {"type_id": "anime",    "type_name": "动漫"},
    {"type_id": "short",    "type_name": "短剧"},
    {"type_id": "doc",      "type_name": "纪录片"},
    {"type_id": "cn",       "type_name": "大陆剧"},
    {"type_id": "hk",       "type_name": "港剧"},
    {"type_id": "tw",       "type_name": "台剧"},
    {"type_id": "us",       "type_name": "美剧"},
    {"type_id": "kr",       "type_name": "韩剧"},
    {"type_id": "jp",       "type_name": "日剧"},
    {"type_id": "th",       "type_name": "泰剧"},
    {"type_id": "uk",       "type_name": "英剧"},
    {"type_id": "ru",       "type_name": "俄剧"},
]

TYPE_MAP = {
    "movie":    8,   "tv":       9,   "variety":  10,  "anime":    11,
    "short":    12,  "doc":      6,   "cn":       34,  "hk":       41,
    "tw":       42,  "us":       35,  "kr":       36,  "jp":       38,
    "th":       39,  "uk":       37,  "ru":       45,
}

def _get(client):
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GuluClient()
    if not _CLIENT.ensure():
        _CLIENT = GuluClient()
        if not _CLIENT.ensure():
            return None
    return _CLIENT

_CLIENT = None

def _safe_str(b):
    try:
        return b.decode("utf-8")
    except Exception:
        return ""

def _parse_vod_item(item_bytes):
    fields = pb_decode(item_bytes)
    d = {}
    for f, w, v in fields:
        if w == 0:
            if f == 1: d["id"] = v
            elif f == 2: d["year"] = v
            elif f == 4: d["type"] = v
        elif w == 2:
            if f == 3: d["name"] = _safe_str(v)
            elif f == 6: d["pic"] = _safe_str(v)
            elif f == 9: d["remark_alt"] = _safe_str(v)
            elif f == 11: d["remark"] = _safe_str(v)
    return d

def _vod_list_from_payload(payload):
    if not payload: return []
    items = []
    for f, w, v in pb_decode(payload):
        if w != 2 or len(v) < 30: continue
        try:
            sub = pb_decode(v)
        except Exception:
            continue
        f66s = [vv for ff, ww, vv in sub if ff == 66 and ww == 2]
        if f66s:
            for vv in f66s:
                d = _parse_vod_item(vv)
                if d.get("id") and d.get("name"):
                    items.append(d)
            continue
        f2_is_int = any(ff == 2 and ww == 0 for ff, ww, _ in sub)
        if f2_is_int:
            d = _parse_vod_item(v)
            if d.get("id") and d.get("name"):
                items.append(d)
        else:
            for ff, ww, vv in sub:
                if ff == 3 and ww == 2 and len(vv) > 30:
                    d = _parse_vod_item(vv)
                    if d.get("id") and d.get("name"):
                        items.append(d)
    return items

class Spider(_BaseSpider):
    HOST = "http://103.45.132.22:22670"

    def getName(self):
        return "咕噜咕噜"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    # ---------- 首页 ----------
    def homeContent(self, filter):
        c = _get(None)
        result = {"class": CATEGORIES, "list": [], "filters": {}}
        # 筛选配置
        years = [{"n": "全部", "v": ""}] + [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)] + [{"n": "更早", "v": "2009"}]
        sorts = [
            {"n": "最热", "v": "vod_hits_week"},
            {"n": "最新", "v": "vod_time"},
            {"n": "评分", "v": "vod_score"},
        ]
        for cat in CATEGORIES:
            tid = cat["type_id"]
            result["filters"][tid] = [
                {"key": "year", "name": "年份", "init": "", "value": years},
                {"key": "sort", "name": "排序", "init": "vod_hits_week", "value": sorts},
            ]
        # 首页推荐: 电视剧第一页 (m=66 真正分类接口, 不重复)
        try:
            r = c.api(3, 66, pb_var(1, 9) + pb_var(2, 1))
            if r and r.get("payload"):
                for d in _vod_list_from_payload(r["payload"])[:24]:
                    result["list"].append(self._item_to_home(d))
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        c = _get(None)
        try:
            r = c.api(3, 66, pb_var(1, 9) + pb_var(2, 1))
            if r and r.get("payload"):
                lst = [self._item_to_home(d) for d in _vod_list_from_payload(r["payload"])[:24]]
                return {"list": lst}
        except Exception:
            pass
        return {}

    def _item_to_home(self, d):
        return {
            "vod_id": str(d["id"]),
            "vod_name": d.get("name", ""),
            "vod_pic": d.get("pic", ""),
            "vod_remark": d.get("remark") or d.get("remark_alt") or "",
        }

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        c = _get(None)
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1
        f1 = TYPE_MAP.get(str(tid), 9)
        # 解析 extend
        ext = {}
        if isinstance(extend, str) and extend:
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}
        elif isinstance(extend, dict):
            ext = extend
        # 构建请求体
        body = pb_var(1, f1) + pb_var(2, page)
        year = ext.get("year", "")
        if year and year != "":
            body += pb_str(3, str(year))
        sort = ext.get("sort", "")
        if sort and sort != "":
            sort_pb = pb_var(1, 1) + pb_var(2, 0) + pb_str(3, sort)
            body += pb_bytes(5, sort_pb)
        r = c.api(3, 66, body)
        items = []
        total = 0
        if r and r.get("payload"):
            lst = _vod_list_from_payload(r["payload"])
            items = [self._item_to_home(d) for d in lst]
            total = len(lst)
        # 翻页阈值
        if f1 in (8, 9, 10, 11, 12):
            threshold = 10
        elif f1 == 6:
            threshold = 3
        else:
            threshold = 2
        hasmore = 1 if len(items) >= threshold else 0
        return {"list": items, "page": page, "pagecount": page + 1 if hasmore else page,
                "limit": max(total, 12), "total": total}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        c = _get(None)
        vid = int(ids[0])
        body = pb_var(1, vid) + pb_str(4, "APP_PLATFORM_ANDROID_TV") + pb_var(5, 0)
        r = c.api(3, 62, body)
        if not r or not r.get("payload"):
            return {}
        detail = pb_decode(r["payload"])
        vod = {
            "vod_id": str(vid),
            "vod_name": "", "vod_pic": "", "vod_actor": "",
            "vod_director": "", "vod_area": "", "vod_year": "",
            "vod_content": "", "vod_remarks": "", "type_name": "",
        }
        genres, actors, directors = [], [], []
        sources = []
        for f, w, v in detail:
            if w == 0: continue
            if f == 5: vod["vod_name"] = _safe_str(v)
            elif f == 13: vod["vod_pic"] = _safe_str(v)
            elif f == 17: actors.append(_safe_str(v))
            elif f == 18: directors.append(_safe_str(v))
            elif f == 12: genres.append(_safe_str(v))
            elif f == 21: vod["vod_content"] = _safe_str(v)
            elif f == 22: vod["vod_remarks"] = _safe_str(v)
            elif f == 28: vod["vod_area"] = _safe_str(v)
            elif f == 30: vod["vod_year"] = _safe_str(v)
            elif f == 75 and w == 2:
                src = pb_decode(v)
                src_name = ""
                eps = []
                for sf, sw, sv in src:
                    if sf == 1 and sw == 2:
                        src_name = _safe_str(sv)
                    elif sf == 2 and sw == 2 and len(sv) > 10:
                        ep = pb_decode(sv)
                        ep_idx = next((x for ef, ew, x in ep if ef == 1 and ew == 0), None)
                        ep_url = next((x for ef, ew, x in ep if ef == 3 and ew == 2), b"")
                        ep_name = next((x for ef, ew, x in ep if ef == 4 and ew == 2), None)
                        if ep_url:
                            url = _safe_str(ep_url)
                            nm = _safe_str(ep_name) if ep_name else (f"第{ep_idx}集" if ep_idx is not None else "")
                            eps.append((nm, url))
                if eps:
                    sources.append((src_name, eps))
        vod["vod_actor"] = "、".join(actors[:12])
        vod["vod_director"] = "、".join(directors)
        vod["type_name"] = "/".join([g for g in genres if g][:4])
        flags = []
        seen = set()
        for src_name, eps in sources:
            keep = []
            for nm, url in eps:
                if url.startswith("http"):
                    keep.append((nm, url))
                elif _cipher_prefix(url):
                    keep.append((nm, url))
            if not keep:
                continue
            fname = LINE_NAMES.get(src_name, src_name)
            if fname in seen: fname += "2"
            seen.add(fname)
            pairs = [f"{nm}${u}" for nm, u in keep]
            flags.append((fname, "#".join(pairs)))
        if not flags:
            return {"list": [vod]}
        vod["vod_play_from"] = "$$$".join(f for f, _ in flags)
        vod["vod_play_url"] = "$$$".join(u for _, u in flags)
        return {"list": [vod]}

    # ---------- 搜索 (修复签名, 兼容 TVBox 三参数调用) ----------
    def searchContent(self, key, quick, pg="1"):
        """TVBox 搜索入口 — 兼容旧版/新版传参差异"""
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        """TVBox 分页搜索 — 支持真正翻页、快速重试、异常兜底"""
        c = _get(None)
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
        key = str(key).strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1
        if page < 1:
            page = 1

        # 搜索限频 1.2 秒
        now = time.time()
        wait = 1.2 - (now - c._last_search)
        if wait > 0 and c._last_search > 0:
            time.sleep(wait)
        c._last_search = time.time()

        sort = pb_var(1, 1) + pb_var(2, 0) + pb_str(3, "vod_hits_week")
        body = pb_str(1, key) + pb_var(2, page) + pb_bytes(5, sort)

        r = None
        for attempt, delay in enumerate((0.5, 1.0, 2.0, 3.0)):
            try:
                r = c.api(3, 61, body)
            except Exception:
                r = None
            if not r:
                if attempt == 3:
                    break
                time.sleep(delay)
                c._last_search = time.time()
                continue
            payload = r.get("payload")
            if payload and len(payload) > 200:
                break
            if attempt == 3:
                break
            time.sleep(delay)
            c._last_search = time.time()

        if not r or not r.get("payload") or len(r.get("payload", b"")) < 200:
            return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}

        lst = _vod_list_from_payload(r["payload"])
        items = [self._item_to_home(d) for d in lst if d.get("name")]
        hasmore = 1 if len(items) >= 10 else 0
        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if hasmore else page,
            "limit": max(len(items), 12),
            "total": len(items)
        }

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}
        if id.startswith("http"):
            is_stream = (".m3u8" in id) or ("m.php" in id)
            return {"parse": 0 if is_stream else 1,
                    "url": id, "header": {"User-Agent": UA}}
        cid = id
        if cid.startswith(("CO4K_", "rose_")) and "+" in cid and "%2B" not in cid:
            cid = cid.replace(" ", "+")
            cid = urllib.parse.quote(cid, safe=":,_-")
        prefix = _cipher_prefix(cid)
        if not prefix:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}
        api_name = CIPHER_API.get(prefix)
        c = _get(None)
        tmpl = (c.parse_apis.get(api_name) if c else None) or API_FALLBACK.get(api_name)
        if not tmpl:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}
        for _attempt in range(2):
            try:
                api_url = tmpl + urllib.parse.quote(cid, safe="")
                req = urllib.request.Request(api_url)
                req.add_header("User-Agent", UA)
                with urllib.request.urlopen(req, timeout=15) as r:
                    txt = r.read(4096).decode("utf-8", errors="replace")
                got = ""
                try:
                    j = json.loads(txt)
                    got = (j.get("url") or "").strip()
                except Exception:
                    m = re.search(r'"url"\s*:\s*"([^"]+)"', txt)
                    got = m.group(1) if m else ""
                if got:
                    got = got.replace("\\/", "/")
                    return {"parse": 0, "url": got,
                            "header": {"User-Agent": UA}}
            except Exception:
                pass
            time.sleep(0.6)
        return {"parse": 0, "url": "", "header": {"User-Agent": UA}}

    def localProxy(self, param):
        return {"list": [], "parse": 0, "url": ""}

    def liveContent(self, url):
        return {"list": []}
