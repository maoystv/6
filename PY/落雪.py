# -*- coding: utf-8 -*-
# 洛雪TV (tv.lxyy.club) TVBox 爬虫源
# 数据源:
#   - 首页/分类:  /api/tmdb.php?path=discover/movie|discover/tv (TMDB 代理, 参数放外层 query)
#   - 采集站搜索: /api/proxy.php?action=search&wd=<关键词>&page=1
#   - 采集站详情: /api/proxy.php?action=detail&source=<源>&id=<源内id>
#   - 热度榜:     /api/ranking.php
# 结构: TMDB discover 提供列表与海报, 采集站提供真实播放(多数源为 m3u8 直链,
#        部分官方线路为平台页面, 需解析器 parse=1)
# 兼容: Python2(Py2/Jython2.7) + Python3, 标准库零依赖
#
# 九次调整 (2026-10-18, "重新加载重新排列正确的分类"):
#   站点把 catalog-categories.js 迁到 /js/ 目录且清单已更新, 按站点
#   最新 CESHI_CATALOG_LISTS 全量去重恢复 38 → 36: 去掉参数与"全部"
#   完全相同的 movie-popular(热门)/series-hot(热播) 两个重复 tab,
#   其余 16+15+6=36 个分类按站点顺序排列 (电影→剧集→动漫); 各分类
#   参数与站点 list() 定义逐项对齐: 合并 movieBase/seriesBase 公共参
#   数、countries 数组转 with_origin_country、动漫高分阈值同站点为
#   100。筛选项改为按 tab 组复用, 不再逐 tab 硬编码。
#
# 修复说明 (2026-10-18):
#   1) 详情改并发拉取: 原版串行拉最多 6 个采集源详情, 单源超时 15s,
#      实测单次详情 5~23s, 真机上再叠加死源超时会越过壳子约 30s 的
#      取数上限, 表现为详情打不开/无线路。并发后总耗时约等于最慢的
#      一个源, 线路顺序按候选排名不变; 详情单请求超时同时收紧到 8s。
#   2) 补 class 级 getName(): 原版只有模块级, 只认实例方法的加载器
#      调用即 AttributeError。
#   3) 详情加标题归一化兜底: TMDB 标题与采集站片名对不上 (译名/别名/
#      带"第X季"后缀) 时, 原版候选评分为 0 被全丢 → 有片无线路;
#      现在归一化 (去标点空格与季号后缀) 后再匹配一轮。
#
# T4 化 (2026-10-18): 业务逻辑与上述修复版逐字一致, 只换骨架——
#   基类四级兼容导入、文末 _sp/_ins() 单例 + 模块级转发 (含
#   searchContentPage)、localProxy 由 404 桩落实为真图片代理
#   (param 多形态解包、魔数定型含 AVIF/HEIC、失败回 200 占位图)。
#   封面默认直链 (TMDB 图床不查 referer), 类属性 _PROXY_PIC=True
#   时列表/搜索/详情封面才改走 localProxy。
#
# 八次调整 (2026-10-18, "有时候加载不出来"): _get 原为单次请求、
#   超时 15s 且不重试, 站点代理偶发抖动即返回空, 壳子表现为时好
#   时坏。改为超时 10s + 失败重试一次 (最坏约 21s, 仍在壳子预算
#   内); 详情的并发拉取不重试 (retry=False), 靠多源并行兜底,
#   免得把详情总时长拖过头。缓存/其余逻辑不变。
#
# 七次调整 (2026-10-18, "4k分辨率不对"): 逐源实测证伪——该站
#   8 个源最高 1920x1080 (电影 1920x800), 根本没有真 4K 流;
#   "4k60帧" 只是采集源自称。蜘蛛变不出真 4K, 能修的是线路名
#   如实化: _honest_line_name 把线名里的 4k60帧 改标 1080p。
#
# 六次调整 (2026-10-18): 三个 tab 下加筛选项 (homeContent 的
#   filters + categoryContent 的 extend): 电影/电视剧有 排序
#   (热门/最新/高分)、类型、地区 三维, 动漫有 排序、地区 两维;
#   原先拆掉的最新/高分/地区/题材以筛选形式回归, 不占 tab。
#   电视剧的国产/日剧默认排动画 (与动漫 tab 分工), 选类型可覆盖。
#
# 五次调整 (2026-10-18): 电视剧同样合并为单一 tab, 最终分类
#   只剩 3 个: 电影 / 电视剧 / 动漫。
#
# 四次调整 (2026-10-18): 电影合并为单一 tab「电影」、动漫合并为
#   单一 tab「动漫」 (不再拆最新/高分/地区/题材), 剧集保留五项,
#   分类 15 → 7。被合掉的分类行在 _build_cats 注释里有恢复说明。
#
# 三次优化 (2026-10-18, "把一样的分类合并"): 实测各分类第一页
#   内容重合度后合并三对近乎同款的 tab——电影·欧美 与 电影·全部
#   重合 85%、剧集·欧美 与 剧集·全部 重合 70% (热门榜本就以欧美
#   为主)、剧集·日剧 与 动漫·日漫 重合 89% (日剧第一页几乎全是
#   动漫), 分别并入 全部 / 全部 / 日漫, 分类 18 → 15。
#
# 二次优化 (2026-10-18, 针对"加载慢 + 分类太分散"):
#   1) _get 加 180 秒内存响应缓存 (按 URL): 首页/分类/搜索/详情的
#      重复打开 (返回重进、翻页折返、详情重开) 直接命中缓存零网络,
#      不再每次都等站点代理的 1~4 秒。只缓存成功的非空响应。
#   2) 分类 35 → 15: 原表里 "全部" 与 "热门" 参数完全相同是重复
#       tab, 且爱情/悬疑/犯罪/纪录片等细类把 tab 条拉得太长。保留
#      每类的 全部/最新/高分 + 主要地区 + 热门题材, 砍掉的见分类表。

import re
import json
import binascii
import socket
import http.client
import base64
import threading
import time

try:
    import http.cookiejar as _cookiejar
    from urllib.parse import urljoin, quote, unquote, urlencode, urlparse
    from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor, HTTPSHandler
    _PY3 = True
except Exception:
    import cookielib as _cookiejar
    from urlparse import urljoin, urlparse
    from urllib import quote, unquote, urlencode
    from urllib2 import Request, urlopen, build_opener, HTTPCookieProcessor
    _PY3 = False

try:
    _UNICODE = unicode
except NameError:
    _UNICODE = str


def _u8(s):
    # 统一转 UTF-8 字节串(供 urlencode/quote 使用, 规避 Py2 unicode 编码异常)
    if s is None:
        return ''
    if isinstance(s, _UNICODE):
        return s.encode('utf-8')
    return str(s)


def _ustr(s):
    # 统一转 unicode(str), 规避 Py2 下 str(unicode中文) 的 ascii 编码崩溃
    if s is None:
        return u''
    if _PY3:
        return str(s)
    if isinstance(s, _UNICODE):
        return s
    return str(s).decode('utf-8', 'replace')


# ---------- 基类四级兼容导入 (T4 规范) ----------
try:
    from base.spider import Spider as BaseSpider
except Exception:
    try:
        from base import Spider as BaseSpider
    except Exception:
        try:
            from spider import Spider as BaseSpider
        except Exception:
            class BaseSpider(object):
                def getName(self): return ''
                def init(self, extend=''): return None
                def homeContent(self, filter=None): return {}
                def homeVideoContent(self): return {}
                def categoryContent(self, tid, pg, filter=None, extend=None): return {}
                def detailContent(self, ids): return {}
                def searchContent(self, key, quick=False, pg='1'): return {}
                def searchContentPage(self, key, quick=False, pg='1'): return {}
                def playerContent(self, flag, id, vipFlags=None): return {}
                def localProxy(self, param): return [404, 'text/plain', b'']
                def isVideoFormat(self, url): return False
                def manualVideoCheck(self): return False
                def getDependence(self): return []
                def getProxyUrl(self): return 'http://127.0.0.1:9978/proxy?do=py'
                def getCache(self, key): return None
                def setCache(self, key, value): pass
                def delCache(self, key): pass


# ---------- 画质探测 (纯 Python 解析 H.264 分辨率; 影视仓无 ffprobe) ----------
# ---------------------------------------------------------------- 纯 Python AES
_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36,0x6c,0xd8,0xab,0x4d]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x11b) & 0xFF
    return a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[x] for x in t]
            t[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _encrypt_block(block, w, nr):
    # 状态列主序: s[r][c] = block[4*c + r]
    s = [list(block[i::4]) for i in range(4)]
    # 初始 AddRoundKey
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[c][r]
    for rnd in range(1, nr + 1):
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]        # 正向 ShiftRows: 左旋 r
        if rnd != nr:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0],2) ^ _mul(a[1],3) ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ _mul(a[1],2) ^ _mul(a[2],3) ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ _mul(a[2],2) ^ _mul(a[3],3)
                s[3][c] = _mul(a[0],3) ^ a[1] ^ a[2] ^ _mul(a[3],2)
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[4 * rnd + c][r]
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[4 * c + r] = s[r][c]
    return bytes(out)


def _decrypt_block(block, w, nr):
    s = [list(block[i::4]) for i in range(4)]
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[4 * nr + c][r]
    for rnd in range(nr - 1, -1, -1):
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[4 * rnd + c][r]
        if rnd:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0],14) ^ _mul(a[1],11) ^ _mul(a[2],13) ^ _mul(a[3],9)
                s[1][c] = _mul(a[0],9)  ^ _mul(a[1],14) ^ _mul(a[2],11) ^ _mul(a[3],13)
                s[2][c] = _mul(a[0],13) ^ _mul(a[1],9)  ^ _mul(a[2],14) ^ _mul(a[3],11)
                s[3][c] = _mul(a[0],11) ^ _mul(a[1],13) ^ _mul(a[2],9) ^ _mul(a[3],14)
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[4 * c + r] = s[r][c]
    return bytes(out)


