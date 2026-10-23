// 引入fongmi/ok壳环境自带的加密库
import 'assets://js/lib/crypto-js.js';

// 获取调用者函数名的公共辅助函数
function getCallerFunctionName() {
    try {
        const stackLines = new Error().stack?.split('\n') || [];
        // stackLines[0] 是 Error 本身，stackLines[1] 是当前辅助函数，stackLines[2] 才是真正的调用者
        if (stackLines.length > 2) {
            const match = stackLines[2].match(/at\s+([^\s]+)\s+/);
            if (match && match[1]) {
                return match[1];
            }
        }
    } catch (e) {
        // 捕获异常防错
    }
    return 'anonymous';
}

function backErr(err) {
    const functionName = getCallerFunctionName();
    console.log(`backErr in ${functionName} err:`, err);
    return JSON.stringify({ msg: err?.message });
}

function mylog(...args) {
    const functionName = getCallerFunctionName();
    console.log(`【${Tag}】[${functionName}方法打印日志]`, ...args);
}

// 生成 32 位随机十六进制 Nonce
function generateNonce() {
    let result = '';
    const characters = '0123456789abcdef';
    for (let i = 0; i < 32; i++) {
        result += characters.charAt(Math.floor(Math.random() * characters.length));
    }
    return result;
}
const Tag = '看剧ai'
const baseUrl = 'https://kanju.ai'


let CK = ``
//封装带动态签名的请求函数
async function requestWithSign(urlStr, options = {}, needSign = true) {
    const method = (options?.method || 'GET').toUpperCase();
    if (!needSign) {
        let res = await http(urlStr, {
            method: method,
            ...options,
            headers: options?.headers,
        });
        return typeof res.content === 'string' ? JSON.parse(res.content) : res.content;
    }
    const SECRET_KEY = '557d0e4ae929f438da6bd84412374e6086b8af09b3fed54bf22601d5bf8c54a0';

    const cleanUrl = urlStr.replace(/^https?:\/\/[^\/]+/, '');
    const pathAndQuery = cleanUrl.split('?')[0] + (cleanUrl.includes('?') ? '?' + cleanUrl.split('?')[1] : '');

    const timestamp = Date.now().toString();
    const nonce = generateNonce();

    let payload = `${method}\n${pathAndQuery}\n${timestamp}\n${nonce}`;
    const signature = CryptoJS.HmacSHA256(payload, SECRET_KEY).toString(CryptoJS.enc.Hex);

    const reqHeaders = {
        'accept': 'application/json',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36',
        'x-ai-movie-build-version': 'dianyingtiantang-v2026.09.15.3-774bcc0013f5-web',
        'x-ai-movie-client-name': 'dianyingtiantang-frontend',
        'x-ai-movie-client-version': '1.0.0',
        'x-ai-movie-protocol-version': '2026-07-05.library-v2.playback-v1',
        'x-ai-movie-timestamp': timestamp,
        'x-ai-movie-nonce': nonce,
        'x-ai-movie-signature': signature,
        "cookie": CK,
        ...options?.headers
    };

    let finalOptions = {
        method: method,
        ...options,
        headers: reqHeaders,
    };

    if (['POST', 'PUT', 'PATCH'].includes(method) && options.data) {
        finalOptions.headers['content-type'] = 'application/json; charset=utf-8';
        finalOptions.body = typeof options.data === 'object' ? JSON.stringify(options.data) : options.data;
        delete finalOptions.data;
    }

    let res = await http(urlStr, finalOptions);
    return typeof res.content === 'string' ? JSON.parse(res.content) : res.content;
}


async function resolveLineUrl(targetLine) {
    if (!targetLine) return "";

    mylog('正在解析指定线路:', targetLine.display_label || targetLine.provider_name, 'url:', targetLine.url);

    // 情况 A：直连 M3U8
    if (targetLine.url_kind === 'm3u8' && !targetLine.resolve_required) {
        return targetLine.url;
    }
    // 情况 B：票据源二次解析
    else if (targetLine.url_kind === 'resolve_ticket' || targetLine.resolve_required) {
        let ticket = targetLine.url.replace('resolve://', '');
        let lineRes = await requestWithSign(`${baseUrl}/v1/playback/resolve-line?view=compact`, {
            method: 'POST',
            data: { ticket: ticket }
        });

        mylog("票据源二次解析 lineRes", lineRes)
        if (lineRes.message) {
            throw new Error(lineRes.message)
        }
        if (lineRes && lineRes.line && lineRes.line.url) {
            return lineRes.line.url;
        }
    }
    return "";
}


