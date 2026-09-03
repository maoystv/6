# -*- coding: utf-8 -*-
# 云朵影视 TVBox spider — RN/Hermes 协议(签名重放模式)
# 依赖用户提供的 x-time/x-nonc/x-sign 三元组(有效期>1.5小时)
import json
import random
import time
import urllib.request
import urllib.parse
import ssl

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

# 签名三元组(由外部配置/手动更新 — 有效期长):
# 永久签名(算法自TV版APK逆向, 4/4样本验证):
FINGER = 'SF-F5F11CB15897115AE6BCFE063C288F730CA865588F572C780A3E8477D0DD3776'
SK = 'SK-sk_13oXDZ7u9j2Tk1c0cawWVFfO'
DEVICE_UUID = 'uuid-a43a3421-2704-4deb-afe4-136aed229307'
USER_TOKEN = 'ZThkNjRlYzhlNmZmNzZkMDI1ZDhhMTVhNzA2YjFlN2YxYjQwMTA5NzBkZThiN2NlZTk0ZGYzOWU2MmQ5NzQ3Y3wxMzI5NnxmemNyeW18MTc4ODM1ODE1Ng=='

HOST = 'http://154.21.198.181:8081'
UA = 'okhttp/4.12.0'


class Spider(_Base):
    _ctx = ssl._create_unverified_context()

    def init(self, ext=''):
        # ext 格式: time|nonc|sign 或完整json(可选)
        global SIGN_TIME, SIGN_NONC, SIGN_SIGN
        try:
            if ext and '|' in ext:
                t, n, s = ext.split('|', 2)
                if t.isdigit() and len(s) >= 32:
                    SIGN_TIME, SIGN_NONC, SIGN_SIGN = t.strip(), n.strip(), s.strip()
        except Exception:
            pass

    def getName(self):
        return '云朵影视'

    def _hdr(self):
        import hashlib as _h
        t = str(int(time.time() * 1000))
        nonce = _h.sha256(DEVICE_UUID.encode()).hexdigest().upper()[:8] + \
            ''.join(str(random.randint(0, 9)) for _ in range(8))
        sign = _h.sha256((
            'finger=' + FINGER + '&id=com.tvcloud.io&nonce=' + nonce +
            '&sk=' + SK + '&time=' + t + '&v=4').encode()).hexdigest().upper()
        return {'User-Agent': 'okhttp/4.12.0', 'accept': 'application/json',
                'x-aid': 'com.tvcloud.io', 'x-ave': '4',
                'x-time': t, 'x-nonc': nonce, 'x-sign': sign,
                'x-device-id': DEVICE_UUID, 'x-device-brand': 'realtek',
                'x-device-model': 'ZIDOO_X9S', 'x-client-type': 'tv',
                'x-update-id': 'embedded',
                'x-user-token': USER_TOKEN}

    def _get(self, path):
        req = urllib.request.Request(HOST + path, headers=self._hdr())
        d = urllib.request.urlopen(req, timeout=20, context=self._ctx).read()
        return json.loads(d)

    def homeContent(self, filter):
        j = self._get('/api.php/app/index/home')
        d = j.get('data', {})
        cats = [{'type_id': 're', 'type_name': '推荐'}]
        for c in d.get('categories', []):
            cats.append({'type_id': str(c.get('type_id')),
                         'type_name': c.get('type_name')})
        cats.append({'type_id': 'his', 'type_name': '历史'})
        self._home_data = d
        return {'class': cats}

    def _fetch_history(self):
        try:
            hdr = self._hdr()
            hdr['Content-Type'] = 'application/json; charset=UTF-8'
            body = json.dumps({'token': USER_TOKEN}).encode()
            req = urllib.request.Request(HOST + '/api.php/app/account/fetch',
                                         data=body, headers=hdr, method='POST')
            j = json.loads(urllib.request.urlopen(req, timeout=15).read())
            hist = (j.get('data') or {}).get('history')
            if not hist:
                return []
            hl = json.loads(hist) if isinstance(hist, str) else hist
            out = []
            for h in hl:
                out.append({'vod_id': str(h.get('id')),
                            'vod_name': h.get('title'),
                            'vod_pic': h.get('cover'),
                            'vod_remarks': h.get('vod_remarks', '')})
            return out
        except Exception:
            return []

    _CAT = {'1': '电影', '2': '剧集', '3': '动漫', '4': '综艺'}

    def _guess(self, v):
        c = ' '.join(v.get('vod_class') or [])
        if '电影' in c or '院线' in c:
            return '1'
        if '动漫' in c or ('动画' in c and '电影' not in c):
            return '3'
        if '综艺' in c or '真人秀' in c or '脱口秀' in c or '晚会' in c:
            return '4'
        return '2'

    def categoryContent(self, tid, pg, filter, extend):
        pg = max(1, int(pg or 1))
        if tid == 're':
            # rankings榜单(4分类×20) + recommend 合并去重 ≈ 80条
            j = self._get('/api.php/app/ranking/list')
            merged, seen = [], set()
            for r in (j.get('data') or {}).get('rankings', []):
                for v in r.get('videos', []):
                    vid = str(v.get('vod_id'))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    merged.append({'vod_id': vid,
                                   'vod_name': v.get('vod_name'),
                                   'vod_pic': v.get('vod_pic'),
                                   'vod_remarks': v.get('vod_remarks', '')})
            try:
                j2 = self._get('/api.php/app/index/home')
                for v in (j2.get('data') or {}).get('recommend', []):
                    vid = str(v.get('vod_id'))
                    if vid not in seen:
                        seen.add(vid)
                        merged.append({'vod_id': vid,
                                       'vod_name': v.get('vod_name'),
                                       'vod_pic': v.get('vod_pic'),
                                       'vod_remarks': v.get('vod_remarks', '')})
            except Exception:
                pass
            return {'list': merged, 'page': 1, 'total': len(merged),
                    'pagecount': max(1, -(-len(merged) // 24)),
                    'limit': 24}
        if tid == 'his':
            lst = self._fetch_history()
            return {'list': lst, 'page': 1, 'total': len(lst),
                    'pagecount': 1, 'limit': 24}
        cat = self._CAT.get(str(tid), '电影')
        import urllib.parse as _up
        p = ('/api.php/app/filter/vod?type_name=' + _up.quote(cat) +
             '&page=%d&limit=24&sort=hits' % pg)
        j = self._get(p)
        lst = j.get('data') or []
        out = [{'vod_id': str(v.get('vod_id')),
                'vod_name': v.get('vod_name'),
                'vod_pic': v.get('vod_pic'),
                'vod_remarks': v.get('vod_remarks', '')} for v in lst]
        total = int(j.get('total') or len(out))
        pagecount = int(j.get('pageCount') or max(1, -(-total // 24)))
        return {'list': out, 'page': pg, 'total': total,
                'pagecount': pagecount, 'limit': 24}

    def detailContent(self, ids):
        j = self._get('/api.php/app/vod/get_detail?vod_id=' + ids[0])
        v = (j.get('data') or [{}])[0]
        pf = (v.get('vod_play_from') or '').split('$$$')
        pu = (v.get('vod_play_url') or '').split('$$$')
        lines, urls = [], []
        for i, ln in enumerate(pf):
            if i >= len(pu):
                continue
            lines.append(ln)
            urls.append(pu[i])
        # 清理详情HTML标签(TVBox部分内核渲染<p>失败→空白):
        import re as _re
        _ct = v.get('vod_content', '') or ''
        _ct = _re.sub(r'<[^>]+>', '', _ct).strip()
        return {'list': [{'vod_id': ids[0],
                          'vod_name': v.get('vod_name'),
                          'vod_pic': v.get('vod_pic'),
                          'vod_remarks': v.get('vod_remarks', ''),
                          'vod_year': v.get('vod_year', ''),
                          'vod_area': v.get('vod_area', ''),
                          'vod_actor': v.get('vod_actor', ''),
                          'vod_director': v.get('vod_director', ''),
                          'vod_content': _ct,
                          'vod_play_from': '$$$'.join(lines),
                          'vod_play_url': '$$$'.join(urls)}]}

    def searchContent(self, key, quick, pg=1):
        j = self._get('/api.php/app/search/index?wd=%s&page=%s' % (
            urllib.parse.quote(key), pg or 1))
        d = j.get('data') or {}
        lst = d if isinstance(d, list) else d.get('videos', [])
        out = []
        for v in lst:
            out.append({'vod_id': str(v.get('vod_id')),
                        'vod_name': v.get('vod_name'),
                        'vod_pic': v.get('vod_pic'),
                        'vod_remarks': v.get('vod_remarks', '')})
        return {'list': out, 'page': int(pg or 1)}

    def playerContent(self, flag, id, vipFlags):
        try:
            _t = int(time.time() * 1000)
            p = '/api.php/app/decode/url/?url=%s&vodFrom=%s&_t=%d' % (
                urllib.parse.quote(id), urllib.parse.quote(flag), _t)
            j = self._get(p)
            url = (j.get('data') or '').strip()
            if url.startswith('http'):
                return {'parse': 0, 'playUrl': '', 'url': url,
                        'header': {'User-Agent': UA}}
        except Exception:
            pass
        return {'parse': 0, 'playUrl': '', 'url': '',
                'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        return True

    def isPlayable(self, url):
        return True
