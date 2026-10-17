# -*- coding: utf-8 -*-
# 多多影视 Spider for TVBox
# 站点: https://323433ssdfd.top
#永久网址：duoduozhuiju.com
# 完整 API 路线:
#   GET  /api.php/web/index/home         首页分类+推荐
#   GET  /api.php/web/filter/vod          分类筛选列表
#   GET  /api.php/web/search/index        搜索
#   GET  /api.php/web/vod/get_detail      影片详情
#   POST /api.php/web/decode/url          解析播放地址 (protobuf)
#
# 请求头:
#   X-Client: 8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a
#   web-sign: ddtvf65f3a83d6d9ad6f
#
# 播放解析流程 (纯 Python, 无需 WASM/Node.js):
#   1. 用 SHA256 生成签名: finger={FINGER}&id={AID}&nonce={nonce}&sk={SK}&time={ts}&v=1
#   2. 构建 protobuf 请求
#   3. POST protobuf 到 /api.php/web/decode/url
#   4. 解析 protobuf 响应获取播放地址

import sys
sys.path.append('..')

from base.spider import Spider
import json
import re
import os
import time
import hashlib
import requests
import urllib3
from urllib.parse import quote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# 签名常量 (从 WASM 逆向获取)
# ============================================================

_FINGER = 'WF-2c064bc5b3400788f31b848849bc3a60f835423ba2dfe69d7ea93974c216e4f2'
_AID = 'com.web.player'
_SK = 'WEB-50a8e9c84a1dc05669a692ded99a2dac46527229e607a7be15db88dbc59059d1'


# ============================================================
# Protobuf 编解码工具 (纯 Python 实现, 无需第三方库)
# ============================================================

def _pb_encode_varint(value):
    """编码 varint"""
    result = bytearray()
    if value < 0:
        value += (1 << 64)
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _pb_encode_string(field_num, s):
    """编码 string 字段"""
    encoded = s.encode('utf-8') if isinstance(s, str) else s
    tag = (field_num << 3) | 2
    return _pb_encode_varint(tag) + _pb_encode_varint(len(encoded)) + encoded


def _pb_encode_varint_field(field_num, value):
    """编码 varint 字段"""
    tag = (field_num << 3) | 0
    return _pb_encode_varint(tag) + _pb_encode_varint(value)


def _pb_decode_varint(data, pos):
    """解码 varint (支持 64 位)"""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _pb_decode(data):
    """解码 protobuf, 返回 {field_number: value} 字典"""
    fields = {}
    pos = 0
    while pos < len(data):
        tag, pos = _pb_decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            val, pos = _pb_decode_varint(data, pos)
            fields[field_number] = val
        elif wire_type == 2:  # length-delimited
            length, pos = _pb_decode_varint(data, pos)
            fields[field_number] = data[pos:pos + length]
            pos += length
        elif wire_type == 5:  # 32-bit
            fields[field_number] = data[pos:pos + 4]
            pos += 4
        elif wire_type == 1:  # 64-bit
            fields[field_number] = data[pos:pos + 8]
            pos += 8
        else:
            break
    return fields


# ============================================================
# 签名生成 (纯 Python, 无需 WASM)
# ============================================================

def _generate_signature(nonce, ts):
    """
    生成签名: SHA256(finger={FINGER}&id={AID}&nonce={nonce}&sk={SK}&time={ts}&v=1)
    返回大写十六进制字符串
    """
    sig_input = f'finger={_FINGER}&id={_AID}&nonce={nonce}&sk={_SK}&time={ts}&v=1'
    return hashlib.sha256(sig_input.encode('utf-8')).hexdigest().upper()