function mapCard2Vod(card) {

    let playable = card?.availability?.playable
    return {
        vod_id: playable ? card.id : card?.availability?.label,
        vod_name: card.title,
        vod_pic: card.poster_url,
        vod_year: card.year,
        vod_remarks: playable ? card.remarks || card.updated_at || card.language : card?.availability?.label,
        // style: {
        //     type: "rect",
        //     ratio: 1.78
        // }
    };
}
async function homeVod() {
    try {
        let videos = [];
        let next_cursor = null;
        let isFirstRequest = true;

        do {
            let url = isFirstRequest
                ? `${baseUrl}/v1/feed/home?scope=public&mode=preview&sections=3&cards=10`
                : `${baseUrl}/v1/feed/home?scope=public&mode=page&sections=3&cards=12&cursor=${next_cursor}`;

            isFirstRequest = false;

            let data = await requestWithSign(url);

            if (!data || !data.sections) break;

            // 优化点：使用传统 for 循环代替 forEach，性能更高
            let sections = data.sections;
            for (let i = 0, secLen = sections.length; i < secLen; i++) {
                let cards = sections[i].cards;
                if (!cards) continue;

                for (let j = 0, cardLen = cards.length; j < cardLen; j++) {
                    let card = cards[j];
                    videos.push(mapCard2Vod(card));
                }
            }

            next_cursor = data.next_cursor;

        } while (next_cursor);

        return JSON.stringify({ list: videos });
    } catch (error) {
        return backErr(error);
    }
}
async function init(ext) {
    let cookie = ext.cookie?.trim() || ''
    mylog({ cookie })
    if (cookie.includes("http") || cookie.includes('file://')) {
        cookie = await req(ext.cookie).content
    }
    CK = cookie
}
async function home(ext) {
    return JSON.stringify({
        class: [
            { type_id: 'sort', type_name: '大家都在看(榜单筛选)' },
            { type_id: 'tv_animation', type_name: '动漫新番' },
            { type_id: 'tv_domestic', type_name: '国产新剧' },
            { type_id: 'movie_high_score', type_name: '高分电影' },
            { type_id: 'movie_hot', type_name: '电影热播' },
            { type_id: 'movie_upcoming', type_name: '即将上映(仅展示)' },
            { type_id: 'movie_hidden_gems', type_name: '冷门好片' },
            { type_id: 'tv_korean', type_name: '韩剧在追' },
            { type_id: 'tv_japanese', type_name: '日剧上新' },
            { type_id: 'tv_american', type_name: '美剧续看' },
            { type_id: 'movie_nowplaying', type_name: '院线热映' },
            { type_id: 'show', type_name: '综艺下饭' },
        ],
        filters: {
            "sort": [
                { key: "window", name: "榜单", value: [{ n: "日榜", v: "day" }, { n: "周榜", v: "week" }, { n: "月榜", v: "month" }, { n: "总榜", v: "total" }] },
                { key: "kind", name: "内容", value: [{ "n": "全部", "v": "" }, { n: "电影", v: "movie" }, { n: "剧集", v: "series" }, { n: "短剧", v: "short_drama" }, { n: "动漫", v: "anime" }, { n: "综艺", v: "variety" }] }
            ]
        }
    });
}

async function category(tid, pg, filter, ext) {
    try {
        let categoryUrl = '';

        // 1. 处理“大家都在看”榜单（带有筛选参数 filter/ext）
        if (tid === 'sort') {
            mylog('大家都在看 榜单');
            let windowType = ext?.window || 'day';
            let kindType = ext?.kind || '';

            categoryUrl = `${baseUrl}/v1/browse/catalog?sort=trending&window=${windowType}&page=${pg}&limit=20&kind=${kindType}`;
        } else {
            // 2. 处理其他常规分类列表
            categoryUrl = `${baseUrl}/v1/browse/catalog?hot_list_key=${tid}&page=${pg}&limit=20`;
        }
        // https://kanju65.com/v1/browse/catalog?hot_list_key=movie_upcoming&include_unavailable=true&page=2&limit=20&offset=
        if (tid === 'movie_upcoming') {
            categoryUrl += '&include_unavailable=true'
        }
        mylog({ categoryUrl });
        let data = await requestWithSign(categoryUrl);

        let cards = data?.cards||[]

        if (tid === 'movie_upcoming') {
           cards = cards?.filter(item=>!item.availability.playable)
        }

        let videos =cards ? cards.map(card => mapCard2Vod(card)) : [];

        mylog(videos.length, videos[0]);

        let hasMore = videos.length > 0;
        let pageCount = hasMore ? pg + 1 : pg;
        return JSON.stringify({
            list: videos,
            pagecount: pageCount
        });

    } catch (error) {
        mylog('Category Error: ' + error);
        return JSON.stringify({ list: [], pagecount: pg });
    }
}

