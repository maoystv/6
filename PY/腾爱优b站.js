/**
 * 腾爱优B站聚合采集 TVBox 源 (解码版)
 * 原始文件经过混淆，此为解码后的可读版本
 */
import $ from 'assets://js/lib/cheerio.min.js';

const sites = ['http://cj.tianwe.cn', 'https://tianwei.qzz.io', 'https://cj.10010888.xyz'];
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const parseApi = 'https://jx.kptv.us/?url=';
const apiPath = '/api.php/provide/vod/?';
let baseUrl = sites[0];

function safeJsonParse(d) { try { return typeof d === 'string' ? JSON.parse(d) : d; } catch(e) { return d; } }
function mylog() { console.log('腾爱优聚合', ...arguments); }

async function myFetch(url, opts = {}) {
    let resp = null;
    try {
        resp = await req(url, { method: opts?.method || 'get', headers: { 'user-agent': UA }, ...opts });
        return safeJsonParse(resp?.content);
    } catch(e) {
        mylog('myfetch err ', e);
        return resp?.content;
    }
}

function backErr(e, prefix = '') {
    mylog(prefix ? prefix + ' err:' : '', e);
    return JSON.stringify({ msg: e.message || String(e) });
}

// ========== 首页 ==========
async function init(ext) {}

async function homeVod() { return JSON.stringify({ list: [] }); }

async function home(ext) {
    try {
        const classList = [
            { type_id: 'qq', type_pid: 0, type_name: '腾讯视频' },
            { type_id: 'qiyi', type_pid: 0, type_name: '爱奇艺' },
            { type_id: 'youku', type_pid: 0, type_name: '优酷视频' },
            { type_id: 'mgtv', type_pid: 0, type_name: '芒果TV' },
            { type_id: 'bilibili', type_pid: 0, type_name: 'B站' }
        ];
        const typeFilter = {
            key: 'class', name: '类型',
            value: [
                { n: '全部', v: '' }, { n: '连续剧', v: '2' }, { n: '电影', v: '1' },
                { n: '动漫', v: '4' }, { n: '综艺', v: '3' }, { n: '少儿', v: '5' },
                { n: '纪录片', v: '6' }, { n: '短剧', v: '7' }
            ]
        };
        const yearFilter = {
            key: 'year', name: '年份',
            value: [
                { n: '全部', v: '' }, { n: '2026', v: '2026' }, { n: '2025', v: '2025' },
                { n: '2024', v: '2024' }, { n: '2023', v: '2023' }, { n: '2022', v: '2022' }
            ]
        };
        let filters = {};
        classList.forEach(cls => { filters[cls.type_id] = [typeFilter, yearFilter]; });
        return JSON.stringify({ class: classList, filters: filters });
    } catch(e) { return backErr(e); }
}

// ========== 详情 ==========
async function detail(id) {
    try {
        let url = baseUrl + apiPath + ['ac=detail', 'ids=' + id].join('&');
        mylog('detailurl', url);
        let data = await myFetch(url);
        let list = [];
        if (Array.isArray(data?.list)) {
            list = data.list.map(item => ({
                vod_id: item.vod_id,
                vod_name: item.vod_name,
                vod_pic: item.vod_pic,
                vod_remarks: item.vod_remarks,
                vod_year: item.vod_year,
                type_name: item.type_name,
                vod_area: item.vod_area,
                vod_lang: item.vod_lang,
                vod_content: item.vod_content,
                vod_play_from: item.vod_play_from,
                vod_play_url: item.vod_play_url
            })).filter(v => v.vod_id);
        }
        return JSON.stringify({ list: list });
    } catch(e) { return backErr(e); }
}

