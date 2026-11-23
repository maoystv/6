# -*- coding: utf-8 -*-
r"""
珊瑚影视 TVBox 爬虫 v7.1
站点: https://www.qisheng1688.com/

v7.1 修复(相对 v7):
1. 【严重】_raw / _request 新增 params 参数, _search_via_page 现在真正把 wd=关键词
   传给 /search.html(此前 params 构造后未使用, 导致搜索恒为空结果)。
2. _blocked 用 try 包裹 resp.text 访问且只取一次, 避免编码异常误触发过盾。
3. _ensure_session 的 TTL 过期判断挪到锁内, 避免多线程互相清 session。
4. _pass_guard 中多余的 `if not ...: pass` 删除, session 重建后短路返回更清晰。
5. searchContent 空结果重建后, 仅当 _pass_guard 真正放行时才再搜一次。

v7 相较 v6 的改动（融合的华动滑块验证自动过盾）:
1. 站点被华动盾拦截(403 + 滑动验证页 / huadong_296d626f_*.js)时, 自动执行三步过盾:
     a) GET 首页 -> 取 key(同时自动获得 server_name_session 等会话 Cookie)
     b) GET /huadong_296d626f_{key}.js 加载滑块 JS(模拟浏览器页面行为, 必须携带会话 Cookie)
     c) GET yanzheng 接口(key + 签名) -> 200 即放行, 服务端下发 32hex 放行 Cookie
   纯 Python 即可, 无需浏览器/鼠标轨迹。
2. 过盾机制提取自 但做了「站点自适应」:
   - yanzheng 接口路径 / type / value 为站点相关常量, 默认取 TVB 同款作兜底;
   - 第 b 步加载滑块 JS 时, 会尝试从 JS 内自动抽取 yanzheng URL/type/value
     (若 JS 内联构造该 URL 即可自适配, 不必硬编码猜常量);
   - 也可用 extend 参数硬覆盖: huadong_yz=/xxx_yanzheng_huadong.php; huadong_type=...; huadong_value=...
3. 所有网络请求统一走 _request(), 命中滑块自动过盾后重放(首页/分类/搜索/详情/播放全覆盖)。
4. 保留 v6 的 Session TTL / 频率限制(10秒)自动重建 / 搜索空结果重建等容错。
"""

import json
import re
import sys
import os
import time
import threading
from urllib.parse import quote, unquote

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def __init__(self, query_params=None, t4_api=None):
            self.query_params = query_params or {}
            self.t4_api = t4_api or ''
            self.extend = ''
            self.ENV = 'T3'
            self._cache = {}

        def fetch(self, url, params=None, headers=None, cookies=None, timeout=8, **kwargs):
            import requests
            return requests.get(url, params=params, headers=headers,
                                cookies=cookies, timeout=timeout, verify=False)


