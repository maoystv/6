# -*- coding: utf-8 -*-
"""
咕噜咕噜 —— TVBox T3 源（type=3 Python 爬虫）。

由上传的 T4 版「咕噜💕.py」改写：
  · 接口层：VodHandler(home/category/detail/search/player) -> T3 Spider 五接口
    (homeContent/categoryContent/detailContent/searchContent/playerContent)
  · 依赖层：T3 运行时无 requests / pycryptodome，全部降级为纯标准库：
    P-256 点运算(ECDH)、AES-256-CBC 握手、AES-256-GCM 会话、urllib HTTP、手动 gzip
  · 协议逻辑（protobuf 编解码、握手、boot 线路表、搜索/详情/播放）原样保留

协议要点（勿删）：
  · handshake：本地生成 P-256 密钥对 -> ECC ECDH 协商共享密钥 -> HKDF 派生会话密钥
  · 会话后所有请求 AES-GCM 加密（nonce+ciphertext+tag），内层 zlib raw-deflate
  · 列表/详情/播放都走 POST（明文 http://103.45.132.22:19987/app/bn/v2）
  · boot() 从服务器拉 players（线路表）+ parsers（解析器表）
  · detail 有版本守卫：响应含 VERSION_GUARD_MARKERS 时拒绝（服务器要求升级）
  · play：id 格式 "play_id@parser_id@vod_name@index"，分服务端/外部解析两种

T3 运行说明：
  - TVBox type=3 配置：api 填本文件公网 URL；searchable/quickSearch/filterable 按需
  - 类名约定 Spider；文件底部另提供模块级函数双入口（drpy site 模式兼容）
  - 命令行自检：python 咕噜💕-T3.py home | search 关键词 | category 分类 页 | detail id | play 解析器 id
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import quote

API_URL = "http://103.45.132.22:19987/app/bn/v2"
HOST = "http://103.45.132.22:19987"
USER_AGENT = "Dart/3.10 (dart:io)"
APP_VERSION = "2.1.3"
BUILD_NUMBER = "20109"
APP_SIGNATURE = "32E0AB4FF93A29CE0E6F0BFB01F2F1B788E76262731F3F30F509CB822428ED58"
DEVICE_BUILD = "pangu-build-component-system-513739-s9vkd-rlxnj-p3rhm"
VERSION_GUARD_MARKERS = ("__v99_", "glgl.tv", "111.170.58.215", "shu.jpg")
FALLBACK_PARSERS = {
    28: {"name": "咕噜金牌", "url": "http://111.170.58.215:5499/api.php?id=",
         "mode": "json", "result_key": "url", "server": False},
}


# ============ protobuf 工具 ============

def _varint(value):
    if value < 0:
        raise ValueError("negative protobuf varint")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field_bytes(number, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _field_varint(number, value):
    return _varint(number << 3) + _varint(value)


def _read_varint(data, position):
    value = 0
    shift = 0
    while position < len(data) and shift < 70:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, position
        shift += 7
    raise ValueError("invalid protobuf varint")


def _parse_fields(data):
    fields = []
    position = 0
    while position < len(data):
        key, position = _read_varint(data, position)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("invalid protobuf field zero")
        if wire == 0:
            value, position = _read_varint(data, position)
        elif wire == 1:
            value = data[position:position + 8]
            position += 8
        elif wire == 2:
            size, position = _read_varint(data, position)
            value = data[position:position + size]
            position += size
        elif wire == 5:
            value = data[position:position + 4]
            position += 4
        else:
            raise ValueError("unsupported protobuf wire type %d" % wire)
        if position > len(data):
            raise ValueError("truncated protobuf field")
        fields.append((number, wire, value))
    return fields


def _field_values(data, number, wire=None):
    return [v for n, w, v in _parse_fields(data)
            if n == number and (wire is None or w == wire)]


def _field_value(data, number, default=None, wire=None):
    values = _field_values(data, number, wire)
    return values[-1] if values else default


def _text(value, default=""):
    if not isinstance(value, bytes):
        return value
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return default


def _packed_varints(data):
    values = []
    position = 0
    while position < len(data):
        value, position = _read_varint(data, position)
        values.append(value)
    return values


def _raw_deflate(data):
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15,
                                  memLevel=8, strategy=zlib.Z_RLE)
    return compressor.compress(data) + compressor.flush()


# ============ 纯标准库密码学 ============

def _xtime(a):
    b = a << 1
    if b & 0x100:
        b ^= 0x11B
    return b & 0xFF


def _gf256_mul(a, b):
    result = 0
    while b:
        if b & 1:
            result ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return result


def _build_aes_tables():
    exp = [0] * 256
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x = _gf256_mul(x, 0x03)
    sbox = [0] * 256
    inv_sbox = [0] * 256
    for i in range(256):
        inv = 0 if i == 0 else exp[(255 - log[i]) % 255]
        t = inv
        s = inv
        for _ in range(4):
            s = ((s << 1) | (s >> 7)) & 0xFF
            t ^= s
        sbox[i] = t ^ 0x63
        inv_sbox[sbox[i]] = i
    return bytes(sbox), bytes(inv_sbox)


_SBOX, _INV_SBOX = _build_aes_tables()


def _expand_key(key):
    rcon = 1
    words = [list(key[i:i + 4]) for i in range(0, 32, 4)]
    while len(words) < 60:
        temp = words[-1][:]
        if len(words) % 8 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        elif len(words) % 8 == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[-8][i] ^ temp[i] for i in range(4)])
    return [sum((words[i:i + 4]), []) for i in range(0, 60, 4)]


def _shift_rows(state, encrypt=True):
    out = [0] * 16
    for r in range(4):
        for c in range(4):
            out[r + 4 * c] = state[r + 4 * ((c + (r if encrypt else -r)) % 4)]
    return out


def _mix_columns(state):
    out = state[:]
    for c in range(4):
        a = out[0 + 4 * c]
        b = out[1 + 4 * c]
        d = out[2 + 4 * c]
        e = out[3 + 4 * c]
        t = a ^ b ^ d ^ e
        out[0 + 4 * c] = a ^ t ^ _xtime(a ^ b)
        out[1 + 4 * c] = b ^ t ^ _xtime(b ^ d)
        out[2 + 4 * c] = d ^ t ^ _xtime(d ^ e)
        out[3 + 4 * c] = e ^ t ^ _xtime(e ^ a)
    return out


def _mul9(x):
    return _xtime(_xtime(_xtime(x))) ^ x


def _mul11(x):
    return _xtime(_xtime(_xtime(x))) ^ _xtime(x) ^ x


def _mul13(x):
    return _xtime(_xtime(_xtime(x))) ^ _xtime(_xtime(x)) ^ x


def _mul14(x):
    return _xtime(_xtime(_xtime(x))) ^ _xtime(_xtime(x)) ^ _xtime(x)


def _inv_mix_columns(state):
    out = state[:]
    for c in range(4):
        a = out[0 + 4 * c]
        b = out[1 + 4 * c]
        d = out[2 + 4 * c]
        e = out[3 + 4 * c]
        out[0 + 4 * c] = _mul14(a) ^ _mul11(b) ^ _mul13(d) ^ _mul9(e)
        out[1 + 4 * c] = _mul9(a) ^ _mul14(b) ^ _mul11(d) ^ _mul13(e)
        out[2 + 4 * c] = _mul13(a) ^ _mul9(b) ^ _mul14(d) ^ _mul11(e)
        out[3 + 4 * c] = _mul11(a) ^ _mul13(b) ^ _mul9(d) ^ _mul14(e)
    return out


def _aes_encrypt_block(block, round_keys):
    state = [s ^ k for s, k in zip(block, round_keys[0])]
    for r in range(1, 14):
        state = [_SBOX[b] for b in state]
        state = _shift_rows(state, True)
        state = _mix_columns(state)
        state = [s ^ k for s, k in zip(state, round_keys[r])]
    state = [_SBOX[b] for b in state]
    state = _shift_rows(state, True)
    return bytes([s ^ k for s, k in zip(state, round_keys[14])])


def _aes_decrypt_block(block, round_keys):
    state = [s ^ k for s, k in zip(block, round_keys[14])]
    for r in range(13, 0, -1):
        state = _shift_rows(state, False)
        state = [_INV_SBOX[b] for b in state]
        state = [s ^ k for s, k in zip(state, round_keys[r])]
        state = _inv_mix_columns(state)
    state = _shift_rows(state, False)
    state = [_INV_SBOX[b] for b in state]
    return bytes([s ^ k for s, k in zip(state, round_keys[0])])


def _pkcs7_pad(data):
    size = 16 - (len(data) % 16)
    return data + bytes([size] * size)


def _pkcs7_unpad(data):
    if not data:
        raise ValueError("empty plaintext")
    size = data[-1]
    if size < 1 or size > 16 or data[-size:] != bytes([size] * size):
        raise ValueError("invalid PKCS7 padding")
    return data[:-size]


def _aes256_cbc_encrypt(key, iv, data):
    round_keys = _expand_key(key)
    previous = iv
    out = bytearray()
    data = _pkcs7_pad(data)
    for i in range(0, len(data), 16):
        block = bytes(b ^ p for b, p in zip(data[i:i + 16], previous))
        enc = _aes_encrypt_block(block, round_keys)
        out += enc
        previous = enc
    return bytes(out)


def _aes256_cbc_decrypt(key, iv, data):
    round_keys = _expand_key(key)
    previous = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        dec = _aes_decrypt_block(block, round_keys)
        out += bytes(b ^ p for b, p in zip(dec, previous))
        previous = block
    return _pkcs7_unpad(bytes(out))


_GCM_REDUCTION = 0xE1000000000000000000000000000000


def _ghash_mul(x, y):
    z = 0
    for i in range(128):
        if (x >> (127 - i)) & 1:
            z ^= y
        if y & 1:
            y = (y >> 1) ^ _GCM_REDUCTION
        else:
            y >>= 1
    return z


def _ghash(h, aad, ciphertext):
    y = 0
    for i in range(0, len(aad), 16):
        block = int.from_bytes(aad[i:i + 16].ljust(16, b"\x00"), "big")
        y = _ghash_mul(y ^ block, h)
    for i in range(0, len(ciphertext), 16):
        block = int.from_bytes(ciphertext[i:i + 16].ljust(16, b"\x00"), "big")
        y = _ghash_mul(y ^ block, h)
    lengths = (len(aad) * 8).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")
    return _ghash_mul(y ^ int.from_bytes(lengths, "big"), h)


def _aes256_gcm_encrypt(key, nonce, data, aad=b""):
    round_keys = _expand_key(key)
    h = int.from_bytes(_aes_encrypt_block(b"\x00" * 16, round_keys), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    counter = int.from_bytes(j0, "big")
    out = bytearray()
    for i in range(0, len(data), 16):
        counter += 1
        keystream = _aes_encrypt_block(counter.to_bytes(16, "big"), round_keys)
        chunk = data[i:i + 16]
        out += bytes(b ^ k for b, k in zip(chunk, keystream))
    ciphertext = bytes(out)
    s = _ghash(h, aad, ciphertext)
    tag_block = _aes_encrypt_block(j0, round_keys)
    tag = (s ^ int.from_bytes(tag_block, "big")).to_bytes(16, "big")[:16]
    return ciphertext, tag


def _aes256_gcm_decrypt(key, nonce, data, tag, aad=b""):
    round_keys = _expand_key(key)
    h = int.from_bytes(_aes_encrypt_block(b"\x00" * 16, round_keys), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    s = _ghash(h, aad, data)
    tag_block = _aes_encrypt_block(j0, round_keys)
    expected = (s ^ int.from_bytes(tag_block, "big")).to_bytes(16, "big")[:16]
    if not hmac.compare_digest(expected, tag):
        raise ValueError("GCM tag mismatch")
    counter = int.from_bytes(j0, "big")
    out = bytearray()
    for i in range(0, len(data), 16):
        counter += 1
        keystream = _aes_encrypt_block(counter.to_bytes(16, "big"), round_keys)
        chunk = data[i:i + 16]
        out += bytes(b ^ k for b, k in zip(chunk, keystream))
    return bytes(out)


# P-256 (secp256r1) 椭圆曲线

_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = _P256_P - 3
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
           0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _modinv(a, m):
    if m == 1:
        return 0
    t, newt = 0, 1
    r, newr = m, a % m
    while newr:
        q = r // newr
        t, newt = newt, t - q * newt
        r, newr = newr, r - q * newr
    if r != 1:
        raise ValueError("no modular inverse")
    return t % m


def _p256_double(point):
    if point is None:
        return None
    x, y = point
    if y == 0:
        return None
    lam = (3 * x * x + _P256_A) * _modinv(2 * y, _P256_P) % _P256_P
    x3 = (lam * lam - 2 * x) % _P256_P
    y3 = (lam * (x - x3) - y) % _P256_P
    return (x3, y3)


def _p256_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % _P256_P == 0:
            return None
        return _p256_double(p1)
    lam = (y2 - y1) * _modinv(x2 - x1, _P256_P) % _P256_P
    x3 = (lam * lam - x1 - x2) % _P256_P
    y3 = (lam * (x1 - x3) - y1) % _P256_P
    return (x3, y3)


def _p256_mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _p256_add(result, addend)
        addend = _p256_double(addend)
        k >>= 1
    return result


def _p256_ecdh_x(private_d, server_point):
    shared = _p256_mul(private_d, server_point)
    if shared is None:
        raise ValueError("ECDH point at infinity")
    return shared[0].to_bytes(32, "big")


def _sec1_export_public(point):
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def _sec1_import_public(data):
    raw = bytes(data or b"")
    if len(raw) == 65 and raw[0] == 4:
        x = int.from_bytes(raw[1:33], "big")
        y = int.from_bytes(raw[33:65], "big")
        return (x, y)
    if len(raw) == 33 and raw[0] in (2, 3):
        x = int.from_bytes(raw[1:], "big")
        y2 = (pow(x, 3, _P256_P) - 3 * x + _P256_B) % _P256_P
        y = pow(y2, (_P256_P + 1) // 4, _P256_P)
        if (y * y) % _P256_P != y2:
            raise ValueError("point not on curve")
        if (y & 1) != (raw[0] & 1):
            y = _P256_P - y
        return (x, y)
    raise ValueError("invalid P-256 SEC1 public key")


def _derive_key(session_id, shared_x):
    prk = hmac.new(session_id.encode("ascii"), shared_x, hashlib.sha256).digest()
    return hmac.new(prk, b"v2-session\x01", hashlib.sha256).digest()


# ============ HTTP（纯 urllib） ============

def _http_post(url, body, headers, timeout=15):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise RuntimeError("HTTP %s: %s" % (error.code, error.read(200)))
    except urllib.error.URLError as error:
        raise RuntimeError("request failed: %s" % (error.reason,))
    content = response.read()
    encoding = response.headers.get("Content-Encoding", "")
    if "gzip" in encoding.lower() or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    return content


def _http_get(url, headers, timeout=15):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        return error.code, error.read(200)
    except urllib.error.URLError as error:
        raise RuntimeError("request failed: %s" % (error.reason,))
    content = response.read()
    encoding = response.headers.get("Content-Encoding", "")
    if "gzip" in encoding.lower() or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    return response.status, content


# ============ 协议客户端 ============

class _GuluProtocol:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.session_id = ""
        self.session_key = b""
        self.device_id = secrets.token_hex(8)
        self.request_id = 0
        self.players = {}
        self.parsers = {}
        self.last_detail_error = ""
        self.lock = threading.RLock()

    def _post(self, body, header_name, header_value, extra_headers=None):
        headers = {
            "User-Agent": USER_AGENT, header_name: header_value,
            "Content-Type": "application/x-protobuf", "Accept-Encoding": "gzip",
            "Content-Length": str(len(body)), "Host": "103.45.132.22:19987",
        }
        if extra_headers:
            headers.update(extra_headers)
        return _http_post(API_URL, body, headers, self.timeout)

    def handshake(self):
        private_d = int.from_bytes(secrets.token_bytes(32), "big") % (_P256_N - 1) + 1
        public_point = _p256_mul(private_d, _P256_G)
        public_key = _sec1_export_public(public_point)
        capabilities = _field_varint(1, 1) + _field_varint(2, 0) + _field_varint(3, 1)
        request = (_field_bytes(1, public_key) + _field_bytes(2, b"1.0.0")
                   + _field_bytes(3, capabilities))
        handshake_key = secrets.token_hex(16)
        iv = secrets.token_bytes(16)
        encrypted = base64.b64encode(
            iv + _aes256_cbc_encrypt(handshake_key.encode("ascii"), iv,
                                     zlib.compress(request, 4)))
        content = self._post(encrypted, "x-handshake-key", handshake_key)
        raw = base64.b64decode(content)
        response_cipher_key = handshake_key.encode("ascii")
        plain = zlib.decompress(
            _aes256_cbc_decrypt(response_cipher_key, raw[:16], raw[16:]))
        session_id = _field_value(plain, 1, wire=2)
        server_public = _field_value(plain, 2, wire=2)
        if not session_id or not server_public:
            raise RuntimeError("invalid handshake response")
        self.session_id = session_id.decode("ascii")
        server_point = _sec1_import_public(server_public)
        shared_x = _p256_ecdh_x(private_d, server_point)
        self.session_key = _derive_key(self.session_id, shared_x)
        self.request_id = 0

    def _encrypt(self, data):
        nonce = secrets.token_bytes(12)
        ciphertext, tag = _aes256_gcm_encrypt(self.session_key, nonce, _raw_deflate(data))
        return nonce + ciphertext + tag

    def _decrypt(self, data):
        if len(data) < 28:
            raise ValueError("invalid GCM payload")
        nonce = data[:12]
        ciphertext = data[12:-16]
        tag = data[-16:]
        compressed = _aes256_gcm_decrypt(self.session_key, nonce, ciphertext, tag)
        return zlib.decompress(compressed, -15)

    def request(self, method, payload=b"", scope=3, extra_headers=None):
        with self.lock:
            if not self.session_id:
                self.handshake()
            self.request_id += 1
            request_id = self.request_id
            core = (_field_varint(1, request_id) + _field_varint(2, scope)
                    + _field_varint(3, method) + _field_bytes(4, self.device_id)
                    + _field_bytes(5, b"") + _field_bytes(6, payload)
                    + _field_varint(7, int(time.time() * 1000)))
            body = _field_varint(1, request_id) + _field_bytes(2, self._encrypt(core))
            content = self._post(body, "x-session-id", self.session_id,
                                 extra_headers=extra_headers)
            encrypted = _field_value(content, 2, wire=2)
            if encrypted is None:
                error = _text(_field_value(content, 3, b"", wire=2))
                raise RuntimeError(error or "server rejected request")
            plain = self._decrypt(encrypted)
            status = _text(_field_value(plain, 3, b"", wire=2))
            if status and status not in ("ok", "success"):
                raise RuntimeError(status)
            return plain

    def boot(self):
        now_us = int(time.time() * 1_000_000)
        app = (_field_bytes(1, "咕噜咕噜") + _field_bytes(2, APP_VERSION)
               + _field_bytes(3, b"com.himrsc.viz") + _field_bytes(4, APP_SIGNATURE)
               + _field_bytes(5, BUILD_NUMBER) + _field_varint(6, now_us)
               + _field_varint(7, now_us))
        device = (_field_bytes(1, self.device_id) + _field_varint(2, 1)
                  + _field_bytes(3, b"15") + _field_bytes(4, b"Redmi K50 Ultra")
                  + _field_bytes(5, b"Redmi/diting/diting:15/AQ3A.240912.001/OS2.0.215.0.VOACNXM:user/release-keys")
                  + _field_bytes(6, b"Redmi") + _field_bytes(7, b"qcom")
                  + _field_varint(8, 0) + _field_bytes(9, b"unknown")
                  + _field_bytes(10, DEVICE_BUILD) + _field_varint(11, 0)
                  + _field_varint(12, 35))
        payload = (_field_bytes(1, b"v2") + _field_bytes(2, b"android")
                   + _field_bytes(3, b"gulu") + _field_bytes(4, app)
                   + _field_bytes(5, device))
        response = self.request(0, payload, scope=1)
        config = _field_value(response, 4, b"", wire=2)
        players = {}
        for item in _field_values(config, 4, wire=2):
            code = _text(_field_value(item, 3, b"", wire=2))
            if not code:
                continue
            parser_ids = []
            for packed in _field_values(item, 8, wire=2):
                parser_ids.extend(_packed_varints(packed))
            players[code] = {"id": _field_value(item, 1, 0, wire=0),
                             "name": _text(_field_value(item, 4, b"", wire=2)),
                             "parser_ids": parser_ids}
        parsers = {}
        for item in _field_values(config, 7, wire=2):
            parser_id = _field_value(item, 1, 0, wire=0)
            if parser_id:
                parsers[parser_id] = {
                    "name": _text(_field_value(item, 2, b"", wire=2)),
                    "url": _text(_field_value(item, 3, b"", wire=2)),
                    "mode": _text(_field_value(item, 4, b"", wire=2)),
                    "result_key": _text(_field_value(item, 10, b"url", wire=2)),
                    "server": bool(_field_value(item, 20, 0, wire=0))}
        self.players = players
        self.parsers = parsers

    def search(self, keyword, page=1, limit=21, category_id=""):
        filters = _field_bytes(18, b"vod_hits_month") + _field_varint(19, 1)
        category_id = str(category_id or "").strip()
        if category_id:
            filters += _field_bytes(3, category_id) + _field_bytes(4, category_id)
        payload = (_field_bytes(1, keyword) + _field_varint(2, int(page))
                   + _field_varint(3, int(limit)) + _field_bytes(5, filters))
        response = self.request(61, payload)
        data = _field_value(response, 4, b"", wire=2)
        videos = []
        for message in _field_values(data, 1, wire=2):
            videos.append({
                "vod_id": str(_field_value(message, 1, 0, wire=0)),
                "vod_name": _text(_field_value(message, 3, b"", wire=2)),
                "vod_pic": _text(_field_value(message, 6, b"", wire=2)),
                "vod_remarks": _text(_field_value(message, 11, b"", wire=2)),
            })
        page_info = _field_value(data, 2, b"", wire=2)
        return {"videos": videos,
                "page": _field_value(page_info, 1, int(page), wire=0),
                "pagecount": _field_value(page_info, 3, 1, wire=0),
                "limit": _field_value(page_info, 2, int(limit), wire=0),
                "total": _field_value(page_info, 4, len(videos), wire=0)}

    def detail(self, vod_id):
        self.last_detail_error = ""
        payload = (_field_varint(1, int(vod_id)) + _field_bytes(3, APP_VERSION)
                   + _field_bytes(4, b"1") + _field_varint(5, 1))
        response = self.request(62, payload,
                                extra_headers={"x-player-page-protection": "1"})
        data = _field_value(response, 4, b"", wire=2)
        name = _text(_field_value(data, 5, b"", wire=2))
        guard_text = " ".join(
            [_text(_field_value(data, field, b"", wire=2)) for field in (5, 13, 21)]
            + [_text(_field_value(source, 1, b"", wire=2))
               for source in _field_values(data, 75, wire=2)]).lower()
        if any(marker in guard_text for marker in VERSION_GUARD_MARKERS):
            self.last_detail_error = "server_version_guard"
            return None
        if not name or name.startswith("最新版本下载地址") or _field_value(data, 1, 0, wire=0) == 0:
            self.last_detail_error = "invalid_detail"
            return None
        sources = []
        for source in _field_values(data, 75, wire=2):
            code = _text(_field_value(source, 1, b"", wire=2))
            if not code or code.startswith("__v99_"):
                continue
            config = self.players.get(code, {})
            episodes = []
            for episode in _field_values(source, 2, wire=2):
                episode_id = _text(_field_value(episode, 3, b"", wire=2))
                if not episode_id:
                    continue
                episodes.append({
                    "index": _field_value(episode, 1, len(episodes) + 1, wire=0),
                    "id": episode_id,
                    "name": _text(_field_value(episode, 4, b"", wire=2)) or "第%d集" % (len(episodes) + 1)})
            if episodes:
                sources.append({"code": code,
                                "name": config.get("name", code),
                                "parser_id": (config.get("parser_ids") or [0])[0],
                                "episodes": episodes})
        return {"id": str(_field_value(data, 1, vod_id, wire=0)),
                "name": name, "pic": _text(_field_value(data, 13, b"", wire=2)),
                "remarks": _text(_field_value(data, 22, b"", wire=2)),
                "content": _text(_field_value(data, 21, b"", wire=2)),
                "area": _text(_field_value(data, 28, b"", wire=2)),
                "year": _text(_field_value(data, 30, b"", wire=2)),
                "sources": sources}

    def play(self, parser_id, play_id):
        payload = _field_varint(1, int(parser_id)) + _field_bytes(2, play_id)
        response = self.request(69, payload)
        data = _field_value(response, 4, b"", wire=2)
        return _text(_field_value(data, 2, b"", wire=2))

    def reset_session(self):
        self.session_id = ""
        self.session_key = b""
        self.request_id = 0


# ============ T3 接口 ============

class Spider:
    """咕噜咕噜 T3 源（TVBox type=3 Python 爬虫）。"""

    source_name = "gulu"
    display_name = "咕噜咕噜"

    HOST = HOST
    UA = USER_AGENT

    _play_order = [
        "咕噜4K", "菲乐4K", "鲸宝4K", "神话", "臻影4K", "精品2K",
        "鲸宝2K", "短剧2K", "天堂", "☆讯飞☆", "☆奇趣☆", "☆果汁☆",
        "☆酷萌☆", "☆哔哩☆", "咖啡", "量子", "非凡", "暴风", "蚂蚁",
        "小熊", "海外", "花旗",
    ]
    _categories = [("1", "电影"), ("2", "电视剧"), ("3", "综艺"),
                   ("4", "动漫"), ("5", "短剧"), ("60", "直播")]

    def __init__(self) -> None:
        self.protocol = _GuluProtocol()
        self.last_error = ""

    def init(self, extend=""):
        """drpy 空闲刷新钩子：仅复位会话无关状态，不依赖本方法被执行。"""
        return None

    def _ensure_boot(self) -> None:
        try:
            if not self.protocol.session_id:
                self.protocol.handshake()
            if not self.protocol.players:
                self.protocol.boot()
        except Exception as e:
            self.last_error = "%s:%s" % (type(e).__name__, e)

    def _search(self, keyword, page=1, limit=21, category_id=""):
        self._ensure_boot()
        try:
            return self.protocol.search(keyword, page, limit, category_id)
        except Exception:
            try:
                self.protocol.reset_session()
                self._ensure_boot()
                return self.protocol.search(keyword, page, limit, category_id)
            except Exception as e:
                self.last_error = "%s" % e
                return {"videos": [], "page": page, "pagecount": 1,
                        "limit": limit, "total": 0}

    # ---- T3 契约 ----

    def homeContent(self, filter=False):
        classes = [{"type_id": tid, "type_name": nm} for tid, nm in self._categories]
        cards = []
        try:
            result = self._search("", 1, 21)
            cards = self._cards(result.get("videos", []), 1, 21)[:20]
        except Exception:
            pass
        return {"class": classes, "filters": {}, "list": cards}

    def homeVideoContent(self):
        return self.homeContent()

    def categoryContent(self, tid, pg="1", filter=True, extend=""):
        pg = max(1, int(pg or 1))
        result = self._search("", pg, 21, str(tid or "").strip())
        return {"class": [{"type_id": tid, "type_name": nm}
                          for tid, nm in self._categories],
                "filters": {},
                "list": self._cards(result.get("videos", []), pg, 21),
                "page": pg, "pagecount": result.get("pagecount", 1),
                "limit": result.get("limit", 21), "total": result.get("total", 0)}

    def detailContent(self, ids, flags=None):
        vod_id = self._detail_id(ids)
        if not vod_id:
            return {"list": []}
        self._ensure_boot()
        try:
            detail = self.protocol.detail(vod_id)
        except Exception:
            self.protocol.reset_session()
            self._ensure_boot()
            detail = self.protocol.detail(vod_id)
        if not detail:
            return {"list": []}

        play_from, play_blocks = [], []
        for source in detail["sources"]:
            episodes = []
            for ep in source["episodes"]:
                idx = ep["index"] or len(episodes) + 1
                encoded = "{}@{}@{}@{}".format(ep["id"], source["parser_id"],
                                               detail["name"], idx)
                episodes.append("%s$%s" % (ep["name"], encoded))
            if episodes:
                play_from.append(self._clean_name(source["name"]))
                play_blocks.append("#".join(episodes))
        paired = list(zip(play_from, play_blocks))
        paired.sort(key=lambda x: self._rank(x[0]))

        vod = {
            "vod_id": detail["id"],
            "vod_name": detail["name"],
            "vod_pic": detail["pic"],
            "vod_year": detail["year"],
            "vod_area": detail["area"],
            "vod_content": detail["content"],
            "vod_remarks": detail["remarks"],
            "vod_play_from": "$$$".join(p[0] for p in paired),
            "vod_play_url": "$$$".join(p[1] for p in paired),
        }
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        kw = (key or "").strip()
        if not kw:
            return {"list": []}
        pg = max(1, int(pg or 1))
        result = self._search(kw, pg, 21)
        return {"list": self._cards(result.get("videos", []), pg, 21)}

    def playerContent(self, flag, id, vipFlags=None):
        header = self._play_header(id)
        try:
            raw_id, parser_id, vod_name, episode_index = id.split("@", 3)
            parser_id = int(parser_id or 0)
        except ValueError:
            raw_id, parser_id, vod_name, episode_index = id, 0, "", "1"
        url = raw_id if (isinstance(raw_id, str) and self._is_playable_url(raw_id)) else ""
        if not url and parser_id:
            self._ensure_boot()
            parser = self.protocol.parsers.get(parser_id, {})
            if parser and not parser.get("server", True):
                try:
                    url = self._external_play(parser_id, raw_id)
                except Exception:
                    url = ""
            if not url:
                try:
                    url = self.protocol.play(parser_id, raw_id)
                except Exception:
                    try:
                        self.protocol.reset_session()
                        self._ensure_boot()
                        url = self.protocol.play(parser_id, raw_id)
                    except Exception:
                        url = ""
        return {"parse": 0, "url": url or "", "header": json.dumps(header)}

    # ---- 工具 ----

    def _cards(self, videos, page, limit):
        cards = []
        for v in videos:
            if v.get("vod_id"):
                cards.append({"vod_id": str(v["vod_id"]),
                              "vod_name": v.get("vod_name") or "",
                              "vod_pic": v.get("vod_pic") or "",
                              "vod_remarks": v.get("vod_remarks") or ""})
        return cards

    @staticmethod
    def _detail_id(ids) -> str:
        text = str(ids).strip()
        if text.isdigit():
            return text
        m = re.search(r"(?:^|[^0-9])(\d{1,12})(?:$|[^0-9])", text)
        return m.group(1) if m else ""

    @staticmethod
    def _clean_name(name: str) -> str:
        if not name:
            return ""
        c = re.sub(r'[【\[\(（].*?[】\]）)]', '', name)
        c = re.sub(r'\s*(?:HD|VIP|备用|推荐|极速|高清|标清|蓝光|超清|试看|抢先|预告|新版|旧版)\s*$',
                   '', c, flags=re.I)
        return re.sub(r'\s+', ' ', c).strip()

    @classmethod
    def _rank(cls, nm: str) -> int:
        c = cls._clean_name(nm).lower()
        for i, name in enumerate(cls._play_order):
            if c == name.lower() or c.startswith(name.lower()) or name.lower() in c:
                return i
        up = cls._clean_name(nm).upper()
        if "4K" in up:
            return 1000
        if "2K" in up:
            return 2000
        if "☆" in nm:
            return 3000
        return 4000

    def _play_header(self, url: str) -> dict:
        # 多数第三方 CDN 带不带 Referer 都能播；但 picovr / ppvod / quark
        # 带 Referer 反而 403（实测）。动态：这些域名去 Referer。
        _no_ref = ("picovr.com", "ppvod", "drive.quark.cn")
        h = {"User-Agent": USER_AGENT}
        if not (url and any(d in url for d in _no_ref)):
            h["Referer"] = self.HOST + "/"
        return h

    def _is_playable_url(self, value) -> bool:
        if not isinstance(value, str):
            return False
        url = value.strip()
        if not re.match(r"^https?://", url, re.I):
            return False
        return any(m in url.lower() for m in
                   (".m3u8", ".mp4", ".mkv", ".flv", ".ts", "/m.php", "?data="))

    def _external_play(self, parser_id, play_id) -> str:
        parser = self.protocol.parsers.get(parser_id, {})
        api_url = str(parser.get("url") or "").strip()
        if not api_url:
            return ""
        encoded = quote(str(play_id), safe="")
        target = api_url.replace("{url}", encoded) if "{url}" in api_url else api_url + encoded
        try:
            status, body = _http_get(target, {"User-Agent": USER_AGENT}, 15)
            payload = json.loads(body.decode("utf-8", "replace")) if status == 200 else {}
        except Exception:
            payload = {}
        return self._extract_play_url(payload, parser.get("result_key") or "url")

    def _extract_play_url(self, value, preferred_key="url") -> str:
        if isinstance(value, str):
            return value if self._is_playable_url(value) else ""
        if isinstance(value, dict):
            for key in (preferred_key, "url", "play_url", "playUrl", "m3u8", "data"):
                if key in value:
                    found = self._extract_play_url(value[key], preferred_key)
                    if found:
                        return found
            for item in value.values():
                found = self._extract_play_url(item, preferred_key)
                if found:
                    return found
        elif isinstance(value, (list, tuple)):
            for item in value:
                found = self._extract_play_url(item, preferred_key)
                if found:
                    return found
        return ""

    # ---- drpy 兼容辅助 ----

    def getName(self):
        return self.display_name

    def getDependence(self):
        return []

    def localProxy(self, param):
        return None

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return {}

    def destroy(self):
        return None


# ============ 模块级双入口（drpy site 模式 / 旧内核兼容） ============

_SINGLETON = None


def _get_singleton():
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Spider()
    return _SINGLETON


def homeContent(filter=False):
    return _get_singleton().homeContent(filter)


def homeVideoContent():
    return _get_singleton().homeVideoContent()


def categoryContent(tid, pg="1", filter=True, extend=""):
    return _get_singleton().categoryContent(tid, pg, filter, extend)


def detailContent(ids, flags=None):
    return _get_singleton().detailContent(ids, flags)


def searchContent(key, quick=False, pg="1"):
    return _get_singleton().searchContent(key, quick, pg)


def playerContent(flag, id, vipFlags=None):
    return _get_singleton().playerContent(flag, id, vipFlags)


# 类名别名（部分内核按小写 spider 约定取类）
spider = Spider


# ============ 命令行自检 ============

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="咕噜咕噜 T3 源自检")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("home")
    sub.add_parser("homevideos")

    p_search = sub.add_parser("search")
    p_search.add_argument("keyword")
    p_search.add_argument("pg", nargs="?", default="1")

    p_cate = sub.add_parser("category")
    p_cate.add_argument("tid")
    p_cate.add_argument("pg", nargs="?", default="1")

    p_detail = sub.add_parser("detail")
    p_detail.add_argument("vod_id")

    p_play = sub.add_parser("play")
    p_play.add_argument("encoded_id",
                        help='完整选集 id，形如 "play_id@parser_id@vod名@序号"，'
                             '也可直接传可播 URL')

    args = parser.parse_args()
    sp = Spider()
    try:
        if args.action == "home":
            result = sp.homeContent()
        elif args.action == "homevideos":
            result = sp.homeVideoContent()
        elif args.action == "search":
            result = sp.searchContent(args.keyword, pg=args.pg)
        elif args.action == "category":
            result = sp.categoryContent(args.tid, args.pg)
        elif args.action == "detail":
            result = sp.detailContent(args.vod_id)
        elif args.action == "play":
            result = sp.playerContent("", args.encoded_id)
        else:
            result = {}
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    except Exception as error:
        sys.stderr.write("%s: %s\n" % (type(error).__name__, error))
        sys.exit(1)