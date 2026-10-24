var rule = {
    title: '腾讯视频',
    host: 'https://v.qq.com',
    homeUrl: 'fyclass',
    detailUrl: 'https://node.video.qq.com/x/api/float_vinfo2?cid=fyid',
    searchUrl: '**',
    searchable: 2,
    filterable: 1,
    multi: 1,
    url: 'fyclass',
    filter_url: '',

    // 解析接口配置（保留第二个文件原有）
    parse_url: [
        'http://8.134.205.252:39466/ceshi/qianyi.php?key=rkd&url=','http://114.66.51.153:2006/api/?key=9df31116c47da6a984097931955ad8d2&url=','http://zq0143yimmi.xian.zxtongshuo.cn/qq.php?url='
    ],

    // 屏蔽地址（保留第二个文件原有）
    blocked_urls: [
        
        '.mp4'
    ],

    headers: {
        'User-Agent': 'PC_UA'
    },
    timeout: 5000,
    cate_exclude: '会员|游戏|全部',
    class_name: '电视剧&电影&短剧&综艺&动漫&少儿&纪录片',
    class_url: 'tv&movie&mini_series&variety&cartoon&child&doco',
    limit: 20,
    play_parse: true,

    // 解析系统（完全保留第二个文件原有）
    lazy: $js.toString(() => {
        let parseIndex = 0;
        let targetUrl = '';

        try {
            let bata = JSON.parse(response);
            log(bata);
            if (bata.url && bata.url.includes("http")) {
                targetUrl = bata.url;
            } else {
                targetUrl = input.split("?")[0];
            }
        } catch {
            targetUrl = input.split("?")[0];
        }

        function isBlockedUrl(url) {
            if (!url) return true;
            return rule.blocked_urls.some(blocked => url.includes(blocked));
        }

        function tryParse(url, index) {
            if (index >= rule.parse_url.length) {
                log('所有解析接口都尝试失败，使用默认解析');
                input = {
                    header: { 'User-Agent': "" },
                    parse: 0,
                    url: targetUrl,
                    jx: 1,
                    danmaku: 'http://127.0.0.1:9978/proxy?do=danmu&site=js&url=' + targetUrl
                };
                return;
            }

            let parseUrl = rule.parse_url[index] + encodeURIComponent(url);
            log('尝试解析接口 ' + (index + 1) + ': ' + parseUrl);

            let result = fetch(parseUrl, { 
                method: 'GET',
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://v.qq.com/'
                },
                timeout: 10000
            });

            try {
                let data = JSON.parse(result);
                if (data && data.url && data.url.includes("http")) {
                    if (isBlockedUrl(data.url)) {
                        log('解析接口 ' + (index + 1) + ' 返回了屏蔽地址，尝试下一个接口');
                        tryParse(url, index + 1);
                        return;
                    }

                    log('解析接口 ' + (index + 1) + ' 成功: ' + data.url);
                    input = {
                        header: { 'User-Agent': "" },
                        parse: 0,
                        url: data.url,
                        jx: 0,
                        danmaku: 'http://127.0.0.1:9978/proxy?do=danmu&site=js&url=' + targetUrl
                    };
                } else {
                    log('解析接口 ' + (index + 1) + ' 返回数据无效，尝试下一个');
                    tryParse(url, index + 1);
                }
            } catch (e) {
                log('解析接口 ' + (index + 1) + ' 失败: ' + e.message);
                tryParse(url, index + 1);
            }
        }

        tryParse(targetUrl, 0);
    }),

    // 一级：使用第一个文件的新版 API（去掉了推荐分类，加上短剧 channelId）
    一级: $js.toString(() => {
        let d = [];
        let fyclass = MY_CATE;
        let fypage = MY_PAGE;
        let fl = MY_FL;

        let channelIds = {
            'tv': '100113',
            'movie': '100173',
            'variety': '100109',
            'cartoon': '100119',
            'child': '100150',
            'doco': '100105',
            'mini_series': '120188'
        };
        let channelId = channelIds[fyclass] || '100113';

        // 构建 filter_params（filter 的 key 即接口参数名，直接拼接）
        let filterParts = [];
        filterParts.push('sort=' + (fl.sort || '75'));

        for (let key in fl) {
            if (key === 'sort') continue;
            let val = fl[key];
            if (val && val !== '' && val !== '-1' && val !== '0') {
                filterParts.push(key + '=' + val);
            }
        }
        let filterParams = filterParts.join('&');

        let apiUrl = 'https://pbaccess.video.qq.com/trpc.multi_vector_layout.mvl_controller.MVLPageHTTPService/getMVLPage?&vversion_platform=2';
        let commonHeaders = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'Origin': 'https://v.qq.com',
            'Referer': 'https://v.qq.com/'
        };

        function doRequest(body) {
            return request(apiUrl, { body: JSON.stringify(body), headers: commonHeaders, method: 'POST' });
        }
        function makeBody(fp, ctx) {
            let b = {"page_params": {"channel_id": channelId, "filter_params": fp, "page_type": "operation", "page_id": "channel_list"}};
            if (ctx) b.page_context = ctx;
            return b;
        }

        // 分页：page_context 串行
        let pageContext = null;
        let cacheKey = 'mvl_' + fyclass + '_' + filterParams;
        if (fypage > 1) {
            try {
                let cached = storage0.getItem(cacheKey);
                if (cached) {
                    let co = JSON.parse(cached);
                    if (co.p && co.c && co.p < fypage) {
                        pageContext = co.c;
                        for (let p = co.p + 1; p < fypage; p++) {
                            let rj = JSON.parse(doRequest(makeBody(filterParams, pageContext)));
                            if (rj.ret === 0 && rj.data && rj.data.page_context) { pageContext = rj.data.page_context; } else { break; }
                        }
                    }
                }
            } catch (e) { pageContext = null; }
        }
        if (fypage > 1 && !pageContext) {
            for (let p = 1; p < fypage; p++) {
                try {
                    let rj = JSON.parse(doRequest(makeBody(filterParams, pageContext)));
                    if (rj.ret === 0 && rj.data && rj.data.page_context) { pageContext = rj.data.page_context; } else { break; }
                } catch (e) { break; }
            }
        }

        try {
            let html = doRequest(makeBody(filterParams, pageContext));
            let json = JSON.parse(html);
            if (json.ret === 0 && json.data) {
                let data = json.data;
                if (data.page_context) {
                    try { storage0.setItem(cacheKey, JSON.stringify({ p: fypage, c: data.page_context })); } catch (e) {}
                }
                let cards = ((data.modules || {}).normal || {}).cards || [];
                cards.forEach(function(card) {
                    let posterCards = ((card.children_list || {}).poster_card || {}).cards || [];
                    posterCards.forEach(function(item) {
                        let params = item.params || {};
                        let title = params.title || '';
                        let cid = params.cid || '';
                        let img = params.new_pic_vt || '';
                        let desc = params.timelong || '';
                        if (!desc) desc = params.second_title || params.sub_title || '';
                        if (cid && title) {
                            d.push({ title: title, img: img, desc: desc, url: cid });
                        }
                    });
                });
            }
        } catch (e) {
            log('列表请求失败: ' + e.message);
        }
        setResult(d);
    }),

    // 二级：完全保留第二个文件原有（含线路命名与花絮分组）
    二级: $js.toString(() => {
        VOD = {};
        let d = [];
        let video_list = [];
        let video_lists = [];
        let QZOutputJson;
        let html = fetch(input, fetch_params);
        let sourceId = /get_playsource/.test(input) ? input.match(/id=(\d*?)&/)[1] : input.split("cid=")[1];
        let cid = sourceId;
        let detailUrl = "https://v.qq.com/detail/m/" + cid + ".html";

        try {
            let json = JSON.parse(html);
            VOD = {
                vod_url: input,
                vod_name: json.c.title,
                type_name: json.typ.join(","),
                vod_actor: json.nam.join(","),
                vod_year: json.c.year,
                vod_content: json.c.description,
                vod_remarks: json.rec,
                vod_pic: urljoin2(input, json.c.pic)
            }
        } catch (e) {
            log("解析详情失败: " + e.message);
        }

        if (/get_playsource/.test(input)) {
            eval(html);
            let indexList = QZOutputJson.PlaylistItem.indexList;
            indexList.forEach(function(it) {
                let dataUrl = "https://s.video.qq.com/get_playsource?id=" + sourceId + "&plat=2&type=4&data_type=3&range=" + it + "&video_type=10&plname=qq&otype=json";
                eval(fetch(dataUrl, fetch_params));
                let vdata = QZOutputJson.PlaylistItem.videoPlayList;
                vdata.forEach(function(item) {
                    d.push({
                        title: item.title,
                        pic_url: item.pic,
                        desc: item.episode_number + "\t\t\t播放量：" + item.thirdLine,
                        url: item.playUrl
                    })
                });
                video_lists = video_lists.concat(vdata)
            })
        } else {
            let json = JSON.parse(html);
            video_lists = json.c.video_ids;
            let url = "https://v.qq.com/x/cover/" + sourceId + ".html";

            if (video_lists.length === 1) {
                let vid = video_lists[0];
                let o_url = "https://union.video.qq.com/fcgi-bin/data?otype=json&tid=1804&appid=20001238&appkey=6c03bbe9658448a4&union_platform=1&idlist=" + vid;
                let o_html = fetch(o_url, fetch_params);
                eval(o_html);
                if (QZOutputJson.results && QZOutputJson.results.length > 0) {
                    let it1 = QZOutputJson.results[0].fields;
                    url = "https://v.qq.com/x/cover/" + cid + "/" + vid + ".html";
                    d.push({
                        title: it1.title,
                        url: url
                    })
                } else {
                    url = "https://v.qq.com/x/cover/" + cid + "/" + vid + ".html";
                    d.push({
                        title: "正片播放",
                        url: url
                    })
                }
            } else if (video_lists.length > 1) {
                for (let i = 0; i < video_lists.length; i += 30) {
                    video_list.push(video_lists.slice(i, i + 30))
                }
                video_list.forEach(function(it, idex) {
                    let o_url = "https://union.video.qq.com/fcgi-bin/data?otype=json&tid=1804&appid=20001238&appkey=6c03bbe9658448a4&union_platform=1&idlist=" + it.join(",");
                    let o_html = fetch(o_url, fetch_params);
                    eval(o_html);
                    QZOutputJson.results.forEach(function(it1) {
                        it1 = it1.fields;
                        let url = "https://v.qq.com/x/cover/" + cid + "/" + it1.vid + ".html";
                        d.push({
                            title: it1.title,
                            pic_url: it1.pic160x90.replace("/160", ""),
                            desc: it1.video_checkup_time,
                            url: url,
                            type: it1.category_map && it1.category_map.length > 1 ? it1.category_map[1] : ""
                        })
                    })
                })
            }
        }

        let playFrom = [];
        let playUrl = [];

        let ygKeywords = ["预告", "花絮", "片花", "特辑", "幕后", "采访", "制作", "MV", "主题曲"];
        let yg = d.filter(function(it) {
            return it.type && ygKeywords.some(keyword => it.type.includes(keyword));
        });
        let zp = d.filter(function(it) {
            return !(it.type && ygKeywords.some(keyword => it.type.includes(keyword)));
        });

        if (zp.length > 0) {
            playFrom.push("正片");
            playUrl.push(zp.map(it => it.title + "$" + it.url).join("#"));
        }

        if (yg.length > 0) {
            let 预告 = yg.filter(it => it.type && it.type.includes("预告"));
            let 花絮片花 = yg.filter(it => it.type && (it.type.includes("花絮") || it.type.includes("片花")));
            let 特辑 = yg.filter(it => it.type && (it.type.includes("特辑") || it.type.includes("幕后")));

            if (预告.length > 0) {
                playFrom.push("预告");
                playUrl.push(预告.map(it => it.title + "$" + it.url).join("#"));
            }
            if (花絮片花.length > 0) {
                playFrom.push("花絮片花");
                playUrl.push(花絮片花.map(it => it.title + "$" + it.url).join("#"));
            }
            if (特辑.length > 0) {
                playFrom.push("特辑");
                playUrl.push(特辑.map(it => it.title + "$" + it.url).join("#"));
            }
        }

        VOD.vod_play_from = playFrom.join("$$$");
        VOD.vod_play_url = playUrl.join("$$$");
    }),

    // 搜索：完全保留第二个文件原有
    搜索: $js.toString(() => {
        let d = [],
            keyword = input.split("/")[3];
        let seenIds = new Set();

        function vodSearch(keyword, page = 0) {
            return request('https://pbaccess.video.qq.com/trpc.videosearch.mobile_search.MultiTerminalSearch/MbSearch?vplatform=2', {
                body: JSON.stringify({
                    version: "25042201",
                    clientType: 1,
                    filterValue: "",
                    uuid: "B1E50847-D25F-4C4B-BBA0-36F0093487F6",
                    retry: 0,
                    query: keyword,
                    pagenum: page,
                    isPrefetch: true,
                    pagesize: 30,
                    queryFrom: 0,
                    searchDatakey: "",
                    transInfo: "",
                    isneedQc: true,
                    preQid: "",
                    adClientInfo: "",
                    extraInfo: {
                        isNewMarkLabel: "1",
                        multi_terminal_pc: "1",
                        themeType: "1",
                        sugRelatedIds: "{}",
                        appVersion: ""
                    }
                }),
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.139 Safari/537.36',
                    'Content-Type': 'application/json',
                    'Origin': 'https://v.qq.com',
                    'Referer': 'https://v.qq.com/'
                },
                method: 'POST'
            });
        }

        const nonMainContentKeywords = [
            '：', '#', '特辑', '剪辑', '片花', '独家', '专访', '纯享',
            '制作', '幕后', '宣传', 'MV', '主题曲', '插曲', '彩蛋',
            '精彩', '集锦', '盘点', '回顾', '解说', '评测', '反应', 'reaction'
        ];

        function isMainContent(title) {
            if (!title) return false;
            if (title.includes('<em>') || title.includes('</em>')) return false;
            return !nonMainContentKeywords.some(keyword => title.includes(keyword));
        }

        function isQQPlatform(playSites) {
            if (!playSites || !Array.isArray(playSites)) return true;
            return playSites.some(site => site.enName && site.enName.toLowerCase() === 'qq');
        }

        try {
            let html = vodSearch(keyword, 0);
            let json = JSON.parse(html);

            function processItemList(itemList) {
                if (!itemList) return;

                itemList.forEach(it => {
                    if (it.doc && it.doc.id && it.videoInfo &&
                        isMainContent(it.videoInfo.title) &&
                        isQQPlatform(it.videoInfo.playSites)) {

                        const itemId = it.doc.id;
                        if (!seenIds.has(itemId)) {
                            seenIds.add(itemId);
                            d.push({
                                title: it.videoInfo.title,
                                img: it.videoInfo.imgUrl || "",
                                url: itemId,
                                desc: it.videoInfo.secondLine || ""
                            });
                        }
                    }
                });
            }

            if (json.data && json.data.normalList) {
                processItemList(json.data.normalList.itemList);
            }

            if (json.data && json.data.areaBoxList) {
                json.data.areaBoxList.forEach(box => {
                    processItemList(box.itemList);
                });
            }

        } catch (e) {
            log("搜索出错: " + e.message);
        }

        setResult(d);
    }),

    filter: {
        "tv": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最新上架", "v": "79"}, {"n": "高分好评", "v": "85"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "爱情", "v": "1"}, {"n": "都市", "v": "2"}, {"n": "青春", "v": "3"}, {"n": "奇幻", "v": "4"}, {"n": "武侠", "v": "5"}, {"n": "古装", "v": "6"}, {"n": "科幻", "v": "7"}, {"n": "猎奇", "v": "8"}, {"n": "竞技", "v": "9"}, {"n": "传奇", "v": "10"}, {"n": "逆袭", "v": "19"}, {"n": "军旅", "v": "11"}, {"n": "家庭", "v": "12"}, {"n": "喜剧", "v": "13"}, {"n": "悬疑", "v": "14"}, {"n": "权谋", "v": "15"}, {"n": "革命", "v": "16"}, {"n": "现实", "v": "17"}, {"n": "刑侦", "v": "18"}, {"n": "民国", "v": "20"}, {"n": "IP改编", "v": "21"}]
        }, {
            "key": "ipay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "限免", "v": "2"}, {"n": "会员", "v": "3"}]
        }, {
            "key": "iarea",
            "name": "地区",
            "value": [{"n": "全部", "v": "-1"}, {"n": "内地", "v": "0"}, {"n": "中国香港", "v": "14"}, {"n": "中国台湾", "v": "4"}, {"n": "美国", "v": "8"}, {"n": "泰国", "v": "9"}, {"n": "英国", "v": "1"}, {"n": "韩国", "v": "5"}, {"n": "日本", "v": "10"}, {"n": "其他", "v": "9999"}]
        }, {
            "key": "iyear",
            "name": "年份",
            "value": [{"n": "全部", "v": "-1"}, {"n": "即将上线", "v": "1"}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2"}, {"n": "2023", "v": "3"}, {"n": "2022", "v": "4"}, {"n": "2021", "v": "5"}, {"n": "2020-2016", "v": "6"}, {"n": "2015-2011", "v": "7"}, {"n": "2010-2000", "v": "8"}, {"n": "更早", "v": "9"}]
        }, {
            "key": "theater",
            "name": "剧场",
            "value": [{"n": "全部", "v": "-1"}, {"n": "X剧场", "v": "1"}, {"n": "板凳单元", "v": "2"}, {"n": "萤火单元", "v": "3"}, {"n": "十分剧场", "v": "4"}]
        }, {
            "key": "award",
            "name": "获奖",
            "value": [{"n": "全部", "v": "-1"}, {"n": "白玉兰奖", "v": "1"}, {"n": "飞天奖", "v": "2"}, {"n": "金鹰奖", "v": "3"}]
        }],
        "movie": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最新", "v": "83"}, {"n": "高分好评", "v": "81"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "动作", "v": "4"}, {"n": "喜剧", "v": "3"}, {"n": "爱情", "v": "5"}, {"n": "科幻", "v": "12"}, {"n": "犯罪", "v": "6"}, {"n": "冒险", "v": "7"}, {"n": "恐怖", "v": "11"}, {"n": "动画", "v": "15"}, {"n": "战争", "v": "8"}, {"n": "悬疑", "v": "10"}, {"n": "灾难", "v": "25"}, {"n": "青春", "v": "26"}]
        }, {
            "key": "ipay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "会员", "v": "8"}, {"n": "付费", "v": "4"}, {"n": "限免", "v": "3300"}]
        }, {
            "key": "iarea",
            "name": "地区",
            "value": [{"n": "全部", "v": "-1"}, {"n": "内地", "v": "100024"}, {"n": "中国香港", "v": "100025"}, {"n": "中国台湾", "v": "100026"}, {"n": "美国", "v": "100029"}, {"n": "日本", "v": "100027"}, {"n": "韩国", "v": "100028"}, {"n": "泰国", "v": "100031"}, {"n": "印度", "v": "100030"}, {"n": "英国", "v": "15"}, {"n": "法国", "v": "16"}, {"n": "德国", "v": "17"}, {"n": "其他", "v": "100033"}]
        }, {
            "key": "iyear",
            "name": "年份",
            "value": [{"n": "全部", "v": "-1"}, {"n": "即将上线", "v": "999"}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "20"}, {"n": "2018", "v": "2018"}, {"n": "2017", "v": "1"}, {"n": "2016", "v": "2"}, {"n": "2015", "v": "3"}, {"n": "更早", "v": "10"}]
        }, {
            "key": "producer",
            "name": "出品方",
            "value": [{"n": "全部", "v": "-1"}, {"n": "腾讯出品", "v": "1"}, {"n": "索尼", "v": "2"}, {"n": "派拉蒙", "v": "3"}, {"n": "迪士尼", "v": "4"}, {"n": "环球", "v": "5"}, {"n": "华谊", "v": "6"}, {"n": "华纳", "v": "7"}, {"n": "光线", "v": "8"}, {"n": "BBC", "v": "10"}, {"n": "20世纪影业", "v": "11"}, {"n": "开心麻花", "v": "12"}]
        }, {
            "key": "characteristic",
            "name": "特征",
            "value": [{"n": "全部", "v": "-1"}, {"n": "院线电影", "v": "1"}, {"n": "网络电影", "v": "2"}, {"n": "独播", "v": "5"}, {"n": "原声", "v": "8"}, {"n": "粤语", "v": "9"}, {"n": "获奖佳片", "v": "6"}]
        }],
        "variety": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最近更新", "v": "23"}, {"n": "高分好评", "v": "85"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "游戏", "v": "10"}, {"n": "脱口秀", "v": "2"}, {"n": "音乐舞台", "v": "11"}, {"n": "情感", "v": "12"}, {"n": "生活", "v": "22"}, {"n": "职场", "v": "20"}, {"n": "喜剧", "v": "14"}, {"n": "美食", "v": "19"}, {"n": "潮流运动", "v": "21"}, {"n": "竞技", "v": "24"}, {"n": "影视", "v": "16"}, {"n": "电竞", "v": "15"}, {"n": "推理", "v": "25"}, {"n": "访谈", "v": "3"}, {"n": "亲子", "v": "17"}, {"n": "文化", "v": "26"}, {"n": "互动", "v": "23"}, {"n": "晚会", "v": "6"}, {"n": "资讯", "v": "7"}]
        }, {
            "key": "ipay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "会员", "v": "6"}]
        }, {
            "key": "exclusive",
            "name": "出品",
            "value": [{"n": "全部", "v": "-1"}, {"n": "腾讯自制", "v": "1"}, {"n": "独播", "v": "2"}]
        }, {
            "key": "iarea",
            "name": "地区",
            "value": [{"n": "全部", "v": "-1"}, {"n": "国内", "v": "1"}, {"n": "海外", "v": "2"}]
        }, {
            "key": "iyear",
            "name": "年份",
            "value": [{"n": "全部", "v": "-1"}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "50"}, {"n": "2019", "v": "7"}, {"n": "2018", "v": "1"}, {"n": "2017", "v": "2"}, {"n": "2016", "v": "3"}, {"n": "更早", "v": "99"}]
        }],
        "cartoon": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最近更新", "v": "23"}, {"n": "高分好评", "v": "85"}]
        }, {
            "key": "iarea",
            "name": "地区",
            "value": [{"n": "全部", "v": "-1"}, {"n": "内地", "v": "1"}, {"n": "日本", "v": "2"}, {"n": "欧美", "v": "3"}, {"n": "其他", "v": "4"}]
        }, {
            "key": "ipay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "867"}, {"n": "会员", "v": "6"}, {"n": "限免", "v": "3300"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "玄幻", "v": "9"}, {"n": "科幻", "v": "4"}, {"n": "奇幻", "v": "21"}, {"n": "武侠", "v": "13"}, {"n": "仙侠", "v": "23"}, {"n": "都市", "v": "24"}, {"n": "恋爱", "v": "7"}, {"n": "搞笑", "v": "1"}, {"n": "冒险", "v": "2"}, {"n": "悬疑", "v": "17"}, {"n": "竞技", "v": "20"}, {"n": "日常", "v": "15"}, {"n": "真人", "v": "18"}, {"n": "治愈", "v": "25"}, {"n": "游戏", "v": "26"}, {"n": "异能", "v": "27"}, {"n": "历史", "v": "19"}, {"n": "古风", "v": "28"}, {"n": "智斗", "v": "29"}, {"n": "恐怖", "v": "30"}, {"n": "美食", "v": "31"}, {"n": "音乐", "v": "32"}, {"n": "其他", "v": "12"}]
        }, {
            "key": "iyear",
            "name": "年份",
            "value": [{"n": "全部", "v": "-1"}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"}, {"n": "2020", "v": "50"}, {"n": "2019", "v": "11"}, {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "1"}, {"n": "更早", "v": "10"}]
        }, {
            "key": "anime_status",
            "name": "状态",
            "value": [{"n": "全部", "v": "-1"}, {"n": "即将上线", "v": "46"}, {"n": "更新中", "v": "44"}, {"n": "已完结", "v": "45"}]
        }],
        "child": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最新", "v": "76"}]
        }, {
            "key": "iyear",
            "name": "年龄",
            "value": [{"n": "全部", "v": "-1"}, {"n": "0-3岁", "v": "1"}, {"n": "4-6岁", "v": "2"}, {"n": "7-9岁", "v": "3"}, {"n": "10岁以上", "v": "4"}, {"n": "全年龄", "v": "7"}]
        }, {
            "key": "ipay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "会员", "v": "2"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "磨耳朵", "v": "22"}, {"n": "涨知识", "v": "23"}, {"n": "冒险", "v": "10"}, {"n": "儿歌", "v": "1"}, {"n": "交通工具", "v": "11"}, {"n": "益智早教", "v": "2"}, {"n": "玩具", "v": "4"}, {"n": "魔幻·科幻", "v": "12"}, {"n": "动物", "v": "13"}, {"n": "真人·特摄", "v": "14"}, {"n": "家长甄选", "v": "17"}, {"n": "动画电影", "v": "20"}]
        }, {
            "key": "gender",
            "name": "性别",
            "value": [{"n": "全部", "v": "-1"}, {"n": "女孩", "v": "1"}, {"n": "男孩", "v": "2"}]
        }],
        "doco": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最新", "v": "74"}, {"n": "高分好评", "v": "85"}]
        }, {
            "key": "itrailer",
            "name": "出品方",
            "value": [{"n": "全部", "v": "-1"}, {"n": "腾讯出品", "v": "15"}, {"n": "央视", "v": "8"}, {"n": "BBC", "v": "1"}, {"n": "国家地理", "v": "4"}, {"n": "探索频道", "v": "3174"}, {"n": "HBO", "v": "3175"}, {"n": "NHK", "v": "2"}, {"n": "ITV", "v": "3530"}, {"n": "历史频道", "v": "7"}]
        }, {
            "key": "itype",
            "name": "类型",
            "value": [{"n": "全部", "v": "-1"}, {"n": "自然", "v": "4"}, {"n": "美食", "v": "10"}, {"n": "社会", "v": "3"}, {"n": "人文", "v": "6"}, {"n": "历史", "v": "1"}, {"n": "军事", "v": "2"}, {"n": "科技", "v": "8"}, {"n": "财经", "v": "14"}, {"n": "探险", "v": "15"}, {"n": "罪案", "v": "7"}, {"n": "竞技", "v": "12"}, {"n": "旅游", "v": "11"}]
        }, {
            "key": "iregion",
            "name": "地区",
            "value": [{"n": "全部", "v": "0"}, {"n": "国内", "v": "1"}, {"n": "国外", "v": "2"}]
        }, {
            "key": "pay",
            "name": "资费",
            "value": [{"n": "全部", "v": "-1"}, {"n": "免费", "v": "1"}, {"n": "会员", "v": "2"}, {"n": "限免", "v": "3"}]
        }, {
            "key": "iyear",
            "name": "年份",
            "value": [{"n": "全部", "v": "-1"}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "1"}, {"n": "2023", "v": "2"}, {"n": "2022", "v": "3"}, {"n": "2021", "v": "4"}, {"n": "2020", "v": "5"}, {"n": "2019-2015", "v": "6"}, {"n": "更早", "v": "9"}]
        }],
        "mini_series": [{
            "key": "sort",
            "name": "排序",
            "value": [{"n": "最热", "v": "75"}, {"n": "最新上架", "v": "76"}, {"n": "限免中", "v": "90"}]
        }, {
            "key": "prefer",
            "name": "偏好",
            "value": [{"n": "全部", "v": "-1"}, {"n": "男频", "v": "2"}, {"n": "女频", "v": "1"}]
        }, {
            "key": "story",
            "name": "故事背景",
            "value": [{"n": "全部", "v": "-1"}, {"n": "古装爱情", "v": "1"}, {"n": "都市爱情", "v": "2"}, {"n": "都市奇幻", "v": "3"}, {"n": "古装权谋", "v": "5"}, {"n": "年代", "v": "6"}, {"n": "青春", "v": "8"}, {"n": "职场", "v": "10"}, {"n": "民国", "v": "11"}, {"n": "末日", "v": "12"}, {"n": "乡村", "v": "15"}, {"n": "悬疑推理", "v": "18"}, {"n": "玄幻", "v": "19"}, {"n": "喜剧", "v": "21"}]
        }, {
            "key": "identity",
            "name": "身份人设",
            "value": [{"n": "全部", "v": "-1"}, {"n": "总裁", "v": "1"}, {"n": "大女主", "v": "2"}, {"n": "战神", "v": "3"}, {"n": "萌娃", "v": "4"}, {"n": "神医", "v": "5"}, {"n": "落难千金", "v": "6"}, {"n": "赘婿", "v": "7"}, {"n": "神豪", "v": "8"}, {"n": "大男主", "v": "9"}, {"n": "女帝", "v": "10"}, {"n": "皇后王妃", "v": "11"}, {"n": "青梅竹马", "v": "13"}, {"n": "欢喜冤家", "v": "16"}, {"n": "大叔", "v": "24"}, {"n": "小人物", "v": "28"}, {"n": "团宠", "v": "29"}]
        }, {
            "key": "attraction",
            "name": "主要看点",
            "value": [{"n": "全部", "v": "-1"}, {"n": "穿越", "v": "3"}, {"n": "重生", "v": "4"}, {"n": "逆袭", "v": "5"}, {"n": "家庭伦理", "v": "6"}, {"n": "虐心", "v": "7"}, {"n": "曲折爱情", "v": "8"}, {"n": "破镜重圆", "v": "9"}, {"n": "马甲", "v": "10"}, {"n": "异能", "v": "11"}, {"n": "甜宠爱情", "v": "12"}, {"n": "奇幻爱情", "v": "13"}, {"n": "闪婚", "v": "15"}, {"n": "系统流", "v": "16"}, {"n": "传承觉醒", "v": "19"}, {"n": "亲情", "v": "20"}, {"n": "宅门风云", "v": "21"}, {"n": "家族恩怨", "v": "22"}, {"n": "身份之谜", "v": "23"}, {"n": "追妻", "v": "25"}, {"n": "虐渣复仇", "v": "29"}, {"n": "权力争夺", "v": "47"}, {"n": "恐怖", "v": "49"}, {"n": "娱乐圈", "v": "88"}, {"n": "脑洞", "v": "89"}]
        }]
    },
};