// ========== 分类 ==========
async function category(tid, pg = 1, filter, ext = {}) {
    try {
        let params = ['from=' + (tid || 'qq'), 'limit=24', 'pg=' + (parseInt(pg) || 1)];
        let typeVal = ext && ext.class ? ext.class : '2';
        params.push('t=' + typeVal);
        if (ext && ext.year) params.push('year=' + encodeURIComponent(ext.year));
        const url = baseUrl + apiPath + params.join('&');
        mylog('api category url ->', url);
        const data = await myFetch(url);
        if (!data) throw new Error('API 请求无响应');
        let list = [];
        if (Array.isArray(data?.list)) {
            list = data.list.map(item => ({
                vod_id: item.vod_id, vod_name: item.vod_name,
                vod_pic: item.vod_pic, vod_remarks: item.vod_remarks, vod_year: item.vod_year
            }));
        }
        const pagecount = parseInt(data?.pagecount) || 1;
        return JSON.stringify({ list: list, pagecount: pagecount });
    } catch(e) { return backErr(e, 'category'); }
}

// ========== 搜索 ==========
async function search(keyword, quick, pg) {
    let pgNum = pg ? parseInt(pg) : 1;
    try {
        const url = baseUrl + '/api.php/provide/vod/?ac=detail&wd=' + encodeURIComponent(keyword) + '&pg=' + pgNum;
        mylog('api searchUrl:', url);
        const data = await myFetch(url);
        if (!data) throw new Error('搜索请求未返回数据');
        let list = [];
        if (Array.isArray(data?.list)) {
            list = data.list.map(item => ({
                vod_id: item.vod_id,
                vod_name: item.vod_name || item.name,
                vod_pic: item.vod_pic || item.pic,
                vod_remarks: item.vod_remarks || ''
            })).filter(v => v.vod_id);
        }
        return JSON.stringify({ list: list, pagecount: parseInt(data?.pagecount) || 1 });
    } catch(e) { return backErr(e); }
}

// ========== 播放 ==========
function isDirectVideoUrl(url) {
    return ['.m3u', 'mp4'].some(ext => (url + '').includes(ext));
}

function extractConfig(html) {
    const match = html.match(/apiToken\s*:\s*["']([^"']+)["']/);
    return { apiToken: match ? match[1] : null };
}

function formatUrl(url) {
    return url ? url?.replace(/\\/g, '')?.replace(/^(https?:\/)((?!\/))/i, '$1/') : '';
}

async function parseVideoUrl(url) {
    if (isDirectVideoUrl(url)) { mylog('直链无需解析，直接返回'); return url; }
    const fullUrl = parseApi + url;
    mylog('正在请求解析地址:', fullUrl);
    try {
        const resp = await req(fullUrl, { headers: { 'user-agent': UA } });
        const html = resp?.content || '';
        const { apiToken } = extractConfig(html);
        if (!apiToken) throw new Error('解析源无 token');
        const tokenUrl = 'https://' + parseApi.split('//')[1].split('/')[0] + '/api/resolve.php?token=' + encodeURIComponent(apiToken);
        const tokenResp = await req(tokenUrl, { headers: { 'user-agent': UA } });
        const realUrl = formatUrl(JSON.parse(tokenResp.content).url);
        if (!realUrl) throw new Error('解析源链接为空');
        mylog('解析成功并返回 ->', realUrl);
        return realUrl;
    } catch(e) { mylog('解析失败: ', e.message); return ''; }
}

async function play(flag, url, vipFlags) {
    mylog('开始获取播放地址: ' + url);

    // 1. 直链直接返回
    if (isDirectVideoUrl(url)) {
        return JSON.stringify({ parse: 0, url: url });
    }

    // 2. 外置解析1: 小白
    const parser1 = '解析';
    try {
        const resp1 = await req(parser1 + encodeURIComponent(url), { headers: { 'user-agent': UA } });
        const data1 = safeJsonParse(resp1?.content);
        if (data1 && data1.url) {
            mylog('解析成功:', data1.url);
            return JSON.stringify({ parse: 0, url: data1.url });
        }
    } catch(e) { mylog('解析失败:', e.message); }

    // 3. 外置解析2: kptv (原解析)
    try {
        const realUrl = await parseVideoUrl(url);
        if (realUrl) {
            return JSON.stringify({ parse: 0, url: realUrl });
        }
    } catch(e) { mylog('kptv解析失败:', e.message); }

    // 4. 兜底: 返回原始URL让TVBox嗅探
    return JSON.stringify({ parse: 1, url: url });
}

export default { init, home, homeVod, category, detail, play, search };
