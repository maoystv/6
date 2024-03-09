import { Crypto,_} from './lib/cat.js';

let siteUrl = 'http://ys.changmengyun.com';
let siteKey = '';
let siteType = 0;

async function request(reqUrl){
	let res = await req(reqUrl, {
        headers: getHeaders(),
		method: 'get',
    });
	return res.content;
}

async function init(cfg) {
    siteKey = cfg.skey;
    siteType = cfg.stype;
}

async function home(filter) {
   
    return JSON.stringify({
        'class': [{'type_id':'2','type_name':'电视剧'},{'type_id':'1','type_name':'电影'},{'type_id':'4','type_name':'动漫'},{'type_id':'3','type_name':'综艺'},{'type_id':'46','type_name':'海外精选'}],
        'filters': {
			"2":[{"key":"class","name":"类型","value":[{"n":"全部","v":"类型"},{"n":"国产剧","v":"国产剧"},{"n":"港台剧","v":"港台剧"}]},{"key":"area","name":"地区","value":[{"n":"全部","v":"地区"},{"n":"内地","v":"内地"},{"n":"香港地区","v":"香港地区"},{"n":"台湾地区","v":"台湾地区"}]},{"key":"year","name":"年份","value":[{"n":"全部","v":"年份"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"10年代","v":"10年代"},{"n":"00年代","v":"00年代"},{"n":"90年代","v":"90年代"},{"n":"80年代","v":"80年代"}]},{"key":"by","name":"排序","value":[{"n":"热播榜","v":"热播榜"},{"n":"好评榜","v":"好评榜"},{"n":"新上线","v":"新上线"}]}],
			"1":[{"key":"class","name":"类型","value":[{"n":"全部","v":"类型"},{"n":"动作片","v":"动作片"},{"n":"喜剧片","v":"喜剧片"},{"n":"爱情片","v":"爱情片"},{"n":"科幻片","v":"科幻片"},{"n":"恐怖片","v":"恐怖片"},{"n":"剧情片","v":"剧情片"},{"n":"战争片","v":"战争片"},{"n":"惊悚片","v":"惊悚片"}]},{"key":"area","name":"地区","value":[{"n":"全部","v":"地区"},{"n":"华语","v":"华语"},{"n":"香港地区","v":"香港地区"},{"n":"美国","v":"美国"},{"n":"欧洲","v":"欧洲"},{"n":"韩国","v":"韩国"},{"n":"日本","v":"日本"},{"n":"台湾地区","v":"台湾地区"},{"n":"泰国","v":"泰国"},{"n":"台湾地区","v":"台湾地区"},{"n":"印度","v":"印度"},{"n":"其它","v":"其它"}]},{"key":"year","name":"年份","value":[{"n":"全部","v":"年份"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"10年代","v":"10年代"},{"n":"00年代","v":"00年代"},{"n":"90年代","v":"90年代"},{"n":"80年代","v":"80年代"}]},{"key":"by","name":"排序","value":[{"n":"热播榜","v":"热播榜"},{"n":"好评榜","v":"好评榜"},{"n":"新上线","v":"新上线"}]}],
			"4":[{"key":"class","name":"类型","value":[{"n":"全部","v":"类型"},{"n":"国产漫","v":"国产漫"},{"n":"欧美漫","v":"欧美漫"},{"n":"日韩漫","v":"日韩漫"},{"n":"港台漫","v":"港台漫"}]},{"key":"area","name":"地区","value":[{"n":"全部","v":"地区"},{"n":"中国大陆","v":"中国大陆"},{"n":"日本","v":"日本"},{"n":"韩国","v":"韩国"},{"n":"欧美","v":"欧美"},{"n":"其它","v":"其它"}]},{"key":"year","name":"年份","value":[{"n":"全部","v":"年份"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"10年代","v":"10年代"},{"n":"00年代","v":"00年代"},{"n":"90年代","v":"90年代"},{"n":"80年代","v":"80年代"}]},{"key":"by","name":"排序","value":[{"n":"热播榜","v":"热播榜"},{"n":"新上线","v":"新上线"}]},{"key":"total","name":"状态","value":[{"n":"全部","v":"状态"},{"n":"连载","v":"连载"},{"n":"完结","v":"完结"}]}],
			"3":[{"key":"class","name":"类型","value":[{"n":"全部","v":"类型"},{"n":"大陆","v":"大陆"},{"n":"港台","v":"港台"},{"n":"日韩","v":"日韩"},{"n":"欧美","v":"欧美"}]},{"key":"area","name":"地区","value":[{"n":"全部","v":"地区"},{"n":"内地","v":"内地"},{"n":"港台","v":"港台"},{"n":"日韩","v":"日韩"},{"n":"欧美","v":"欧美"},{"n":"其它","v":"其它"}]},{"key":"year","name":"年份","value":[{"n":"全部","v":"年份"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"10年代","v":"10年代"},{"n":"00年代","v":"00年代"},{"n":"90年代","v":"90年代"},{"n":"80年代","v":"80年代"}]},{"key":"by","name":"排序","value":[{"n":"热播榜","v":"热播榜"},{"n":"新上线","v":"新上线"}]}],
			"46":[{"key":"class","name":"类型","value":[{"n":"全部","v":"类型"},{"n":"日韩剧","v":"日韩剧"},{"n":"欧美剧","v":"欧美剧"},{"n":"海外剧","v":"海外剧"}]},{"key":"area","name":"地区","value":[{"n":"全部","v":"地区"},{"n":"韩国","v":"韩国"},{"n":"美剧","v":"美剧"},{"n":"日本","v":"日本"},{"n":"泰国","v":"泰国"},{"n":"英国","v":"英国"},{"n":"新加坡","v":"新加坡"},{"n":"其他","v":"其他"}]},{"key":"year","name":"年份","value":[{"n":"全部","v":"年份"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"10年代","v":"10年代"},{"n":"00年代","v":"00年代"},{"n":"90年代","v":"90年代"},{"n":"80年代","v":"80年代"}]},{"key":"by","name":"排序","value":[{"n":"热播榜","v":"热播榜"},{"n":"好评榜","v":"好评榜"},{"n":"新上线","v":"新上线"}]}]
		},
    });
}

