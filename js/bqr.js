var rule = {
    title:'不求人搜',
    host:'https://news.bqrdh.com',
    url:'',
    detailUrl:'/pgc/view/web/season?season_id=fyid',
    filter_url:'fl={{fl}}',
    searchUrl:'/x/web-interface/search/type?keyword=**&page=fypage&search_type=',
    searchable:1,
    filterable:1,
    quickSearch:0,
	headers:{
		'User-Agent': PC_UA,
		'Accept': '*/*',
		'Referer': 'https://news.bqrdh.com',
		'Content-Type': 'application/json'
	},
    timeout:5000,
    class_name:'华语电影&日韩电影&欧美电影&其他电影&华语电视&日韩电视&欧美电视&其他电视&欧美动漫&国漫动漫&日本动漫&纪录片&综艺片&教育&其他视频&华语音乐&日韩音乐&欧美音乐&其他音乐',
    class_url:'2&3&4&5&7&8&9&10&14&12&13&16&17&18&19&21&22&23&24',
    play_parse:true,
    lazy:`js:
    input = panPlay(input,playObj.flag)
    `,
    limit:5,
    推荐:`js:
		function parseVodList(resp) {
			const rspData = resp;
			const jsonData = base64Decode(rspData.payload.substring(9));
			const json = JSON.parse(jsonData);
			const videos = [];
			for (const item of json.payload) {
				videos.push({
					vod_id: item.fullSourceUrl,
					vod_name: item.title,
					vod_pic: '',
					vod_remarks: item.source
				});
			}
			return videos;
		}
		const tid = "";
		let pg = 1;
        let url = rule.homeUrl + '/api/busi/res/list?typeId=&source=ALI_WP&q=&statuses=PUBLISH&statuses=INVALID&orderBy2=&pageSize=25&pageNum=' + pg + '&total=0&_t=' + new Date().getTime();
		let html = request(url);
        let resp = JSON.parse(html);
        VODS = parseVodList(resp)
    `,
    一级:`js:
		function parseVodList(resp) {
			const rspData = resp;
			const jsonData = base64Decode(rspData.payload.substring(9));
			const json = JSON.parse(jsonData);
			const videos = [];
			for (const item of json.payload) {
				videos.push({
					vod_id: item.fullSourceUrl,
					vod_name: item.title,
					vod_pic: '',
					vod_remarks: item.source
				});
			}
			return videos;
		}
		const tid = "";
		let pg = MY_PAGE;
		let url = rule.homeUrl + '/api/busi/res/list?typeId=' + MY_CATE + '&source=ALI_WP&q=&statuses=PUBLISH&statuses=INVALID&orderBy2=&pageSize=25&pageNum=' + pg + '&total=0&_t=' + new Date().getTime();
		let html = request(url);
		let resp = JSON.parse(html);
		VODS = parseVodList(resp)
    `,
	二级:`js:
	let id=input;
	let title="";
	let pic="";
	let typeName="";
	let dec=id;
	let remark="";
	let vod={vod_id:id,vod_name:title,vod_pic:pic,type_name:typeName,vod_remarks:remark,vod_content:dec};
	
	initPan();
	let panVod = panDetailContent(vod ,[input]);
	TABS = panVod.tabs
	LISTS = panVod.lists
	detailError = panVod.error
	vod["vod_play_from"]=panVod.tabs.join("$$$");

	for (var i in LISTS) {
		if (LISTS.hasOwnProperty(i)) {
		  // print(i);
		  try {
			LISTS[i] = LISTS[i].map(function (it) {
			  return it.split('$').slice(0, 2).join('$');
			});
		  } catch (e) {
			print('格式化LISTS发生错误:' + e.message);
		  }
		}
	}
	vod_play_url = LISTS.map(function (it) {
		return it.join('#');
	}).join("$$$");
	vod["vod_play_url"]=vod_play_url;
	VOD=vod;
 `,
    搜索:`js:
	function parseVodList(resp) {
		const rspData = resp;
		const jsonData = base64Decode(rspData.payload.substring(9));
		const json = JSON.parse(jsonData);
		const videos = [];
		for (const item of json.payload) {
			videos.push({
				vod_id: item.fullSourceUrl,
				vod_name: item.title,
				vod_pic: '',
				vod_remarks: item.source
			});
		}
		return videos;
	}
	const tid = "";
	let pg = MY_PAGE;
	let url = rule.homeUrl + '/api/busi/res/list?source=&q=' + KEY + '&statuses=PUBLISH&statuses=INVALID&orderBy2=newest&pageSize=25&pageNum=' + pg + '&total=0&_t=' + new Date().getTime();
	let html = request(url);
	let resp = JSON.parse(html);
	VODS = parseVodList(resp);
    `,
}
