# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import zlib
from urllib.parse import quote

from Crypto.Cipher import AES
from Crypto.PublicKey import ECC
from Crypto.Util.Padding import pad, unpad
from base.spider import Spider

# 优先用 requests；如果盒子环境真没有（概率极低，因为旧版依赖它），再兜底
try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

API_URL = "http://103.45.132.22:19987/app/bn/v2"
USER_AGENT = "Dart/3.10 (dart:io)"
APP_VERSION = "2.2.5"
BUILD_NUMBER = "20109"
APP_SIGNATURE = "32E0AB4FF93A29CE0E6F0BFB01F2F1B788E76262731F3F30F509CB822428ED58"
DEVICE_BUILD = "pangu-build-component-system-513739-s9vkd-rlxnj-p3rhm"
VERSION_GUARD_MARKERS = (
    "__v99_",
    "glgl.tv",
    "111.170.58.215",
    "shu.jpg",
)
FALLBACK_PARSERS = {
    28: {
        "name": "咕噜金牌",
        "url": "http://111.170.58.215:5499/api.php?id=",
        "mode": "json",
        "result_key": "url",
        "server": False,
    },
}


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
            raise ValueError(f"unsupported protobuf wire type {wire}")
        if position > len(data):
            raise ValueError("truncated protobuf field")
        fields.append((number, wire, value))
    return fields


def _field_values(data, number, wire=None):
    return [
        value
        for field_number, field_wire, value in _parse_fields(data)
        if field_number == number and (wire is None or field_wire == wire)
    ]


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
    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=-15,
        memLevel=8,
        strategy=zlib.Z_RLE,
    )
    return compressor.compress(data) + compressor.flush()


def _derive_key(session_id, shared_x):
    prk = hmac.new(session_id.encode("ascii"), shared_x, hashlib.sha256).digest()
    return hmac.new(prk, b"v2-session\x01", hashlib.sha256).digest()


_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


def _sec1_export_public(key):
    point = key.public_key().pointQ
    x = int(point.x).to_bytes(32, "big")
    y = int(point.y).to_bytes(32, "big")
    return b"\x04" + x + y