async function homeVod() {
	try {
		let url = siteUrl + '/api.php/provide/vod_rank?app=ylys&sort_type=month&imei=c431ea542cee9679&id=2&page=1';
		let data = await request(url);
		let res = JSON.parse(data);
		let videos = _.map(res, (vod) => {
			return {
				vod_id: vod.id,
				vod_name: vod.name,
				vod_pic: vod.img,
				vod_remarks: vod.remarks,
			}
		});
		return JSON.stringify({
			list: videos,
		});
	} catch (error) {
		//console.log('error', error);
	}
    
}

async function category(tid, pg, filter, extend) {
	if(pg <= 0) pg = 1;
	let area = extend['area']?extend['area']:'';
	let year = extend['year']?extend['year']:'';
	let type = extend['class']?extend['class']:'';
	
    let url = siteUrl + '/api.php/provide/vod_list?app=ylys&id='+tid+'&area='+ area +'&year='+year+'&type='+type+'&page='+pg+'&imei=c431ea542cee9679';
	let res = JSON.parse(await request(url));
    let videos = _.map(res['list'], (vod) => {
		return {
            vod_id: vod.id,
            vod_name: vod.name,
            vod_pic: vod.img,
            vod_remarks: vod.msg,
        }
	});
    return JSON.stringify({
        page: pg,
        limit: res['limit'],
        list: videos,
    });
}

async function detail(id) {
    let data = JSON.parse(await request(siteUrl + '/api.php/provide/vod_detail?app=ylys&imei=c431ea542cee9679&id=' + id))['data'];
    let vod = {
        vod_name: data.name,
        vod_pic: data.img,
        type_name: data.type,
        vod_year: data.year,
        vod_remarks: data.msg,
        vod_content: '💕一个分享者💕' + data.info,
    };
    let episodes = data.player_info;
    let playFroms = [];
	let playUrls = [];
    for (let i=0;i<episodes.length;i++) {
		let episode = episodes[i];
		playFroms.push(episode.show);
        let nameUrls = [];
        for (const play of episode.video_info) {
            nameUrls.push(play.name + '$' + play['url'][0]);
        }
		playUrls.push(nameUrls.join('#'));
    }
    vod.vod_play_from = playFroms.join('$$$');
    vod.vod_play_url = playUrls.join('$$$');
    return JSON.stringify({
        list: [vod],
    });
}

async function play(flag, id, flags) {
    try {
		let input = {parse: 0,url: id,};
        if (id.indexOf(',') > 0) {
                let mjurl = id.split(',')[1]
                let videoUrl = await getvideo(mjurl);
                input = {
                    jx: 0,
                    url: videoUrl,
                    parse: 0,
                    header: JSON.stringify({
                        'user-agent': 'Lavf/58.12.100'
                    })
                }
		} else {
			let videoUrl = await getvideo(id);
			if (videoUrl.indexOf('jhapi') > 0) {
				videoUrl = await getvideo(videoUrl);
				input = {
					jx: 0,
					url: videoUrl,
					parse: 0,
					header: JSON.stringify({
						'user-agent': 'Lavf/58.12.100'
					})
				}
			} else {
				input = {
					jx: 0,
					url: videoUrl,
					parse: 0
				}
			}
		}
		return JSON.stringify(input);
    } catch (e) {
        return JSON.stringify({
            parse: 0,
            url: id,
        });
    }
}

async function getvideo(url) {
	let jData = JSON.parse(await request(url));
	if (jData.code == 1) {
		return jData.data.url
	} else {
		return 'http://43.154.104.152:1234/jhapi/cs.php?url=' + url.split('=')[1]
	}
}

async function search(wd, quick, pg) {
    let page = pg || 1;
    if (page == 0) page = 1;
    let data = JSON.parse(await request(siteUrl + '/api.php/provide/search_result_more?app=ylys&video_name='+wd+'&pageSize=20&tid=0&imei=c431ea542cee9679&page='+page));
    let videos = [];
    for (const vod of data.data) {
        videos.push({
            vod_id: vod.id,
            vod_name: vod.video_name,
            vod_pic: vod.img,
            vod_remarks: vod.qingxidu,
        });
    }
    return JSON.stringify({
        page: page,
        list: videos,
    });
}

function getHeaders() {
    let t = new Date().getTime().toString();
	return {
        'version_name': '1.0.6',
        'version_code': '6',
        'package_name': 'com.app.nanguatv',
        'sign': Crypto.MD5('c431ea542cee9679#uBFszdEM0oL0JRn@' + t).toString().toUpperCase(),
        'imei': 'c431ea542cee9679',
        'timeMillis': t,
        'User-Agent': 'okhttp/4.6.0'
	};
}

export function __jsEvalReturn() {
    return {
        init: init,
        home: home,
        homeVod: homeVod,
        category: category,
        detail: detail,
        play: play,
        search: search,
    };
}