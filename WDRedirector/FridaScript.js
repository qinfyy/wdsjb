'use strict';

import Java from 'frida-java-bridge';
import { Buffer } from 'buffer';

let CONFIG = __CONFIG_REPLACEMENT__;
CONFIG = JSON.parse(Buffer.from(CONFIG, 'base64').toString('utf8'));

const MAX_STRING_LENGTH = 32768;
const POLL_INTERVAL_MS = 100;

const FUNCTION_SIGNATURES = {
    'il2cpp::vm::String::NewLen': [
        'f5 0f 1d f8 f4 4f 01 a9 fd 7b 02 a9 fd 83 00 91 e1 03 01 2a e8 23 00 91 ?? ?? ?? ?? f4 07 40 f9 95 82 5e b8 e0 03 15 2a ?? ?? ?? ?? f3 03 00 aa e0 03 13 aa ?? ?? ?? ?? a8 7a 1f 53 02 7d 40 93 e1 03 14 aa ?? ?? ?? ?? e8 07 40 f9',
    ],
    'il2cpp::vm::Object::NewAllocSpecific': [
        'f4 4f be a9 fd 7b 01 a9 fd 43 00 91 f3 03 00 aa ?? ?? ?? ?? e0 03 13 aa ?? ?? ?? ?? 80 00 00 36 e0 03 13 aa ?? ?? ?? ?? f3 03 00 aa 68 9a 44 39 a8 00 28 37 e0 03 13 aa ?? ?? ?? ?? f4 03 00 aa 12 00 00 14',
    ],
    // 用选表入口解析 HandleData 和尾跳目标
    'il2cpp::gc::GCHandle::New.anchor': [
        '3f 00 00 72 e8 03 1a 32 e9 07 1b 32 28 11 88 9a ?? ?? ?? ?? ?? ?? ?? ?? 28 01 08 8b e9 03 00 aa e0 03 08 aa e1 03 09 aa e2 03 1f 2a ?? ?? ?? ?? fa 67 bb a9',
    ],
    'il2cpp::gc::GCHandle::AllocHandle': [
        'fa 67 bb a9 f8 5f 01 a9 f6 57 02 a9 f4 4f 03 a9 fd 7b 04 a9 fd 03 01 91 f3 03 00 aa ?? ?? ?? ?? ?? ?? ?? ?? f5 03 02 2a f4 03 01 aa ?? ?? ?? ?? 68 12 40 b9 48 03 00 35 68 52 40 39 e9 03 1b 32 69 12 00 b9 1f 09 00 71 c3 00 00 54 e0 03 18 32 e1 03 1f aa ?? ?? ?? ?? 60 06 00 f9',
    ],
    'il2cpp::gc::GCHandle::Free': [
        'f7 0f 1c f8 f6 57 01 a9 f4 4f 02 a9 fd 7b 03 a9 fd c3 00 91 f3 03 00 2a 68 0a 00 12 16 05 00 51 df 0e 00 71 c9 00 00 54 fd 7b 43 a9 f4 4f 42 a9 f6 57 41 a9 f7 07 44 f8 c0 03 5f d6 ?? ?? ?? ?? ?? ?? ?? ?? 77 7e 03 53 ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? 14 15 16 8b',
    ],
    'UnityWebRequest.SetUrl': [
        'f5 0f 1d f8 f4 4f 01 a9 fd 7b 02 a9 fd 83 00 91 d5 79 02 f0 a2 9e 45 f9 f3 03 01 aa f4 03 00 aa e2 01 00 b5 a0 42 01 d0 00 64 38 91 ?? ?? ?? 97 e2 03 00 aa 22 01 00 b5 a0 42 01 d0 00 64 38 91 e2 07 00 f9 ?? ?? ?? 97',
    ],
    'UnityWebRequest.set_url': [
        'f5 0f 1d f8 f4 4f 01 a9 fd 7b 02 a9 fd 83 00 91 f5 79 02 90 a8 a6 6c 39 f4 03 01 aa f3 03 00 aa e8 00 00 37 48 4e 02 d0 08 09 41 f9 00 01 40 b9 ?? ?? ?? 97 e8 03 00 32 a8 a6 2c 39',
    ],
    'WebRequestUtils.MakeInitialUrl': [
        'f9 0f 1b f8 f8 5f 01 a9 f6 57 02 a9 f4 4f 03 a9 fd 7b 04 a9 fd 03 01 91 d4 79 02 f0 88 7a 70 39 f5 03 01 aa f3 03 00 aa e8 00 00 37 68 50 02 b0 08 81 44 f9 00 01 40 b9 ?? ?? ?? 97 e8 03 00 32 88 7a 30 39',
    ],
    'BestHTTP.HTTPRequest.ctor': [
        'f8 5f bc a9 f6 57 01 a9 f4 4f 02 a9 fd 7b 03 a9 fd c3 00 91 98 94 03 90 08 47 74 39 f5 03 05 aa f6 03 03 2a f4 03 02 2a f7 03 01 aa f3 03 00 aa e8 00 00 37 88 5f 03 d0 08 45 46 f9',
    ],
    'System.Uri.ctor': [
        'f5 0f 1d f8 f4 4f 01 a9 fd 7b 02 a9 fd 83 00 91 55 5d 03 90 a8 12 4c 39 f3 03 01 aa f4 03 00 aa e8 00 00 37 68 38 03 90 08 dd 46 f9 00 01 40 b9 ?? ?? ?? 97 e8 03 00 32 a8 12 0c 39',
    ],
    'System.Uri.get_OriginalString': [
        'f3 0f 1e f8 fd 7b 01 a9 fd 43 00 91 f3 03 00 aa ?? ?? ?? 94 68 62 00 91 69 42 00 91 1f 00 00 72 08 11 89 9a 00 01 40 f9 fd 7b 41 a9 f3 07 42 f8',
    ],
};

