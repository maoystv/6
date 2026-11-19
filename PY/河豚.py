# -*- coding: utf-8 -*-
import base64
import json
import random
import re
import struct
import time
import uuid

try:
    import requests
except Exception:
    requests = None

try:
    from Crypto.Cipher import AES, PKCS1_v1_5
    from Crypto.PublicKey import RSA
    from Crypto.Util.Padding import pad, unpad
except Exception:
    AES = PKCS1_v1_5 = RSA = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

class Spider(BaseSpider):
    CONFIG = {
        "appName": "河豚",
        "publicKey": "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB",
        "mSafeCode": "V04XQZNYRWN6T0JODZFIAG5CTZB3PT0=",
        "dataIv": "OC1A06E197EF10CF3F6058CA7A803B5E",
        "pkg": "com.djlxxl.xcydzkj",
        "host": "https://az1-1456692500.cos.ap-guangzhou.myqcloud.com/az1.txt",
        "vName": "7.0.0.2",
        "from": "蓝光4k,蓝光"
    }

    # 每页条数（与接口 pagesize 保持一致）
    PAGE_SIZE = 21

    # 分类接口 converUrl 里的字段 -> (筛选键, 筛选标题)
    # 键名用中文，同时 categoryContent 兼容英文别名
    FILTER_FIELDS = (
        ("class", "剧情", "剧情"),
        ("area", "地区", "地区"),
        ("year", "年代", "年代"),
        ("lang", "语言", "语言"),
        ("star", "演员", "演员"),
        ("director", "导演", "导演"),
        ("extend_sort", "排序", "排序"),
    )

    # 源站这几个分类的 converUrl 只是占位数据，按对应条件筛会返回 0 条，
    # 所以整组不展示，避免点了出现空白页
    FILTER_SKIP = {
        "直播": ("剧情", "地区", "年代", "语言", "演员", "导演"),
        "漫剧": ("年代",),
    }

    # converUrl 是各分类共用的一套模板，个别取值实测没有内容（2026-11-19 全量抽查 442 项，空 26 项），
    # 这里隐藏掉；源站补片后想放出来，删掉对应项即可
    FILTER_HIDE = {
        "电影": {"剧情": ("经典", "微电影")},
        "剧集": {"剧情": ("乡村", "情景")},
        "动漫": {"地区": ("其他",)},
        "综艺": {"语言": ("闽南语",), "演员": ("周立波",)},
        "纪录片": {"语言": ("闽南语",)},
        "短剧": {"年代": ("2019", "2018", "2017", "2016", "2015", "2014", "2013",
                          "2012", "2011", "2010", "2008", "2007", "2006", "2004",
                          "2003", "2002", "2001", "2000")},
    }

    def getName(self):
        return self.cfg.get("appName", "河豚")

    def init(self, extend=""):
        self.cfg = dict(self.CONFIG)
        if isinstance(extend, str) and '$' in extend:
            path, key = extend.split('$', 1)
            ext = self._load_config(path.strip(), key.strip())
            if isinstance(ext, dict):
                self.cfg.update(ext)
            elif ext:
                self.cfg['host'] = str(ext).strip()
        elif isinstance(extend, dict):
            self.cfg.update(extend)
        elif isinstance(extend, str) and extend.strip():
            try:
                self.cfg.update(json.loads(extend)) if extend.startswith('{') else setattr(self, 'host', extend.strip())
            except:
                self.cfg['host'] = extend.strip()

        self.host = str(self.cfg.get("host", "")).rstrip("/")
        self.public_key = str(self.cfg.get("publicKey", ""))
        self.data_key = str(self.cfg.get("mSafeCode", ""))
        self.data_iv = str(self.cfg.get("dataIv", ""))
        self.common_key = "ed5fdsgucxumegqa"
        self.version = str(self.cfg.get("vName", "3.0.2.1"))
        self.session = requests.Session() if requests else None
        self.dynamic_key = ""

        from_config = self.cfg.get("from", "")
        self.line_order, self.line_block = [], []
        if from_config and '@' in from_config:
            parts = from_config.split('@')
            if parts[0].strip():
                self.line_order = [k.strip() for k in re.split(r',|@@', parts[0]) if k.strip()]
            if len(parts) > 1 and parts[1].strip():
                self.line_block = [k.strip() for k in re.split(r',|@@', parts[1]) if k.strip()]
        elif from_config:
            self.line_order = [k.strip() for k in re.split(r',|@@', from_config) if k.strip()]

        if self.host and self.session and self.host.endswith(('.txt', '.json')):
            try:
                domain = self.session.get(self.host, timeout=12).json().get("domain", "").strip().rstrip("/")
                if domain:
                    self.host = domain
            except:
                pass

        if self.host:
            try:
                self._load_dynamic_key()
            except:
                pass

    def _load_config(self, config_path, config_key=None):
        try:
            fetcher = self.fetch if hasattr(self, 'fetch') else lambda url, **kw: requests.get(url, timeout=12)
            content = fetcher(config_path, headers={}).text
            try:
                config = json.loads(content)
            except:
                content = re.sub(r'(export\s+default\s+|module\.exports\s*=)|//.*?$|/\*.*?\*/', '', content, flags=re.MULTILINE|re.DOTALL)
                config = json.loads(re.search(r'(\{[\s\S]*\})', content).group(1))
            return config.get(config_key) if config_key else config
        except:
            return None

    def isVideoFormat(self, url):
        return bool(re.search(r"(?i)\.(?:mp4|m3u8|flv|mkv|avi|ts|mov|mpd|m4a|wmv)(?:\?.*)?$", str(url)))

    def manualVideoCheck(self):
        return False

    @staticmethod
    def _varint(value):
        value = int(value)
        out = bytearray()
        while value > 0x7f:
            out.append((value & 0x7f) | 0x80)
            value >>= 7
        out.append(value)
        return bytes(out)

    @classmethod
    def _pb_int(cls, field, value):
        return cls._varint(field << 3) + cls._varint(value)

    @classmethod
    def _pb_bytes(cls, field, value):
        if isinstance(value, str):
            value = value.encode("utf-8")
        return cls._varint((field << 3) | 2) + cls._varint(len(value)) + value

    @staticmethod
    def _read_varint(data, pos):
        value = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            value |= (b & 0x7f) << shift
            if not b & 0x80:
                return value, pos
            shift += 7
        raise ValueError("bad protobuf varint")

    @classmethod
    def _pb_parse(cls, data):
        fields = {}
        pos = 0
        while pos < len(data):
            key, pos = cls._read_varint(data, pos)
            field, wire = key >> 3, key & 7
            if wire == 0:
                value, pos = cls._read_varint(data, pos)
            elif wire == 1:
                value = data[pos:pos + 8]
                pos += 8
            elif wire == 2:
                size, pos = cls._read_varint(data, pos)
                value = data[pos:pos + size]
                pos += size
            elif wire == 5:
                value = data[pos:pos + 4]
                pos += 4
            else:
                raise ValueError("unsupported protobuf wire type: %s" % wire)
            fields.setdefault(field, []).append(value)
        return fields

    @staticmethod
    def _first(fields, number, default=b""):
        values = fields.get(number)
        return values[0] if values else default

    @staticmethod
    def _text(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
        return str(value or "")

    @staticmethod
    def _unescape(text):
        """还原接口里的 HTML 实体（&#039; &amp; 等），否则名字/封面地址会带乱码"""
        if not text or "&" not in str(text):
            return text
        text = str(text)
        text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
        for src, dst in (("&quot;", '"'), ("&apos;", "'"), ("&nbsp;", " "),
                         ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
            text = text.replace(src, dst)
        return text

    @classmethod
    def _clean(cls, value, default=""):
        return cls._unescape(cls._text(value)) or default

    @classmethod
    def _clean_area(cls, value):
        """个别条目的地区字段夹带 JSON 碎片，截掉引号/花括号后面的脏尾巴"""
        text = cls._clean(value)
        text = re.split(r'["{}&]', text, 1)[0]
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _random(length):
        chars = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        return "".join(random.choice(chars) for _ in range(max(0, length - 1))) + "="

    @staticmethod
    def _check_crypto():
        if AES is None or RSA is None:
            raise RuntimeError("缺少 pycryptodome")

    @classmethod
    def _aes_encrypt_ecb(cls, text, key):
        cls._check_crypto()
        cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
        return base64.b64encode(cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))).decode("utf-8")

    @classmethod
    def _aes_decrypt_ecb(cls, text, key):
        cls._check_crypto()
        raw = base64.b64decode(text)
        cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
        return unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8", "ignore")

    @classmethod
    def _aes_encrypt_cbc_hex(cls, text, key):
        cls._check_crypto()
        key_b = key.encode("utf-8")
        cipher = AES.new(key_b, AES.MODE_CBC, iv=key_b)
        return cipher.encrypt(pad(text.encode("utf-8"), AES.block_size)).hex()

    @classmethod
    def _rsa_encrypt(cls, text, public_key_b64):
        cls._check_crypto()
        der = base64.b64decode(public_key_b64)
        key = RSA.import_key(der)
        return base64.b64encode(PKCS1_v1_5.new(key).encrypt(text.encode("utf-8"))).decode("utf-8")

    def _device(self):
        uid = uuid.uuid4().hex.upper()
        return {
            "country": "CN", "vName": self.version, "cpuId": "MT6893Z%2FCZA", "young": 0,
            "facturer": "Xiaomi", "pkg": self.cfg.get("pkg", ""), "uuid": uid,
            "resolution": "1080x2272", "mac": "02%3A00%3A00%3A00%3A00%3A00", "abid": "397",
            "model": "M2012K11AC", "plat": "android", "udid": uid, "dpi": "440", "net": "1",
            "lang": "zh", "brand": "Xiaomi", "density": "2.75", "appName": self.cfg.get("appName", "橘汁"),
            "cpu": "arm64-v8a", "chid": "10000", "carrier": "%E8%81%94%E9%80%9A",
            "_vOsCode": 30, "vOs": "11", "v": 1, "tenantId": "",
            "vApp": self.version.replace(".", ""), "device": 0, "androidID": uid.lower()[:16]
        }

    def _public_headers(self, protobuf=True):
        key = self.dynamic_key or self.public_key
        device = self._device()
        timestamp = int(time.time() * 1000)
        random_str = self._random(16)
        vapp = device.get("vApp") or "3019"
        device["sig"] = self._rsa_encrypt(str(timestamp) + random_str + vapp, key)
        device["random_str"] = random_str
        device["timestamp"] = timestamp
        sig23 = self._aes_encrypt_ecb(str(timestamp) + random_str, self.data_iv)
        device["sig2"] = sig23[:8]
        device["sig3"] = sig23[8:]
        params = self._aes_encrypt_cbc_hex(json.dumps(device, ensure_ascii=False, separators=(",", ":")), self.common_key)
        ctype = "application/x-protobuf" if protobuf else "application/json; charset=utf-8"
        accept = "application/x-protobuf" if protobuf else "application/json"
        return {
            "User-Agent": "okhttp/3.12.1", "Accept": accept, "Content-Type": ctype,
            "publicParams": json.dumps({"paramsData": params}, ensure_ascii=False, separators=(",", ":"))
        }

    def _secure_body(self, params):
        timestamp = int(time.time() * 1000)
        random8 = self._random(8)
        fake20 = self._random(20)
        query = "&".join("%s=%s" % (k, v) for k, v in params.items() if v is not None and str(v) != "")
        encrypted = random8 + self._aes_encrypt_ecb(query + str(timestamp), self.data_key)
        return b"".join([
            self._pb_bytes(1, encrypted[:20]), self._pb_bytes(2, encrypted[20:]),
            self._pb_bytes(3, fake20), self._pb_int(4, timestamp), self._pb_bytes(5, random8)
        ])

    def _post(self, path, body):
        if not self.session or not self.host:
            raise RuntimeError("接口域名获取失败")
        r = self.session.post(self.host + path, data=body, headers=self._public_headers(True), timeout=18)
        r.raise_for_status()
        return r.content

    def _get_json(self, path):
        if not self.session or not self.host:
            raise RuntimeError("接口域名获取失败")
        r = self.session.get(self.host + path, headers=self._public_headers(False), timeout=18)
        r.raise_for_status()
        return r.json()

    def _api_data(self, raw):
        return self._first(self._pb_parse(raw), 3, b"")

    def _load_dynamic_key(self):
        timestamp = int(time.time() * 1000)
        random_str = self._random(16)
        sign = self._rsa_encrypt(str(timestamp) + random_str, self.public_key)
        body = b"".join([
            self._pb_int(1, timestamp), self._pb_bytes(2, sign), self._pb_bytes(3, self._random(16)),
            self._pb_bytes(4, random_str), self._pb_bytes(5, self._random(16))
        ])
        data = self._api_data(self._post("/api/v5/find/app/zone", body))
        f = self._pb_parse(data)
        self.dynamic_key = "".join(self._text(self._first(f, n)) for n in (2, 3, 4, 5))

    def _parse_cover(self, raw):
        f = self._pb_parse(raw)
        return {"path": self._clean(self._first(f, 1)), "thumb": self._clean(self._first(f, 2))}

    def _parse_drama(self, raw):
        f = self._pb_parse(raw)
        cover_raw = self._first(f, 2, b"")
        cover = self._parse_cover(cover_raw) if cover_raw else {}
        return {
            "vod_id": str(self._first(f, 3, 0)), "vod_name": self._clean(self._first(f, 5)),
            "vod_pic": cover.get("thumb") or cover.get("path", ""), "vod_remarks": self._clean(self._first(f, 13)),
            "vod_year": str(self._first(f, 14, "")), "vod_area": self._clean_area(self._first(f, 1))
        }

    def _parse_drama_page(self, raw):
        page = self._pb_parse(self._api_data(raw))
        return [self._parse_drama(v) for v in page.get(1, [])]

    @classmethod
    def _pb_total(cls, fields):
        """列表接口第 16 字段是当前筛选条件下的总条数"""
        value = cls._first(fields, 16, 0)
        if isinstance(value, bytes):
            try:
                value = cls._read_varint(value, 0)[0]
            except Exception:
                return 0
        try:
            return max(0, int(value))
        except Exception:
            return 0

    @staticmethod
    def _split_filter_values(raw):
        if isinstance(raw, (list, tuple)):
            values = [str(v).strip() for v in raw]
        else:
            values = [v.strip() for v in str(raw or "").split(",")]
        result = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _build_filters(self, items):
        """把分类接口的 converUrl 转成 TVBox 的筛选结构"""
        filters = {}
        for item in items or []:
            tid = str(item.get("id") or "").strip()
            if not tid:
                continue
            name = str(item.get("name") or "").strip()
            skip = self.FILTER_SKIP.get(name, ())
            hide = self.FILTER_HIDE.get(name, {})
            try:
                data = json.loads(item.get("converUrl") or "{}")
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            groups = []
            for field, key, label in self.FILTER_FIELDS:
                if key in skip:
                    continue
                hidden = hide.get(key, ())
                values = [v for v in self._split_filter_values(data.get(field)) if v not in hidden]
                if not values:
                    continue
                options = [] if key == "排序" else [{"n": "全部", "v": ""}]
                options.extend({"n": value, "v": value} for value in values)
                groups.append({"key": key, "name": label, "value": options})
            if groups:
                filters[tid] = groups
        return filters

    @staticmethod
    def _extend_get(extend, keys, default=""):
        """extend 里取值：兼容中文键和英文键，空值视为未选"""
        for key in keys:
            value = extend.get(key)
            if value is None:
                continue
            value = str(value).strip()
            if value and value != "全部":
                return value
        return default

    def _parse_video(self, raw):
        f = self._pb_parse(raw)
        return {
            "title": self._text(self._first(f, 2)), "path": self._text(self._first(f, 4)),
            "source": self._text(self._first(f, 9)), "source_cn": self._text(self._first(f, 10))
        }

    def _is_match_line(self, line_name, keyword):
        name = line_name.strip().lower()
        key = keyword.strip()
        try:
            if key.startswith('/') and key.endswith('/'):
                return bool(re.search(key[1:-1], name, re.IGNORECASE))
        except:
            pass
        return key.lower() in name

    def _sort_and_filter_lines(self, lines):
        if not lines:
            return lines
        if self.line_block:
            filtered = [l for l in lines if not any(self._is_match_line(l['name'], kw) for kw in self.line_block)]
            lines = filtered
        if self.line_order:
            sorted_lines = []
            remaining = lines[:]
            for keyword in self.line_order:
                matched, unmatched = [], []
                for line in remaining:
                    (matched if self._is_match_line(line['name'], keyword) else unmatched).append(line)
                sorted_lines.extend(matched)
                remaining = unmatched
            lines = sorted_lines + remaining
        return lines

    def homeContent(self, filter):
        classes, filters = [], {}
        try:
            obj = self._get_json("/api/v3/drama/getCategory?orderBy=type_id")
            data = obj.get("data") or []
            for item in data:
                if str(item.get("name", "")) == "公告":
                    continue
                tid, name = str(item.get("id", "")), str(item.get("name", ""))
                if not tid:
                    continue
                classes.append({"type_id": tid, "type_name": name})
            # 筛选项直接从同一份分类数据的 converUrl 生成，跟着源站走
            filters = self._build_filters(data)
        except Exception:
            pass
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        try:
            obj = self._get_json("/api/ex/v3/security/tag/list")
            data = obj.get("data", "")
            if data and isinstance(data, str):
                stripped = data.strip()
                if stripped and stripped[0] not in ('[', '{'):
                    data = self._aes_decrypt_ecb(data, self.data_key)
                    data = self._aes_decrypt_ecb(data, self.data_iv)
            arr = json.loads(data) if isinstance(data, str) else data
            videos = []
            for block in arr or []:
                for section in block.get("sections") or []:
                    for vod in section.get("vodList") or []:
                        pic = (vod.get("coverImage") or {}).get("path", "")
                        videos.append({"vod_id": str(vod.get("id", "")), "vod_name": vod.get("name", ""), "vod_pic": pic, "vod_remarks": vod.get("remark", "")})
            return {"list": videos}
        except:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        ext = extend if isinstance(extend, dict) else {}
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        params = {
            "pagesize": str(self.PAGE_SIZE),
            "typeId1": str(tid),
            "page": str(page),
            "vodOrderBy": self._extend_get(ext, ("排序", "sort", "order"), "最新"),
            "vodArea": self._extend_get(ext, ("地区", "area")),
            "vodLang": self._extend_get(ext, ("语言", "lang")),
            "vodClass": self._extend_get(ext, ("剧情", "类型", "class")),
            "vodYear": self._extend_get(ext, ("年代", "年份", "year")),
            "vodActor": self._extend_get(ext, ("演员", "star", "actor")),
            "vodDirector": self._extend_get(ext, ("导演", "director")),
        }
        try:
            data = self._pb_parse(self._api_data(
                self._post("/api/proto/v5/drama/category", self._secure_body(params))))
            dramas, seen = [], set()
            for item in data.get(1, []) or []:
                if not isinstance(item, bytes):
                    continue
                vod = self._parse_drama(item)
                if not vod.get("vod_id") or vod["vod_id"] in seen:
                    continue
                seen.add(vod["vod_id"])
                dramas.append(vod)
            total = self._pb_total(data)
            pagecount = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE if total else 9999
            return {"list": dramas, "page": page, "pagecount": pagecount,
                    "limit": self.PAGE_SIZE, "total": total or len(dramas)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 0,
                    "limit": self.PAGE_SIZE, "total": 0}

    def detailContent(self, ids):
        try:
            raw = self._post("/api/proto/v5/drama/getDetail", self._secure_body({"id": str(ids[0])}))
            f = self._pb_parse(self._api_data(raw))
            cover_raw = self._first(f, 2, b"")
            cover = self._parse_cover(cover_raw) if cover_raw else {}
            sources = {}
            for item in f.get(29, []):
                video = self._parse_video(item)
                quality = video.get("source_cn", "") or video.get("source", "") or "未知"
                source = video.get("source", "") or ""
                line_name = f"{quality} ({source})" if source and quality != source else quality
                path = video["path"]
                if not self.isVideoFormat(path):
                    token = base64.b64encode(json.dumps({"vodPlayFrom": video["source"], "playUrl": path}, ensure_ascii=False, separators=(",", ":")).encode()).decode()
                else:
                    token = path
                sources.setdefault(line_name, []).append((video["title"] or "播放") + "$" + token)
            
            lines = [{"name": name, "urls": urls} for name, urls in sources.items()]
            lines = self._sort_and_filter_lines(lines)
            play_from = "$$$".join([line["name"] for line in lines])
            play_url = "$$$".join(["#".join(line["urls"]) for line in lines])
            
            vod = {
                "vod_id": str(ids[0]), "vod_name": self._clean(self._first(f, 9)),
                "vod_pic": cover.get("path") or cover.get("thumb", ""),
                "vod_actor": self._clean(self._first(f, 25)), "vod_director": self._clean(self._first(f, 12)),
                "vod_area": self._clean_area(self._first(f, 1)), "vod_year": str(self._first(f, 18, "")),
                "vod_remarks": self._clean(self._first(f, 26)), "vod_content": self._clean(self._first(f, 6)),
                "vod_play_from": play_from, "vod_play_url": play_url
            }
            return {"list": [vod]}
        except:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        try:
            data = self._pb_parse(self._api_data(
                self._post("/api/proto/v5/drama/search",
                           self._secure_body({"searchKeys": key, "page": str(page),
                                              "pagesize": str(self.PAGE_SIZE)}))))
            results, seen = [], set()
            for item in data.get(1, []) or []:
                if not isinstance(item, bytes):
                    continue
                vod = self._parse_drama(item)
                if not vod.get("vod_id") or vod["vod_id"] in seen:
                    continue
                seen.add(vod["vod_id"])
                results.append(vod)
            total = self._pb_total(data)
            pagecount = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE if total else (1 if results else 0)
            return {"list": results, "page": page, "pagecount": pagecount,
                    "limit": self.PAGE_SIZE, "total": total or len(results)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 0, "limit": self.PAGE_SIZE, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        try:
            if self.isVideoFormat(id):
                return {"parse": 0, "url": id, "header": {}}
            params = json.loads(base64.b64decode(id).decode("utf-8"))
            raw = self._post("/api/proto/v5/videoUsableUrl", self._secure_body(params))
            f = self._pb_parse(self._api_data(raw))
            headers = {}
            for entry in f.get(6, []):
                ef = self._pb_parse(entry)
                k, v = self._text(self._first(ef, 1)), self._text(self._first(ef, 2))
                if k:
                    headers[k] = v
            return {"parse": 0, "url": self._text(self._first(f, 1)), "header": headers}
        except:
            return {"parse": 1, "url": id, "header": {}}

    def localProxy(self, param):
        return [404, "text/plain", "", None]

    def destroy(self):
        if self.session:
            try:
                self.session.close()
            except:
                pass