def _create_decode_request(url, vod_from):
    """
    生成带签名的 protobuf 请求 (纯 Python 实现)
    字段:
      1: url (string)
      2: vod_from (string)
      3: timestamp (varint)
      4: nonce (string, 32 hex chars)
      5: signature (string, 64 hex chars)
      6: aid (string, "com.web.player")
      7: v (varint, 1)
    """
    ts = int(time.time() * 1000)
    nonce = os.urandom(16).hex()

    signature = _generate_signature(nonce, ts)

    pb = (
        _pb_encode_string(1, url) +
        _pb_encode_string(2, vod_from) +
        _pb_encode_varint_field(3, ts) +
        _pb_encode_string(4, nonce) +
        _pb_encode_string(5, signature) +
        _pb_encode_string(6, _AID) +
        _pb_encode_varint_field(7, 1)
    )

    return pb


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):
    host = 'https://323433ssdfd.top'

    # API 请求头常量
    X_CLIENT = '8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a'
    WEB_SIGN = 'ddtvf65f3a83d6d9ad6f'

    # 线路显示名 -> from_code 映射 (detailContent 时构建)
    _source_map = {}

    # type_id -> type_name 映射 (homeContent 时构建)
    _type_map = {}

    # 不可用线路黑名单 (from_code 或 site_name 命中即过滤)
    # qsvip: 服务端永久停用; RE蓝光: co源不可靠
    # qq/qiyi/youku/mgtv/bilibili: VIP平台网页链接, 非m3u8, TVBox无法直接播放
    _BLOCKED_SOURCES = {'qsvip', 'RE蓝光', 'qq', 'qiyi', 'youku', 'mgtv', 'bilibili'}

    # 海报 CDN 不可访问域名 (SSL错误/403/502等), 用图片代理替换
    _BAD_PIC_DOMAINS = {
        'img.ffzy888.com', 'pps.vodfeiss.com',
        'lain.bgm.tv', 'ps.ryzypics.com', 'img.gejiba.com',
        '4k.jdyx.pro', 'y.gtimg.cn', 'cfimg.cnyuncdn.com',
    }

    # 完全封锁域名 (代理也无法访问, 返回空让TVBox显示默认图)
    # img.bwcgee.cn: 403; api.zxki.cn: 豆瓣图片代理; doubanio: 防爬418无法代理
    # xyslzy-vip: 代理后仍404
    _DEAD_PIC_DOMAINS = {
        'img.bwcgee.cn', 'api.zxki.cn',
        'img1.doubanio.com', 'img2.doubanio.com', 'img3.doubanio.com', 'img9.doubanio.com',
        'xyslzy-vip-1-10.xysl.it.com',
    }

    # 需要代理的图片域名 (可访问但防爬, 如豆瓣 418)
    _PROXY_PIC_DOMAINS = {
        'img1.doubanio.com', 'img2.doubanio.com', 'img3.doubanio.com',
        'img9.doubanio.com',
    }

    def init(self, extend=''):
        """初始化, 支持配置 ext 传入自定义域名"""
        try:
            if extend:
                ext = json.loads(extend) if isinstance(extend, str) else extend
                site = ext.get('site') or ext.get('host') or ext.get('url')
                if site:
                    self.host = site.strip().rstrip('/')
        except Exception:
            if extend and isinstance(extend, str) and extend.startswith('http'):
                self.host = extend.strip().rstrip('/')
        self.host = (self.host or 'https://323433ssdfd.top').rstrip('/')

    def getName(self):
        return '多多影视'

    def isVideoFormat(self, url):
        return 0

    def manualVideoCheck(self):
        return 0

    def destroy(self):
        pass

    def localProxy(self, param):
        """本地代理: 代理m3u8内容, 解决Content-Type和SSL问题
        param: dict, 包含 type(m3u8/ts) 和 url 参数
        返回: [status_code, content, mimetype]
        """
        try:
            action = param.get('type', '')
            url = param.get('url', '')

            if not url:
                return [200, 'text/plain', b'error: no url']

            from urllib.parse import unquote
            url = unquote(url)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            if action == 'm3u8':
                # 获取m3u8内容
                resp = requests.get(url, verify=False, timeout=15, headers=headers)
                content = resp.text

                # 获取代理URL前缀, 用于重写ts URL
                proxy_base = self._get_proxy_base()

                # 重写ts URL为本地代理URL
                lines = content.split('\n')
                modified = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        ts_url = stripped
                        if not ts_url.startswith('http'):
                            base = url.rsplit('/', 1)[0]
                            ts_url = base + '/' + ts_url
                        proxy_ts_url = f'{proxy_base}do=py&type=ts&url={quote(ts_url)}'
                        modified.append(proxy_ts_url)
                    else:
                        modified.append(line)

                return [200, 'application/x-mpegURL', '\n'.join(modified)]

            elif action == 'ts':
                # 代理ts分段
                resp = requests.get(url, verify=False, timeout=30, headers=headers)
                return [200, 'video/mp2t', resp.content]

            return [200, 'text/plain', b'error: unknown type']
        except Exception as e:
            return [200, 'text/plain', str(e).encode()]

    def _get_proxy_base(self):
        """获取本地代理URL前缀"""
        try:
            if hasattr(self, 'dport'):
                port = self.dport
                if isinstance(port, int):
                    return f'http://127.0.0.1:{port}/proxy?'
                elif isinstance(port, str):
                    if port.startswith('http'):
                        return port if port.endswith('?') or port.endswith('&') else port + '?'
                    return f'http://127.0.0.1:{port}/proxy?'
            return 'http://127.0.0.1:9978/proxy?'
        except Exception:
            return 'http://127.0.0.1:9978/proxy?'

    # ============================================================
    # HTTP 请求工具
    # ============================================================

    def _headers(self):
        """返回 API 请求头"""
        return {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile',
            'Accept': 'application/json',
            'X-Client': self.X_CLIENT,
            'web-sign': self.WEB_SIGN,
            'Referer': f'{self.host}/',
            'Origin': self.host,
        }

    def _play_header(self):
        """播放请求头 — 不带 Referer, 某些 CDN 会因 Referer 返回 403"""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        }

    def _api_get(self, path, params=None):
        """GET JSON API 请求 (直接使用 requests, 避免部分 TVBox 版本 fetch 不兼容)"""
        from urllib.parse import urlencode
        url = f'{self.host}{path}'
        if params:
            url = f'{url}?{urlencode(params)}'
        resp = requests.get(url, headers=self._headers(), verify=False, timeout=30)
        return resp.json()

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        """首页内容: 分类列表 + 推荐 + 筛选条件"""
        try:
            response = self._api_get('/api.php/web/index/home')
        except Exception:
            return {'class': [], 'list': []}

        data = response.get('data') or {}
        categories = data.get('categories') or []

        classes = []
        videos = []

        for cat in categories:
            type_id = cat.get('type_id')
            type_name = cat.get('type_name') or ''
            if not type_id or not type_name:
                continue
            # 保存 type_id -> type_name 映射, 供 categoryContent 使用
            self._type_map[str(type_id)] = type_name
            classes.append({'type_id': type_id, 'type_name': type_name})
            videos.extend(self._arr2vods(cat.get('videos') or []))

        return {
            'class': classes,
            'list': videos,
            'filters': self._build_filters()
        }

    def homeVideoContent(self):
        """首页推荐视频"""
        try:
            data = self.homeContent(False)
            return {'list': data.get('list', [])}
        except Exception:
            return {'list': []}

    def _build_filters(self):
        """构建分类筛选条件"""
        return {
            "1": [
                {"key": "class", "name": "类型", "value": [
                    {"n": "全部", "v": ""}, {"n": "动作", "v": "动作"},
                    {"n": "喜剧", "v": "喜剧"}, {"n": "爱情", "v": "爱情"},
                    {"n": "科幻", "v": "科幻"}, {"n": "恐怖", "v": "恐怖"},
                    {"n": "悬疑", "v": "悬疑"}, {"n": "犯罪", "v": "犯罪"},
                    {"n": "战争", "v": "战争"}, {"n": "动画", "v": "动画"},
                    {"n": "冒险", "v": "冒险"}, {"n": "历史", "v": "历史"},
                    {"n": "灾难", "v": "灾难"}, {"n": "纪录", "v": "纪录"},
                    {"n": "剧情", "v": "剧情"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"},
                    {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
                    {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
                    {"n": "韩国", "v": "韩国"}, {"n": "泰国", "v": "泰国"},
                    {"n": "印度", "v": "印度"}, {"n": "英国", "v": "英国"},
                    {"n": "法国", "v": "法国"}, {"n": "德国", "v": "德国"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"},
                    {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "人气", "v": "hits"}, {"n": "最新", "v": "time"},
                    {"n": "评分", "v": "score"}, {"n": "年份", "v": "year"},
                ]},
            ],
            "2": [
                {"key": "class", "name": "类型", "value": [
                    {"n": "全部", "v": ""}, {"n": "国产剧", "v": "国产剧"},
                    {"n": "港台剧", "v": "港台剧"}, {"n": "日韩剧", "v": "日韩剧"},
                    {"n": "欧美剧", "v": "欧美剧"}, {"n": "海外剧", "v": "海外剧"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"},
                    {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
                    {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
                    {"n": "韩国", "v": "韩国"}, {"n": "英国", "v": "英国"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "人气", "v": "hits"}, {"n": "最新", "v": "time"},
                    {"n": "评分", "v": "score"}, {"n": "年份", "v": "year"},
                ]},
            ],
            "3": [
                {"key": "class", "name": "类型", "value": [
                    {"n": "全部", "v": ""}, {"n": "国产动漫", "v": "国产动漫"},
                    {"n": "日本动漫", "v": "日本动漫"}, {"n": "欧美动漫", "v": "欧美动漫"},
                    {"n": "海外动漫", "v": "海外动漫"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "人气", "v": "hits"}, {"n": "最新", "v": "time"},
                    {"n": "评分", "v": "score"}, {"n": "年份", "v": "year"},
                ]},
            ],
            "4": [
                {"key": "class", "name": "类型", "value": [
                    {"n": "全部", "v": ""}, {"n": "大陆综艺", "v": "大陆综艺"},
                    {"n": "港台综艺", "v": "港台综艺"}, {"n": "日韩综艺", "v": "日韩综艺"},
                    {"n": "欧美综艺", "v": "欧美综艺"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "人气", "v": "hits"}, {"n": "最新", "v": "time"},
                    {"n": "评分", "v": "score"}, {"n": "年份", "v": "year"},
                ]},
            ],
        }

    # ============================================================
    # 分类列表
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        """分类筛选: GET /api.php/web/filter/vod
        注意: API 不支持 type_id 筛选, 必须用 type_name
        """
        try:
            page = int(pg) if pg else 1
            # type_id → type_name 映射 (API 只支持 type_name 筛选)
            type_name = self._type_map.get(str(tid), '')
            params = {
                'page': page,
                'sort': 'hits',
            }
            if type_name:
                params['type_name'] = type_name

            if extend:
                ext = extend if isinstance(extend, dict) else json.loads(extend)
                if ext.get('class'):
                    params['class'] = ext['class']
                if ext.get('area'):
                    params['area'] = ext['area']
                if ext.get('year'):
                    params['year'] = ext['year']
                if ext.get('sort'):
                    params['sort'] = ext['sort']

            response = self._api_get('/api.php/web/filter/vod', params)
        except Exception:
            return {'list': [], 'page': int(pg) if pg else 1,
                    'pagecount': 1, 'limit': 20, 'total': 0}

        data = response.get('data') or []
        items = data if isinstance(data, list) else []

        # API 的 pageCount 不可靠 (始终返回1), 改为根据返回数据量判断是否有更多页
        # 与网站 JS 逻辑一致: 返回条数 >= 18 说明有下一页
        limit = int(response.get('limit') or 24)
        if len(items) >= 18:
            page_count = page + 1  # 还有更多页
        else:
            page_count = page  # 当前页就是最后一页

        total = int(response.get('total') or 999999)

        return {
            'list': self._arr2vods(items),
            'page': page,
            'pagecount': page_count,
            'limit': limit,
            'total': total,
        }

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg='1'):
        """搜索: GET /api.php/web/search/index"""
        try:
            page = int(pg) if pg else 1
            response = self._api_get('/api.php/web/search/index', {
                'wd': key,
                'page': page,
            })
        except Exception:
            return {'list': [], 'page': 1}

        data = response.get('data') or []
        page_count = int(response.get('pageCount') or
                         response.get('pagecount') or 9999)

        return {
            'list': self._arr2vods(data if isinstance(data, list) else []),
            'page': page,
            'pagecount': page_count,
        }

    # ============================================================
    # 详情
    # ============================================================

    def detailContent(self, ids):
        """详情: GET /api.php/web/vod/get_detail + 聚合外部线路"""
        try:
            response = self._api_get('/api.php/web/vod/get_detail', {
                'vod_id': ids[0],
            })
        except Exception:
            return {'list': []}

        data_list = response.get('data') or []
        if isinstance(data_list, dict):
            data = data_list
        elif isinstance(data_list, list) and data_list:
            data = data_list[0]
        else:
            return {'list': []}

        play_from = str(data.get('vod_play_from') or '')
        play_url = str(data.get('vod_play_url') or '')
        vod_name = data.get('vod_name') or ''

        shows = []
        play_urls = []
        source_map = {}  # 显示名 -> from_code

        raw_from_list = play_from.split('$$$')
        raw_url_list = play_url.split('$$$')

        # 主线路
        for from_code, urls_str in zip(raw_from_list, raw_url_list):
            if not from_code or not urls_str:
                continue
            # 过滤黑名单线路
            if from_code in self._BLOCKED_SOURCES:
                continue

            eps = [e for e in urls_str.split('#') if e.strip() and '$' in e]
            if eps:
                play_urls.append('#'.join(eps))
                shows.append(from_code)
                source_map[from_code] = from_code

        # 追加聚合搜索的外部线路
        ext_sources = self._fetch_aggregate_sources(vod_name)
        for site_name, from_code, urls_str in ext_sources:
            # 过滤黑名单线路 (按 from_code 或 site_name 匹配)
            if from_code in self._BLOCKED_SOURCES or site_name in self._BLOCKED_SOURCES:
                continue
            # 跳过与主线路重复的 from_code
            if from_code in [source_map.get(s) for s in shows]:
                continue
            eps = [e for e in urls_str.split('#') if e.strip() and '$' in e]
            if eps:
                play_urls.append('#'.join(eps))
                shows.append(site_name)
                source_map[site_name] = from_code

        # 保存映射供 playerContent 使用
        self._source_map = source_map

        # 缓存线路信息供 playerContent 回退使用
        # 格式: {vod_id: {from_code: [(ep_name, ep_url), ...]}}
        if not hasattr(self, '_ep_cache'):
            self._ep_cache = {}
        ep_map = {}
        for show_name, purls in zip(shows, play_urls):
            fc = source_map.get(show_name, show_name)
            ep_list = []
            for e in purls.split('#'):
                if '$' in e:
                    en, eu = e.split('$', 1)
                    ep_list.append((en, eu))
            ep_map[fc] = ep_list
        self._ep_cache[str(data.get('vod_id', ids[0]))] = ep_map

        video = {
            'vod_id': data.get('vod_id', ids[0]),
            'vod_name': data.get('vod_name', ''),
            'vod_pic': self._fix_pic(data.get('vod_pic', '')),
            'vod_remarks': data.get('vod_remarks', ''),
            'vod_year': data.get('vod_year', ''),
            'vod_area': data.get('vod_area', ''),
            'vod_actor': data.get('vod_actor', ''),
            'vod_director': data.get('vod_director', ''),
            'vod_content': re.sub(r'<[^>]+>', '', (data.get('vod_content') or '')),
            'vod_play_from': '$$$'.join(shows),
            'vod_play_url': '$$$'.join(play_urls),
            'type_name': data.get('vod_class') or data.get('type_name') or '',
        }
        return {'list': [video]}

    def _fetch_aggregate_sources(self, vod_name):
        """调用聚合搜索 API 获取外部线路, 返回 [(site_name, from_code, play_url), ...]
        当原始名称无结果时, 尝试用去除后缀的名称重试"""
        if not vod_name:
            return []

        # 按优先级尝试的搜索名称列表
        search_names = [vod_name]

        # 去除常见后缀生成备选名称: 年番/第一季/第二季/第三季/上部/下部 等
        clean_name = re.sub(
            r'\s*(年番|第[一二三四五六七八九十\d]+季|第[一二三四五六七八九十\d]+部|上部|下部|上集|下集|完结篇|最终季|特别篇|OVA|ova)\s*',
            '', vod_name
        ).strip()
        if clean_name and clean_name != vod_name:
            search_names.append(clean_name)

        for name in search_names:
            try:
                resp = self._api_get('/api.php/web/internal/search_aggregate', {
                    'name': name,
                })
            except Exception:
                continue

            results = resp.get('data') or []
            if not isinstance(results, list) or not results:
                continue

            sources = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                site_name = r.get('site_name') or r.get('site_key') or ''
                from_code = r.get('vod_play_from') or ''
                play_url = r.get('vod_play_url') or ''
                if not site_name or not from_code or not play_url:
                    continue
                sources.append((site_name, from_code, play_url))

            if sources:
                return sources

        return []

    # ============================================================
    # 播放解析
    # ============================================================

    def playerContent(self, flag, vid, vip_flags):
        """解析播放地址: 纯 Python 签名 + protobuf 请求"""

        raw_url = vid

        # HTTP 直链 (外部线路 decode_status=0): 无需解码, 直接返回
        if raw_url.startswith('http'):
            result = {
                'jx': 0,
                'parse': 0,
                'url': raw_url,
                'header': self._play_header(),
            }
            # m3u8 直链也需要指定 format
            if 'm3u8' in raw_url.lower():
                result['format'] = 'application/x-mpegURL'
            return result

        # 需要解码的线路: 通过映射表查找 from_code
        vod_from = self._source_map.get(flag, flag)

        # 用纯 Python 生成签名并解码
        play_url = self._decode_url(vod_from, raw_url)

        # CO4K 返回 MPD (DASH) 格式时, TVBox 无法播放
        # 回退到 co 线路 (返回直接 MP4)
        if play_url and '.mpd' in play_url:
            fallback_url = self._try_fallback_line(flag, vid, ['co'])
            if fallback_url:
                play_url = fallback_url

        if play_url and play_url.startswith('http'):
            result = {
                'jx': 0,
                'parse': 0,
                'url': play_url,
                'header': self._play_header(),
            }
            # NBY等线路的m3u8返回 application/octet-stream Content-Type
            # ExoPlayer无法识别为HLS, 需指定format
            if 'm3u8' in play_url.lower():
                result['format'] = 'application/x-mpegURL'
            return result

        # 解码失败且非 HTTP URL: 设置 jx=1 让 TVBox 尝试嗅探解析
        return {
            'jx': 1,
            'parse': 1,
            'url': raw_url,
            'header': self._play_header(),
        }

    def _try_fallback_line(self, original_flag, original_vid, fallback_codes):
        """当主线路返回不可播放格式(MPD等)时, 尝试其他线路的同一集"""
        if not hasattr(self, '_ep_cache'):
            return None

        # 在所有缓存的影片中查找当前集的 URL
        for vod_id, ep_map in self._ep_cache.items():
            # 找到当前线路和集数
            current_eps = None
            current_from = None
            for fc, eps in ep_map.items():
                for en, eu in eps:
                    if eu == original_vid:
                        current_eps = eps
                        current_from = fc
                        break
                if current_eps:
                    break

            if not current_eps:
                continue

            # 找到当前集的索引
            ep_idx = None
            for i, (en, eu) in enumerate(current_eps):
                if eu == original_vid:
                    ep_idx = i
                    break

            if ep_idx is None:
                continue

            # 在回退线路中找同一集
            for fb_code in fallback_codes:
                fb_eps = ep_map.get(fb_code)
                if fb_eps and ep_idx < len(fb_eps):
                    fb_en, fb_eu = fb_eps[ep_idx]
                    fb_url = self._decode_url(fb_code, fb_eu)
                    if fb_url and fb_url.startswith('http') and '.mpd' not in fb_url:
                        return fb_url

        return None

    def _decode_url(self, vod_from, raw_url):
        """纯 Python 解码播放地址"""
        try:
            # 生成带签名的 protobuf 请求
            pb_data = _create_decode_request(raw_url, vod_from)

            resp = requests.post(
                f'{self.host}/api.php/web/decode/url',
                data=pb_data,
                headers={
                    'Content-Type': 'application/x-protobuf',
                    'Accept': 'application/x-protobuf',
                    'X-Client': self.X_CLIENT,
                    'web-sign': self.WEB_SIGN,
                    'Referer': f'{self.host}/',
                    'Origin': self.host,
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile',
                },
                verify=False,
                timeout=15
            )

            fields = _pb_decode(resp.content)
            code = fields.get(1, 0)

            if code != 1:
                return None

            # 遍历所有字段查找播放地址 (更健壮: 不只看 field 3)
            for k, v in fields.items():
                if isinstance(v, bytes) and b'http' in v:
                    idx = v.index(b'http')
                    return v[idx:].decode('utf-8', errors='replace').rstrip('\x00')

            return None
        except Exception:
            return None

    # ============================================================
    # 工具方法
    # ============================================================

    def _fix_pic(self, url):
        """修复海报URL: 不可访问域名通过图片代理替换"""
        if not url:
            return ''
        # 补全协议
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            return ''
        # 检查是否为代理URL (如 4k.jdyx.pro/img.php?url=xxx 或 IP:端口/imgs.php?url=xxx)
        if 'url=' in url:
            import urllib.parse as up
            parsed = up.urlparse(url)
            qs = up.parse_qs(parsed.query)
            if 'url' in qs:
                url = qs['url'][0]
                if not url.startswith('http'):
                    url = 'https://' + url
        # 提取域名
        try:
            domain = url.split('/')[2]
        except (IndexError, ValueError):
            return url
        # 完全封锁域名 → 返回空, TVBox显示默认占位图
        if domain in self._DEAD_PIC_DOMAINS:
            return ''
        # 不可访问域名 → 用 images.weserv.nl 代理
        if domain in self._BAD_PIC_DOMAINS:
            return 'https://images.weserv.nl/?url=' + url.replace('http://', '').replace('https://', '')
        # 防爬域名 (豆瓣等) → 也用代理
        if domain in self._PROXY_PIC_DOMAINS:
            return 'https://images.weserv.nl/?url=' + url.replace('http://', '').replace('https://', '')
        return url

    def _arr2vods(self, arr):
        """将 API 返回的数组转换为 VOD 列表"""
        videos = []
        if not isinstance(arr, list):
            return videos

        for item in arr:
            if not isinstance(item, dict):
                continue

            type_name = item.get('type_name') or ''
            vod_class = item.get('vod_class') or ''
            if isinstance(vod_class, list):
                vod_class = ','.join(vod_class)
            if vod_class:
                type_name = f'{type_name},{vod_class}' if type_name else vod_class

            vod_area = item.get('vod_area') or ''
            if isinstance(vod_area, list):
                vod_area = ','.join(vod_area)

            videos.append({
                'vod_id': item.get('vod_id', ''),
                'vod_name': item.get('vod_name', ''),
                'vod_pic': self._fix_pic(item.get('vod_pic', '')),
                'vod_remarks': item.get('vod_remarks', ''),
                'type_name': type_name,
                'vod_year': item.get('vod_year', ''),
                'vod_area': vod_area,
            })
        return videos
