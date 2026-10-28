# coding = utf-8
# !/usr/bin/python
# 新时代青年 2025.06.25 getApp第三版
# 基于原作者修改版本，仅限个人学习爬虫技术，严禁将其用于任何商业用途，下载后请于 24 小时内删除，搜索结果均来自源站，本人不承担任何责任。

from Crypto.Cipher import AES
from base.spider import Spider
from Crypto.Util.Padding import pad,unpad
import re,sys,time,uuid,json,base64,urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.append('..')

class Spider(Spider):
    xurl,key,iv,init_data,search_verify,suggest_search,username,password,device_id,version,get_type,def_headers= '','','','','','','', '', '','', '0',{}

    def init(self, extend=''):
        ext=json.loads(extend.strip())
        api = str(ext.get('api'))
        if api == '2' or api == 'qiji':
            self.get_type = 'qiji'
            api = '/api.php/qijiappapi'
        elif api == 'flutter':
            self.get_type = 'flutter'
            api = '/api.php/getappapi'
        else:
            self.get_type = 'get'
            api = '/api.php/getappapi'
        host = ext['host']
        domain_set = set()
        if not re.match(r'^https?://[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*(:\d+)?(/)?$',host):
            host_data = self.fetch(host, headers=self.get_headers(1), timeout=10, verify=False).text
            domain_set.update([domain.strip() for domain in host_data.split('\n')])
        else:
            domain_set.add(host)
        ua = ext.get('ua')
        if ua: self.def_headers['User-Agent'] = ua
        token = ext.get('token')
        if token:
            self.def_headers['app-user-token'] = token
        else:
            self.username = ext.get('username')
            self.password = ext.get('password')
        self.device_id = ext.get('devideid')
        self.version = str(ext.get('version',''))
        self.key = ext.get('key',ext.get('datakey'))
        if not self.key: return
        self.iv = ext.get('iv',ext.get('dataiv')) or self.key
        if self.device_id:
            self.def_headers['app-user-device-id'] = self.device_id
        for i in domain_set:
            try:
                self.xurl = i + api
                res = self.fetch(self.xurl + '.index/initV119', headers=self.get_headers(), timeout=(5, 5), verify=False).json()
                encrypted_data = res['data']
                response = self.decrypt(encrypted_data)
                init_data = json.loads(response)
            except Exception:
                continue
            if init_data:
                self.init_data = init_data
                self.search_verify = init_data['config'].get('system_search_verify_status', False)
                break

    def homeContent(self, filter):
        kjson = self.init_data
        result = {"class": [], "filters": {}}
        for i in kjson['type_list']:
            if not(i['type_name'] in {'全部', 'QQ', 'juo.one'} or '企鹅群' in i['type_name']):
                result['class'].append({"type_id": i['type_id'], "type_name": i['type_name']})
            name_mapping = {'class': '类型', 'area': '地区', 'lang': '语言', 'year': '年份', 'sort': '排序'}
            filter_items = []
            for filter_type in i.get('filter_type_list', []):
                filter_name = filter_type.get('name')
                values = filter_type.get('list', [])
                if not values: continue
                value_list = [{"n": value, "v": value} for value in values]
                display_name = name_mapping.get(filter_name, filter_name)
                key = 'by' if filter_name == 'sort' else filter_name
                filter_items.append({ "key": key, "name": display_name, "value": value_list})
            type_id = i.get('type_id')
            if filter_items:
                result["filters"][str(type_id)] = filter_items
        return result

    def homeVideoContent(self):
        videos = []
        kjson = self.init_data
        for i in kjson['type_list']:
            videos.extend(self.arr2vods(i['recommend_list']))
        return {'list': videos}

    def categoryContent(self, cid, pg, filter, ext):
        payload = {
            'area': ext.get('area','全部'),
            'year': ext.get('year','全部'),
            'type_id': cid,
            'page': str(pg),
            'sort': ext.get('sort','最新'),
            'lang': ext.get('lang','全部'),
            'class': ext.get('class','全部')
        }
        res = self.post(f'{self.xurl}.index/typeFilterVodList', headers=self.get_headers(), data=payload, verify=False).json()
        encrypted_data = res['data']
        kjson = self.decrypt(encrypted_data)
        kjson1 = json.loads(kjson)
        videos = self.arr2vods(kjson1['recommend_list'])
        return {'list': videos, 'page': pg, 'pagecount': 9999, 'limit': 90, 'total': 999999}

    def searchContent(self, key, quick, pg="1"):
        videos = []
        if self.suggest_search == '1':
            host = self.xurl.split('api.php')[0]
            data = self.fetch(f'{host}index.php/ajax/suggest?mid=1&wd={key}').json()
            for i in data['list']:
                videos.append({
                    "vod_id": i['id'],
                    "vod_name": i['name'],
                    "vod_pic": i.get('pic')
                })
        else:
            payload = {'keywords': key, 'type_id': "0", 'page': str(pg)}
            if self.search_verify:
                verifi = self.verification()
                if verifi is None:
                    return {'list':[]}
                payload['code'] = verifi['code']
                payload['key'] = verifi['uuid']
            res = self.post(f'{self.xurl}.index/searchList', data=payload, headers=self.get_headers(), verify=False).json()
            if not res.get('data'):
                return {'list':[] ,'msg': res.get('msg')}
            encrypted_data = res['data']
            kjson = self.decrypt(encrypted_data)
            kjson1 = json.loads(kjson)
            videos.extend(self.arr2vods(kjson1['search_list']))
        return {'list': videos, 'page': pg}

    def detailContent(self, ids):
        payload = {'vod_id': ids[0]}
        if 'qijiappapi' in self.xurl:
            api_endpoints = ['vodDetail2', 'vodDetail3']
        else:
            api_endpoints = ['vodDetail']
        self.login()
        response = {}
        for endpoint in api_endpoints:
            try:
                response = self.post(f'{self.xurl}.index/{endpoint}', headers=self.get_headers(), data=payload, verify=False).json()
            except Exception:
                continue
            if '到期' in response['msg'] or response['code'] == 0:
                return None
            break
        if not response: return None
        encrypted_data = response['data']
        kjson1 = self.decrypt(encrypted_data)
        kjson = json.loads(kjson1)
        videos, play_form, play_url = [], [], []
        lineid = 1
        name_count = {}
        for line in kjson['vod_play_list']:
            keywords = {'防走丢', '群', '防失群', '官网'}
            player_show = line['player_info']['show']
            if any(keyword in player_show for keyword in keywords):
                player_show = f'{lineid}线'
                line['player_info']['show'] = player_show
            count = name_count.get(player_show, 0) + 1
            name_count[player_show] = count
            if count > 1:
                line['player_info']['show'] = f"{player_show}{count}"
            play_form.append(line['player_info']['show'])
            parse = line['player_info']['parse']
            parse_type = line['player_info']['parse_type']
            player_parse_type = line['player_info']['player_parse_type']
            kurls = []
            for vod in line['urls']:
                token = vod['token']
                kurls.append(f"{str(vod['name'])}${parse},{vod['url']},{token},{player_parse_type},{parse_type}")
            play_url.append('#'.join(kurls))
            lineid += 1
        play_form = '$$$'.join(play_form)
        play_url = '$$$'.join(play_url)
        videos.append({
            "vod_id": ids[0],
            "vod_name": kjson['vod']['vod_name'],
            "vod_actor": kjson['vod']['vod_actor'].replace('演员', ''),
            "vod_director": kjson['vod'].get('vod_director', '').replace('导演', ''),
            "vod_content": kjson['vod']['vod_content'],
            "vod_remarks": kjson['vod']['vod_remarks'],
            "vod_year": kjson['vod']['vod_year'],
            "vod_area": kjson['vod']['vod_area'],
            "vod_play_from": play_form,
            "vod_play_url": play_url
        })
        return {'list': videos}

    def playerContent(self, flag, vid, vip_flags):
        url = ''
        uid, raw_url, token, player_parse_type, parse_type = vid.split(',', 4)
        if parse_type == '0':
            res =  {"parse": 0, "url": raw_url, "header": {'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 14; 23113RK12C Build/SKQ1.231004.001)'}}
        elif parse_type == '2':
            res = {"parse": 1, "url": f'{uid}{raw_url}', "header": {'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 14; 23113RK12C Build/SKQ1.231004.001)'}}
        elif player_parse_type == '2':
            try:
                response = self.fetch(f'{uid}{raw_url}', headers=self.get_headers(1), verify=False).json()
                url = response['url']
            except Exception:
                pass
            res = {"parse": 0, "url": url, "header": {'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 14; 23113RK12C Build/SKQ1.231004.001)'}}
        else:
            id1 = self.encrypt(raw_url)
            payload = {
                'parse_api': uid,
                'url': id1,
                'player_parse_type': player_parse_type,
                'token': token
            }
            try:
                response = self.post(f"{self.xurl}.index/vodParse", headers=self.get_headers(), data=payload, verify=False).json()
                encrypted_data = response['data']
                kjson = self.decrypt(encrypted_data)
                kjson1 = json.loads(kjson)['json']
                kjson2 = json.loads(kjson1)
                url = kjson2['url']
            except Exception:
                pass
            res = {"parse": 0, "playUrl": '', "url": url, "header": {'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 14; 23113RK12C Build/SKQ1.231004.001)'}}
        return res

    def localProxy(self, params):
        if params['type'] == "m3u8":
            return self.proxyM3u8(params)
        elif params['type'] == "media":
            return self.proxyMedia(params)
        elif params['type'] == "ts":
            return self.proxyTs(params)
        return None

    def get_headers(self,main=0):
        get_type = self.get_type
        if get_type == 'qiji':
            headers = {
                'User-Agent': 'okhttp/3.10.0',
                'Connection': 'Keep-Alive',
                'Accept-Encoding': 'gzip'
            }
        elif get_type == 'flutter':
            main_headers = {
                'User-Agent': 'Dart/3.5 (dart:io)',
                'Accept-Encoding': 'gzip'
            }
            if main == 1: return main_headers
            headers = {
                'User-Agent': '',
                'Accept-Encoding': '',
                'app-version-code': self.version,
                'app-os': 'android',
                'app-ui-mode': 'light',
                **main_headers
            }
        else:
            timestamp = str(int(time.time()))
            main_headers ={
                'User-Agent': 'okhttp/3.14.9',
                'Accept-Encoding': 'gzip'
            }
            if main == 1: return main_headers
            headers = {
                'User-Agent': '',
                'Connection': 'Keep-Alive',
                'Accept-Encoding': '',
                'app-version-code': self.version,
                'app-ui-mode': 'light',
                'app-user-device-id': self.device_id,
                'app-api-verify-time': timestamp,
                'app-api-verify-sign': self.encrypt(timestamp),
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                **main_headers
            }
        return {**headers, **self.def_headers}

    def login(self):
        if self.username and self.password and self.device_id:
            payload = {
                'password': self.password,
                'code': "",
                'device_id': self.device_id,
                'user_name': self.username,
                'invite_code': "",
                'is_emulator': "0"
            }
            response = self.post(f'{self.xurl}.index/appLogin', data=payload, headers=self.get_headers()).json()
            data = self.decrypt(response['data'])
            auth_token = json.loads(data)['user']['auth_token']
            self.def_headers['app-user-token'] = auth_token

    def arr2vods(self, arr):
        videos = []
        if arr and isinstance(arr, list):
            for i in arr:
                videos.append({
                    'vod_id': i['vod_id'],
                    'vod_name': i['vod_name'],
                    'vod_pic': i.get('vod_pic'),
                    'vod_remarks': i.get('vod_remarks')
                })
        return videos

    def decrypt(self, encrypted_data_b64):
        key_bytes = self.key.encode('utf-8')
        iv_bytes = self.iv.encode('utf-8')
        encrypted_data = base64.b64decode(encrypted_data_b64)
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
        decrypted_padded = cipher.decrypt(encrypted_data)
        decrypted = unpad(decrypted_padded, AES.block_size)
        return decrypted.decode('utf-8')

    def encrypt(self, sencrypted_data):
        key_bytes = self.key.encode('utf-8')
        iv_bytes = self.iv.encode('utf-8')
        data_bytes = sencrypted_data.encode('utf-8')
        padded_data = pad(data_bytes, AES.block_size)
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
        encrypted_bytes = cipher.encrypt(padded_data)
        encrypted_data_b64 = base64.b64encode(encrypted_bytes).decode('utf-8')
        return encrypted_data_b64

    def ocr(self, base64img):
        dat2 = self.post('https://api.nn.ci/ocr/b64/text', data=base64img, headers=self.get_headers(1), verify=False).text
        if dat2: return dat2
        return None

    def verification(self):
        random_uuid = str(uuid.uuid4())
        dat = self.fetch(f'{self.xurl}.verify/create?key={random_uuid}', headers=self.get_headers(), verify=False).content
        base64_img = base64.b64encode(dat).decode('utf-8')
        if not dat:
            return None
        code = self.ocr(base64_img)
        if not code:
            return None
        code = self.replace_code(code)
        if not (len(code) == 4 and code.isdigit()):
            return None
        return {'uuid': random_uuid, 'code': code}

    def replace_code(self,text):
        replacements = {'y':'9','口':'0','q':'0','u':'0','o':'0','>':'1','d':'0','b':'8','已':'2','D':'0','五':'5'}
        if len(text) == 3:
            text = text.replace('566', '5066').replace('066', '1666')
        return ''.join(replacements.get(c, c) for c in text)

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass