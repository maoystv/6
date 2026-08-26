# -*- coding: utf-8 -*-
import base64
import json
import random
import re
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
        "appName": "橘汁",
        "publicKey": "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB",
        "dataKey": "OW1WBLFZCLJ0WTNJCDMYEGXWYVP3PT0=",
        "dataIv": "OC1A06E197EF10CF3F6058CA7A803B5E",
        "pkg": "com.mxj.wylcjbxyx",
        "host": "http://juziapp.hzhcbkj.cn",
        "site": "https://123-1349250429.cos.ap-shanghai.myqcloud.com/app.txt",
        "version": "3.0.2.3",
        "decrypt": "1"
    }

    def getName(self):
        return "橘汁"

    def init(self, extend=""):
        self.cfg = dict(self.CONFIG)
        if isinstance(extend, dict):
            self.cfg.update(extend)
        elif isinstance(extend, str) and extend.strip():
            try:
                self.cfg.update(json.loads(extend))
            except Exception:
                pass

        self.host = str(self.cfg.get("host", "")).rstrip("/")
        self.public_key = str(self.cfg.get("publicKey", ""))
        self.dynamic_key = ""
        self.data_key = str(self.cfg.get("dataKey", ""))
        self.data_iv = str(self.cfg.get("dataIv", ""))
        self.common_key = "ed5fdsgucxumegqa"
        self.session = requests.Session() if requests else None

        site = str(self.cfg.get("site", ""))
        if site and self.session and not self.host:
            try:
                obj = self.session.get(site, timeout=12).json()
                domain = str(obj.get("domain", "")).strip().rstrip("/")
                if domain:
                    self.host = domain
            except Exception:
                pass

        if self.host:
            try:
                self._load_dynamic_key()
            except Exception:
                self.dynamic_key = ""

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
            if shift > 70:
                raise ValueError("bad protobuf varint")
        raise ValueError("truncated protobuf varint")

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
        version = str(self.cfg.get("version", ""))
        return {
            "country": "CN", "vName": version, "cpuId": "MT6893Z%2FCZA", "young": 0,
            "facturer": "Xiaomi", "pkg": self.cfg.get("pkg", ""), "uuid": uid,
            "resolution": "1080x2272", "mac": "02%3A00%3A00%3A00%3A00%3A00", "abid": "397",
            "model": "M2012K11AC", "plat": "android", "udid": uid, "dpi": "440", "net": "1",
            "lang": "zh", "brand": "Xiaomi", "density": "2.75", "appName": self.cfg.get("appName", "橘汁"),
            "cpu": "arm64-v8a", "chid": "10000", "carrier": "%E8%81%94%E9%80%9A",
            "_vOsCode": 30, "vOs": "11", "v": 1, "tenantId": "",
            "vApp": version.replace(".", ""), "device": 0, "androidID": uid.lower()[:16]
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
            raise RuntimeError("橘汁接口域名获取失败")
        r = self.session.post(self.host + path, data=body, headers=self._public_headers(True), timeout=18)
        r.raise_for_status()
        return r.content

    def _get_json(self, path):
        if not self.session or not self.host:
            raise RuntimeError("橘汁接口域名获取失败")
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
        return {"path": self._text(self._first(f, 1)), "thumb": self._text(self._first(f, 2))}

    def _parse_drama(self, raw):
        f = self._pb_parse(raw)
        cover = self._parse_cover(self._first(f, 2, b"")) if self._first(f, 2, b"") else {}
        return {
            "vod_id": str(self._first(f, 3, 0)), "vod_name": self._text(self._first(f, 5)),
            "vod_pic": cover.get("thumb") or cover.get("path", ""), "vod_remarks": self._text(self._first(f, 13)),
            "vod_year": str(self._first(f, 14, "")), "vod_area": self._text(self._first(f, 1))
        }

    def _parse_drama_page(self, raw):
        page = self._pb_parse(self._api_data(raw))
        return [self._parse_drama(v) for v in page.get(1, [])]

    def _parse_video(self, raw):
        f = self._pb_parse(raw)
        return {
            "title": self._text(self._first(f, 2)), "path": self._text(self._first(f, 4)),
            "source": self._text(self._first(f, 9)), "source_cn": self._text(self._first(f, 10))
        }

    def homeContent(self, filter):
        try:
            obj = self._get_json("/api/v3/drama/getCategory?orderBy=type_id")
            classes, filters = [], {}
            for item in obj.get("data") or []:
                if str(item.get("name", "")) == "公告":
                    continue
                tid, name = str(item.get("id", "")), str(item.get("name", ""))
                if not tid:
                    continue
                classes.append({"type_id": tid, "type_name": name})

                # 优先从 typeExtend 接口获取最新筛选条件
                fl = []
                try:
                    ext_obj = self._get_json("/api/ex/v3/drama/typeExtend?cate=" + tid)
                    ext_data = ext_obj.get("data", {})
                    if isinstance(ext_data, dict):
                        mapping = [
                            ("movieClass", "class", "类型"),
                            ("area", "area", "地区"),
                            ("lang", "lang", "语言"),
                            ("year", "year", "年份"),
                            ("extendSort", "extend_sort", "排序"),
                        ]
                        for src_key, dst_key, dst_name in mapping:
                            value = ext_data.get(src_key, "")
                            if value:
                                vals = [x for x in str(value).split(",") if x]
                                fl.append({"key": dst_key, "name": dst_name, "value": [{"n": x, "v": x} for x in vals]})
                except Exception:
                    pass

                # fallback: 从 converUrl 解析
                if not fl:
                    raw_filter = item.get("converUrl") or ""
                    try:
                        ext = json.loads(raw_filter) if isinstance(raw_filter, str) else raw_filter
                    except Exception:
                        ext = {}
                    for key in ("class", "lang", "area", "year", "extend_sort"):
                        value = ext.get(key, "") if isinstance(ext, dict) else ""
                        if value:
                            vals = [x for x in str(value).split("|") if x]
                            fl.append({"key": key, "name": key, "value": [{"n": x, "v": x} for x in vals]})

                if fl:
                    filters[tid] = fl
            return {"class": classes, "filters": filters}
        except Exception as e:
            return {"class": [], "filters": {}, "error": str(e)}

    def homeVideoContent(self):
        videos = []
        err_msg = ""
        try:
            obj = self._get_json("/api/ex/v3/security/tag/list")
            raw_data = obj.get("data", "")
            if isinstance(raw_data, (list, dict)):
                arr = [raw_data] if isinstance(raw_data, dict) else raw_data
            else:
                data_str = str(raw_data) if raw_data else ""
                arr = None
                if data_str:
                    try:
                        arr = json.loads(data_str)
                    except Exception:
                        pass
                if arr is None and str(self.cfg.get("decrypt", "1")) != "0" and data_str:
                    try:
                        decrypted = self._aes_decrypt_ecb(data_str, self.data_key)
                        arr = json.loads(decrypted)
                    except Exception:
                        pass
                if arr is None and str(self.cfg.get("decrypt", "1")) != "0" and data_str:
                    try:
                        decrypted1 = self._aes_decrypt_ecb(data_str, self.data_key)
                        decrypted2 = self._aes_decrypt_ecb(decrypted1, self.data_iv)
                        arr = json.loads(decrypted2)
                    except Exception as e2:
                        err_msg = "双层解密失败: " + str(e2)
            if arr is None:
                arr = []
            for block in arr or []:
                if not isinstance(block, dict):
                    continue
                if "vodList" in block:
                    for vod in block.get("vodList") or []:
                        self._append_vod(videos, vod)
                    continue
                for section in block.get("sections") or []:
                    if not isinstance(section, dict):
                        continue
                    for vod in section.get("vodList") or []:
                        self._append_vod(videos, vod)
            if videos:
                return {"list": videos}
        except Exception as e:
            err_msg = "推荐接口异常: " + str(e)
        try:
            home = self.homeContent(False)
            classes = home.get("class", [])
            if classes:
                first_tid = classes[0].get("type_id", "")
                if first_tid:
                    cat = self.categoryContent(first_tid, "1", False, {})
                    fallback = cat.get("list", [])
                    if fallback:
                        return {"list": fallback, "note": "首页推荐降级至分类内容"}
        except Exception as e2:
            err_msg += " | 降级也失败: " + str(e2)
        return {"list": videos, "error": err_msg}

    def _append_vod(self, videos, vod):
        if not isinstance(vod, dict):
            return
        pic = ""
        cover = vod.get("coverImage") or vod.get("cover") or {}
        if isinstance(cover, dict):
            pic = cover.get("path") or cover.get("thumb") or cover.get("url") or ""
        videos.append({
            "vod_id": str(vod.get("id") or vod.get("vod_id") or ""),
            "vod_name": str(vod.get("name") or vod.get("vod_name") or ""),
            "vod_pic": pic,
            "vod_remarks": str(vod.get("remark") or vod.get("vod_remarks") or "")
        })

    def categoryContent(self, tid, pg, filter, extend):
        params = {
            "pagesize": "21", "typeId1": str(tid), "page": str(pg),
            "vodOrderBy": (extend or {}).get("extend_sort", "最新"),
            "vodArea": (extend or {}).get("area", ""), "vodLang": (extend or {}).get("lang", ""),
            "vodClass": (extend or {}).get("class", ""), "vodYear": (extend or {}).get("year", "")
        }
        try:
            raw = self._post("/api/proto/v5/drama/list", self._secure_body(params))
            videos = self._parse_drama_page(raw)
            page = int(pg)
            return {"list": videos, "page": page, "pagecount": page + (1 if len(videos) >= 21 else 0), "limit": 21, "total": 999999}
        except Exception as e:
            return {"list": [], "page": int(pg or 1), "pagecount": 1, "limit": 21, "total": 0, "error": str(e)}

    def detailContent(self, ids):
        try:
            raw = self._post("/api/proto/v5/drama/getDetail", self._secure_body({"id": str(ids[0])}))
            f = self._pb_parse(self._api_data(raw))
            cover_raw = self._first(f, 2, b"")
            cover = self._parse_cover(cover_raw) if cover_raw else {}
            sources = {}
            for item in f.get(29, []):
                video = self._parse_video(item)
                source = video["source_cn"] or "橘汁"
                path = video["path"]
                if not self.isVideoFormat(path):
                    token = base64.b64encode(json.dumps({"vodPlayFrom": video["source"], "playUrl": path}, ensure_ascii=False, separators=(",", ":")).encode()).decode()
                else:
                    token = path
                sources.setdefault(source, []).append((video["title"] or "播放") + "$" + token)
            vod = {
                "vod_id": str(ids[0]), "vod_name": self._text(self._first(f, 9)),
                "vod_pic": cover.get("path") or cover.get("thumb", ""),
                "vod_actor": self._text(self._first(f, 25)), "vod_director": self._text(self._first(f, 12)),
                "vod_area": self._text(self._first(f, 1)), "vod_year": str(self._first(f, 18, "")),
                "vod_remarks": self._text(self._first(f, 26)), "vod_content": self._text(self._first(f, 6)),
                "vod_play_from": "$$$".join(sources.keys()),
                "vod_play_url": "$$$".join("#".join(v) for v in sources.values())
            }
            return {"list": [vod]}
        except Exception as e:
            return {"list": [], "error": str(e)}

    def searchContent(self, key, quick, pg="1"):
        try:
            raw = self._post("/api/proto/v5/drama/search", self._secure_body({"searchKeys": key, "page": str(pg), "pagesize": "21"}))
            return {"list": self._parse_drama_page(raw)}
        except Exception as e:
            return {"list": [], "error": str(e)}

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
        except Exception as e:
            return {"parse": 1, "url": id, "header": {}, "error": str(e)}

    def localProxy(self, param):
        return [404, "text/plain", "", None]