class _AESEngine(object):
    MODE_ECB = 1
    MODE_CBC = 2

    def __init__(self, key, mode, iv=None):
        if isinstance(key, str):
            key = key.encode('utf-8')
        self.mode = mode
        self.iv = iv or b'\x00' * 16
        if isinstance(self.iv, str):
            self.iv = self.iv.encode('utf-8')
        self.w, self.nr = _expand_key(key)

    def encrypt(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        if self.mode == _AESEngine.MODE_ECB:
            out = bytearray()
            for i in range(0, len(data), 16):
                out += _encrypt_block(data[i:i + 16], self.w, self.nr)
            return bytes(out)
        out = bytearray()
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
            enc = _encrypt_block(blk, self.w, self.nr)
            out += enc
            prev = enc
        return bytes(out)

    def decrypt(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        if self.mode == _AESEngine.MODE_ECB:
            out = bytearray()
            for i in range(0, len(data), 16):
                out += _decrypt_block(data[i:i + 16], self.w, self.nr)
            return bytes(out)
        out = bytearray()
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            dec = _decrypt_block(blk, self.w, self.nr)
            out += bytes(a ^ b for a, b in zip(dec, prev))
            prev = blk
        return bytes(out)


class AES(object):
    """兼容 pycryptodome 的极简 AES。"""
    MODE_ECB = _AESEngine.MODE_ECB
    MODE_CBC = _AESEngine.MODE_CBC
    block_size = 16

    def __init__(self, key, mode, iv=None):
        self._e = _AESEngine(key, mode, iv)

    @classmethod
    def new(cls, key, mode, iv=None):
        return cls(key, mode, iv)

    def encrypt(self, data):
        return self._e.encrypt(data)

    def decrypt(self, data):
        return self._e.decrypt(data)





# ffprobe 逐源实测(2026-10-30, 仙逆全线路采样): 该站 8 个采集源最高只有
# 1920x816(1080P 宽银幕), 没有任何真 4K; 源站自称 "4k60帧" 的那条实测
# 1920x816, 属于虚假宣称。所以线路名一律改用**实测分辨率**。
def _unescape_rb(rb):
    out = bytearray()
    zeros = 0
    for b in rb:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


class _RBits(object):
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.p < len(self.d) * 8:
            if self.u(1):
                break
            z += 1
            if z > 32:
                return 0
        return (1 << z) - 1 + self.u(z) if z else 0

    def se(self):
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def _sps_size(rb):
    try:
        b = _RBits(rb)
        profile = b.u(8)
        b.u(8)
        b.u(8)
        b.ue()
        if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128,
                       138, 139, 134, 135):
            chroma = b.ue()
            if chroma == 3:
                b.u(1)
            b.ue()
            b.ue()
            b.u(1)
            if b.u(1):
                return None
        b.ue()
        poc = b.ue()
        if poc == 0:
            b.ue()
        elif poc == 1:
            b.u(1); b.se(); b.se()
            cnt = b.ue()
            for _ in range(cnt):
                b.se()
        else:
            b.ue(); b.ue(); b.ue(); b.ue(); b.ue()
        b.ue()
        b.u(1)
        w_mbs = b.ue() + 1
        h_map = b.ue() + 1
        frame_mbs_only = b.u(1)
        if not frame_mbs_only:
            b.u(1)
        b.u(1)
        cl = cr = ct = cb = 0
        if b.u(1):
            cl = b.ue(); cr = b.ue(); ct = b.ue(); cb = b.ue()
        w = w_mbs * 16 - cl * 2 - cr * 2
        h = (2 - frame_mbs_only) * h_map * 16 - ct * 2 - cb * 2
        if w <= 0 or h <= 0 or w > 8000 or h > 5000:
            return None
        return (w, h)
    except Exception:
        return None


def _ts_resolution(data, max_scan=400000):
    if not data:
        return None
    data = data[:max_scan]
    n = len(data)
    i = 0
    while i < n - 4:
        if data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 1:
            if (data[i + 3] & 0x1f) == 7:
                r = _sps_size(_unescape_rb(data[i + 4:i + 4 + 4096]))
                if r:
                    return r
            i += 4
            continue
        i += 1
    return None


def _mp4_resolution(data, max_scan=600000):
    # fMP4(m4s)分片: moov→trak→...→avc1→avcC 里带 SPS
    if not data:
        return None
    data = data[:max_scan]
    i = data.find(b'avcC')
    if i < 0:
        return None
    p = i + 4
    try:
        p += 5                     # version+profile/compat/level+lengthSizeMinusOne
        sps_len = (data[p] << 8) | data[p + 1]
        p += 2
        if sps_len <= 0 or sps_len > 4096:
            return None
        sps = data[p:p + sps_len]
        # avcC 里的 SPS 是 NAL unit(含 1 字节 nal header)
        r = _sps_size(_unescape_rb(sps[1:])) if sps and (sps[0] & 0x1f) == 7 else None
        if r:
            return r
        return _sps_size(_unescape_rb(sps))
    except Exception:
        return None


def _m3u8_resolution(text):
    if not text:
        return None
    best = None
    for m in re.finditer(r'RESOLUTION=(\d+)x(\d+)', text):
        w = int(m.group(1)); h = int(m.group(2))
        if best is None or w * h > best[0] * best[1]:
            best = (w, h)
    return best


# group → 可读后缀(同一采集源有多个 group 时才显示, 不暴露内部 id)
GROUP_SUFFIX = {
    'jlm3u8': u'直链', 'jlplayer': u'网页', 'mjzy': u'直链',
    'youku': u'优酷', 'iqiyi': u'爱奇艺', 'qq': u'腾讯',
    'bilibili': u'B站', 'mgtv': u'芒果', 'letv': u'乐视',
}


def _quality_label(w, h):
    # 按**短边**判定: 竖屏 1080x1920 是 1080P(不是 2K), 1920x816 也是 1080P
    if not w or not h:
        return ''
    short = min(w, h)
    long_ = max(w, h)
    if short >= 2000 or long_ >= 3800:
        return '4K'
    if short >= 1400 or long_ >= 2500:
        return '2K'
    if short >= 1000 or long_ >= 1900:
        return '1080P'
    if short >= 700 or long_ >= 1200:
        return '720P'
    if short >= 480 or long_ >= 800:
        return '480P'
    return '%dx%d' % (w, h)


def _m3u8_aes_key(text, url):
    # 取 EXT-X-KEY:METHOD=AES-128,URI="...",IV=0x... → (key_url, iv)
    if not text or 'EXT-X-KEY' not in text:
        return None
    m = re.search(r'#EXT-X-KEY:METHOD=AES-128,URI="([^"]+)"(?:,IV=0x([0-9a-fA-F]+))?', text)
    if not m:
        return None
    try:
        ku = urljoin(url, m.group(1))
        iv = binascii.unhexlify(m.group(2)) if m.group(2) else b'\x00' * 16
        return (ku, iv)
    except Exception:
        return None


def _resolve_quality(text, url, fetch, depth=0):
    """m3u8 → 真实分辨率: RESOLUTION 属性 → 子清单 → 媒体分片 SPS
    加密流(AES-128)先取 key 解密分片再解析 SPS"""
    if not text or depth > 3:
        return None
    r = _m3u8_resolution(text)
    if r:
        return r
    lines = []
    for l in text.splitlines():
        l = l.strip()
        if l and not l.startswith('#'):
            lines.append(l)
    if not lines:
        return None
    subs = [l for l in lines if l.lower().split('?')[0].endswith('.m3u8')]
    if subs:
        try:
            su = urljoin(url, subs[0])
            tb = fetch(su)
            if tb:
                return _resolve_quality(tb.decode('utf-8', 'replace'), su, fetch, depth + 1)
        except Exception:
            return None
    try:
        su = urljoin(url, lines[0])
        tb = fetch(su)
        if tb:
            # AES-128 加密流: 解密后才能找到 SPS
            ki = _m3u8_aes_key(text, url)
            if ki:
                try:
                    kb = fetch(ki[0])
                    if kb and len(kb) >= 16:
                        tb = AES.new(kb[:16], AES.MODE_CBC, ki[1]).decrypt(tb)
                except Exception:
                    pass
            r = _ts_resolution(tb)
            if r:
                return r
            return _mp4_resolution(tb)     # fMP4(m4s)
    except Exception:
        return None
    return None


class Spider(BaseSpider):
    BASE = 'https://tv.lxyy.club'
    # 封面走本地图片代理开关: 默认直链; 某图床开始查 referer 时改 True
    _PROXY_PIC = False
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # 分类表: tid -> (mediaType, TMDB discover 参数)
    # 构造自站点 catalog-categories.js 的 CESHI_CATALOG_LISTS
    CATS = None

    def __init__(self):
        self.headers = {
            'User-Agent': self.UA,
            'Accept': '*/*',
            'Referer': self.BASE + '/',
        }
        self._cat_map = None
        self._cat_order = []
        self._tabs_mode = 'group'
        self._cache = {}
        self._cache_ttl = 180
        # 详情缓存: source|id -> 采集站详情;  详情结果缓存: vid -> vod
        self._detail_cache = {}
        self._vod_cache = {}
        # 播放地址缓存: url -> 解析结果(TTL 120s)
        self._play_cache = {}
        # 官方 4K 链路的 grant 索引: 播放页 URL → playback_grant
        self._grant_map = {}
        self._session_ok = False
        # 画质探测结果缓存(lines 列表 id → 探测结果), 后台线程回填
        self._quality_cache = {}
        # 会话建立必须**加锁**: 详情是并发拉多个源, 每个源都调 _ensure_session
        # 会并发 POST session → cookie 互相覆盖 → 官方源(qilin/fy)随机失败,
        # 于是"官方源/洛雪4K"线路时有时无。
        self._session_lock = threading.Lock()
        # 洛雪官方解析链(player_api -> apiToken -> resolve.php)需要保持会话:
        # 播放器页发的 token 与 cookie 绑定, 无 cookie 会解析失败
        self._cj = _cookiejar.CookieJar()
        try:
            self._opener = build_opener(HTTPCookieProcessor(self._cj))
        except Exception:
            self._opener = None
        # 备用: 宽松 SSL 的 opener(某些网络环境证书链不全时兜底)
        self._opener_lax = None
        try:
            import ssl as _ssl_mod
            _lax = getattr(_ssl_mod, '_create_unverified_context', None)
            if _lax is not None:
                try:
                    self._opener_lax = build_opener(HTTPCookieProcessor(self._cj),
                                                   HTTPSHandler(context=_lax()))
                except Exception:
                    self._opener_lax = None
        except Exception:
            self._opener_lax = None
        # 线路名 -> 站点自带解析器(player_api), 详情阶段写入, 播放阶段取用
        self._api_cache = {}

    # ---------- 基础请求 ----------

    def _get(self, url, timeout=10, retry=True):
        # 带一次重试: 站点代理偶发抖动/慢响应时, 原版单次请求失败就
        # 返回空, 壳子表现为"有时候加载不出来"; 超时从 15s 收到 10s,
        # 两次尝试最坏约 21s 仍在壳子约 30s 的取数预算内
        now = time.time()
        hit = self._cache.get(url)
        if hit and now - hit[0] < self._cache_ttl:
            return hit[1]
        text = None
        for attempt in range(2 if retry else 1):
            try:
                req = Request(url, headers=self.headers)
                resp = urlopen(req, timeout=timeout)
                code = resp.getcode() if hasattr(resp, 'getcode') else 200
                if code != 200:
                    raise IOError('http %s' % code)
                text = resp.read().decode('utf-8', 'replace')
                break
            except Exception:
                text = None
                if attempt == 0:
                    time.sleep(0.6)
        if text:
            if len(self._cache) > 128:
                self._cache.clear()
            self._cache[url] = (now, text)
        return text

    def _get_json(self, url, timeout=10, retry=True):
        text = self._get(url, timeout, retry)
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    # ---------- id 编码 ----------
    # v5 起 vod_id 携带采集源坐标, 详情页免去"再搜一遍标题"(实测搜索要 5~6s,
    # 详情再搜一次是最慢的一环):
    #   s:<src1>~<id1>|<src2>~<id2>|...|<title>   新格式(带源, 直连 detail)
    #   t:<title>                                 旧格式(仅标题, 回退用)
    # 标题用最后一个 '|' 切分, 标题本身含 '|' 也不会错位。

    def _encode_vid(self, title, source=None, sid=None, srcs=None):
        pairs = []
        if srcs:
            for it in srcs:
                try:
                    pairs.append((str(it[0]), str(it[1])))
                except Exception:
                    continue
        elif source not in (None, '') and sid not in (None, ''):
            pairs.append((str(source), str(sid)))
        if pairs:
            head = '|'.join(['%s~%s' % (quote(_u8(s), safe=''), quote(_u8(i), safe=''))
                             for s, i in pairs])
            return 's:' + head + '|' + quote(_u8(title), safe='')
        return 't:' + quote(_u8(title), safe='')

    def _decode_vid(self, vid):
        # 返回 dict: {'mode','srcs':[(source,id),...],'title'}
        v = vid if isinstance(vid, str) else _ustr(vid or '')
        out = {'mode': 't', 'srcs': [], 'title': ''}
        if v.startswith('s:'):
            body = v[2:]
            try:
                head, title = body.rsplit('|', 1)
            except Exception:
                head, title = body, ''
            srcs = []
            for part in head.split('|'):
                if '~' in part:
                    a, b = part.split('~', 1)
                    a = self._unq(a)
                    b = self._unq(b)
                    if a and b:
                        srcs.append((a, b))
            if srcs:
                out['mode'] = 's'
                out['srcs'] = srcs
                out['title'] = self._unq(title)
                return out
            v = title
        if v.startswith('t:'):
            v = v[2:]
        out['title'] = self._unq(v)
        return out

    def _unq(self, s):
        try:
            s = unquote(_ustr(s or ''))
            if isinstance(s, bytes):
                s = s.decode('utf-8', 'replace')
            return s
        except Exception:
            return _ustr(s or '')

    # ---------- 分类表 ----------

    def _build_cats(self):
        if self._cat_map is not None:
            return self._cat_map
        movie_base = {'sort_by': 'popularity.desc',
                      'primary_release_date_lte': 'today',
                      'include_adult': 'false',
                      'include_video': 'false'}
        series_base = {'sort_by': 'popularity.desc',
                       'first_air_date_lte': 'today',
                       'include_null_first_air_dates': 'false',
                       'include_adult': 'false'}
        anime_base = dict(series_base)
        anime_base['with_genres'] = '16'

        saved = {}
        order = []
        if getattr(self, '_tabs_mode', 'group') == 'detail':
            # 旧版: 36 个细分 tab(把排序/类型/地区摊平成 tab)
            raw = [
                ('movie-all', u'电影·全部', 'movie', movie_base),
                ('movie-latest', u'电影·最新', 'movie', dict(movie_base, sort_by='primary_release_date.desc')),
                ('movie-rated', u'电影·高分', 'movie', dict(movie_base, sort_by='vote_average.desc', vote_count_gte='200')),
                ('cn-movie', u'电影·国产', 'movie', dict(movie_base, with_original_language='zh', with_origin_country='CN')),
                ('movie-hktw', u'电影·港澳台', 'movie', dict(movie_base, with_origin_country='HK|TW|MO')),
                ('movie-western', u'电影·欧美', 'movie', dict(movie_base, with_original_language='en')),
                ('movie-jpkr', u'电影·日韩', 'movie', dict(movie_base, with_origin_country='JP|KR')),
                ('movie-action', u'电影·动作', 'movie', dict(movie_base, with_genres='28')),
                ('movie-comedy', u'电影·喜剧', 'movie', dict(movie_base, with_genres='35')),
                ('movie-romance', u'电影·爱情', 'movie', dict(movie_base, with_genres='10749')),
                ('movie-mystery', u'电影·悬疑', 'movie', dict(movie_base, with_genres='9648')),
                ('movie-scifi', u'电影·科幻', 'movie', dict(movie_base, with_genres='878')),
                ('movie-horror', u'电影·恐怖', 'movie', dict(movie_base, with_genres='27')),
                ('movie-animation', u'电影·动画', 'movie', dict(movie_base, with_genres='16')),
                ('movie-documentary', u'电影·纪录片', 'movie', dict(movie_base, with_genres='99')),
                ('series-all', u'剧集·全部', 'tv', series_base),
                ('series-latest', u'剧集·最新', 'tv', dict(series_base, sort_by='first_air_date.desc')),
                ('series-rated', u'剧集·高分', 'tv', dict(series_base, sort_by='vote_average.desc', vote_count_gte='200')),
                ('cn-tv', u'剧集·国产', 'tv', dict(series_base, with_original_language='zh', with_origin_country='CN', without_genres='16')),
                ('series-korea', u'剧集·韩剧', 'tv', dict(series_base, with_origin_country='KR')),
                ('series-japan', u'剧集·日剧', 'tv', dict(series_base, with_origin_country='JP')),
                ('series-western', u'剧集·欧美', 'tv', dict(series_base, with_original_language='en')),
                ('series-action', u'剧集·动作冒险', 'tv', dict(series_base, with_genres='10759')),
                ('series-comedy', u'剧集·喜剧', 'tv', dict(series_base, with_genres='35')),
                ('series-mystery', u'剧集·悬疑', 'tv', dict(series_base, with_genres='9648')),
                ('series-crime', u'剧集·犯罪', 'tv', dict(series_base, with_genres='80')),
                ('series-scifi', u'剧集·科幻奇幻', 'tv', dict(series_base, with_genres='10765')),
                ('series-animation', u'剧集·动画', 'tv', dict(series_base, with_genres='16')),
                ('series-documentary', u'剧集·纪录片', 'tv', dict(series_base, with_genres='99')),
                ('western-animation', u'剧集·英文动画', 'tv', dict(series_base, with_genres='16', with_original_language='en')),
                ('anime-all', u'动漫·全部', 'tv', anime_base),
                ('anime-cn', u'动漫·国漫', 'tv', dict(anime_base, with_original_language='zh', with_origin_country='CN')),
                ('anime-japan', u'动漫·日漫', 'tv', dict(anime_base, with_origin_country='JP')),
                ('anime-western', u'动漫·欧美', 'tv', dict(anime_base, with_original_language='en')),
                ('anime-latest', u'动漫·最新', 'tv', dict(anime_base, sort_by='first_air_date.desc')),
                ('anime-rated', u'动漫·高分', 'tv', dict(anime_base, sort_by='vote_average.desc', vote_count_gte='100')),
            ]
        else:
            # 新版: 3 个组 tab, 排序/类型/地区全部走筛选(功能一个不丢, 主页更干净)
            raw = [
                ('movie', u'电影', 'movie', movie_base),
                ('series', u'剧集', 'tv', series_base),
                ('anime', u'动漫', 'tv', anime_base),
            ]
        for tid, label, mt, params in raw:
            saved[tid] = (label, mt, params)
            order.append(tid)
        self._cat_map = saved
        self._cat_order = order
        return self._cat_map

    # ---------- TVBox 必需接口 ----------

    def getName(self):
        return u'洛雪TV'

    def getDependence(self):
        return []

    def init(self, extend=""):
        # extend 兼容 str / dict / JSON 字符串
        if isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not isinstance(extend, dict):
            extend = {}
        tabs = _ustr(extend.get('tabs') or '').strip().lower()
        self._tabs_mode = 'detail' if tabs in ('detail', 'full', 'many') else 'group'
        self._build_cats()
        return None

    def homeContent(self, filter=None):
        cats = self._build_cats()
        cls = []
        for tid in self._cat_order:
            if tid in cats:
                cls.append({'type_id': tid, 'type_name': cats[tid][0]})
        return {'class': cls, 'filters': self._filter_defs()}

    def homeVideoContent(self):
        # 首页推荐: Nostr 热度榜 + TMDB 热门电影/剧集兜底
        items = self._ranking_items(24)
        if not items:
            items = self._tmdb_mix(12)
        return {'list': items}

    # ---------- 列表数据 ----------

    def _ranking_items(self, limit):
        data = self._get_json(self.BASE + '/api/ranking.php')
        if not data or not data.get('available'):
            return []
        items = []
        seen = set()
        for r in (data.get('items') or [])[:limit]:
            nm = _ustr(r.get('title') or '').strip()
            if not nm or nm in seen:
                continue
            seen.add(nm)
            poster = r.get('posterPath') or ''
            pic = ('https://image.tmdb.org/t/p/w342' + poster) if poster.startswith('/') else poster
            yr = r.get('year') or r.get('releaseYear') or ''
            items.append({'vod_id': self._encode_vid(nm), 'vod_name': nm,
                          'vod_pic': self._pic(pic),
                          'vod_remarks': _ustr(yr),
                          'vod_year': _ustr(yr)})
        return items

    def _tmdb_mix(self, per):
        # 热门电影 + 热门剧集 混合
        out = []
        for mt in ('movie', 'tv'):
            params = {'sort_by': 'popularity.desc'}
            lst, pg, pages = self._tmdb_list(mt, params, 1)
            if lst:
                out.extend(lst[:per])
        return out

    def _tmdb_list(self, media_type, params, page):
        q = []
        for k, v in (params or {}).items():
            if v is None or v == '':
                continue
            q.append((k, _u8(v)))
        q.append(('page', str(page)))
        url = self.BASE + '/api/tmdb.php?path=discover/' + media_type + '&' + urlencode(q)
        data = self._get_json(url)
        if not data or 'results' not in data:
            return ([], page, 1)
        items = []
        seen = set()
        for r in (data.get('results') or []):
            nm = _ustr(r.get('title') or r.get('name') or '').strip()
            if not nm or nm in seen:
                continue
            seen.add(nm)
            poster = r.get('poster_path') or ''
            # 无海报条目整条过滤 (与站点热度榜 filter 一致), 避免列表页
            # 出现无图灰卡; TMDB 未定档/新片常无 poster_path
            if not poster.startswith('/'):
                continue
            pic = 'https://image.tmdb.org/t/p/w342' + poster
            dt = r.get('release_date') or r.get('first_air_date') or ''
            year = dt[:4] if len(dt) >= 4 else ''
            items.append({
                'vod_id': self._encode_vid(nm),
                'vod_name': nm,
                'vod_pic': self._pic(pic),
                'vod_remarks': year,
            })
        pg = data.get('page') or page
        pages = data.get('total_pages') or 1
        if pages > 200:
            pages = 200
        return (items, pg, pages)


    # ---------- 筛选 (tab 下筛选项, 经 categoryContent 的 extend 传入) ----------

    def _filter_defs(self):
        # 3 个组 tab 各带完整筛选; 旧版细分 tab 只在"全部"给筛选,
        # 避免 _apply_filters 覆盖 tab 自带的固定参数(选「电影·动作」+类型=喜剧
        # 会把 with_genres 冲掉, 动作语义丢失)。
        cats = self._build_cats()

        def opts(pairs):
            return [{'n': n, 'v': v} for n, v in pairs]

        sort_f = {'key': 'sort', 'name': u'排序', 'value': opts([
            (u'热门', ''), (u'最新', 'new'), (u'高分', 'rated')])}
        movie_genre = {'key': 'genre', 'name': u'类型', 'value': opts([
            (u'全部', ''), (u'动作', '28'), (u'喜剧', '35'), (u'爱情', '10749'),
            (u'悬疑', '9648'), (u'科幻', '878'), (u'恐怖', '27'), (u'犯罪', '80'),
            (u'剧情', '18'), (u'动画', '16'), (u'纪录片', '99')])}
        movie_area = {'key': 'area', 'name': u'地区', 'value': opts([
            (u'全部', ''), (u'国产', 'cn'), (u'港澳台', 'hktw'),
            (u'欧美', 'west'), (u'日韩', 'jpkr')])}
        tv_genre = {'key': 'genre', 'name': u'类型', 'value': opts([
            (u'全部', ''), (u'剧情', '18'), (u'喜剧', '35'), (u'悬疑', '9648'),
            (u'犯罪', '80'), (u'动作冒险', '10759'), (u'科幻奇幻', '10765'),
            (u'动画', '16'), (u'纪录片', '99')])}
        tv_area = {'key': 'area', 'name': u'地区', 'value': opts([
            (u'全部', ''), (u'国产', 'cn'), (u'韩剧', 'kr'),
            (u'日剧', 'jp'), (u'欧美', 'west')])}
        anime_area = {'key': 'area', 'name': u'地区', 'value': opts([
            (u'全部', ''), (u'国漫', 'cn'), (u'日漫', 'jp'), (u'欧美', 'west')])}

        out = {}
        for tid in self._cat_order:
            label, mt, params = cats[tid]
            if tid == 'movie':
                out[tid] = [sort_f, movie_genre, movie_area]
            elif tid == 'series':
                out[tid] = [sort_f, tv_genre, tv_area]
            elif tid == 'anime':
                out[tid] = [sort_f, anime_area]
            elif tid.endswith('-all'):
                out[tid] = [sort_f, movie_genre, movie_area] if mt == 'movie' else (
                    [sort_f, anime_area] if tid.startswith('anime') else [sort_f, tv_genre, tv_area])
            else:
                out[tid] = []
        return out

    def _apply_filters(self, tid, mt, params, extend):
        # extend 兼容 dict / JSON 字符串; 维度合并顺序 排序→地区→类型,
        # 选了具体类型时去掉地区带来的 without_genres 以免互相打架
        if isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not isinstance(extend, dict):
            return params
        p = dict(params)
        t = _ustr(tid)
        is_anime = (t == 'anime') or t.startswith('anime')
        sort = _ustr(extend.get('sort') or '')
        if sort == 'new':
            p['sort_by'] = ('primary_release_date.desc' if mt == 'movie'
                            else 'first_air_date.desc')
        elif sort == 'rated':
            p['sort_by'] = 'vote_average.desc'
            # 动漫高分阈值与站点一致 (100), 其余组 200
            p['vote_count_gte'] = '100' if is_anime else '200'
        area = _ustr(extend.get('area') or '')
        area_map = {
            'cn': {'with_original_language': 'zh', 'with_origin_country': 'CN'},
            'hktw': {'with_origin_country': 'HK|TW|MO'},
            'west': {'with_original_language': 'en'},
            'jpkr': {'with_origin_country': 'JP|KR'},
            'kr': {'with_origin_country': 'KR'},
            'jp': {'with_origin_country': 'JP'},
        }
        if area in area_map:
            p.update(area_map[area])
            if (t == 'series' or t == 'series-all') and area in ('cn', 'jp'):
                # 国产剧/日剧默认排动画, 与"动漫"tab 分工 (选类型可覆盖)
                p['without_genres'] = '16'
        genre = _ustr(extend.get('genre') or '')
        if genre:
            p['with_genres'] = genre
            p.pop('without_genres', None)
        return p

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        cats = self._build_cats()
        tid_s = str(tid)
        if tid_s not in cats:
            return {'list': [], 'page': 1, 'pagecount': 1}
        label, mt, params = cats[tid_s]
        params = self._apply_filters(tid_s, mt, params, extend)
        try:
            p = int(pg or 1)
        except Exception:
            p = 1
        items, page, pages = self._tmdb_list(mt, params, p)
        return {'list': items, 'page': page, 'pagecount': pages, 'limit': 20, 'total': len(items)}

    # ---------- 采集站搜索/详情 ----------

    def _search_raw(self, title, pg):
        url = (self.BASE + '/api/proxy.php?action=search&wd=' +
               quote(_u8(title), safe='') + '&page=' + str(pg))
        # 站点搜索接口会偶发 502 / 空响应, 重试 3 次
        for attempt in range(3):
            data = self._get_json(url, timeout=12, retry=(attempt == 0))
            if data and data.get('results'):
                return data.get('results') or []
            time.sleep(0.5)
        return []

    def _ensure_session(self):
        # 官方线路的 detail 只在**有播放会话**时才带 playback_grant,
        # 所以先 POST 一次 /api/playback-session.php 建立会话。
        # (实测: 带会话的 detail 响应 40678 字节, 裸 GET 只有 24442 —— 差的
        #  16KB 就是 playback_grant。没有会话 → 没有 grant → 4K 链必然失败。)
        if getattr(self, '_session_ok', False):
            return
        try:
            self._session_lock.acquire()
        except Exception:
            self._session_lock = None
        try:
            if getattr(self, '_session_ok', False):
                return
            self._build_session()
        finally:
            try:
                if self._session_lock is not None:
                    self._session_lock.release()
            except Exception:
                pass

    def _build_session(self):
        url = self.BASE + '/api/playback-session.php'
        hdrs = {'User-Agent': self.UA, 'Content-Type': 'application/json',
                'Referer': self.BASE + '/', 'Accept': 'application/json, text/plain, */*'}
        for opx in (self._opener, self._opener_lax):
            if opx is None:
                continue
            try:
                rq = Request(url, data=b'', headers=hdrs)
                opx.open(rq, timeout=25).read()
                self._session_ok = True
                return
            except Exception as e:
                print('[洛雪] 建立播放会话失败(%s): %s' % (type(e).__name__, str(e)[:70]))
        # 兜底: 走通用 _get
        try:
            rq = Request(url, data=b'', headers=hdrs)
            urlopen(rq, timeout=25).read()
            self._session_ok = True
        except Exception as e:
            print('[洛雪] 建立播放会话失败(兜底): %s' % str(e)[:70])

    def _detail_raw(self, source, vid, timeout=8):
        ckey = str(source) + '|' + str(vid)
        now = time.time()
        hit = self._detail_cache.get(ckey)
        if hit and now - hit[0] < self._cache_ttl:
            return hit[1]
        url = (self.BASE + '/api/proxy.php?action=detail&source=' +
               quote(_u8(str(source)), safe='') + '&id=' + quote(_u8(str(vid)), safe=''))
        data = None
        self._ensure_session()
        for opx in (self._opener, self._opener_lax):
            if opx is None:
                continue
            try:
                rq = Request(url, headers={'User-Agent': self.UA,
                                           'Referer': self.BASE + '/',
                                           'Accept': 'application/json, text/plain, */*'})
                resp = opx.open(rq, timeout=timeout)
                data = json.loads(resp.read(600000).decode('utf-8', 'replace'))
                break
            except Exception:
                continue
        if data is None:
            data = self._get_json(url, timeout=timeout, retry=False)
        if not data or not data.get('success'):
            return None
        details = data.get('details') or []
        if not details:
            return None
        one = details[0] or None
        if one:
            if len(self._detail_cache) > 128:
                self._detail_cache.clear()
            self._detail_cache[ckey] = (now, one)
        return one

    # 采集站常见的"衍生内容"关键词: 命中即降权/淘汰(解说/花絮/盘点…)
    # 注意: "剧情"/"纪录片" 是类型词不是衍生内容, 不能进这个表
    BAD_KW = [u'解说', u'手语', u'速览', u'揭秘', u'合集', u'名场面', u'预告',
              u'助听', u'分享', u'盘点', u'彩蛋', u'花絮', u'精彩',
              u'高光', u'解读', u'混剪', u'片段', u'剪辑', u'抢先', u'预览',
              u'评测', u'影评', u'反应', u'reaction', u'cut', u'全程', u'解说版',
              u'番外', u'吐槽', u'杂谈', u'幕后', u'导演阐述', u'特辑', u'速看']

    # 合法的"版本后缀": 命中这些说明是同一部剧的正常版本, 不是衍生内容
    VER_TAIL = [u'粤语', u'国语', u'英文', u'日语', u'韩语', u'普通话', u'中字',
                u'高清', u'超清', u'蓝光', u'4k', u'4K', u'8k', u'8K', u'hd',
                u'HD', u'tv版', u'TV版', u'tv', u'TV', u'完整版', u'全一集',
                u'未删减', u'修复版', u'导演剪辑版', u'国英', u'粤语版', u'国语版',
                u'英文版', u'重制版', u'加长版', u'收藏版', u'在线看', u'特别版',
                u'特别篇', u'特别篇', u'终极', u'终章', u'第二部', u'剧场版',
                u'电影版', u'剧场', u'剧场特别篇', u'先行版', u'抢先版']

    def _is_version_suffix(self, rest):
        # rest = 去掉标题后的剩余部分; 全由版本词/序号/季号构成 → 视为同一部剧的版本
        r = re.sub(r'[\s·\-—_:：、,，.。/\\|()（）【】\[\]!！?？]', '', _ustr(rest or ''))
        if not r:
            return True
        if len(r) > 16:
            return False
        if r.isdigit():          # "斗罗大陆2" / "庆余年3"
            return True
        if re.match(r'^第?[0-9一二三四五六七八九十]+[季部集篇话卷]', r):
            return True
        for v in self.VER_TAIL:
            if r == v or r == v.lower():
                return True
        # 多个版本词拼接, 如 "粤语版TV版"
        s = r
        changed = True
        while changed:
            changed = False
            for v in self.VER_TAIL:
                if s.lower().startswith(v.lower()) and len(s) > len(v):
                    s = s[len(v):]
                    changed = True
                    break
        return s == ''

    def _rank_candidates(self, title, results):
        scored = []
        for r in results:
            nm = _ustr(r.get('name') or '')
            src_name = _ustr(r.get('source_name') or '')
            typ = _ustr(r.get('type') or '')
            if not nm:
                continue
            score = 0
            if nm == title:
                score += 100
            elif nm.startswith(title):
                # 标题前缀相同: 后缀是合法版本词才算同一部剧, 否则是衍生内容
                if self._is_version_suffix(nm[len(title):]):
                    score += 50
                else:
                    score -= 40
            elif title in nm:
                if self._is_version_suffix(nm.replace(title, '', 1)):
                    score += 20
                else:
                    score -= 30
            if u'自营' in src_name:
                score += 25
            if u'4k' in src_name or u'60' in src_name:
                score += 15
            if u'官采' in src_name:
                score += 10
            for kw in self.BAD_KW:
                if kw in nm:
                    score -= 60
                    break
            if u'短剧' in typ:
                score -= 20
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, r in scored:
            if s > 0:
                out.append(r)
        return out

    def _add_lines(self, cands, details, lines_from, lines_url, line_apis):
        # 把若干源详情里的线路/集数并进结果列表
        for c, d in zip(cands, details):
            if not d:
                continue
            base_name = _ustr(d.get('source_name') or c.get('source_name') or u'线路')
            api = _ustr(d.get('player_api') or '')
            groups = d.get('episodes') or []
            made = 0
            for gi, g in enumerate(groups):
                eps = g.get('episodes') or []
                gname = _ustr(g.get('group') or '')
                pairs = []
                official = []
                for ep in eps:
                    ep_name = self._ep_name(ep.get('name'), len(pairs))
                    ep_url = _ustr(ep.get('url') or '')
                    if not ep_url:
                        continue
                    fixed = self._fix_url(ep_url)
                    gp = ep.get('playback_grant')
                    if gp:
                        self._grant_map[fixed] = _ustr(gp)
                        # 只有**网页型**播放页(腾讯/优酷/爱奇艺)才需要解析器;
                        # 采集源的直链 m3u8 本身就是可播的, 不必再挂解析器
                        if not fixed.lower().split('?')[0].endswith(('.m3u8', '.mp4', '.ts', '.m4s')):
                            official.append((ep_name, fixed, _ustr(gp)))
                    pairs.append((ep_name, fixed))
                if not pairs:
                    continue
                ln = base_name + (u' ' + GROUP_SUFFIX.get(gname, u'') if gname else u'')
                ln = self._uniq_line_name(ln, lines_from)
                lines_from.append(ln)
                lines_url.append(u'#'.join([u'%s$%s' % (n, u) for n, u in pairs]))
                line_apis.append(api)
                made += 1
                # 官方线路(带 playback_grant)额外按解析器展开成多条:
                #   "官采蓝光·洛雪4K" / "官采蓝光·蓝光" ...
                # URL 里编上 <source>|<source_id>|<真实播放页URL>, 播放时据此
                # 取对应解析器并实时换取 4K 直链。
                if official and c.get('source') in self.OFFICIAL_SOURCES:
                    for rid in self.DEFAULT_PARSERS:
                        pname = self.PARSERS.get(rid, (rid, 'json'))[0]
                        pln = self._uniq_line_name(base_name + u'·' + pname, lines_from)
                        enc = u'%s|%s|%s' % (c.get('source'), c.get('id'), fixed)
                        lines_from.append(pln)
                        lines_url.append(u'#'.join(
                            [u'%s$%s' % (n, enc) for n, _u, _g in official]))
                        line_apis.append(api)
            if not made and d.get('play_url'):
                ln = self._uniq_line_name(base_name, lines_from)
                lines_from.append(ln)
                lines_url.append(_ustr(d.get('play_url')))
                line_apis.append(api)
        return (lines_from, lines_url, line_apis)

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ''
        else:
            vid = str(ids or '')
        # 结果级缓存: 整个详情缓存, 重复打开同一剧直接秒开
        vhit = self._vod_cache.get(vid)
        if vhit and time.time() - vhit[0] < self._cache_ttl:
            return {'list': [vhit[1]]}
        info = self._decode_vid(vid)
        title = (info.get('title') or '').strip()
        if not title:
            return {'list': []}

        picked = []
        raw_details = []
        lines_from = []
        lines_url = []
        line_apis = []

        # --- 快路径: vod_id 自带采集源坐标, 直接并发拉详情, 免掉全站搜索 ---
        if info.get('mode') == 's' and info.get('srcs'):
            # 官方平台源(qilin/fy)**优先**占位 —— 否则它们常排在第 5 位之后,
            # 被 [:5] 截掉, 于是"官方源/洛雪4K"线路整条消失。
            _srcs = info['srcs']
            _off = [x for x in _srcs if x[0] in self.OFFICIAL_SOURCES][:2]
            _rest = [x for x in _srcs if x[0] not in self.OFFICIAL_SOURCES]
            cands = [{'source': s, 'id': i} for s, i in (_off + _rest)[:5]]
            raw_details = self._fetch_details_parallel(cands, timeout=3, budget=3.0)
            # 注意: picked 与 raw_details 必须**一一对应**, 否则 zip 配对错位
            # 会把线路全部丢掉(曾导致详情页"线路/选集"全空)
            picked = cands
            if not any(raw_details):
                # 所有源都没取到(站点抖动/超时) → 强制走回退搜索, 否则详情全空
                picked = []
        if not picked:
            # --- 回退: 老格式 vod_id 或直连全失败, 按标题走全站搜索 ---
            results = self._search_raw(title, 1)
            if not results:
                return {'list': []}
            cands = self._rank_candidates(title, results)
            picked = self._pick_sources(cands)
            if not picked:
                nt = self._norm_title(title)
                if nt:
                    alias = [r for r in results
                             if self._norm_title(_ustr(r.get('name') or '')) == nt]
                    picked = self._pick_sources(alias)
            if not picked:
                return {'list': []}
            raw_details = self._fetch_details_parallel(picked, timeout=3, budget=3.0)

        lines_from, lines_url, line_apis = self._add_lines(
            picked, raw_details, lines_from, lines_url, line_apis)

        vod = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': '',
            'vod_content': '',
            'vod_actor': '',
            'vod_director': '',
            'vod_year': '',
            'vod_area': '',
            'vod_remarks': '',
        }
        for c, d in zip(picked, raw_details):
            if not d:
                continue
            if not vod['vod_name'] or vod['vod_name'] == title:
                if d.get('name'):
                    vod['vod_name'] = _ustr(d.get('name'))
            if not vod['vod_pic']:
                vod['vod_pic'] = self._pic(_ustr(d.get('pic') or ''))
            if not vod['vod_content']:
                vod['vod_content'] = _ustr(d.get('content') or '')
            if not vod['vod_actor']:
                vod['vod_actor'] = _ustr(d.get('actor') or '')
            if not vod['vod_director']:
                vod['vod_director'] = _ustr(d.get('director') or '')
            if not vod['vod_year']:
                vod['vod_year'] = _ustr(d.get('year') or '')
            if not vod['vod_area']:
                vod['vod_area'] = _ustr(d.get('area') or '')
            if not vod['vod_remarks']:
                vod['vod_remarks'] = _ustr(d.get('remarks') or '')

        # ---- 线路实测: 可达性 + 真实分辨率 ----
        # 只探测**直链**线路: 网页播放器(腾讯/优酷/自营网页组)本就没有可测分辨率,
        # 测它们纯浪费时间和带宽。
        # 线路名换成**实测画质**(取代源站的虚假宣称), 排序 直链 > 画质高 > 可达
        if lines_from:
            # 画质探测**放后台**: 要拉子清单+分片, 耗时 1~3s。同步阻塞在详情里
            # 会让 App 端取数超时, 表现为详情页"线路/选集"全空。
            # 这里只同步取"已缓存的"探测结果, 没有就先用源站原名返回, 后台回填。
            pr = list(self._quality_cache.get(id(lines_from), []) or [])
            if len(pr) != len(lines_from):
                pr = [(False, None)] * len(lines_from)
            idx_direct = [i for i in range(len(lines_url))
                          if '.m3u8' in lines_url[i].split('#')[0].split('$')[-1].lower()]
            sub_urls = [lines_url[i] for i in idx_direct]
            if sub_urls and idx_direct:
                # 同步只探**第一条**(0.8s 内), 保证首次打开就有一行带画质;
                # 其余全部放后台, 不拖慢详情(详情慢会让 App 端取数超时)
                try:
                    first_pr = self._probe_quality(sub_urls[:1], budget=0.6, limit=1)
                    if first_pr:
                        pr[idx_direct[0]] = first_pr[0]
                except Exception:
                    pass

                def _bg():
                    try:
                        sub_pr = self._probe_quality(sub_urls[1:], budget=2.5, limit=4)
                        full = list(pr)
                        for j, i in enumerate(idx_direct[1:]):
                            if j < len(sub_pr):
                                full[i] = sub_pr[j]
                        self._quality_cache[id(lines_from)] = full
                    except Exception:
                        pass
                bt = threading.Thread(target=_bg)
                bt.daemon = True
                bt.start()
            rank = {'4K': 5, '2K': 4, '1080P': 3, '720P': 2, '480P': 1}
            rows = []
            for i in range(len(lines_from)):
                ok, wh = pr[i] if i < len(pr) else (False, None)
                lab = _quality_label(wh[0], wh[1]) if wh else ''
                nm = self._uniq_line_name(self._honest_line_name(lines_from[i], lab),
                                          [r[3] for r in rows])
                api_i = line_apis[i] if i < len(line_apis) else ''
                rows.append((0 if self._has_direct(lines_url[i]) else 1,
                             -rank.get(lab, 0), 0 if ok else 1, nm, lines_url[i], api_i))
            rows.sort(key=lambda r: (r[0], r[1], r[2]))
            lines_from = [r[3] for r in rows]
            lines_url = [r[4] for r in rows]
            for r in rows:
                if r[5]:
                    self._api_cache[r[3]] = r[5]

        if lines_from:
            vod['vod_play_from'] = u'$$$'.join(lines_from)
            vod['vod_play_url'] = u'$$$'.join(lines_url)
        if len(self._vod_cache) > 64:
            self._vod_cache.clear()
        self._vod_cache[vid] = (time.time(), vod)
        return {'list': [vod]}

    def _ep_name(self, raw, idx):
        # 集名统一成"第N集"(源站五花八门: "第 1 集" / "01" / "第01集" / "1");
        # 没有数字的特殊集名(正片/片头…)保留原样
        t = _ustr(raw or '').strip()
        if not t:
            return u'第%d集' % (idx + 1)
        m = re.search(r'(\d+)', t)
        if m:
            try:
                v = int(m.group(1))
            except Exception:
                return t
            if 0 < v <= 999:
                return u'第%d集' % v
        return t

    def _fetch_bytes(self, url, timeout=12, maxbytes=150000):
        try:
            req = Request(url, headers={'User-Agent': self.UA,
                                        'Referer': self.BASE + '/',
                                        'Accept': '*/*'})
            resp = urlopen(req, timeout=timeout)
            return resp.read(maxbytes)
        except Exception:
            return None

    def _probe_quality(self, line_urls, budget=4.0, limit=8):
        # 并发探测每条线路: (可达, 真实分辨率)。一次网络往返同时拿到两项。
        res = [(False, None)] * len(line_urls)
        n_probe = min(limit, len(line_urls))

        def _w(i):
            u = line_urls[i].split('#')[0].split('$')[-1]
            if not u.startswith('http'):
                res[i] = (True, None)
                return
            tb = self._fetch_bytes(u)
            if not tb:
                res[i] = (False, None)
                return
            txt = tb.decode('utf-8', 'replace')
            if '#EXTM3U' in txt:
                def _small(x, _mb=96000):
                    return self._fetch_bytes(x, maxbytes=_mb)
                res[i] = (True, _resolve_quality(txt, u, _small))
            else:
                res[i] = (True, None)   # 网页播放器: 可达但画质未知

        threads = []
        for i in range(n_probe):
            t = threading.Thread(target=_w, args=(i,))
            t.daemon = True
            t.start()
            threads.append(t)
        deadline = time.time() + budget
        for t in threads:
            left = deadline - time.time()
            if left <= 0:
                break
            t.join(left)
        return res

    # 上游 CDN 的已知坏源: m3u8 里塞的是 PNG 图片, 播不出来。
    # 洛雪自己的 dead_check 也把 png.ruyijx.com 列在 m3u8_sources 里。
    KNOWN_BAD_M3U8 = ('png.ruyijx.com',)
    # 洛雪官方 4K 解析链(站方给网页/TVBox 用):
    #   ① detail 的 episode 里带 playback_grant
    #   ② GET  /json-player.php?route=<官方4K路由>&url=..&source=..&grant=..
    #        → 页面里 data-authorization
    #   ③ POST /api/json-parse.php {route,url,source,authorization}
    #        → {format:'hls', manifest_url:'/api/json-manifest.php?url=<官方CDN m3u8>'}
    #   ④ GET  /api/json-manifest.php?url=..  → m3u8 正文(段是腾讯官方CDN绝对地址)
    # 官方 4K 路由(来自 /api/proxy.php?action=config 的 official_routes):
    OFFICIAL_4K_ROUTE = 'official_musbpyqz'
    # 洛雪站方的解析线路表(实测自 /api/proxy.php?action=config 的 official_routes)
    #   id → (显示名, 类型)  type=json 的走站方 json-player 链, iframe 的走 iframe
    PARSERS = {
        'official_musbpyqz': (u'洛雪4K', 'json'),
        'official_muh2fkp2': (u'蓝光', 'json'),
        'official_default': (u'默认解析', 'iframe'),
        'official_mv83mv2y': (u'TXNP', 'iframe'),
        'official_mugf3fgl': (u'闪电', 'iframe'),
        'official_muh2ffwq': (u'm1907', 'iframe'),
        'official_mugf3kf6': (u'洛雪聚合', 'iframe'),
    }
    # 详情里默认给每条官方线路挂上的解析器(可由 ext 覆盖)
    DEFAULT_PARSERS = ['official_musbpyqz']
    # 官方平台源(优先带进详情, 否则"官采"线路会缺失)
    OFFICIAL_SOURCES = ('qilin', 'fy')
    # 洛雪站方的"还原"接口: 把伪装链的 m3u8 正文 POST 上去, 换回可直连的真链
    IMPORT_API = 'https://img.ruyijx.com/import.php'
    IMPORT_KEY = 'qilingood888'

    def _ql_resolve(self, player_api, target_url, tries=3):
        # 洛雪官方解析链(官方线路):
        #   1) GET  <player_api>?url=<目标页面>   → 页面里 playerConfig.apiToken
        #   2) GET  <origin>/api/resolve.php?token=<apiToken> → {code,url,type}
        # 注意: 第 1 步和第 2 步必须**同一个 cookie 会话**, 否则解析失败。
        if not player_api or not target_url:
            return ''
        op = self._opener
        origin = player_api.split('?')[0].rstrip('/')
        mm = re.match(r'https?://[^/]+', origin)
        if not mm:
            return ''
        origin = mm.group(0)
        for attempt in range(tries):
            try:
                full = player_api + quote(_u8(target_url), safe='')
                page = ''
                for opx in (op, self._opener_lax):
                    if opx is None:
                        continue
                    try:
                        rq = Request(full, headers={'User-Agent': self.UA,
                                                   'Referer': self.BASE + '/'})
                        resp = opx.open(rq, timeout=15)
                        page = resp.read(400000).decode('utf-8', 'replace')
                        if page:
                            break
                    except Exception:
                        continue
                if not page:
                    page = self._get(full, timeout=15, retry=False) or ''
            except Exception:
                return ''
            if not page:
                return ''
            m = re.search(r'apiToken:\s*"([^"]+)"', page)
            if not m:
                return ''
            try:
                api = origin + '/api/resolve.php?token=' + quote(_u8(m.group(1)), safe='')
                raw = ''
                for opx in (op, self._opener_lax):
                    if opx is None:
                        continue
                    try:
                        rq2 = Request(api, headers={'User-Agent': self.UA,
                                                    'Referer': player_api})
                        resp2 = opx.open(rq2, timeout=15)
                        raw = resp2.read(200000).decode('utf-8', 'replace')
                        if raw:
                            break
                    except Exception:
                        continue
                if not raw:
                    raw = self._get(api, timeout=15, retry=False) or ''
                j = json.loads(raw)
            except Exception:
                return ''
            if j.get('code') != 200 or not j.get('url'):
                return ''
            out = j.get('url')
            # 上游会随机分配不同链路:
            #   a) png.ruyijx.com 伪装链(m3u8 里是 PNG 图片, 播不出来)
            #      → 走站方的 import.php 还原, 换回可直连的真链
            #   b) 其他 → 校验第一段, 是 PNG 就换一次
            if any(bad in out for bad in self.KNOWN_BAD_M3U8):
                fixed = self._ql_import(out, target_url)
                if fixed:
                    return fixed
                continue
            if self._is_fake_m3u8(out):
                continue
            return out
        return ''

    def _fetch_bytes_ip(self, url, timeout=12, maxbytes=300000):
        # 域名解析不了时的兜底: 用同 IP(ruyijx 系同机)+ Host 头直连
        try:
            u = urlparse(url)
            host = u.hostname or ''
            ip = None
            for cand in (host, 'img.ruyijx.com', 'svip.qlplayer.cyou'):
                if not cand:
                    continue
                try:
                    ip = socket.gethostbyname(cand)
                    if ip:
                        break
                except Exception:
                    continue
            if not ip:
                return None
            path = u.path or '/'
            if u.query:
                path += '?' + u.query
            c = http.client.HTTPSConnection(ip, 443, timeout=timeout)
            c.request('GET', path, headers={'Host': host, 'User-Agent': self.UA})
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                loc = r.getheader('Location')
                r.read()
                if loc:
                    return self._fetch_bytes_ip(loc, timeout, maxbytes)
                return None
            return r.read(maxbytes)
        except Exception:
            return None

    def _official_4k(self, video_url, grant, route=None, timeout=15, source='qilin'):
        # 官方 4K 链路: json-player.php(取 authorization) → json-parse.php
        # (换 manifest_url)。返回站方 manifest 代理地址(带 Referer 即可播)。
        route = route or self.OFFICIAL_4K_ROUTE
        op = self._opener
        try:
            tgt = (self.BASE + '/json-player.php?route=' + quote(_u8(route), safe='') +
                   '&url=' + quote(_u8(video_url), safe='') +
                   '&source=' + quote(_u8(source), safe='') +
                   '&grant=' + quote(_u8(grant), safe=''))
            # 注意: json-player 生成的 authorization 是**一次性**的,
            # 两步必须用**同一个 opener/会话**, 否则第二步会 403
            # 「播放授权已失效, 请刷新页面」。
            used = None
            page = ''
            # json-player 偶发超时, 重试 2 次(每次都重新要 authorization)
            for _try in range(2):
                if _try:
                    time.sleep(1.2)      # 退避, 避开上游瞬时限流
                for opx in (op, self._opener_lax):
                    if opx is None:
                        continue
                    try:
                        rq = Request(tgt, headers={'User-Agent': self.UA,
                                                   'Referer': self.BASE + '/'})
                        resp = opx.open(rq, timeout=timeout)
                        page = resp.read(400000).decode('utf-8', 'replace')
                        if page:
                            used = opx
                            break
                    except Exception as e:
                        # 403 = 授权已被用掉或被风控限流 → 直接走回退, 不重试(省时间)
                        code = getattr(e, 'code', 0)
                        if code == 403:
                            break
                        continue
                if page and used is not None:
                    break
                time.sleep(0.5)
            if not page or used is None:
                return ''
            m = re.search(r'data-authorization="([^"]+)"', page)
            if not m:
                return ''
            auth = m.group(1)
            body = json.dumps({'route': route, 'url': video_url,
                               'source': source, 'authorization': auth}).encode('utf-8')
            raw = ''
            try:
                rq2 = Request(self.BASE + '/api/json-parse.php', data=body,
                              headers={'User-Agent': self.UA,
                                       'Referer': self.BASE + '/',
                                       'Content-Type': 'application/json'})
                resp2 = used.open(rq2, timeout=timeout)
                raw = resp2.read(300000).decode('utf-8', 'replace')
            except Exception:
                return ''
            if not raw:
                return ''
            j = json.loads(raw)
            mu = j.get('manifest_url') or j.get('url') or ''
            if not mu:
                return ''
            if mu.startswith('/'):
                mu = self.BASE + mu
            # manifest_url 形如 /api/json-manifest.php?url=<encode(真实m3u8)>,
            # 真实地址已经编码在里面 —— 直接解出来交给播放器:
            # 既省一次请求, 也不依赖播放器带站方 cookie。
            mm = re.search(r'[?&]url=([^&]+)', mu)
            if mm:
                try:
                    real = unquote(mm.group(1))
                    if real.startswith('http'):
                        return real
                except Exception:
                    pass
            return mu
        except Exception:
            return ''

    def _route_from_flag(self, flag):
        # 线路名形如 "官采蓝光·洛雪4K" → 解析器 id
        f = _ustr(flag or '')
        for rid, (pname, _t) in self.PARSERS.items():
            if pname and pname in f:
                return rid
        return None

    def _find_grant(self, det, want_url):
        # 在详情里找到该播放页 URL 对应的 playback_grant(播放时实时取, 防过期)
        if not det:
            return ''
        for g in (det.get('episodes') or []):
            for ep in (g.get('episodes') or []):
                if self._fix_url(_ustr(ep.get('url') or '')) == want_url:
                    gp = ep.get('playback_grant')
                    if gp:
                        return _ustr(gp)
        return ''

    def _ql_import(self, m3u8_url, original_url, timeout=15):
        # 洛雪"还原"接口: POST m3u8 正文 + key, 返回可直连的新 m3u8 地址
        try:
            body_txt = self._fetch_bytes(m3u8_url, timeout=timeout, maxbytes=300000)
            if not body_txt:
                # 域名解析不了 → 用同 IP 直连兜底
                body_txt = self._fetch_bytes_ip(m3u8_url, timeout=timeout, maxbytes=300000)
            if not body_txt:
                return ''
            t = body_txt.decode('utf-8', 'replace')
            if '#EXTM3U' not in t:
                return ''
            fields = [('key', self.IMPORT_KEY),
                      ('url', original_url or m3u8_url),
                      ('m3u8', t),
                      ('play_url', m3u8_url)]
            data = urlencode(fields).encode('utf-8')
            rq = Request(self.IMPORT_API, data=data,
                         headers={'User-Agent': self.UA,
                                  'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'})
            op = self._opener
            if op is not None:
                resp = op.open(rq, timeout=timeout)
                raw = resp.read(200000).decode('utf-8', 'replace')
            else:
                raw = self._get(self.IMPORT_API, timeout=timeout, retry=False) or ''
            j = json.loads(raw)
            if j.get('code') == 200 and j.get('url'):
                return j.get('url')
        except Exception:
            return ''
        return ''

    def _is_fake_m3u8(self, m3u8_url, timeout=8):
        # 检测"伪装链": m3u8 的第一段其实是 PNG 图片(洛雪 png.ruyijx.com 已知问题,
        # 站方自己的 dead_check 也把它列为已知死源)。
        # 段取不到(403/DNS 不通)时不做判断, 保留直链 —— 那种情况往往是网络环境问题。
        try:
            txt = self._fetch_bytes(m3u8_url, timeout=timeout, maxbytes=200000)
            if not txt:
                return False
            t = txt.decode('utf-8', 'replace')
            if '#EXTM3U' not in t:
                return False
            segs = []
            for l in t.splitlines():
                l = l.strip()
                if l and not l.startswith('#'):
                    segs.append(l)
            if not segs:
                return False
            seg = segs[0]
            if not seg.startswith('http'):
                seg = urljoin(m3u8_url, seg)   # 相对路径段要按 m3u8 的 url 拼
            tb = self._fetch_bytes(seg, timeout=timeout, maxbytes=4096)
            return bool(tb) and tb[:4] == b'\x89PNG'
        except Exception:
            return False

    def _has_direct(self, line_urls):
        # 该线路是否含可直接播放的直链(m3u8/mp4)
        low = _ustr(line_urls or '').lower()
        return ('.m3u8' in low) or ('.mp4' in low)

    def _pick_sources(self, cands):
        # 按候选顺序去重取源, 最多 6 个
        picked = []
        seen_src = []
        for c in cands:
            src = str(c.get('source') or '')
            if not src or src in seen_src:
                continue
            seen_src.append(src)
            picked.append(c)
            if len(picked) >= 6:
                break
        return picked

    def _norm_title(self, s):
        # 标题归一化: 去空白/标点与结尾的季号后缀, 供译名/别名兜底匹配
        s = _ustr(s or '')
        s = re.sub(r"[\s·•・:：_()（）\[\]【】\-—/、,.。，!！?？]", '', s)
        s = re.sub(r'第[0-9一二三四五六七八九十]+[季期]$', '', s)
        return s.lower()

    def _fetch_details_parallel(self, picked, timeout=6, budget=7):
        # 并发拉各源详情 (纯 threading, Py2/Py3 通用); 结果按 picked
        # 原顺序回填, 单个源失败/超时只丢它自己那条线路。
        # budget = 总时间预算(秒): 到点即用已就绪的线路返回, 不被最慢的
        # 死源拖住(原版等满 timeout+3, 实测详情 10.3s 超过壳子取数上限)
        results = [None] * len(picked)

        def _work(i, c):
            # 官方平台源(qilin/fy)响应体大(4万字节,带 playback_grant),
            # 比采集源慢, 给更宽的超时
            off = (c.get('source') in self.OFFICIAL_SOURCES)
            try:
                results[i] = self._detail_raw(c.get('source'), c.get('id'),
                                              timeout=(min(4, budget + 2) if off else timeout))
            except Exception:
                results[i] = None

        threads = []
        for i, c in enumerate(picked):
            t = threading.Thread(target=_work, args=(i, c))
            t.daemon = True
            t.start()
            threads.append(t)
        deadline = time.time() + budget
        for t in threads:
            left = deadline - time.time()
            if left <= 0:
                break
            t.join(left)
        # 第二轮: 仅对**官方平台源**(qilin/fy, 提供真 4K 线路)做一次限时补试;
        # 其余采集源不重要, 不再等待。整个补试受剩余预算 + 单源 2.0s 双重约束,
        # 绝不会把详情拖回旧版的几秒~几十秒(旧版 4×9s 串行重试)。
        miss = [i for i in range(len(results)) if not results[i]]
        for i in miss:
            if picked[i].get('source') not in self.OFFICIAL_SOURCES:
                continue
            left = deadline - time.time()
            if left < 1.2:
                break
            try:
                results[i] = self._detail_raw(picked[i].get('source'), picked[i].get('id'),
                                              timeout=min(2.0, left))
            except Exception:
                results[i] = None
        return results

    def searchContent(self, key, quick=False, pg='1'):
        title = _ustr(key or '').strip()
        if not title:
            return {'list': [], 'page': 1, 'pagecount': 1}
        results = self._search_raw(title, 1)
        cands = self._rank_candidates(title, results)
        if not cands:
            cands = results
        items = []
        group = {}
        first = {}
        for r in cands:
            nm = _ustr(r.get('name') or '').strip()
            if not nm:
                continue
            # 同名候选聚合成一条: 组内优先保留带海报的候选, 避免搜出
            # 无图灰卡 (采集站多数源不带 pic, 只有少数源返回海报)
            if nm not in first:
                first[nm] = r
            if nm not in group:
                group[nm] = r
            elif not group[nm].get('pic') and r.get('pic'):
                group[nm] = r
        pool = []
        srcmap = {}
        first = {}
        group = {}
        for r in cands:
            nm = _ustr(r.get('name') or '').strip()
            if not nm:
                continue
            # 同名候选聚合成一条: 组内优先保留带海报的候选, 避免搜出
            # 无图灰卡 (采集站多数源不带 pic, 只有少数源返回海报)
            if nm not in first:
                first[nm] = r
            if nm not in group:
                group[nm] = r
            elif not group[nm].get('pic') and r.get('pic'):
                group[nm] = r
            # 同一部剧的多个采集源坐标: 详情页直接并发直连这些源, 不用再搜
            src = r.get('source')
            sid = r.get('id')
            if src and sid:
                lst = srcmap.setdefault(nm, [])
                if len(lst) < 8 and (src, str(sid)) not in lst:
                    lst.append((src, str(sid)))
        # 官方平台源(qilin/fy)必须进坐标, 否则详情里没有"官采"线路。
        # 搜索结果里官方源的剧名可能和主剧名不同(同一部剧的多个别名),
        # 所以这里把**所有**官方候选收集起来挂到每个主结果上。
        off_list = []
        for r in cands:
            if r.get('source') in self.OFFICIAL_SOURCES and r.get('id') is not None:
                off_list.append((_ustr(r.get('name') or '').strip(),
                                 r.get('source'), str(r.get('id'))))
        for nm, lst in srcmap.items():
            # **同名**的官方候选优先(避免把"斗罗大陆Ⅱ"当成"斗罗大陆"的官方源)
            same = [(s, i) for (n2, s, i) in off_list if n2 == nm][:1]
            others = [(s, i) for (n2, s, i) in off_list if n2 != nm][:1]
            for pair in (same + others)[:2]:
                if pair not in lst:
                    lst.insert(0, pair)
        items = []
        for nm, r in group.items():
            items.append({
                'vod_id': self._encode_vid(nm, srcs=srcmap.get(nm)),
                'vod_name': nm,
                'vod_pic': self._pic(_ustr(r.get('pic') or '')),
                'vod_remarks': _ustr(r.get('remarks') or ''),
                'vod_year': _ustr(r.get('year') or ''),
                'vod_type': _ustr(r.get('type') or ''),
            })
            if not r.get('pic') and nm in first:
                pool.append((nm, first[nm]))
            if len(items) >= 30:
                break
        # 采集站搜索接口大多数源不带海报: 对列表头部缺图条目用详情接口
        # 并发补海报 (失败忽略, 缺图条目照常返回), 避免首屏整片灰卡
        self._backfill_pic(items, pool[:4], srcmap)
        return {'list': items, 'page': 1, 'pagecount': 1}

    def _backfill_pic(self, items, pool, srcmap=None):
        # 按搜索候选并发拉详情补 vod_pic; 单条失败只丢它自己的图。
        # 补图用短超时(4s), 慢源直接放弃, 避免搜索响应被拖长
        if not pool:
            return
        cands = []
        for nm, c in pool:
            lst = (srcmap or {}).get(nm) or []
            if lst:
                cands.append({'source': lst[0][0], 'id': lst[0][1]})
            else:
                cands.append(c)
        details = self._fetch_details_parallel(cands, timeout=2, budget=1.2)
        by_name = {}
        for (nm, _c), d in zip(pool, details):
            if d and d.get('pic'):
                by_name[nm] = self._pic(_ustr(d.get('pic')))
        if by_name:
            for it in items:
                if not it.get('vod_pic') and it.get('vod_name') in by_name:
                    it['vod_pic'] = by_name[it['vod_name']]

    def _media_ok(self, u):
        # 返回前最后一道保险: 只有真正的媒体地址才算成功
        if not u:
            return False
        low = _ustr(u).split('?')[0].lower()
        return low.endswith(('.m3u8', '.m3u', '.mp4', '.ts', '.m4s', '.flv'))

    def playerContent(self, flag, ids, vipFlags=None):
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ''
        else:
            vid = str(ids or '')
        url = vid.strip()
        now = time.time()
        if not url:
            return {'parse': 1, 'jx': 0, 'playUrl': '', 'url': '', 'header': {}}
        if url.startswith('//'):
            url = 'https:' + url
        low = url.lower()
        is_m3u8 = ('.m3u8' in low) or low.endswith('.m3u')
        is_mp4 = low.endswith('.mp4') or low.endswith('.flv')
        # 注意: 官方解析线路的 URL 形如 <src>|<id>|<播放页URL>, 含 '|',
        # 必须**先**于直链判断处理, 否则会被当成直链原样返回。
        if not (is_m3u8 or is_mp4):
            _p = url.split('|', 2)
            if len(_p) == 3 and _p[0] and _p[1]:
                _src, _sid, _real = _p
                _rid = self._route_from_flag(flag)
                _m = ''
                if _rid:
                    # detail 偶发失败, 重试几次(拿不到 grant 就没法走 4K 链)
                    _det = None
                    for _try in range(3):
                        _det = self._detail_raw(_src, _sid, timeout=7)
                        if _det:
                            break
                        time.sleep(0.4)
                    _g = self._find_grant(_det, _real)
                    if _g:
                        _m = self._official_4k(_real, _g, route=_rid, source=_src)
                if _m:
                    out = {
                        'parse': 0, 'jx': 0, 'playUrl': '', 'url': _m,
                        'format': 'application/x-mpegURL',
                        'header': {'User-Agent': self.UA,
                                   'Referer': self.BASE + '/'},
                    }
                    if len(self._play_cache) > 128:
                        self._play_cache.clear()
                    self._play_cache[url] = (now, out)
                    return out
                # 官方 4K 链没成 → 用**真实播放页URL**继续走后面的回退链,
                # 绝不能把带 '|' 的编码串丢给壳子(会 400)
                url = _real
                low = url.lower()
                is_m3u8 = ('.m3u8' in low) or low.endswith('.m3u')
                is_mp4 = low.endswith('.mp4') or low.endswith('.flv')
        if is_m3u8 or is_mp4:
            fmt = 'application/x-mpegURL' if is_m3u8 else 'video/mp4'
            # 直链不带 Referer: 采集 CDN 多数不校验, 带陌生站 Referer 反而
            # 可能被拒(实测三种 Referer 均可, 不带最通用)
            return {
                'parse': 0, 'jx': 0, 'playUrl': '', 'url': url, 'format': fmt,
                'header': {'User-Agent': self.UA},
            }

        # 关键优化: 非直链线路(采集源的网页播放器)页面里通常直接内嵌
        # m3u8 地址(如自营 jlplayer 组给出 smart.m3u8 + 两条备用线路),
        # 源自己解析出直链比丢给壳子解析器稳得多
        # 播放缓存: 同一集反复点/切集不重复抓页面(抓一次 1s+)
        hit = self._play_cache.get(url)
        if hit and now - hit[0] < 120:
            return hit[1]
        # ---- 官方线路 + 指定解析器(如"洛雪4K")----
        # URL 形如 <source>|<source_id>|<播放页URL>: 播放时**实时**重取 grant,
        # 再走对应解析器的 json-player → json-parse → manifest 链。
        if url.count('|') >= 2:
            _p = url.split('|', 2)
            if len(_p) == 3 and _p[0] and _p[1]:
                _src, _sid, _real = _p
                _rid = self._route_from_flag(flag)
                if _rid:
                    _det = self._detail_raw(_src, _sid, timeout=6)
                    _g = self._find_grant(_det, _real)
                    if _g:
                        _m = self._official_4k(_real, _g, route=_rid, source=_src)
                        if _m:
                            out = {
                                'parse': 0, 'jx': 0, 'playUrl': '', 'url': _m,
                                'format': 'application/x-mpegURL',
                                'header': {'User-Agent': self.UA,
                                           'Referer': self.BASE + '/'},
                            }
                            if len(self._play_cache) > 128:
                                self._play_cache.clear()
                            self._play_cache[url] = (now, out)
                            return out

        # ---- 官方 4K 链路(洛雪4K 解析器): 实测能换出 3840x1632 HEVC 真 4K ----
        grant = self._grant_map.get(url) or ''
        if grant and not url.lower().split('?')[0].endswith(('.m3u8', '.mp4', '.ts')):
            m4k = self._official_4k(url, grant)
            if m4k:
                out = {
                    'parse': 0, 'jx': 0, 'playUrl': '', 'url': m4k,
                    'format': 'application/x-mpegURL',
                    'header': {'User-Agent': self.UA, 'Referer': self.BASE + '/'},
                }
                if len(self._play_cache) > 128:
                    self._play_cache.clear()
                self._play_cache[url] = (now, out)
                return out
        # 洛雪官方解析链: 腾讯/优酷/爱奇艺这类"网页线路"用站方自己的
        # player_api 换直链(实测能换出真 m3u8, 不必丢给壳子慢慢解析)
        api = self._api_cache.get(_ustr(flag or '')) or ''
        if api:
            real = self._ql_resolve(api, url)
            if real:
                out = {
                    'parse': 0, 'jx': 0, 'playUrl': '', 'url': real,
                    'format': 'application/x-mpegURL',
                    'header': {'User-Agent': self.UA},
                }
                if len(self._play_cache) > 128:
                    self._play_cache.clear()
                self._play_cache[url] = (now, out)
                return out
        real = self._extract_m3u8(url)
        if real:
            out = {
                'parse': 0, 'jx': 0, 'playUrl': '', 'url': real,
                'format': 'application/x-mpegURL',
                'header': {'User-Agent': self.UA},
            }
            if len(self._play_cache) > 128:
                self._play_cache.clear()
            self._play_cache[url] = (now, out)
            return out

        # 兜底: 到这里还没拿到媒体地址 → 交壳子解析器(绝不能返回 HTML)
        return {'parse': 1, 'jx': 0, 'playUrl': url, 'url': url,
                'header': {'User-Agent': self.UA, 'Referer': self.BASE + '/'}}

        # 平台官方线路(B站/腾讯/优酷等页面), 交由壳子解析器处理
        api = self._api_cache.get(_ustr(flag or '')) or ''
        play = url
        if api:
            try:
                play = api + quote(_u8(url), safe='')
            except Exception:
                play = url
        return {
            'parse': 1, 'jx': 0, 'playUrl': play, 'url': play,
            'header': {'User-Agent': self.UA, 'Referer': self.BASE + '/'},
        }

    def _extract_m3u8(self, page_url, timeout=8):
        # 抓网页播放器页面, 从 HTML 里提取 m3u8 直链; 优先 smart.m3u8 /
        # lines/line1.m3u8 这类主线路, 其次任意 m3u8
        try:
            html = self._get(page_url, timeout=timeout, retry=False)
        except Exception:
            html = None
        if not html:
            return ''
        cands = re.findall(r'https?://[^"\'\s<>\\]{6,240}\.m3u8[^"\'\s<>\\]{0,80}', html)
        if not cands:
            return ''
        seen = []
        for c in cands:
            c = c.replace('\\/', '/').replace('&amp;', '&')
            if c not in seen:
                seen.append(c)
        for c in seen:
            low = c.lower()
            if 'smart.m3u8' in low or '/lines/line1.m3u8' in low:
                return c
        # 兜底: 只接受真正的媒体地址, 防止把 HTML 页面当播放地址
        for c in seen:
            low = c.split('?')[0].lower()
            if low.endswith(('.m3u8', '.m3u', '.mp4', '.ts', '.m4s')):
                return c
        return ''

    def searchContentPage(self, key, quick=False, pg='1'):
        return self.searchContent(key, quick, pg)

    # ---------- 本地图片代理 (T4) ----------

    def localProxy(self, param):
        # 拉原图、按魔数定型后回吐; 任何失败回 200 占位图, 避免壳子
        # 对 404 反复重试、整页海报发灰
        try:
            p = self._unwrap_proxy_param(param)
            url = unquote(_ustr(p.get('url') or p.get('u') or ''))
            if not url.startswith('http'):
                return [200, 'image/png', self._placeholder_png()]
            data = self._fetch_pic_bytes(url)
            mime = self._img_mime(data)
            if not mime:
                return [200, 'image/png', self._placeholder_png()]
            return [200, mime, data]
        except Exception:
            return [200, 'image/png', self._placeholder_png()]

    def _unwrap_proxy_param(self, param):
        # param 多形态归一化: dict / 查询串 / 整条代理 URL / Java
        # ArrayList 串 (["do=py","type=pic","url=..."]); url 的值若含
        # 未编码的 & 会被切散, 按 key 定位后取到串尾重组
        if isinstance(param, dict):
            return dict(param)
        s = _ustr(param or '').strip()
        out = {}
        if not s:
            return out
        if s.startswith('{'):
            try:
                d = json.loads(s)
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
        if '?' in s and ('proxy' in s or 'do=py' in s):
            s = s.split('?', 1)[1]
        s = s.strip().strip('[]')
        for part in re.split(r'[,&]', s):
            part = part.strip().strip('"').strip("'")
            if '=' not in part:
                continue
            k, v = part.split('=', 1)
            k = k.strip()
            if k in ('url', 'u'):
                idx = s.find(part)
                if idx >= 0:
                    out[k] = s[idx + len(k) + 1:].strip().strip('"').strip("'")
                else:
                    out[k] = v.strip()
                break
            out[k] = v.strip()
        return out

    def _fetch_pic_bytes(self, url):
        try:
            req = Request(url, headers={
                'User-Agent': self.UA,
                'Referer': self.BASE + '/',
                'Accept': 'image/*,*/*',
            })
            resp = urlopen(req, timeout=10)
            data = resp.read()
            if data and data[:2] == b'\x1f\x8b':
                try:
                    import gzip
                    import io
                    data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
                except Exception:
                    pass
            return data
        except Exception:
            return None

    def _img_mime(self, data):
        if not data or len(data) < 12:
            return ''
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:3] == b'\xff\xd8\xff':
            return 'image/jpeg'
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        if data[4:8] == b'ftyp':
            brands = data[8:64]
            if b'avif' in brands or b'avis' in brands:
                return 'image/avif'
            if (b'heic' in brands or b'heix' in brands or b'hevc' in brands
                    or b'mif1' in brands or b'msf1' in brands):
                return 'image/heic'
            return ''
        if data[:2] == b'BM':
            return 'image/bmp'
        return ''

    def _placeholder_png(self):
        return base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
            'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        if not url:
            return False
        u = _ustr(url).lower()
        return ('m3u8' in u) or u.endswith('.mp4') or u.endswith('.flv')

    def action(self, action):
        return {}

    def destroy(self):
        return None

    # ---------- 工具 ----------

    def _pic(self, url):
        # 封面出口: 默认直链; _PROXY_PIC 打开时包成本地代理地址
        if not url or not self._PROXY_PIC:
            return url
        try:
            base = self.getProxyUrl()
        except Exception:
            base = ''
        if not base:
            base = 'http://127.0.0.1:9978/proxy?do=py'
        if '/proxy' not in base and '?do=py' in base:
            base = base.replace('?do=py', '/proxy?do=py')
        sep = '&' if '?' in base else '?'
        return '%s%stype=pic&url=%s' % (base, sep, quote(_u8(url), safe=''))

    def _fix_url(self, url):
        if not url:
            return ''
        u = _ustr(url)
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http://') or u.startswith('https://'):
            return u
        return urljoin(self.BASE + '/', u)


    def _honest_line_name(self, name, quality=''):
        # 线路名如实化: 源站自称的画质是**虚假宣称** —— ffprobe 逐源实测
        # (2026-10-30, 仙逆全线路采样): 该站 8 个采集源最高只有 1920x816
        # (1080P 宽银幕), 没有任何真 4K; 自称 "4k60帧" 的那条实测 1920x816。
        # 用**实测分辨率**取代自称的画质, 并前置到名字最前:
        #   "4k60帧🔥" + 1080P → "1080P🔥"
        #   "自营🔥"    + 1080P → "1080P 自营🔥"
        # 没测出画质时也要**去掉虚假宣称**(宁可不说, 也不能骗人说 4K)。
        q = _ustr(name or '')
        if not re.search(r'4k60|4k|uhd|2160', q, re.I):
            return (quality + u' ' + q).strip() if quality else q.strip()
        q = re.sub(r'4k60帧?', quality or '', q, flags=re.I)
        q = re.sub(r'\b4k\b|\buhd\b|2160p?', quality or '', q, flags=re.I)
        q = q.strip()
        if not quality:
            # 去掉宣称后只剩符号/表情 → 用来源标识兜底(如 "4k60帧🔥" → "MJ🔥")
            if not re.search(r'[A-Za-z0-9\u4e00-\u9fff]', q):
                q = _ustr(name or '').replace('4k60帧', u'MJ').replace('4K', u'MJ').replace('4k', u'MJ')
        else:
            # 替换后已经以画质开头就别再前置, 否则会出现 "1080P 1080P🔥"
            if not q.startswith(quality):
                q = quality + u' ' + q
        return q.strip()

    def _uniq_line_name(self, name, existing):
        n = name
        i = 2
        while n in existing:
            n = name + u'-' + str(i)
            i += 1
        return n


# ---------- 模块级转发 (T4 规范: _sp 单例 + _ins()) ----------
_sp = None


def _ins():
    global _sp
    if _sp is None:
        _sp = Spider()
    return _sp


def getName():
    return _ins().getName()


def init(extend=""):
    return _ins().init(extend)


def homeContent(filter=None):
    return _ins().homeContent(filter)


def homeVideoContent():
    return _ins().homeVideoContent()


def categoryContent(tid, pg=1, filter=None, extend=None):
    return _ins().categoryContent(tid, pg, filter, extend)


def detailContent(ids):
    return _ins().detailContent(ids)


def searchContent(key, quick=False, pg='1'):
    return _ins().searchContent(key, quick, pg)


def searchContentPage(key, quick=False, pg='1'):
    return _ins().searchContentPage(key, quick, pg)


def playerContent(flag, ids, vipFlags=None):
    return _ins().playerContent(flag, ids, vipFlags)


def localProxy(param):
    return _ins().localProxy(param)


def manualVideoCheck():
    return _ins().manualVideoCheck()


def isVideoFormat(url):
    return _ins().isVideoFormat(url)


def getDependence():
    return _ins().getDependence()


def action(action):
    return _ins().action(action)


def destroy():
    return _ins().destroy()