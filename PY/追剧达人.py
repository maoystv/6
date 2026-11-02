# -*- coding: utf-8 -*-
import sys, re, json, base64, time, threading
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import requests

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers or {}, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

APP_HOST = 'http://23.224.111.70:7788'
APP_HDR = {'user-agent': 'Dart/3.13 (dart:io)', 'version': '2.1.6', 'version-number': '2108',
           'pk-id': 'com.okbyrk.zjdr.dre', 'build-time': '1789369676921', 'platform': 'android',
           'platform-version': 'PJZ110_16.0.10.501(CN01)', 'content-type': 'text/plain',
           'accept-encoding': 'gzip'}
UA = 'Mozilla/5.0 (Linux; Android 13; PJZ110 Build/TP1A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'
TYPES = [('2', '剧集'), ('1', '电影'), ('4', '动漫'), ('3', '综艺'), ('27', '纪录'), ('28', '短剧'), ('29', '少儿')]
CAT_T = {'2': '13%2C14%2C15%2C16%2C21%2C22%2C23%2C24', '1': '6%2C7%2C8%2C9%2C10%2C11%2C12%2C45',
         '4': '29%2C30%2C31%2C32%2C33', '3': '25%2C26%2C27%2C28',
         '27': '20', '28': '46', '29': '49'}
S_CAT = 'https://cj.lziapi.com/api.php/provide/vod/at/json/?ac=detail&t=%s&pg=%s'
S_CAT2 = 'https://cj.ffzyapi.com/api.php/provide/vod/at/json/?ac=detail&t=%s&pg=%s'
PARSER = 'http://49.233.180.127:880'
TAG_PARSER = {'k4': PARSER + '/4kys.php?url='}
S_LZ = 'https://cj.lziapi.com/api.php/provide/vod/at/json/?ac=detail&wd='
S_FF = 'https://cj.ffzyapi.com/api.php/provide/vod/at/json/?ac=detail&wd='
S_ZUI = 'https://api.zuidapi.com/api.php/provide/vod/at/json/?ac=detail&wd='
S_JS = 'https://jszyapi.com/api.php/provide/vod/at/json/?ac=detail&wd='
S_HN = 'https://www.hongniuzy2.com/api.php/provide/vod/at/json/?ac=detail&wd='
S_MD = 'https://caiji.moduapi.cc/api.php/provide/vod/at/json/?ac=detail&wd='
S_YZ = 'https://api.yzzyapi.com/api.php/provide/vod/?ac=detail&wd='
S_YZI = 'https://api.yzzyapi.com/api.php/provide/vod/?ac=videolist&ids='
S_K4 = 'https://www.4kvm.top'
LINES = [('追剧1', 'lz', S_LZ), ('专线·飞速', 'ff', S_FF), ('专线·最大', 'zui', S_ZUI),
         ('专线·极速', 'js', S_JS), ('专线·红牛', 'hn', S_HN), ('专线·魔都', 'md', S_MD),
         ('专线·宇宙', 'yz', S_YZ), ('专线·4K', 'k4', S_K4)]
VIDEO_EXTS = 'm3u8|mp4|flv|mkv|avi|ts'
SITE_KEY = 'zhuijudaren'
TO = 10


