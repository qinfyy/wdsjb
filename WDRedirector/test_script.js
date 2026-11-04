import http from 'node:http';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { gunzipSync, inflateSync } from 'node:zlib';

const root = dirname(fileURLToPath(import.meta.url));
const { values } = parseArgs({ options: {
    host: { type: 'string', default: '0.0.0.0' },
    port: { type: 'string', default: '21000' },
    har: { type: 'string', default: resolve(root, '..', 'Reverse', 'HTTP自动登录.har') },
    report: { type: 'string', default: resolve(root, 'dist', 'redirect-test-report.json') },
    responses: { type: 'string' },
    duration: { type: 'string' },
} });
const port = Number(values.port);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('--port 必须是 1 到 65535 的整数');
const fixtures = values.responses ? JSON.parse(readFileSync(values.responses, 'utf8')) : {};
const har = JSON.parse(readFileSync(values.har, 'utf8'));
const regions = har.log.entries.filter(entry => new URL(entry.request.url).pathname === '/query_region'
    && entry.response.status === 200 && typeof entry.response.content.text === 'string');
if (regions.length === 0) throw new Error('HAR 中没有成功的 /query_region 响应');
const reportPath = resolve(values.report);
const state = { startedAt: new Date().toISOString(), requests: [], regionRequests: 0, loginRequests: 0, sdkRequests: 0 };
const loginPaths = new Set(['/account/ma-cn-passport/app/loginByPassword', '/account/ma-cn-passport/app/loginByMobileCaptcha']);

function persist() {
    mkdirSync(dirname(reportPath), { recursive: true });
    writeFileSync(reportPath, JSON.stringify(state, null, 2) + '\n');
}

function parseBody(buffer, headers) {
    if (headers['content-encoding'] === 'gzip') buffer = gunzipSync(buffer);
    if (headers['content-encoding'] === 'deflate') buffer = inflateSync(buffer);
    const text = buffer.toString('utf8');
    return text;
}

function responseFor(path) {
    if (fixtures[path] !== undefined) return fixtures[path];
    if (loginPaths.has(path) || /\/login$/.test(path)) {
        // 只接收测试请求，不伪造成功账号，也不向官方转发。
        return { retcode: -101, message: 'WDRedirector 测试已收到登录请求', data: {} };
    }
    if (/getConfig|loadConfig/.test(path)) {
        return { retcode: 0, message: 'OK', data: {
            app_name: 'WD', protocol: false, qr_enabled: false, log_level: 'INFO', announce_url: '',
            enable_user_center: true, disable_ysdk_guard: true, functional_switch_configs: {},
            client_type: 1, game_key: 'wd', guest: false, disable_regist: false, enable_email: true,
            enable_ps: true, enable_password: true, enable_phone: true, enable_sms: true,
            enable_realname: false, enable_auth_login: false, enable_captcha: false,
            thirdparty: [], thirdparty_login_configs: [],
        } };
    }
    if (path.includes('/box/api/config/')) return { retcode: 0, message: 'OK', data: { config: '{}' } };
    if (/getSwitchStatus/.test(path)) return { retcode: 0, message: 'OK', data: { switch_status: {}, switch_statuses: [] } };
    if (/getAuthLoginConfig/.test(path)) return { retcode: 0, message: 'OK', data: { enabled: false } };
    if (/preCheck|check$/.test(path)) return { retcode: 0, message: 'OK', data: { id: '', action: 'ACTION_NONE', aigis: '', challenge: '' } };
    if (/getFont/.test(path)) return { retcode: 0, message: 'OK', data: { fonts: [] } };
    return { retcode: 0, message: 'OK', data: {} };
}

const server = http.createServer(async (request, response) => {
    try {
        const url = new URL(request.url, 'http://localhost');
        if (url.pathname === '/__test/status') {
            response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            response.end(JSON.stringify(state));
            return;
        }
        const chunks = [];
        let size = 0;
        for await (const chunk of request) {
            size += chunk.length;
            if (size > 4 * 1024 * 1024) throw new Error('请求超过 4 MiB');
            chunks.push(chunk);
        }
        const body = parseBody(Buffer.concat(chunks), request.headers);
        const isSdk = /\/account\/|\/combo\/|\/mdk\/|\/shield\//.test(url.pathname);
        if (isSdk) state.sdkRequests++;
        const entry = {
            time: new Date().toISOString(), method: request.method, path: url.pathname,
            host: request.headers.host, bytes: size,
        };
        state.requests.push(entry);
        console.log('[收到请求] ' + request.method + ' ' + url.pathname + '，Host=' + request.headers.host);
        if (request.method === 'POST' && loginPaths.has(url.pathname)) {
            state.loginRequests++;
            // 按用户要求只在控制台打印这两个登录入口，报告文件不保存账号字段。
            console.log('[POST 内容] ' + url.pathname + '\n' + body);
        }
        if (state.requests.length > 2000) state.requests.shift();
        if (url.pathname === '/query_region') {
            const entry = regions.find(entry => entry.request.method === request.method
                && new URL(entry.request.url).search === url.search) || regions[regions.length - 1];
            const content = entry.response.content;
            const replay = Buffer.from(content.text, content.encoding === 'base64' ? 'base64' : 'utf8');
            state.regionRequests++;
            persist();
            // HAR content 是解码后的响应体，不回放原有 Content-Encoding / Content-Length。
            response.writeHead(entry.response.status, {
                'Content-Type': content.mimeType || 'application/json',
                'Access-Control-Allow-Origin': '*',
            });
            response.end(replay);
            console.log('[HAR 回放] /query_region，' + replay.length + ' 字节');
            return;
        }
        persist();
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
        response.end(JSON.stringify(responseFor(url.pathname)));
    } catch (error) {
        console.error('[请求错误] ' + error.message);
        response.writeHead(400, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ retcode: -1, message: error.message, data: {} }));
    }
});

server.on('error', error => { console.error('[服务器错误] ' + error.message); process.exitCode = 1; });
server.listen(port, values.host, () => {
    persist();
    console.log('WDRedirector 模拟服务器已启动：http://' + values.host + ':' + port);
    console.log('query_region 回放：' + resolve(values.har));
    console.log('只打印 loginByPassword / loginByMobileCaptcha 的 POST 内容，不校验测试密码。');
    console.log('结果文件：' + reportPath + '；状态接口：/__test/status');
});
function stop() {
    persist();
    server.close();
    server.closeAllConnections();
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
if (values.duration !== undefined) {
    const duration = Number(values.duration);
    if (!Number.isFinite(duration) || duration <= 0) throw new Error('--duration 必须是正秒数');
    setTimeout(stop, duration * 1000).unref();
}