def _sec1_import_public(data):
    raw = bytes(data or b"")
    if len(raw) == 65 and raw[0] == 4:
        x = int.from_bytes(raw[1:33], "big")
        y = int.from_bytes(raw[33:65], "big")
    elif len(raw) == 33 and raw[0] in (2, 3):
        x = int.from_bytes(raw[1:], "big")
        y2 = (pow(x, 3, _P256_P) - 3 * x + _P256_B) % _P256_P
        y = pow(y2, (_P256_P + 1) // 4, _P256_P)
        if (y & 1) != (raw[0] & 1):
            y = _P256_P - y
    else:
        raise ValueError("invalid P-256 SEC1 public key")
    return ECC.construct(curve="P-256", point_x=x, point_y=y)


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
        """
        盒子专用：使用 requests 而非 http.client。
        Chaquopy 下 http.client 的 putrequest/endheaders 在 32位 Android 上极不稳定。
        """
        if not HAS_REQUESTS:
            raise RuntimeError("当前环境缺少 requests 模块，无法运行新版咕噜咕噜")
        headers = {
            "user-agent": USER_AGENT,
            header_name: header_value,
            "content-type": "application/x-protobuf",
            "accept-encoding": "gzip",
            "content-length": str(len(body)),
            "host": "103.45.132.22:19987",
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = requests.post(
                API_URL,
                data=body,
                headers=headers,
                timeout=self.timeout,
                stream=False,
            )
            if resp.status_code < 200 or resp.status_code >= 300:
                raise RuntimeError("HTTP %s: %s" % (resp.status_code, resp.text[:200]))
            return resp.content
        except requests.exceptions.Timeout:
            raise RuntimeError("请求超时，请检查网络")
        except requests.exceptions.ConnectionError:
            raise RuntimeError("连接失败，服务器可能不可达")

    def handshake(self):
        private_key = ECC.generate(curve="P-256")
        public_key = _sec1_export_public(private_key)
        capabilities = _field_varint(1, 1) + _field_varint(2, 0) + _field_varint(3, 1)
        request = (
            _field_bytes(1, public_key)
            + _field_bytes(2, b"1.0.0")
            + _field_bytes(3, capabilities)
        )
        handshake_key = secrets.token_hex(16)
        iv = secrets.token_bytes(16)
        cipher = AES.new(handshake_key.encode("ascii"), AES.MODE_CBC, iv)
        encrypted = base64.b64encode(
            iv + cipher.encrypt(pad(zlib.compress(request, 4), AES.block_size))
        )
        content = self._post(encrypted, "x-handshake-key", handshake_key)
        raw = base64.b64decode(content)
        response_cipher = AES.new(handshake_key.encode("ascii"), AES.MODE_CBC, raw[:16])
        plain = zlib.decompress(unpad(response_cipher.decrypt(raw[16:]), AES.block_size))
        session_id = _field_value(plain, 1, wire=2)
        server_public = _field_value(plain, 2, wire=2)
        if not session_id or not server_public:
            raise RuntimeError("invalid handshake response")
        self.session_id = session_id.decode("ascii")
        server_key = _sec1_import_public(server_public)
        shared_point = server_key.pointQ * int(private_key.d)
        shared_x = int(shared_point.x).to_bytes(32, "big")
        self.session_key = _derive_key(self.session_id, shared_x)
        self.request_id = 0

    def _encrypt(self, data):
        nonce = secrets.token_bytes(12)
        cipher = AES.new(self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=16)
        ciphertext, tag = cipher.encrypt_and_digest(_raw_deflate(data))
        return nonce + ciphertext + tag

    def _decrypt(self, data):
        if len(data) < 28:
            raise ValueError("invalid GCM payload")
        nonce, ciphertext, tag = data[:12], data[12:-16], data[-16:]
        compressed = AES.new(
            self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=16
        ).decrypt_and_verify(ciphertext, tag)
        return zlib.decompress(compressed, -15)

    def request(self, method, payload=b"", scope=3, extra_headers=None):
        with self.lock:
            if not self.session_id:
                self.handshake()
            self.request_id += 1
            request_id = self.request_id
            core = (
                _field_varint(1, request_id)
                + _field_varint(2, scope)
                + _field_varint(3, method)
                + _field_bytes(4, self.device_id)
                + _field_bytes(5, b"")
                + _field_bytes(6, payload)
                + _field_varint(7, int(time.time() * 1000))
            )
            body = _field_varint(1, request_id) + _field_bytes(2, self._encrypt(core))
            content = self._post(
                body,
                "x-session-id",
                self.session_id,
                extra_headers=extra_headers,
            )
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
        app = (
            _field_bytes(1, "咕噜咕噜")
            + _field_bytes(2, APP_VERSION)
            + _field_bytes(3, b"com.himrsc.viz")
            + _field_bytes(4, APP_SIGNATURE)
            + _field_bytes(5, BUILD_NUMBER)
            + _field_varint(6, now_us)
            + _field_varint(7, now_us)
        )
        device = (
            _field_bytes(1, self.device_id)
            + _field_varint(2, 1)
            + _field_bytes(3, b"15")
            + _field_bytes(4, b"Redmi K50 Ultra")
            + _field_bytes(5, b"Redmi/diting/diting:15/AQ3A.240912.001/OS2.0.215.0.VOACNXM:user/release-keys")
            + _field_bytes(6, b"Redmi")
            + _field_bytes(7, b"qcom")
            + _field_varint(8, 0)
            + _field_bytes(9, b"unknown")
            + _field_bytes(10, DEVICE_BUILD)
            + _field_varint(11, 0)
            + _field_varint(12, 35)
        )
        payload = (
            _field_bytes(1, b"v2")
            + _field_bytes(2, b"android")
            + _field_bytes(3, b"gulu")
            + _field_bytes(4, app)
            + _field_bytes(5, device)
        )
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
            players[code] = {
                "id": _field_value(item, 1, 0, wire=0),
                "name": _text(_field_value(item, 4, b"", wire=2)),
                "parser_ids": parser_ids,
            }
        parsers = {}
        for item in _field_values(config, 7, wire=2):
            parser_id = _field_value(item, 1, 0, wire=0)
            if parser_id:
                parsers[parser_id] = {
                    "name": _text(_field_value(item, 2, b"", wire=2)),
                    "url": _text(_field_value(item, 3, b"", wire=2)),
                    "mode": _text(_field_value(item, 4, b"", wire=2)),
                    "result_key": _text(_field_value(item, 10, b"url", wire=2)),
                    "server": bool(_field_value(item, 20, 0, wire=0)),
                }
        self.players = players
        self.parsers = parsers

    def search(self, keyword, page=1, limit=21, category_id=""):
        filters = _field_bytes(18, b"vod_hits_month") + _field_varint(19, 1)
        category_id = str(category_id or "").strip()
        if category_id:
            filters += _field_bytes(3, category_id) + _field_bytes(4, category_id)
        payload = (
            _field_bytes(1, keyword)
            + _field_varint(2, int(page))
            + _field_varint(3, int(limit))
            + _field_bytes(5, filters)
        )
        response = self.request(61, payload)
        data = _field_value(response, 4, b"", wire=2)
        videos = []
        for message in _field_values(data, 1, wire=2):
            classes = [_text(v) for v in _field_values(message, 17, wire=2)]
            videos.append({
                "vod_id": str(_field_value(message, 1, 0, wire=0)),
                "vod_name": _text(_field_value(message, 3, b"", wire=2)),
                "vod_pic": _text(_field_value(message, 6, b"", wire=2)),
                "vod_remarks": _text(_field_value(message, 11, b"", wire=2)),
                "vod_year": str(_field_value(message, 2, 0, wire=0)),
                "vod_content": _text(_field_value(message, 20, b"", wire=2)),
                "type_name": ",".join(classes),
                "vod_area": _text(_field_value(message, 16, b"", wire=2)),
                "vod_actor": ",".join(_text(v) for v in _field_values(message, 14, wire=2)),
                "vod_director": ",".join(_text(v) for v in _field_values(message, 15, wire=2)),
                "_type": _field_value(message, 4, 0, wire=0),
            })
        page_info = _field_value(data, 2, b"", wire=2)
        return {
            "videos": videos,
            "page": _field_value(page_info, 1, int(page), wire=0),
            "pagecount": _field_value(page_info, 3, 1, wire=0),
            "limit": _field_value(page_info, 2, int(limit), wire=0),
            "total": _field_value(page_info, 4, len(videos), wire=0),
        }

    def detail(self, vod_id):
        self.last_detail_error = ""
        payload = (
            _field_varint(1, int(vod_id))
            + _field_bytes(3, APP_VERSION)
            + _field_bytes(4, b"1")
            + _field_varint(5, 1)
        )
        response = self.request(
            62,
            payload,
            extra_headers={"x-player-page-protection": "1"},
        )
        data = _field_value(response, 4, b"", wire=2)
        name = _text(_field_value(data, 5, b"", wire=2))
        guard_text = " ".join(
            [_text(_field_value(data, field, b"", wire=2)) for field in (5, 13, 21)]
            + [
                _text(_field_value(source, 1, b"", wire=2))
                for source in _field_values(data, 75, wire=2)
            ]
        ).lower()
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
                    "name": _text(_field_value(episode, 4, b"", wire=2)) or f"第{len(episodes) + 1}集",
                })
            if episodes:
                sources.append({
                    "code": code,
                    "name": config.get("name", code),
                    "parser_id": (config.get("parser_ids") or [0])[0],
                    "episodes": episodes,
                })
        return {
            "id": str(_field_value(data, 1, vod_id, wire=0)),
            "name": name,
            "pic": _text(_field_value(data, 13, b"", wire=2)),
            "remarks": _text(_field_value(data, 22, b"", wire=2)),
            "content": _text(_field_value(data, 21, b"", wire=2)),
            "classes": [
                _text(value) for value in _field_values(data, 12, wire=2)
            ],
            "area": _text(_field_value(data, 28, b"", wire=2)),
            "year": _text(_field_value(data, 30, b"", wire=2)),
            "sources": sources,
        }

    def play(self, parser_id, play_id):
        payload = _field_varint(1, int(parser_id)) + _field_bytes(2, play_id)
        response = self.request(69, payload)
        data = _field_value(response, 4, b"", wire=2)
        return _text(_field_value(data, 2, b"", wire=2))