class Spider(Spider):
    def init(self, extend=''):
        self.base = APP_HOST
        self.ua = UA
        self._c = {}
        self.s = requests.Session()
        self.s.headers.update({'user-agent': UA})
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self):
        for _, _, u in LINES:
            try:
                self.s.get(u + 'x', timeout=8)
            except Exception:
                pass
        for tid, _ in TYPES:
            t = CAT_T.get(tid)
            if t:
                try:
                    self._catlist(S_CAT % (t, 1))
                except Exception:
                    pass

    def _rq(self, url, headers=None, timeout=TO):
        for _ in range(2):
            try:
                return self.s.get(url, headers=headers or None, timeout=timeout)
            except Exception:
                pass
        return None

    def _app(self, path):
        if path in self._c:
            return self._c[path]
        r = self._rq(self.base + path, APP_HDR)
        d = None
        if r is not None and r.status_code == 200:
            try:
                d = r.json()
            except Exception:
                d = None
        self._c[path] = d
        return d

    def _applist(self, pg=1, limit=50):
        j = self._app('/index.php/ajax/data?mid=1&page=%d&limit=%d' % (pg, limit))
        return (j.get('list') or []) if isinstance(j, dict) else []

    def _wid(self, s):
        return 'z' + base64.urlsafe_b64encode((s or '').encode('utf-8')).decode().rstrip('=')

    def _unid(self, s):
        s = re.sub(r'^[zw]', '', str(s or ''))
        try:
            return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', 'ignore')
        except Exception:
            return ''

    def _item(self, name, pic='', remark='', year=''):
        return {'vod_id': self._wid(name), 'vod_name': name or '', 'vod_pic': pic or '',
                'vod_remarks': remark or '', 'vod_year': year or ''}

    def _items(self, lst):
        return [self._item(v.get('vod_name'), v.get('vod_pic'), v.get('vod_remarks'), v.get('vod_year'))
                for v in lst if v.get('vod_name')]

    def homeContent(self, filter=False):
        return {'class': [{'type_id': k, 'type_name': v} for k, v in TYPES],
                'list': self._items(self._applist(1, 20)[:20])}

    def homeVideoContent(self):
        return {'list': self._items(self._applist(1, 20)[:20])}

    def _catfetch(self, url):
        try:
            r = requests.get(url, headers={'user-agent': UA}, timeout=(5, 8))
            if r.status_code != 200:
                return [], 9999
            j = r.json()
            L = j.get('list') or []
            return [self._item(v.get('vod_name'), v.get('vod_pic'), v.get('vod_remarks'), v.get('vod_year'))
                    for v in L if v.get('vod_name')], int(j.get('pagecount') or 9999)
        except Exception:
            return [], 9999

    def _catlist(self, url):
        key = 'c:' + url
        if key in self._c:
            return self._c[key]
        ex = ThreadPoolExecutor(max_workers=1)
        fu = ex.submit(self._catfetch, url)
        try:
            out, pc = fu.result(timeout=12)
        except Exception:
            out, pc = [], 9999
        ex.shutdown(wait=False)
        if out:
            self._c[key] = (out, pc)
        return out, pc

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        pn = max(int(str(pg) or 1), 1)
        t = CAT_T.get(str(tid))
        if not t:
            return {'list': [], 'page': pn, 'pagecount': 9999, 'limit': 20, 'total': 0}
        out, pc = self._catlist(S_CAT % (t, pn))
        if not out:
            alt = '36' if t == '46' else t
            o2, pc2 = self._catlist(S_CAT2 % (alt, pn))
            if o2:
                out, pc = o2, pc2
        return {'list': out, 'page': pn, 'pagecount': pc, 'limit': 20, 'total': 999999}

    def searchContent(self, key, quick=False, pg='1'):
        out = []
        j = self._app('/index.php/ajax/suggest?mid=1&wd=' + quote(key or ''))
        for v in ((j or {}).get('list') or []):
            out.append(self._item(v.get('name'), v.get('pic')))
        if not out:
            for v in self._applist(1, 50):
                if key and key in (v.get('vod_name') or ''):
                    out.append(self._item(v.get('vod_name'), v.get('vod_pic'), v.get('vod_remarks'), v.get('vod_year')))
        return {'list': out}

    def _pic(self, name):
        r = self._rq(S_LZ + quote(name), None, TO)
        if r is None or r.status_code != 200:
            return ''
        try:
            for v in (r.json().get('list') or []):
                if self._match(name, v.get('vod_name')) and v.get('vod_pic'):
                    return v.get('vod_pic')
        except Exception:
            pass
        return ''

    def _pick(self, groups):
        for g in groups:
            if 'm3u8' in g and '/share/' not in g:
                return g
        for g in groups:
            if 'm3u8' in g:
                return g
        for g in groups:
            if '/share/' not in g:
                return g
        return groups[0] if groups else ''

    def _norm(self, s):
        return re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', s or '')

    def _match(self, want, got):
        a, b = self._norm(want), self._norm(got)
        return bool(a and b and (a == b or a in b or b in a))

    def _ep_from_json(self, tag, host_url, want=''):
        r = self._rq(host_url, None, TO)
        eps = []
        if r is None or r.status_code != 200:
            return eps
        try:
            L = (r.json().get('list') or [])
        except Exception:
            return eps
        for v in L:
            if want and not self._match(want, v.get('vod_name')):
                continue
            pu = v.get('vod_play_url') or ''
            if not pu:
                continue
            pick = self._pick([g for g in pu.split('$$$') if '$' in g])
            if not pick:
                continue
            for seg in pick.split('#'):
                if '$' not in seg:
                    continue
                nm, u = seg.split('$', 1)
                u = u.strip()
                if u.startswith('http') or u.startswith('//'):
                    eps.append((re.sub(r'[#$|]', '', nm).strip() or ('第%d集' % (len(eps) + 1)), '%s|%s' % (tag, u)))
            if eps:
                break
        return eps

    def _ep_yz(self, tag, name):
        r = self._rq(S_YZ + quote(name), None, TO)
        if r is None or r.status_code != 200:
            return []
        ids = []
        for blk in re.findall(r'<video>(.*?)</video>', r.text, re.S):
            mm = re.search(r'<name>(.*?)</name>', blk, re.S)
            nmv = re.sub(r'<!\[CDATA\[|\]\]>', '', mm.group(1)).strip() if mm else ''
            mi = re.search(r'<id>(\d+)</id>', blk)
            if mi and (not name or self._match(name, nmv)):
                ids.append(mi.group(1))
        eps = []
        for vid in ids[:2]:
            r2 = self._rq(S_YZI + vid, None, TO)
            if r2 is None or r2.status_code != 200:
                continue
            grp = [m.group(1) for m in re.finditer(r'<dd flag="[^"]*">(.*?)</dd>', r2.text, re.S)]
            if not grp:
                mu = re.search(r'<play_url>(.*?)</play_url>', r2.text, re.S)
                grp = [mu.group(1)] if mu else []
            pick = self._pick([re.sub(r'<!\[CDATA\[|\]\]>', '', g) for g in grp])
            for seg in pick.split('#'):
                if '$' not in seg:
                    continue
                nm, u = seg.split('$', 1)
                u = re.sub(r'<!\[CDATA\[|\]\]>', '', u).strip()
                if u.startswith('http') or u.startswith('//'):
                    eps.append((re.sub(r'[#$|]', '', nm).strip() or ('第%d集' % (len(eps) + 1)), '%s|%s' % (tag, u)))
            if eps:
                break
        return eps

    def _ep_4kvm(self, name):
        r = self._rq(S_K4 + '/search?q=' + quote(name), None, TO)
        if r is None or r.status_code != 200:
            return []
        hit = ''
        for m in re.finditer(r'href="(/play/[a-z0-9]+)"[^>]*>(.{0,200}?)</a>', r.text, re.S):
            if name and name in re.sub(r'<[^>]+>', '', m.group(2)):
                hit = m.group(1)
                break
        if not hit:
            m = re.search(r'href="(/play/[a-z0-9]+)"', r.text)
            hit = m.group(1) if m else ''
        if not hit:
            return []
        r2 = self._rq(S_K4 + hit, None, TO)
        if r2 is None or r2.status_code != 200:
            return []
        tm = re.search(r'<title>(.*?)</title>', r2.text, re.S)
        if name and tm and not self._match(name, re.sub(r'<[^>]+>', '', tm.group(1))):
            return []
        pre = hit[:7]
        seq = []
        for s2 in re.findall(r'href="(/play/[a-z0-9]+)"', r2.text):
            if s2.startswith(pre) and s2 not in seq:
                seq.append(s2)
        if len(seq) < 2:
            return []
        return [('第%02d集' % i, 'k4|' + S_K4 + s) for i, s in enumerate(seq, 1)]

    def _line_eps(self, nm, tag, src, name):
        try:
            if tag == 'k4':
                return self._ep_4kvm(name)
            if tag == 'yz':
                return self._ep_yz(tag, name)
            url = src + quote(name)
            return self._ep_from_json(tag, url, name)
        except Exception:
            return []

    def detailContent(self, ids, quick='1'):
        vid = str(ids[0] if isinstance(ids, list) else ids or '')
        name = self._unid(vid)
        if not name:
            return {'list': [{'vod_id': vid, 'vod_name': ''}]}
        key = 'd:' + name
        if key in self._c:
            return self._c[key]
        ex = ThreadPoolExecutor(max_workers=8)
        fus = [ex.submit(self._line_eps, nm, tag, src, name) for nm, tag, src in LINES]
        end = time.time() + 12
        got, miss = {}, []
        for i, fu in enumerate(fus):
            try:
                eps = fu.result(timeout=max(0.5, end - time.time()))
            except Exception:
                eps = []
            if eps:
                got[i] = eps
            else:
                miss.append(i)
        for i in miss:
            try:
                eps = fus[i].result(timeout=4)
            except Exception:
                eps = []
            if eps:
                got[i] = eps
        lines = [(LINES[i][0], got[i]) for i in range(len(LINES)) if i in got]
        ex.shutdown(wait=False)
        pic = ''
        j = self._app('/index.php/ajax/suggest?mid=1&wd=' + quote(name))
        for v in ((j or {}).get('list') or []):
            if (v.get('name') or '').strip() == name:
                pic = v.get('pic') or ''
                break
        if not pic:
            pic = self._pic(name)
        d = {'vod_id': vid, 'vod_name': name, 'vod_pic': pic, 'vod_content': name, 'vod_remarks': ''}
        if lines:
            d['vod_play_from'] = '$$$'.join(x[0] for x in lines)
            d['vod_play_url'] = '$$$'.join('#'.join('%s$%s' % (n, u) for n, u in x[1]) for x in lines)
        r = {'list': [d]}
        self._c[key] = r
        return r

    def _via_parser(self, url):
        r = self._rq(PARSER + '/ff.php?url=' + quote(url, safe=''),
                     {'user-agent': 'okhttp/3.12.0', 'accept-encoding': 'gzip'}, 12)
        if r is None:
            return ''
        try:
            j = r.json()
            if str(j.get('code')) == '200' and j.get('url'):
                return j.get('url')
        except Exception:
            pass
        return ''

    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or '')
        tag, _, payload = raw.partition('|')
        real = payload.strip()
        pre = TAG_PARSER.get(tag)
        if pre and real.startswith('http'):
            r = self._rq(pre + quote(real, safe=''), {'user-agent': 'okhttp/3.12.0', 'accept-encoding': 'gzip'}, 12)
            if r is not None:
                try:
                    j = r.json()
                    if str(j.get('code')) == '200' and j.get('url'):
                        real = j.get('url')
                except Exception:
                    m = re.search(r'https?://[^\s"\'<>\\]+\.(?:m3u8|mp4)[^\s"\'<>\\]*', r.text or '')
                    if m:
                        real = m.group(0)
        if real.startswith('//'):
            real = 'https:' + real
        if real.startswith('http') and '49.233.180.127' not in real:
            r = self._rq(real, {'user-agent': UA}, 6)
            if r is None or r.status_code != 200 or len(r.content) < 16:
                alt = self._via_parser(real)
                if alt:
                    real = alt
        return {'parse': 0, 'playUrl': '', 'url': real, 'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        return bool(url) and bool(re.search(r'\.(?:%s)(?:\?|$)' % (VIDEO_EXTS or 'm3u8'), url, re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def destroy(self):
        try:
            self._c.clear()
        except Exception:
            pass

    def progressVideo(self, speed, time, end):
        return False

    def setVideoFlags(self, siteKey, flags):
        return None

    def localProxy(self, param):
        return None