// 仅覆盖反编译中已确认的账号 SDK 字符串入口，不修改通用加密 API。
const SDK_RSA_METHODS = [
    { className: 'com.mihoyo.platform.account.sdk.utils.RSAUtils', arguments: ['java.lang.String'] },
    { className: 'com.miHoYo.support.utils.RSAUtils', arguments: ['java.lang.String', 'java.lang.String'] },
];
const reported = new Set();
let stringNewLen = null;
let nativeBridgeReplacement = null;

function report(event, message) {
    send({ event: event, message: message });
}

function reportOnce(key, event, message) {
    if (!reported.has(key)) {
        reported.add(key);
        report(event, message);
    }
}

function redirectUrl(original) {
    if (typeof original !== 'string') {
        return null;
    }
    const match = /^(https?):\/\/([^/?#]+)([^#]*)(#.*)?$/i.exec(original);
    if (match === null) {
        return null;
    }
    const origin = (match[1] + '://' + match[2]).toLowerCase();
    if (origin === CONFIG.httpUrlBase.toLowerCase()) {
        return null;
    }
    const host = match[2].split('@').pop().toLowerCase();
    if (/^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)) {
        return null;
    }
    const path = match[3].startsWith('/') ? match[3] : '/' + match[3];
    return CONFIG.httpUrlBase + path + (match[4] || '');
}

function readIl2CppString(value) {
    if (value.isNull()) {
        return null;
    }
    const length = value.add(0x10).readS32();
    if (length < 0 || length > MAX_STRING_LENGTH) {
        return null;
    }
    return value.add(0x14).readUtf16String(length);
}

function signatureAddress(module, name) {
    const ranges = module.enumerateRanges('r-x');
    if (CONFIG.emulator) {
        ranges.push(...module.enumerateRanges('r--'));
    }
    for (const pattern of FUNCTION_SIGNATURES[name]) {
        const matches = new Map();
        for (const range of ranges) {
            for (const match of Memory.scanSync(range.base, range.size, pattern)) {
                matches.set(match.address.toString(), match.address);
            }
        }
        if (matches.size > 1) {
            throw new Error(name + ' 特征命中 ' + matches.size + ' 次，拒绝安装 Hook');
        }
        if (matches.size === 0) {
            continue;
        }
        const address = matches.values().next().value;
        const range = Process.findRangeByAddress(address);
        if (range === null || (!CONFIG.emulator && !range.protection.includes('x'))) {
            throw new Error(name + ' 地址不可执行：' + address);
        }
        report('address', '[地址] ' + name + ' = ' + address + '，RVA=' + address.sub(module.base));
        return address;
    }
    throw new Error(name + ' 特征未命中');
}

function createIl2CppString(value) {
    const result = stringNewLen(Memory.allocUtf8String(value), Buffer.byteLength(value, 'utf8'));
    if (result.isNull()) {
        throw new Error('il2cpp::vm::String::NewLen 返回空指针');
    }
    return result;
}

function resolveGcHandleAllocator(module) {
    const allocator = signatureAddress(module, 'il2cpp::gc::GCHandle::AllocHandle');
    const anchor = signatureAddress(module, 'il2cpp::gc::GCHandle::New.anchor');
    const normal = Instruction.parse(anchor.add(0x04));
    const page = Instruction.parse(anchor.add(0x10));
    const offset = Instruction.parse(anchor.add(0x14));
    const branch = Instruction.parse(anchor.add(0x2c));
    if (normal.mnemonic !== 'mov' || normal.operands[0].value !== 'w8' || normal.operands[1].type !== 'imm'
            || page.mnemonic !== 'adrp' || page.operands[0].value !== 'x9' || page.operands[1].type !== 'imm'
            || offset.mnemonic !== 'add' || offset.operands[0].value !== 'x9' || offset.operands[1].value !== 'x9'
            || offset.operands[2].type !== 'imm' || (offset.operands[2].shift && offset.operands[2].shift.value !== 0)
            || branch.mnemonic !== 'b' || branch.operands[0].type !== 'imm') {
        throw new Error('GCHandle 选表/尾跳指令不符合预期');
    }
    const target = ptr(branch.operands[0].value.toString());
    if (!target.equals(allocator)) {
        throw new Error('GCHandle 尾跳目标与核心 allocator 特征不一致：' + target);
    }
    // 从 ADRP + ADD + NORMAL 偏移获取表地址，不能硬编码全局 RVA。
    const normalHandles = ptr(page.operands[1].value.toString())
        .add(offset.operands[2].value.toNumber()).add(normal.operands[1].value.toNumber());
    if (normalHandles.compare(module.base) < 0 || normalHandles.add(0x20).compare(module.base.add(module.size)) > 0
            || normalHandles.add(0x14).readU8() !== 2) {
        throw new Error('GCHandle NORMAL 表地址或类型不符合预期：' + normalHandles);
    }
    report('address', '[地址] GCHandle NORMAL HandleData = ' + normalHandles + '，RVA=' + normalHandles.sub(module.base));
    return { allocator: allocator, normalHandles: normalHandles };
}

function installUnityWebRequestHook(module) {
    if (Process.arch !== 'arm64' || Process.pointerSize !== 8) {
        throw new Error('UnityWebRequest Hook 仅支持 ARM64 Realm');
    }
    const constructor = signatureAddress(module, 'il2cpp::vm::String::NewLen');
    const setUrl = signatureAddress(module, 'UnityWebRequest.SetUrl');
    const setter = signatureAddress(module, 'UnityWebRequest.set_url');
    const initialUrl = signatureAddress(module, 'WebRequestUtils.MakeInitialUrl');
    stringNewLen = new NativeFunction(constructor, 'pointer', ['pointer', 'uint']);
    const callbacks = {
        onEnter: function (args) {
            try {
                const original = readIl2CppString(args[1]);
                const redirected = redirectUrl(original);
                if (redirected === null) {
                    return;
                }
                args[1] = createIl2CppString(redirected);
                // URL 查询参数可能包含令牌，日志只保留路径。
                const path = original.split(/[?#]/)[0];
                reportOnce(path, 'redirect', '[重定向] UnityWebRequest.SetUrl: ' + path + ' -> ' + redirected.split(/[?#]/)[0]);
            } catch (error) {
                reportOnce('url-error', 'error', '[错误] URL 改写失败：' + String(error));
            }
        },
    };
    Interceptor.attach(setUrl, callbacks);
    Interceptor.attach(setter, callbacks);
    Interceptor.attach(initialUrl, {
        onLeave: function (retval) {
            try {
                const original = readIl2CppString(retval);
                const redirected = redirectUrl(original);
                if (redirected !== null) {
                    retval.replace(createIl2CppString(redirected));
                    reportOnce(original.split(/[?#]/)[0], 'redirect', '[重定向] WebRequestUtils.MakeInitialUrl: ' + original.split(/[?#]/)[0] + ' -> ' + redirected.split(/[?#]/)[0]);
                }
            } catch (error) {
                reportOnce('initial-url-error', 'error', '[错误] URL 规范化改写失败：' + String(error));
            }
        },
    });
    report('native-ready', '[就绪] UnityWebRequest Hook，HTTP -> ' + CONFIG.httpUrlBase);
}

function waitForUnityWebRequest() {
    function attempt() {
        const module = Process.findModuleByName('libil2cpp.so');
        if (module === null) {
            return false;
        }
        installUnityWebRequestHook(module);
        installBestHttpHook(module);
        return true;
    }
    if (!attempt()) {
        const poller = setInterval(function () {
            try {
                if (attempt()) {
                    clearInterval(poller);
                }
            } catch (error) {
                clearInterval(poller);
                report('error', '[错误] Native HTTP Hook 安装失败：' + String(error));
            }
        }, POLL_INTERVAL_MS);
    }
}

function installBestHttpHook(module) {
    const requestConstructor = signatureAddress(module, 'BestHTTP.HTTPRequest.ctor');
    const uriConstructor = new NativeFunction(signatureAddress(module, 'System.Uri.ctor'), 'void', ['pointer', 'pointer', 'pointer']);
    const originalString = new NativeFunction(signatureAddress(module, 'System.Uri.get_OriginalString'), 'pointer', ['pointer', 'pointer']);
    const objectNew = new NativeFunction(signatureAddress(module, 'il2cpp::vm::Object::NewAllocSpecific'), 'pointer', ['pointer']);
    const { allocator, normalHandles } = resolveGcHandleAllocator(module);
    const handleNew = new NativeFunction(allocator, 'uint', ['pointer', 'pointer', 'uint8']);
    const handleFree = new NativeFunction(signatureAddress(module, 'il2cpp::gc::GCHandle::Free'), 'void', ['uint']);
    Interceptor.attach(requestConstructor, {
        onEnter: function (args) {
            this.handles = [];
            try {
                if (args[1].isNull()) {
                    return;
                }
                const original = readIl2CppString(originalString(args[1], ptr(0)));
                const redirected = redirectUrl(original);
                if (redirected === null) {
                    return;
                }
                const text = createIl2CppString(redirected);
                this.handles.push(handleNew(normalHandles, text, 0));
                // 新建 Uri
                const uri = objectNew(args[1].readPointer());
                if (uri.isNull()) {
                    throw new Error('il2cpp::vm::Object::NewAllocSpecific 返回空指针');
                }
                this.handles.push(handleNew(normalHandles, uri, 0));
                uriConstructor(uri, text, ptr(0));
                args[1] = uri;
                const path = original.split(/[?#]/)[0];
                reportOnce('best-http:' + path, 'redirect', '[重定向] BestHTTP.HTTPRequest: ' + path + ' -> ' + redirected.split(/[?#]/)[0]);
            } catch (error) {
                reportOnce('best-http-error', 'error', '[错误] BestHTTP URI 改写失败：' + String(error));
            }
        },
        onLeave: function () {
            // HTTPRequest 构造后持有 Uri 引用，释放构造期间的临时 GC 根。
            for (const handle of this.handles) {
                handleFree(handle);
            }
        },
    });
    report('native-ready', '[就绪] BestHTTP Native HTTP Hook，HTTP -> ' + CONFIG.httpUrlBase);
}

function redirectSdkUrl(value, label) {
    if (value === null) {
        return null;
    }
    const original = String(value);
    const match = /^https?:\/\/([^/?#]+)/i.exec(original);
    if (match === null || !/(^|\.)(mihoyo\.com|hoyoverse\.com)(:\d+)?$/i.test(match[1])) {
        return null;
    }
    const redirected = redirectUrl(original);
    if (redirected !== null) {
        reportOnce(label + original.split(/[?#]/)[0], 'java-redirect', '[重定向] Java SDK ' + label + ': ' + original.split(/[?#]/)[0] + ' -> ' + redirected.split(/[?#]/)[0]);
    }
    return redirected;
}

function installJavaSdkRedirector() {
    Java.perform(function () {
        let porte = null;
        let envHooked = false;
        const fields = ['loginBaseUrl', 'cdnBaseUrl', 'dataUploadUrl', 'webPlatBaseUrl', 'forgetPwdHost', 'accountAppealUrl', 'commonProblemUrl'];
        function rewritePorte() {
            for (const name of fields) {
                const value = porte[name].value;
                const redirected = redirectSdkUrl(value, 'PorteInfo.' + name);
                if (redirected !== null) {
                    porte[name].value = redirected;
                }
            }
        }
        function attempt() {
            if (!envHooked) {
                try {
                    const env = Java.use('com.mihoyo.combo.config.EnvConfig');
                    const url = env.url.overload('java.lang.String');
                    url.implementation = function (key) {
                        const original = url.call(this, key);
                        return redirectSdkUrl(original, 'EnvConfig.url(' + key + ')') || original;
                    };
                    envHooked = true;
                    report('java-ready', '[就绪] Java SDK EnvConfig URL 重定向');
                } catch (_) {
                    reportOnce('env-wait', 'waiting', '[等待] Java SDK EnvConfig');
                }
            }
            if (porte === null) {
                try {
                    porte = Java.use('com.mihoyo.platform.account.sdk.PorteInfo');
                    const setup = porte.setup.overload('android.content.Context', 'com.mihoyo.platform.account.sdk.PorteConfig');
                    setup.implementation = function (context, config) {
                        const result = setup.call(this, context, config);
                        rewritePorte();
                        return result;
                    };
                    report('java-ready', '[就绪] Java SDK PorteInfo URL 守护');
                } catch (_) {
                    porte = null;
                    reportOnce('porte-wait', 'waiting', '[等待] Java SDK PorteInfo');
                }
            }
            if (porte !== null) {
                rewritePorte();
            }
        }
        attempt();
        // 配置会在回登录页时重新初始化，持续守护七个字段。
        setInterval(function () { Java.perform(attempt); }, POLL_INTERVAL_MS);
    });
}

function installJavaRsaBypass() {
    if (!Java.available) {
        throw new Error('当前 Realm 没有可用的 Java VM');
    }
    Java.perform(function () {
        const pending = new Set(SDK_RSA_METHODS);
        function attempt() {
            for (const item of pending) {
                try {
                    const rsa = Java.use(item.className);
                    const method = rsa.encryptByPublicKey.overload(...item.arguments);
                    method.implementation = function (data) {
                        reportOnce(item.className + ':hit', 'rsa-bypass', '[命中] RSA Bypass: ' + item.className);
                        return data;
                    };
                    pending.delete(item);
                    report('rsa-ready', '[就绪] RSA Bypass: ' + item.className);
                } catch (error) {
                    reportOnce(item.className + ':wait', 'waiting', '[等待] SDK RSA 类或方法尚未加载：' + item.className);
                }
            }
            return pending.size === 0;
        }
        if (!attempt()) {
            const poller = setInterval(function () {
                Java.perform(function () {
                    if (attempt()) {
                        clearInterval(poller);
                    }
                });
            }, POLL_INTERVAL_MS);
        }
    });
}

function installEmulatedRealmLoader() {
    const bridge = Process.getModuleByName('libnativebridge.so');
    const create = new NativeFunction(bridge.getExportByName('NativeBridgeCreateNamespace'), 'pointer', ['pointer', 'pointer', 'pointer', 'uint64', 'pointer', 'pointer']);
    const address = bridge.getExportByName('NativeBridgeLoadLibrary');
    const original = new NativeFunction(address, 'pointer', ['pointer', 'int']);
    const loadExt = new NativeFunction(bridge.getExportByName('NativeBridgeLoadLibraryExt'), 'pointer', ['pointer', 'int', 'pointer']);
    const agentPath = CONFIG.emulatedAgentPath;
    const directory = agentPath.slice(0, agentPath.lastIndexOf('/'));
    const ns = create(Memory.allocUtf8String('wd-redirector-emulated'), Memory.allocUtf8String(directory),
        Memory.allocUtf8String(directory + ':/system/lib64/arm64:/system_ext/lib64/arm64'), 0,
        Memory.allocUtf8String(directory + ':/system'), ptr(0));
    if (ns.isNull()) {
        throw new Error('NativeBridgeCreateNamespace 返回空指针');
    }
    nativeBridgeReplacement = new NativeCallback(function (path, flags) {
        if (path.readCString() === agentPath) {
            return loadExt(path, flags, ns);
        }
        return original(path, flags);
    }, 'pointer', ['pointer', 'int']);
    Interceptor.replace(address, nativeBridgeReplacement);
    report('bridge-ready', '[就绪] Native Bridge ARM64 agent 加载器');
}

function waitForEmulatedRealmLoader() {
    const poller = setInterval(function () {
        const bridge = Process.findModuleByName('libnativebridge.so');
        if (bridge === null) {
            return;
        }
        // 只在 guest IL2CPP 已映射后探测 Emulated Realm，避免 Houdini 早期 linker 崩溃。
        if (!Process.enumerateRanges('r--').some(function (range) {
                return range.file && /\/libil2cpp\.so$/.test(range.file.path);
            })) {
            return;
        }
        clearInterval(poller);
        try {
            installEmulatedRealmLoader();
        } catch (error) {
            report('error', '[错误] Native Bridge 初始化失败：' + String(error));
        }
    }, POLL_INTERVAL_MS);
}

function start() {
    const role = CONFIG.runtimeRole || (CONFIG.emulator ? (Process.arch === 'arm64' ? 'il2cpp' : 'platform') : 'all');
    if (role !== 'il2cpp') {
        installJavaSdkRedirector();
        if (CONFIG.useJavaBypassRsa !== false) {
            installJavaRsaBypass();
        }
        if (CONFIG.emulator) {
            waitForEmulatedRealmLoader();
        }
    }
    if (role !== 'platform') {
        waitForUnityWebRequest();
    }
    report('script-ready', '[就绪] WDRedirector 脚本已自动启动');
}

try {
    start();
} catch (error) {
    report('error', '[错误] WDRedirector 启动失败：' + String(error.stack || error));
}