class Spider(BaseSpider):
    SITE_URL = "https://www.qisheng1688.com"

    CATEGORY_MAP = {
        "最近更新": "new",
        "电影":    "077770",
        "连续剧":  "N77770",
        "综艺":    "Q77770",
        "动漫":    "W77770",
        "短剧":    "q77770",
    }

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 12; Pixel 5) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": SITE_URL + "/",
    }

    _SEARCH_CACHE_TTL      = 300   # 搜索结果缓存 5 分钟
    _SEARCH_CACHE_MAX      = 200   # 缓存条数上限
    _SESSION_FAIL_COOLDOWN = 15    # Session 初始化失败后的冷却秒数
    _SESSION_TTL           = 900   # Session 有效期 15 分钟，过期自动重建

    _NORMALIZE_SOURCE_NAMES = [
        "抖音云", "豆瓣云", "新浪云", "量子云", "非凡云", "天空云", "快看云",
    ]

    # ==================== 华动滑块验证常量(融合自, 站点相关, 可覆盖) ====================
    # key 从滑块页动态抽取(通用); 以下 yanzheng 接口参数为站点相关常量:
    #   _YZ_URL   : yanzheng 接口路径(默认取 TVB 同款兜底, 运行时优先用 JS 自动抽取值)
    #   _YZ_TYPE  : type 参数
    #   _VALUE_MD5: value 签名 = MD5(stringtoHex(固定常量)), 直接用预计算值
    # 若珊瑚影视华动部署不同, 在 init 的 extend 里填 huadong_yz=...; huadong_type=...; huadong_value=...
    _GUARD_JS_KEY_RE = r'/huadong_296d626f_([a-f0-9]{32})\.js'
    _YZ_URL     = '/a20be899_96a6_40b2_88ba_32f1f75f1552_yanzheng_huadong.php'  # TVB 同款默认
    _YZ_TYPE    = 'ad82060c2e67cc7e2cc47552a4fc1242'
    _VALUE_MD5  = '0fbbd1286220f2d0de5502dd031d04cc'

    # ==================== 初始化 ====================

    def init(self, extend=""):
        self.extend = extend or ""
        # extend 兜底/覆盖: huadong_yz=...; huadong_type=...; huadong_value=...
        self._apply_huadong_extend(self.extend)
        self._session = None
        self._session_ts = 0.0
        self._session_lock = threading.Lock()
        self._session_ready = threading.Event()
        self._session_fail_ts = 0.0
        self._search_cache = {}
        threading.Thread(target=self._warmup_async, daemon=True).start()
        return {"status": 0}

    def _apply_huadong_extend(self, extend):
        """extend 覆盖华动 yanzheng 参数: huadong_yz / huadong_type / huadong_value"""
        if not extend:
            return
        for k, v in re.findall(r'huadong_(\w+)=([^;]+)', extend):
            v = v.strip()
            if k == 'yz' and v:
                self._YZ_URL = v
            elif k == 'type' and v:
                self._YZ_TYPE = v
            elif k == 'value' and v:
                self._VALUE_MD5 = v

    def _warmup_async(self):
        try:
            self._ensure_session()
        except Exception as e:
            print(f"[珊瑚] async warmup: {e}")
        finally:
            self._session_ready.set()

    def getName(self):
        return "🐠珊瑚影视"

    # ==================== 首页分类 ====================

    def homeContent(self, filter):
        classes = [{"type_id": t, "type_name": n}
                   for n, t in self.CATEGORY_MAP.items()]
        filters = {}
        if filter:
            for n, t in self.CATEGORY_MAP.items():
                if t == "new":
                    continue
                filters[t] = self._build_filters(n)
        return {"class": classes, "filters": filters}

    def _build_filters(self, name):
        areas = [("全部", ""), ("大陆", "大陆"), ("香港", "香港"), ("台湾", "台湾"),
                 ("美国", "美国"), ("韩国", "韩国"), ("日本", "日本"),
                 ("泰国", "泰国"), ("英国", "英国"), ("法国", "法国"),
                 ("德国", "德国"), ("印度", "印度"), ("加拿大", "加拿大")]

        classes = [
            ("全部", ""),
            ("喜剧", "喜剧"), ("爱情", "爱情"), ("恐怖", "恐怖"), ("动作", "动作"),
            ("科幻", "科幻"), ("剧情", "剧情"), ("战争", "战争"), ("警匪", "警匪"),
            ("犯罪", "犯罪"), ("动画", "动画"), ("奇幻", "奇幻"), ("武侠", "武侠"),
            ("冒险", "冒险"), ("枪战", "枪战"), ("悬疑", "悬疑"), ("惊悚", "惊悚"),
            ("经典", "经典"), ("青春", "青春"), ("文艺", "文艺"), ("微电影", "微电影"),
            ("古装", "古装"), ("历史", "历史"), ("运动", "运动"), ("农村", "农村"),
            ("儿童", "儿童"), ("网络电影", "网络电影"),
        ]

        years = [("全部", "")] + [(str(y), str(y)) for y in range(2026, 2009, -1)]

        return [
            {"key": "class", "name": "类型",
             "value": [{"n": n, "v": v} for n, v in classes]},
            {"key": "area", "name": "地区",
             "value": [{"n": n, "v": v} for n, v in areas]},
            {"key": "year", "name": "年份",
             "value": [{"n": n, "v": v} for n, v in years]},
        ]

    def homeVideoContent(self):
        try:
            rsp = self._request("GET", self.SITE_URL + "/", headers=self.HEADERS)
            if rsp is None:
                return {"list": []}
            rsp.encoding = "utf-8"
            return {"list": self._parse_video_list(rsp.text)}
        except Exception as e:
            print(f"[珊瑚] homeVideoContent: {e}")
            return {"list": []}

    # ==================== 分类内容 ====================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1

            if tid == "new":
                if pg > 1:
                    return {"list": [], "page": pg, "pagecount": 1,
                            "limit": 20, "total": 0}
                rsp = self._request("GET", self.SITE_URL + "/", headers=self.HEADERS)
                if rsp is None:
                    return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
                rsp.encoding = "utf-8"
                videos = self._parse_video_list(rsp.text)
                print(f"[珊瑚] category=new got {len(videos)}")
                return {"list": videos, "page": 1, "pagecount": 1,
                        "limit": 20, "total": len(videos)}

            url = self._build_category_url(tid, pg, extend)
            print(f"[珊瑚] categoryContent url: {url}")
            rsp = self._request("GET", url, headers=self.HEADERS)
            if rsp is None:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            rsp.encoding = "utf-8"
            html = rsp.text
        except Exception as e:
            print(f"[珊瑚] categoryContent: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

        videos = self._parse_video_list(html)
        pagecount = self._parse_pagecount(html, pg)
        print(f"[珊瑚] categoryContent got {len(videos)}, pagecount={pagecount}")
        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": pagecount * 20,
        }

    def _build_category_url(self, tid, pg, extend):
        area = cls = year = ""
        if extend and isinstance(extend, dict):
            area = (extend.get("area") or "").strip()
            cls = (extend.get("class") or "").strip()
            year = (extend.get("year") or "").strip()

        if not area and not cls and not year:
            if pg > 1:
                return f"{self.SITE_URL}/vodtype/{tid}-{pg}.html"
            return f"{self.SITE_URL}/vodtype/{tid}.html"

        enc_area = quote(area, safe="") if area else ""
        enc_cls = quote(cls, safe="") if cls else ""
        base = f"{self.SITE_URL}/vodshow/{tid}-{enc_area}--{enc_cls}--------{year}"
        if pg > 1:
            return f"{base}-{pg}.html"
        return f"{base}.html"

    # ==================== 华动滑块验证(融合自) ====================

    def _is_slide_verify(self, html):
        if not html:
            return False
        head = html[:800]
        return ("滑动验证" in head) or ("slideBox" in html and "huadong_" in html)

    def _blocked(self, resp):
        """是否被华动盾拦截(403 + 滑块页标记 / 滑动验证字样)。

        注意: resp.text 在部分响应(编码异常/未正确解压)下会抛异常,
        这里用 try 包裹并只读取一次, 避免误触发过盾。
        """
        if resp is None:
            return False
        try:
            head = resp.content[:800]
        except Exception:
            return False
        if b'huadong_296d626f' in head:
            return True
        try:
            txt = resp.text[:800]
        except Exception:
            return False
        return ('滑动验证' in txt) or ('slideBox' in txt and 'huadong_' in txt)

    def _ajax_headers(self):
        """yanzheng 接口需要的类 AJAX 请求头(带 Origin / X-Requested-With)"""
        h = dict(self.HEADERS)
        h.update({
            'Accept': '*/*',
            'Origin': self.SITE_URL,
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Priority': 'u=1, i',
        })
        return h

    @staticmethod
    def _extract_yz_from_js(js_text):
        """从华动滑块 JS 内抽取 yanzheng 接口路径/type/value(站点自适应)。
        命中内联构造的 URL(含字符串拼接 "+k+")时返回 (yz_url, type, value_md5)，
        仅暴露路径时返回 (yz_url, None, None)，否则 None。"""
        if not js_text:
            return None
        # 主: 内联(可能经字符串拼接)构造的 yanzheng URL
        #     key 占位可能是明文或 "+k+"，用 [^&]*? 兼容(不含下一个 &)
        m = re.search(
            r'([^"\'?\s]*yanzheng_huadong\.php)\?type=([a-f0-9]{32})'
            r'&key=([^&]*?)&value=([a-f0-9]{32})', js_text)
        if m:
            return (m.group(1), m.group(2), m.group(4))
        # 退化: 仅暴露 yanzheng 路径, type/value 在附近另行赋值
        m = re.search(r'([^"\'?\s]*yanzheng_huadong\.php)', js_text)
        if m:
            yz_url = m.group(1)
            win = js_text[m.start():m.start() + 600]
            mt = re.search(r'\btype\s*[=:]\s*["\']?([a-f0-9]{32})', win)
            mv = re.search(r'\bvalue\s*[=:]\s*["\']?([a-f0-9]{32})', win)
            return (yz_url, mt.group(1) if mt else None,
                    mv.group(1) if mv else None)
        return None

    def _raw(self, method, url, headers=None, data=None, params=None, tries=3):
        """底层请求: 复用会话 + 有限重试(5xx/断连)。"""
        s = self._session
        if s is None:
            s = self._ensure_session(force=True)
        if s is None:
            return None
        last = None
        for i in range(tries):
            try:
                if method == 'POST':
                    r = s.post(url, headers=headers or self.HEADERS,
                               data=data, params=params, timeout=15, verify=False)
                else:
                    r = s.get(url, headers=headers or self.HEADERS,
                              params=params, timeout=15, verify=False)
                if r.status_code < 500:
                    return r
                last = Exception('HTTP %d' % r.status_code)
            except Exception as e:
                last = e
            time.sleep(0.8 + i * 0.6)
        print('[珊瑚] 请求失败:', url, str(last)[:80])
        return None

    def _request(self, method, url, headers=None, data=None, params=None):
        """带盾检测请求: 被拦截自动过盾后重放。"""
        if self._session is None:
            if self._ensure_session(force=True) is None:
                return None
        r = self._raw(method, url, headers, data, params=params)
        if r is not None and self._blocked(r):
            if self._pass_guard():
                r = self._raw(method, url, headers, data, params=params)
        return r

    def _pass_guard(self):
        """过盾(纯 Python 三步, 提取自):
           1. GET 首页 -> 滑块页, 取 key(会话自动获得 server_name_session cookie)
           2. GET /huadong_296d626f_{key}.js 加载滑块 JS(必须, 携 cookie; 顺便抽 yanzheng 参数)
           3. GET yanzheng 接口(key+签名) -> 200 即放行
           # 关键: 跳过第 2 步直接提交会被 403; 请求头需完整浏览器特征(见 HEADERS)
        """
        s = self._session or self._ensure_session(force=True)
        if s is None:
            return False
        for attempt in range(3):
            try:
                r = self._raw('GET', self.SITE_URL + '/')
                if r is None:
                    time.sleep(1)
                    continue
                if not self._blocked(r):
                    return True  # 已处于放行状态
                m = re.search(self._GUARD_JS_KEY_RE, r.text)
                if not m:
                    print('[珊瑚][guard] 滑块页未取到 key')
                    time.sleep(1)
                    continue
                key = m.group(1)
                # 第 2 步: 加载滑块 JS(必须, 携 cookie)
                js = self._raw('GET', '%s/huadong_296d626f_%s.js'
                               % (self.SITE_URL, key), headers=self.HEADERS)
                if js is None or js.status_code != 200:
                    print('[珊瑚][guard] 滑块 JS 未加载(key=%s...), 重试' % key[:8])
                    time.sleep(1)
                    continue
                # 站点自适应: 优先用 JS 内抽出的 yanzheng 参数, 兜底用类常量
                yz_url, yz_type, value = self._YZ_URL, self._YZ_TYPE, self._VALUE_MD5
                ex = self._extract_yz_from_js(js.text)
                if ex:
                    if ex[0]:
                        yz_url = ex[0]
                    if ex[1]:
                        yz_type = ex[1]
                    if ex[2]:
                        value = ex[2]
                # 第 3 步: 提交签名
                yz = '%s%s?type=%s&key=%s&value=%s' % (
                    self.SITE_URL, yz_url, yz_type, key, value)
                r2 = self._raw('GET', yz, headers=self._ajax_headers())
                if r2 is not None and r2.status_code == 200 and len(r2.content) < 800:
                    # 验证接口接受(非滑块页) -> 重访首页确认放行
                    r3 = self._raw('GET', self.SITE_URL + '/')
                    if r3 is not None and not self._blocked(r3):
                        return True
                print('[珊瑚][guard] 验证未通过(key=%s...), 换会话重试' % key[:8])
                self._reset_session()
                if self._ensure_session(force=True) is None:
                    return False
                time.sleep(1)
            except Exception as e:
                print('[珊瑚][guard] 异常:', str(e)[:80])
                time.sleep(1)
        return False

    # ==================== Session 管理 ====================

    def _ensure_session(self, force=False):
        """线程安全的 Session 懒加载。

        - 成功：缓存 Session 对象 + 时间戳，后续复用。
        - 失败：记时间戳 + 返回 None，冷却期内不再重复尝试（force=True 跳过冷却）。
        - TTL：超过 _SESSION_TTL 自动重建，避免 Cookie 老化失效。
        - 预热：首页/搜索页尽量建立会话并下发 Cookie；命中滑块也不在此硬失败，
          交由 _request / _pass_guard 自动过盾(滑块页本身会下发 server_name_session)。
        """
        with self._session_lock:
            # TTL 判断放在锁内, 避免多线程相互覆盖/竞态
            if self._session is not None:
                if time.time() - self._session_ts < self._SESSION_TTL:
                    return self._session
                print("[珊瑚] session expired, rebuilding")
                self._session = None

            if not force and (time.time() - self._session_fail_ts
                              < self._SESSION_FAIL_COOLDOWN):
                return None

            try:
                import requests
                s = requests.Session()
                s.headers.update(self.HEADERS)

                # 1) 首页：尽量建立会话(命中滑块也接受, 滑块页会下发 Cookie)
                for attempt in range(2):
                    try:
                        r = s.get(self.SITE_URL + "/", timeout=5, verify=False)
                        if r.status_code == 200 and not self._is_slide_verify(r.text):
                            break
                        print(f"[珊瑚] warmup home attempt {attempt + 1}: "
                              f"status={r.status_code} verify={self._is_slide_verify(r.text)}")
                    except Exception as e:
                        print(f"[珊瑚] warmup home attempt {attempt + 1}: {e}")

                # 2) 搜索页：触发站点发放搜索相关 Cookie
                try:
                    s.get(self.SITE_URL + "/search.html",
                          params={"wd": "a"}, timeout=5, verify=False)
                except Exception as e:
                    print(f"[珊瑚] warmup search: {e}")

                self._session = s
                self._session_ts = time.time()
                print("[珊瑚] session ready")
                return s
            except Exception as e:
                print(f"[珊瑚] session init: {e}")
                self._session_fail_ts = time.time()
                return None

    def _reset_session(self):
        """销毁当前 Session（下次 _ensure_session 会重建）。"""
        with self._session_lock:
            self._session = None
            self._session_ts = 0.0

    def _gc_search_cache(self):
        now = time.time()
        dead = [k for k, (ts, _) in self._search_cache.items()
                if now - ts >= self._SEARCH_CACHE_TTL]
        for k in dead:
            self._search_cache.pop(k, None)
        if dead:
            print(f"[珊瑚] search cache gc: -{len(dead)}")

    def searchContent(self, key, quick, pg=1):
        """搜索：直接走 page（站点 suggest 无效）。
        首次空结果时自动重建 Session / 过盾 再搜一次，等价于"用户刷新"。
        """
        key = (key or "").strip()
        if not key:
            return {"list": []}
        pg = int(pg) if pg else 1

        # 1) 缓存（只缓存非空）
        cache_key = f"{key}@{pg}"
        cached = self._search_cache.get(cache_key)
        if cached:
            ts, data = cached
            if time.time() - ts < self._SEARCH_CACHE_TTL:
                print(f"[珊瑚] search cache hit: {key}")
                return {"list": data}

        if len(self._search_cache) >= self._SEARCH_CACHE_MAX:
            self._gc_search_cache()

        # 2) 等异步预热完成，最多 3 秒
        ready = getattr(self, "_session_ready", None)
        if ready is not None and not ready.is_set():
            ready.wait(timeout=3)

        # 3) 确保 Session 就绪（force=True：搜索是关键路径，跳过冷却）
        if not self._ensure_session(force=True):
            print(f"[珊瑚] search: session unavailable for {key}")
            return {"list": []}

        # 4) 第一次搜索
        videos = self._search_via_page(key, pg)

        # 5) 空结果：销毁 Session 重建(含过盾) 再搜一次（关键修复）
        #    仅当 _pass_guard 真正放行时才重搜, 避免在盾未解时白跑一遍。
        if not videos:
            print(f"[珊瑚] search empty, rebuilding session & retrying for {key}")
            self._reset_session()
            if self._ensure_session(force=True):
                time.sleep(0.2)
                if not self._pass_guard():
                    print(f"[珊瑚] search rebuild failed to pass guard for {key}")
                    return {"list": []}
                videos = self._search_via_page(key, pg)

        # 6) 只缓存非空结果
        if videos:
            self._search_cache[cache_key] = (time.time(), videos)
            print(f"[珊瑚] search got {len(videos)} for {key}")
        else:
            print(f"[珊瑚] search empty for {key}")
        return {"list": videos}

    def _search_via_page(self, key, pg):
        """Session 复用，超时 3 秒。命中滑块自动过盾，force=True 保证不被冷却卡住。"""
        sess = self._ensure_session(force=True)
        if not sess:
            return []
        url = self.SITE_URL + "/search.html"
        params = {"wd": key}
        if pg > 1:
            params["page"] = pg
        headers = {
            "Referer": self.SITE_URL + "/",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, */*; q=0.01",
        }
        try:
            rsp = self._request("GET", url, headers=headers, params=params)
            if rsp is None:
                return []
            rsp.encoding = "utf-8"
            html = rsp.text or ""
            if self._is_slide_verify(html):
                print("[珊瑚] search page hit slide verify, retry after guard")
                if self._pass_guard():
                    rsp = self._request("GET", url, headers=headers, params=params)
                    if rsp is None:
                        return []
                    rsp.encoding = "utf-8"
                    html = rsp.text or ""
            return self._parse_video_list(html)
        except Exception as e:
            print(f"[珊瑚] search page: {e}")
            return []

    # ==================== 详情 ====================

    def detailContent(self, ids):
        vod_id = ids[0] if isinstance(ids, list) else ids
        if isinstance(vod_id, str) and vod_id.startswith("http"):
            url = vod_id
        else:
            url = f"{self.SITE_URL}/shvod/{vod_id}.html"

        try:
            rsp = self._request("GET", url, headers=self.HEADERS)
            if rsp is None:
                return {"list": []}
            rsp.encoding = "utf-8"
            return self._parse_detail(rsp.text, vod_id)
        except Exception as e:
            print(f"[珊瑚] detailContent: {e}")
            return {"list": []}

    def _parse_detail(self, html, vod_id):
        d = {
            "vod_id": str(vod_id), "vod_name": "", "vod_pic": "",
            "vod_content": "", "vod_actor": "", "vod_director": "",
            "vod_year": "", "vod_area": "", "vod_remarks": "",
            "vod_play_from": "", "vod_play_url": "",
        }

        m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h1>', html)
        if m:
            d["vod_name"] = m.group(1).strip()

        m = re.search(
            r'<div[^>]*class="[^"]*stui-content__thumb[^"]*"[^>]*>(.*?)</div>',
            html, re.S)
        if m:
            mm = re.search(r'(?:data-original|src)="([^"]+)"', m.group(1))
            if mm:
                d["vod_pic"] = mm.group(1).strip()

        m = re.search(r'<span[^>]*>状态：</span>([^<]+)', html)
        if m:
            d["vod_remarks"] = m.group(1).strip()

        m = re.search(r'年份：</span><a[^>]*>(\d+)</a>', html)
        if m:
            d["vod_year"] = m.group(1)

        m = re.search(r'地区：</span><a[^>]*>([^<]+)</a>', html)
        if m:
            d["vod_area"] = m.group(1).strip()

        m = re.search(r'<span>主演：</span>(.*?)</p>', html, re.S)
        if m:
            actors = re.findall(r'>([^<]+)</a>', m.group(1))
            d["vod_actor"] = ", ".join(a.strip() for a in actors if a.strip())

        m = re.search(r'<span>导演：</span>(.*?)</p>', html, re.S)
        if m:
            directors = re.findall(r'>([^<]+)</a>', m.group(1))
            d["vod_director"] = ", ".join(x.strip() for x in directors if x.strip())

        m = re.search(
            r'<div[^>]*class="[^"]*stui-content__desc[^"]*"[^>]*>(.*?)</div>',
            html, re.S)
        if m:
            d["vod_content"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        pf, pu = self._parse_playlist(html)
        d["vod_play_from"] = pf
        d["vod_play_url"] = pu

        ep_count = len(pu.split("$$$")[0].split("#")) if pu else 0
        print(f"[珊瑚] detail name={d['vod_name']!r} from={pf!r} ep={ep_count}")
        return {"list": [d]}

    def _parse_playlist(self, html):
        """源间 $$$ / 源内 # / 每集 "名称$链接"。
        全部默认名时按位置整体替换，混用正式名时保留原状只补空。
        """
        tabs = re.findall(r'data-tab="(playlist-\d+)"[^>]*>([^<]+)<span', html)

        parts = re.split(r'<div[^>]*\bid="(playlist-\d+)"[^>]*>', html)
        eps_by_id = {}
        for i in range(1, len(parts), 2):
            pid = parts[i]
            content = parts[i + 1] if i + 1 < len(parts) else ""
            eps = re.findall(
                r'<a href="(/shplay/[^"]+)"[^>]*title="([^"]*)"[^>]*>([^<]+)</a>',
                content)
            if eps:
                eps_by_id[pid] = list(reversed(eps))

        if not eps_by_id:
            eps = re.findall(r'<a href="(/shplay/[^"]+)"[^>]*>([^<]+)</a>', html)
            if not eps:
                return "", ""
            eps = list(reversed(eps))
            return "抖音云", "#".join(f"{n}${h}" for h, n in eps)

        raw_names, urls = [], []
        for pid, name in tabs:
            if pid in eps_by_id:
                raw_names.append(name.strip())
                urls.append("#".join(f"{t}${h}" for h, _, t in eps_by_id[pid]))

        if not raw_names:
            for pid in eps_by_id.keys():
                raw_names.append("")
                urls.append("#".join(f"{t}${h}" for h, _, t in eps_by_id[pid]))

        def is_default_name(s):
            if not s:
                return True
            if re.fullmatch(r'线路\d+', s):
                return True
            if re.fullmatch(r'源\d+', s):
                return True
            return False

        if all(is_default_name(n) for n in raw_names):
            final_names = [
                self._NORMALIZE_SOURCE_NAMES[i]
                if i < len(self._NORMALIZE_SOURCE_NAMES) else f"源{i + 1}"
                for i in range(len(raw_names))
            ]
        else:
            final_names = [n if n else f"源{i + 1}"
                           for i, n in enumerate(raw_names)]

        return "$$$".join(final_names), "$$$".join(urls)

    # ==================== 播放 ====================

    def playerContent(self, flag, vid, vip_flags=None):
        _ = (flag, vip_flags)
        play_header = json.dumps({
            "User-Agent": self.HEADERS["User-Agent"],
            "Referer": self.SITE_URL + "/",
        })

        if isinstance(vid, str) and vid.startswith("/"):
            url = self.SITE_URL + vid
        elif isinstance(vid, str) and vid.startswith("http"):
            url = vid
        else:
            url = f"{self.SITE_URL}/shplay/{vid}.html"

        try:
            rsp = self._request("GET", url, headers=self.HEADERS)
            if rsp is None:
                return {"parse": 1, "playUrl": "", "url": url, "header": play_header}
            rsp.encoding = "utf-8"
            media = self._extract_player_url(rsp.text)
            if media:
                print(f"[珊瑚] media: {media}")
                return {"parse": 0, "playUrl": "",
                        "url": media, "header": play_header}

            m = re.search(r'<iframe[^>]+src="(https?://[^"]+)"', rsp.text)
            if m:
                return {"parse": 1, "playUrl": "",
                        "url": m.group(1), "header": play_header}
        except Exception as e:
            print(f"[珊瑚] playerContent: {e}")

        return {"parse": 1, "playUrl": "", "url": url, "header": play_header}

    def _extract_player_url(self, html):
        m = re.search(r'\bplayer_aaaa\s*=\s*(\{)', html)
        if not m:
            return ""
        brace = m.start(1)

        depth, in_str, esc, end = 0, False, False, -1
        for i in range(brace, len(html)):
            c = html[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        if end < 0:
            return ""

        raw = html[brace:end]
        try:
            data = json.loads(raw)
            for key in ("url", "url_next", "link"):
                u = (data.get(key) or "").strip()
                if not u:
                    continue
                u = u.replace("\\/", "/")
                if "%3A%2F%2F" in u.upper():
                    try:
                        u = unquote(u)
                    except Exception:
                        pass
                if u.startswith("/"):
                    u = self.SITE_URL + u
                if key == "link" and not (".m3u8" in u or ".mp4" in u):
                    continue
                return u
        except Exception as e:
            print(f"[珊瑚] player_aaaa json: {e}")

        for pat in (
            r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'"url_next"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'"url"\s*:\s*"([^"]+\.mp4[^"]*)"',
            r'"url_next"\s*:\s*"([^"]+\.mp4[^"]*)"',
        ):
            m = re.search(pat, raw)
            if m:
                u = m.group(1).replace("\\/", "/")
                if "%3A%2F%2F" in u.upper():
                    try:
                        u = unquote(u)
                    except Exception:
                        pass
                return u
        return ""

    # ==================== 列表解析 ====================

    def _parse_video_list(self, html):
        videos, seen = [], set()
        chunks = re.split(
            r'<li[^>]+class="[^"]*stui-vodlist__item[^"]*"[^>]*>', html)
        for chunk in chunks[1:]:
            end = chunk.find("</li>")
            card = chunk[:end] if end > 0 else chunk[:3000]

            m = re.search(r'href="/shvod/(\d+)\.html"', card)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue

            title_m = re.search(r'title="([^"]*)"', card)

            img_m = (re.search(r'data-original="([^"]+)"', card)
                     or re.search(r'data-src="([^"]+)"', card)
                     or re.search(r'(?<![-\w])src="([^"]+)"', card))
            pic = img_m.group(1).strip() if img_m else ""
            if pic.startswith("data:"):
                pic = ""

            role_m = re.search(
                r'<span[^>]*class="[^"]*pic-text[^"]*"[^>]*>([^<]*)</span>', card)

            seen.add(vid)
            videos.append({
                "vod_id": vid,
                "vod_name": title_m.group(1).strip() if title_m else "",
                "vod_pic": pic,
                "vod_remarks": role_m.group(1).strip() if role_m else "",
            })
        return videos

    def _parse_pagecount(self, html, current_pg):
        m = re.search(r'<span[^>]*class="[^"]*num[^"]*"[^>]*>\d+/(\d+)</span>', html)
        if m:
            return int(m.group(1))
        m = re.search(r'/(\d+)\.html">尾页</a>', html)
        if m:
            return int(m.group(1))
        pages = re.findall(r'/vodtype/[A-Za-z0-9]+-(\d+)\.html', html)
        if pages:
            return max(int(p) for p in pages)
        return int(current_pg) + 1


def main():
    pass


if __name__ == "__main__":
    main()