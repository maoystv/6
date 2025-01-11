rule = {
    name: '皮皮虾影视',
    host: 'http://ppxys.vip',
    class_name: '剧集&电影&动漫',
    class_url: '1&2&3',
    homeVod: 'div.module-items > a;&&title;&&href;img&&data-original;.module-item-note&&Text',
    url: '/s/fyclass/page/fypage.html',
    categoryVod: 'div.module-items > a;&&title;&&href;img&&data-original;.module-item-note&&Text',
    detailVod: {
        playFrom: '.module-tab-items-box > .module-tab-item > span&&Text',
        playUrl: '.module-play-list > .module-play-list-content;a;&&Text;&&href',
    },
    lazy: `
        request(HOST + input);|||
        const json = getPlay4aJson(html);
        request('http://java.shijie.chat/player?url=' + unescape(base64Decode(JSON.parse(json).url)));|||
        let encData = html.split('Video: "')[1].split('",')[0];
        playUrl = JSON.parse(aesDecode(encData, 'ASD010QNC636LJY9', 'C636LJY9ASD010QN')).url;
    `,
    searchUrl: '/vodsearch.html?wd=**',
    searchVod: '.module-card-item > a;img&&alt;&&href;img&&data-original;.module-item-note&&Text',
}