class Spider(Spider):
    def __init__(self):
        self.ext = ""
        self.name = "咕噜咕噜"
        self.version_name = APP_VERSION
        self.build_number = BUILD_NUMBER
        self.package = "com.jymqfh.xee"
        self.api_version = "v2"
        self.ua = USER_AGENT
        # 手动排序：优先线路 → 4K → 2K → 自建(☆) → 采集
        self.play_order = [
            # === 优先线路（你指定的前6个）===
            "咕噜4K",
            "菲乐4K",
            "鲸宝4K",
            "神话",
            "臻影4K",
            "精品2K",
            "鲸宝2K",
            "短剧2K",
            "天堂",
            # === 自建线路（带☆）===
            "☆讯飞☆",
            "☆奇趣☆",
            "☆果汁☆",
            "☆酷萌☆",
            "☆哔哩☆",
            # === 采集类 ===
            "咖啡",
            "量子",
            "非凡",
            "暴风",
            "蚂蚁",
            "小熊",
            "海外",
            "花旗",
        ]
        self.categories = [
            {"id": "1", "name": "电影"},
            {"id": "2", "name": "电视剧"},
            {"id": "3", "name": "综艺"},
            {"id": "4", "name": "动漫"},
            {"id": "5", "name": "短剧"},
            {"id": "60", "name": "直播"},
        ]
        self.player_config = {}
        self.parser_apis = dict(FALLBACK_PARSERS)
        self.protocol = _GuluProtocol()
        self.last_error = ""
        self._fallback_players()
        self.protocol.players = dict(self.player_config)
        self.protocol.parsers = dict(self.parser_apis)

    def getName(self):
        return "咕噜咕噜"

    def getDependence(self):
        return []

    def setExtendInfo(self, extend):
        self.ext = extend or ""
        return None

    def homeLayout(self):
        return 0

    def init(self, extend=""):
        self.ext = getattr(self, "ext", "") or extend or ""
        if not hasattr(self, "protocol") or self.protocol is None:
            self.__init__()
        try:
            self.protocol.handshake()
            self.protocol.boot()
            self.player_config = self.protocol.players
            self.parser_apis = self.protocol.parsers
            self.last_error = ""
        except Exception as error:
            self.last_error = "init:%s:%s" % (type(error).__name__, error)
            self.log("[咕噜] " + self.last_error)

    def _fallback_players(self):
        # 这个字典只负责"服务器code → 中文显示名"的映射，顺序由 play_order 控制
        fallback = {
            "JD4K": ("鲸宝4K", 32), "CO4K": ("菲乐4K", 23), "rose": ("咖啡", 22),
            "NBY": ("蚂蚁", 25), "lzm3u8": ("量子", 33), "bfzym3u8": ("暴风", 34),
            "ffm3u8": ("非凡", 35), "dyttm3u8": ("天堂", 13), "jplink": ("精品2K", 28),
            "xfyun": ("咕噜4K", 27), "zydj": ("短剧2K", 29), "hqdj": ("花旗", 21),
            "bilibili": ("☆哔哩☆", 22), "qq": ("☆讯飞☆", 22), "qiyi": ("☆奇趣☆", 22),
            "mgtv": ("☆果汁☆", 22), "youku": ("☆酷萌☆", 22), "IMDB": ("臻影", 26),
            "qingshan": ("小熊", 26), "rrmj": ("海外", 21), "qsvip": ("神话", 26),
        }
        for code, (name, parser_id) in fallback.items():
            self.player_config.setdefault(code, {"name": name, "parser_ids": [parser_id]})

    def _search(self, keyword, page=1, limit=21, category_id=""):
        self.last_error = ""
        try:
            return self.protocol.search(keyword, page, limit, category_id)
        except Exception as first_error:
            try:
                self.protocol.session_id = ""
                self.protocol.session_key = b""
                self.protocol.request_id = 0
                result = self.protocol.search(keyword, page, limit, category_id)
                return result
            except Exception as second_error:
                self.last_error = "query:%s:%s | retry:%s:%s" % (
                    type(first_error).__name__, first_error,
                    type(second_error).__name__, second_error,
                )
                self.log("[咕噜] " + self.last_error)
                return {
                    "videos": [], "page": page, "pagecount": 1,
                    "limit": limit, "total": 0, "error": self.last_error,
                }

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": item["id"], "type_name": item["name"]}
                for item in self.categories
            ],
            "filters": {},
        }
        if getattr(self, "last_error", ""):
            result["msg"] = "初始化异常: " + self.last_error
        return result

    def homeVideoContent(self):
        result = self._search("", 1, 21)
        videos = result.get("videos", [])
        for item in videos:
            item.pop("_type", None)
        response = {"list": videos[:20]}
        if result.get("error"):
            response["msg"] = result["error"]
        return response

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        category_id = str(tid or "").strip()
        result = self._search("", page, 21, category_id)
        videos = result.get("videos", [])
        for item in videos:
            item.pop("_type", None)
        response = {
            "page": int(result.get("page", page) or page),
            "pagecount": int(result.get("pagecount", 1) or 1),
            "limit": int(result.get("limit", 21) or 21),
            "total": int(result.get("total", len(videos)) or 0),
            "list": videos,
        }
        if result.get("error"):
            response["msg"] = result["error"]
        return response

    def searchContent(self, key, quick, pg="1"):
        result = self._search(key, int(pg), 21)
        for item in result["videos"]:
            item.pop("_type", None)
        response = {
            "list": result["videos"],
            "page": int(pg),
            "pagecount": result.get("pagecount", 1),
        }
        if result.get("error"):
            response["msg"] = result["error"]
        return response

    def _detail_id(self, ids):
        pending = [ids]
        while pending:
            value = pending.pop(0)
            if isinstance(value, (list, tuple, set)):
                pending[0:0] = list(value)
                continue
            if isinstance(value, dict):
                for key in ("vod_id", "vodId", "id", "key"):
                    if key in value:
                        pending.insert(0, value[key])
                        break
                continue
            if isinstance(value, bytes):
                value = value.decode("utf-8", "ignore")
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            if text[:1] in ("[", "{"):
                try:
                    pending.insert(0, json.loads(text))
                    continue
                except (TypeError, ValueError):
                    pass
            if text.isdigit():
                return text
            match = re.search(r"(?:^|[^0-9])(\d{1,12})(?:$|[^0-9])", text)
            if match:
                return match.group(1)
        return ""

    def detailContent(self, ids):
        vod_id = self._detail_id(ids)
        if not vod_id:
            return {"list": [], "msg": "无效的视频ID"}
        try:
            if not hasattr(self, "protocol") or self.protocol is None:
                self.init("")
            try:
                detail = self.protocol.detail(vod_id)
            except Exception:
                self.protocol.session_id = ""
                self.protocol.session_key = b""
                self.protocol.request_id = 0
                self.protocol.handshake()
                detail = self.protocol.detail(vod_id)
            if not detail:
                result = {"list": []}
                if getattr(self.protocol, "last_detail_error", "") == "server_version_guard":
                    result["msg"] = "服务器要求更新咕噜咕噜版本，详情接口暂不可用"
                else:
                    result["msg"] = "获取详情失败，视频可能已下架"
                return result
            play_from = []
            play_blocks = []
            for source in detail["sources"]:
                episodes = []
                for episode in source["episodes"]:
                    index = episode["index"] or len(episodes) + 1
                    encoded = "{}@{}@{}@{}".format(
                        episode["id"], source["parser_id"], detail["name"], index
                    )
                    episodes.append(f"{episode['name']}${encoded}")
                if episodes:
                    # 清洗显示名称，界面不再显示【看公告】等后缀
                    display_name = self._clean_display_name(source["name"])
                    play_from.append(display_name)
                    play_blocks.append("#".join(episodes))
            paired = list(zip(play_from, play_blocks))
            paired.sort(key=lambda item: self._play_order_key(item[0]))
            vod = {
                "vod_id": detail["id"],
                "vod_name": detail["name"],
                "vod_pic": detail["pic"],
                "vod_remarks": detail["remarks"],
                "vod_year": detail["year"],
                "vod_content": detail["content"],
                "type_name": ",".join(detail["classes"]),
                "vod_area": detail["area"],
                "vod_actor": "",
                "vod_director": "",
                "vod_play_from": "$$$".join(item[0] for item in paired),
                "vod_play_url": "$$$".join(item[1] for item in paired),
            }
            return {"list": [vod]}
        except Exception as error:
            self.log("[咕噜] detailContent error: %s" % error)
            return {"list": [], "msg": "获取详情失败: %s" % error}

    def _clean_display_name(self, name):
        """
        统一清洗线路显示名称。
        去掉 【看公告】、[VIP]、（备用）、HD 等装饰性前后缀，
        让界面只保留干净的线路名。
        """
        if not isinstance(name, str) or not name:
            return name or ""
        # 1. 去除各类括号及其内部内容：【...】 [...] （...） (...)
        clean = re.sub(r'[【\[\(（].*?[】\]）)]', '', name)
        # 2. 去除尾部常见独立标记（不区分大小写）
        clean = re.sub(
            r'\s*(?:HD|VIP|备用|推荐|极速|高清|标清|蓝光|超清|试看|抢先|预告|新版|旧版)\s*$',
            '', clean, flags=re.I
        )
        # 3. 去除多余空格
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _play_order_key(self, source_name):
        """
        计算播放源排序权重。
        三层策略：
        1. play_order 精确/前缀/包含匹配（权重 0~999，最高优先级）
        2. 基于线路特征的智能分类（权重 1000+，兜底防改名）
           - 4K线路 → 1000
           - 2K线路 → 2000
           - 自建(☆) → 3000
           - 其他采集 → 4000
        这样即使服务器后期改了线路名称（如"咕噜4K"→"咕噜超清4K"），
        只要包含"4K"/"2K"/"☆"等特征，大类顺序就不会乱。
        """
        if not source_name:
            return 9999

        # 统一清洗，保证排序和显示逻辑一致
        clean = self._clean_display_name(source_name)
        clean_lower = clean.lower()

        # === 第一层：play_order 精确匹配（不区分大小写）===
        for i, name in enumerate(self.play_order):
            if clean_lower == name.lower():
                return i

        # === 第二层：play_order 前缀/包含匹配（不区分大小写）===
        for i, name in enumerate(self.play_order):
            name_lower = name.lower()
            if clean_lower.startswith(name_lower) or name_lower in clean_lower:
                return i

        # === 第三层：基于特征的智能分类（防改名兜底）===
        upper = clean.upper()
        if '4K' in upper:
            return 1000
        if '2K' in upper:
            return 2000
        if '☆' in clean:
            return 3000
        # 纯中文采集类默认排最后
        return 4000

    def _is_playable_url(self, value):
        if not isinstance(value, str):
            return False
        url = value.strip()
        if not re.match(r"^https?://", url, re.I):
            return False
        return any(mark in url.lower() for mark in (".m3u8", ".mp4", ".mkv", ".flv", ".ts", "/m.php", "?data="))

    def _extract_play_url(self, value, preferred_key="url"):
        if isinstance(value, str):
            value = value.strip()
            return value if self._is_playable_url(value) else ""
        if isinstance(value, dict):
            keys = [preferred_key, "url", "play_url", "playUrl", "m3u8", "data"]
            for key in dict.fromkeys(keys):
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

    def _external_play(self, parser_id, play_id):
        parser = self.protocol.parsers.get(parser_id, {})
        api_url = str(parser.get("url") or "").strip()
        if not api_url:
            return ""
        encoded = quote(str(play_id), safe="")
        target = api_url.replace("{url}", encoded) if "{url}" in api_url else api_url + encoded
        response = self.fetch(target, headers={"User-Agent": USER_AGENT}, timeout=15)
        if isinstance(response, (dict, list, str)):
            payload = response
        else:
            try:
                payload = response.json()
            except Exception:
                payload = getattr(response, "text", "")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                pass
        return self._extract_play_url(payload, parser.get("result_key") or "url")

    def playerContent(self, flag, id, vipFlags):
        try:
            raw_id, parser_id, vod_name, episode_index = id.split("@", 3)
            parser_id = int(parser_id or 0)
        except ValueError:
            raw_id, parser_id, vod_name, episode_index = id, 0, "", "1"
        url = raw_id if self._is_playable_url(raw_id) else ""
        if not url and parser_id:
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
                        self.protocol.session_id = ""
                        self.protocol.session_key = b""
                        self.protocol.request_id = 0
                        self.protocol.handshake()
                        url = self.protocol.play(parser_id, raw_id)
                    except Exception:
                        url = ""
        if not url:
            return {
                "parse": 0,
                "url": "",
                "header": json.dumps({"User-Agent": USER_AGENT}),
                "msg": "解析失败，请尝试更换播放源",
            }
        danmaku = (
            "http://127.0.0.1:9978/proxy?do=appdanmu&vodName="
            + quote(vod_name, safe="")
            + "&vodIndex="
            + quote(str(episode_index), safe="")
            + "&vodUrl="
        )
        return {
            "parse": 0,
            "url": url,
            "header": json.dumps({"User-Agent": USER_AGENT}),
            "danmaku": danmaku,
        }

    def isVideoFormat(self, url):
        return self._is_playable_url(url)

    def manualVideoCheck(self):
        return False

    def proxy(self, params):
        pass

    def localProxy(self, params):
        pass