async function search(keyword, quick, pg) {

    try {
        if (pg > 1) {
            return JSON.stringify({ list: [] })
        }
        let url = `${baseUrl}/v1/threads`;
        let postData = {
            "title": keyword,
            "metadata": {
                "search_fields": "title",
                "search_scope_label": "影片名",
                "search_mode": "fast",
                "source": "movie_composer_route",
                "submission_id": "64d8a1a6-598e-4ec1-90c0-faf61a68dde1"
            }
        };

        let res = await requestWithSign(url, { method: "post", data: postData });
        let thread_id = res.id;

        if (!thread_id) {
            return JSON.stringify({ list: [] });
        }

        let searchUrl = `${baseUrl}/v1/browse/catalog?page=${pg || 1}&limit=20&query_mode=fast_v3&thread_id=${thread_id}&search_fields=title&q=${encodeURIComponent(keyword)}`;
        let searchRes = await requestWithSign(searchUrl);

        let cards = searchRes.cards || [];
        let videos = [];

        cards.forEach(card => {
            videos.push(mapCard2Vod(card));
        });

        return JSON.stringify({ list: videos, pagecount: 1 });
    } catch (e) {
        return backErr(e)
    }
}

async function detail(id) {
    try {

        if (!id.startsWith('av_')) {
            throw new Error(id)
        }
        let detailUrl = `${baseUrl}/v1/catalog/${id}/detail`;
        let episodesUrl = `${baseUrl}/v1/catalog/${id}/episodes?limit=9999&offset=0`;

        let [detailRes, episodesRes] = await Promise.all([
            requestWithSign(detailUrl),
            requestWithSign(episodesUrl)
        ]);

        let vodInfo = detailRes || {};
        let episodes = episodesRes.episodes || [];

        if (episodes.length === 0) {
            throw new Error("未获取到任何剧集信息");
        }

        let sampleToken = episodes[0].token;
        let resolveRes = await requestWithSign(`${baseUrl}/v1/playback/resolve/${sampleToken}`);
        let sampleLineOptions = resolveRes.line_options || [];

        mylog("sampleLineOptions label", sampleLineOptions.map(item => item.display_label || item.provider_name));

        if (sampleLineOptions.length === 0) {
            throw new Error("当前影片没有找到任何可用的播放线路");
        }

        // 线路排序规则：4K优先 > 官方优先 > 在线优先 > 其他
        sampleLineOptions.sort((a, b) => {
            let nameA = (a.display_label || a.provider_name || '')
            let nameB = (b.display_label || b.provider_name || '')

            // 计算权重函数
            function getScore(name) {
                name = name.toLowerCase()
                if (name.includes('4k') || name.includes('超清')) return 5;
                if (name.includes('官方') && name.includes('1080')) return 4;
                if (name.includes('1080')) return 3;
                if (name.includes('资源')) return 2;
                return 1;
            }

            let scoreA = getScore(nameA);
            let scoreB = getScore(nameB);

            return scoreB - scoreA; // 权重高的排在前面
        });

        let activeLines = sampleLineOptions.slice(0, 10);
        let playSources = activeLines.map(line => line.display_label || line.provider_name || '默认线路');

        let episodesList = [];
        episodes.forEach(ep => {
            let epTitle = ep.title || `第${ep.number}集`;
            let epToken = ep.token;
            if (epToken) {
                episodesList.push(`${epTitle}$${epToken}`);
            }
        });

        let playUrlSingle = episodesList.join('#');
        let playFromList = playSources.join('$$$');
        let playUrl = playSources.map(() => playUrlSingle).join('$$$');

        let vod = {
            vod_id: vodInfo.id || id,
            vod_name: vodInfo.title || '',
            vod_pic: vodInfo.poster_url || '',
            type_name: vodInfo.genres ? vodInfo.genres.join(',') : '',
            vod_remarks: vodInfo.remarks || '',
            vod_year: vodInfo.year || '',
            vod_area: vodInfo.area || '',
            vod_actor: vodInfo.actors ? vodInfo.actors.join(',') : '',
            vod_director: vodInfo.directors ? vodInfo.directors.join(',') : '',
            vod_content: vodInfo.description || '',
            vod_play_from: playFromList,
            vod_play_url: playUrl
        };

        return JSON.stringify({ list: [vod] });
    } catch (e) {
        return backErr(e)
    }
}

async function play(flag, id, vipFlags) {
    try {
        mylog('play start, flag:', flag, 'id:', id);
        let resolveUrl = `${baseUrl}/v1/playback/resolve/${id}`;
        let resolveRes = await requestWithSign(resolveUrl);
        let lineOptions = resolveRes.line_options || [];

        if (lineOptions.length === 0) {
            throw new Error("当前集数没有找到任何可用的播放线路");
        }
        let targetLine = null;
        if (flag) {
            targetLine = lineOptions.find(line =>
                (line.display_label === flag) || (line.provider_name === flag)
            );
        }
        // 仅解析目标线路
        let finalPlayUrl = await resolveLineUrl(targetLine);

        if (!finalPlayUrl) {
            throw new Error(`所选线路 [${flag || targetLine.display_label || '默认线路'}] 解析失败`);
        }
        mylog('播放地址解析成功:', finalPlayUrl);
        return JSON.stringify({
            parse: 0,
            url: finalPlayUrl,
            header: {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
            }
        });

    } catch (e) {
        return backErr(e);
    }
}

export default { init, home, category, detail, homeVod, search, play };