'use strict';

import Java from 'frida-java-bridge';

let CONFIG = null;
let TARGET = null;
const MODULE_WAIT_TIMEOUT_MS = 30000;
const MAX_STRING_LENGTH = 32768;
const MAX_MANAGED_REWRITE_PASSES = 180;
const MAX_MANAGED_RANGE_SIZE = 64 * 1024 * 1024;
const MAX_INFLATE_OUTPUT_SIZE = 512 * 1024;
const JAVA_CONFIG_REWRITE_INTERVAL_MS = 100;
const EMULATED_NAMESPACE_DIRECTORY = '/data/local/tmp/re.frida.server';

const TARGETS = {
    x86: {
        processArch: 'ia32',
        pointerSize: 4,
        il2CppString: {
            length: 0x08,
            chars: 0x0c,
        },
        zlibStream: {
            nextOut: 0x0c,
            availOut: 0x10,
        },
        baseNetworkClient: {
            serverAddress: 0x14,
            serverAddressV6: 0x18,
            serverPort: 0x1c,
        },
    },
    'arm64-v8a': {
        processArch: 'arm64',
        pointerSize: 8,
        il2CppString: {
            length: 0x10,
            chars: 0x14,
        },
        zlibStream: {
            nextOut: 0x18,
            availOut: 0x20,
        },
        baseNetworkClient: {
            serverAddress: 0x20,
            serverAddressV6: 0x28,
            serverPort: 0x30,
        },
    },
};

// 每个候选在已验证的同 ABI 客户端中均唯一命中；相对调用和布局相关字段使用 ?? 掩码。
// 运行时不判断客户端版本，按候选顺序扫描并且只接受唯一命中的地址。
const FUNCTION_SIGNATURES = {
    x86: {
        // Il2CppString* il2cpp_string_new(const char* str);
        il2cpp_string_new:
            '55 8d 2c 24 53 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 8b 45 08 81 c3 ?? ?? ?? 08 89 04 24 e8 2c 83 02 00 8d 65 fc 5b 5d c3 55 8d 2c 24 53 83 e4',
        // Il2CppString* il2cpp_string_new_utf16(const Il2CppChar* text, int32_t len);
        il2cpp_string_new_utf16:
            '55 8d 2c 24 53 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 8b 45 08 8b 4d 0c 81 c3 ?? ?? ?? 08 8d 64 24 f8 51 50 e8 6a ab 03 00 8d 64 24 10 8d 65 fc',
        // internal static string MakeInitialUrl(string targetUrl, string localUrl);
        'WebRequestUtils.MakeInitialUrl':
            '55 89 e5 53 57 56 83 e4 f0 8d 64 24 e0 e8 00 00 00 00 5b 8b 75 08 81 c3 ?? ?? ?? 04 80 bb ?? ?? 48 00 00 75 1d 8b 83 ?? ?? f3 ff 8b 00 8d 64 24 f4 50 e8 ?? ?? ?? fb 8d 64 24 10 c6 83 ?? ?? 48 00 01 8d 64 24 f8 6a 00 56 e8 ?? c2 fd fe 8d 64',
        // public void set_url(string value);
        'UnityWebRequest.set_url':
            '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 04 80 bb ?? ?? 48 00 00 75 17 8b 83 ?? ?? f3 ff 8b 00 89 04 24 e8 ?? ?? ?? fb c6 83 ?? ?? 48 00 01 8b 83 ?? ?? f3 ff 8b 8b ?? ?? f3 ff 8b 7d 0c 8b 00 8b 31 f6 80 bb 00',
        // protected virtual void LoadDefaultServerInfo();
        'BaseNetworkClient.LoadDefaultServerInfo':
            '55 89 e5 53 57 56 83 e4 f0 8d 64 24 e0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 01 80 bb ?? ?? 5d 00 00 75 17 8b 83 ?? ?? fa ff 8b 00 89 04 24 e8 ?? ?? 5f f9 c6 83 ?? ?? 5d 00 01 8b 7d 08 c7 44 24 04 00 00 00 00 c7 04 24 9c 00 00 00 e8 ?? ?? ?? fa',
        // public bool SetNetAddrPort(string addr, string addrV6, int port);
        'BaseNetworkClient.SetNetAddrPort':
            '55 89 e5 53 57 56 83 e4 f0 8d 64 24 e0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 01 80 bb ?? ?? 5d 00 00 75 1d 8b 83 ?? ?? fa ff 8b 00 8d 64 24 f4 50 e8 ?? ?? 5f f9 8d 64 24 10 c6 83 ?? ?? 5d 00 01 8b 75 14 8b 7d 08 8d 64 24 f8 6a 00 68 ?? 86 00 00',
        // public void SetIpAddress(string ipv4Address, string ipv6Address, int port);
        'NetConnetData.SetIpAddress':
            '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 8b 7d 0c 8b 75 08 81 c3 ?? ?? ?? 05 8d 64 24 f8 6a 00 68 ac 00 00 00 e8 ?? ?? ?? ff 8d',
    },
    'arm64-v8a': {
        // Il2CppString* il2cpp_string_new(const char* str);
        il2cpp_string_new:
            'fd 7b be a9 f3 0b 00 f9 fd 03 00 91 f3 03 00 aa ?? ?? ?? 95 e1 03 00 aa e0 03 13 aa f3 0b 40 f9 fd 7b c2 a8 22 3b 00 14 fd 7b be a9 f4 4f 01 a9 fd 03 00 91 f3 03 00 aa 00 00 40 f9 f4 03 01 aa',
         // Il2CppString* il2cpp_string_new_utf16(const Il2CppChar* text, int32_t len);
        il2cpp_string_new_utf16:
            'fd 7b bd a9 f5 0b 00 f9 f4 4f 02 a9 fd 03 00 91 f4 03 00 aa e0 03 01 2a f3 03 01 2a 7f 1a 00 94 f5 03 00 aa 83 2d 01 94 68 7a 1f 53 e1 03 14 aa 02 7d 40 93 ?? ?? ?? 95 e0 03 15 aa f4 4f 42 a9',
        // internal static string MakeInitialUrl(string targetUrl, string localUrl);
        'WebRequestUtils.MakeInitialUrl': [
            'fd 7b bb a9 fa 67 01 a9 f8 5f 02 a9 f6 57 03 a9 f4 4f 04 a9 fd 03 00 91 ?? 29 02 f0 f5 03 01 aa',
        ],
        // public void set_url(string value);
        'UnityWebRequest.set_url': [
            'fd 7b bd a9 f5 0b 00 f9 f4 4f 02 a9 fd 03 00 91 ?? ?? 02 90 f4 03 01 aa f3 03 00 aa a8 ?? ?? 39 e8 00 00 37 ?? d6 01 ?? 08 ?? ?? f9 00 01 40 b9 ?? ?? ?? 97 28 00 80 52 a8 ?? ?? 39 ?? d6 01 ?? 08 ?? ?? f9 00 01 40 f9',
        ],
        // protected virtual void LoadDefaultServerInfo();
        'BaseNetworkClient.LoadDefaultServerInfo': [
            'fd 7b be a9 f4 4f 01 a9 fd 03 00 91 d4 ?? 01 d0 f3 03 00 aa 88 ?? ?? 39 e8 00 00 37 c8 ?? 00 ?? 08 ?? ?? f9 00 01 40 b9 ?? ?? a1 96 28 00 80 52 88 ?? ?? 39 80 13 80 52',
        ],
        // public bool SetNetAddrPort(string addr, string addrV6, int port);
        'BaseNetworkClient.SetNetAddrPort': [
            'fd 7b bc a9 f7 0b 00 f9 f6 57 02 a9 f4 4f 03 a9 fd 03 00 91 d7 ?? 01 d0 f4 03 03 2a f5 03 02 aa',
        ],
        // public void SetIpAddress(string ipv4Address, string ipv6Address, int port);
        'NetConnetData.SetIpAddress': [
            'fd 7b bd a9 f6 57 01 a9 f4 4f 02 a9 fd 03 00 91 f6 03 01 aa f4 03 00 aa 80 15 80 52 e1 03 1f aa',
        ],
    },
};

const SDK_URL_AUTHORITIES = [
    'https://sdk-static.mihoyo.com',
    'https://api-sdk.mihoyo.com',
    'https://passport-api.mihoyo.com',
    'https://public-data-api.mihoyo.com',
    'https://webstatic.mihoyo.com',
    'https://h5log-api-dualstack.mihoyo.com',
    'https://apm-log-upload-v6.mihoyo.com',
    'https://sdk-common-static.mihoyo.com',
    'https://assets.hsod2.benghuai.com',
    'https://static-image.benghuai.com',
];

const JAVA_REDIRECT_HOST_SUFFIXES = [
    '.mihoyo.com',
    '.hoyoverse.com',
    '.benghuai.com',
];

let managedUrlRewrites = [];

let stringNewUtf8 = null;
let stringNewUtf16 = null;
let nativeBridgeLoadReplacement = null;
let managedRewritePasses = 0;
const reportedRedirects = new Set();
const rewrittenManagedAddresses = new Set();

function report(message) {
    send({ message: message });
}

function reportStatus(event, message) {
    send({ event: event, message: message });
}

function readIl2CppString(value) {
    if (value === null || value === undefined || value.isNull()) {
        return null;
    }

    try {
        const length = value.add(TARGET.il2CppString.length).readU32();
        if (length > MAX_STRING_LENGTH) {
            return null;
        }
        return value.add(TARGET.il2CppString.chars).readUtf16String(length);
    } catch (_) {
        return null;
    }
}

function createIl2CppString(value) {
    if (stringNewUtf8 !== null) {
        return stringNewUtf8(Memory.allocUtf8String(value));
    }
    if (stringNewUtf16 !== null) {
        return stringNewUtf16(Memory.allocUtf16String(value));
    }
    throw new Error('找不到 IL2CPP 字符串构造函数');
}

function redirectUrl(original) {
    if (original === null) {
        return null;
    }

    const match = /^(https?):\/\/([^\/?#]+)(\/[^?#]*)?(\?[^#]*)?(?:#.*)?$/i.exec(original);
    if (match === null) {
        return null;
    }

    const target = CONFIG.httpUrlBase.toLowerCase();
    const currentOrigin = (match[1] + '://' + match[2]).toLowerCase();
    if (currentOrigin === target) {
        return null;
    }

    const authority = match[2].toLowerCase();
    if (
        authority === 'localhost' ||
        authority.startsWith('localhost:') ||
        authority === '127.0.0.1' ||
        authority.startsWith('127.0.0.1:')
    ) {
        return null;
    }

    return CONFIG.httpUrlBase + (match[3] || '/') + (match[4] || '');
}

function redirectJavaUrl(original) {
    const match = /^https?:\/\/([^\/?#]+)/i.exec(original);
    if (match === null) {
        return null;
    }

    const authority = match[1].split('@').pop().toLowerCase();
    const host = authority.startsWith('[') ? authority.slice(1, authority.indexOf(']')) : authority.split(':')[0];
    if (!JAVA_REDIRECT_HOST_SUFFIXES.some(function (suffix) {
            return host.endsWith(suffix);
        })
    ) {
        return null;
    }
    return redirectUrl(original);
}

function reportOnce(key, message) {
    if (reportedRedirects.has(key)) {
        return;
    }
    reportedRedirects.add(key);
    report(message);
}

function reportRedirect(kind, original, redirected) {
    const key = kind + '\n' + original + '\n' + redirected;
    reportOnce(key, '[重定向] ' + kind + ': ' + original + ' -> ' + redirected);
}

function asciiPattern(value) {
    const bytes = [];
    for (let index = 0; index < value.length; index++) {
        bytes.push(value.charCodeAt(index).toString(16).padStart(2, '0'));
    }
    return bytes.join(' ');
}

function asciiBytes(value) {
    const bytes = new Uint8Array(value.length);
    for (let index = 0; index < value.length; index++) {
        bytes[index] = value.charCodeAt(index);
    }
    return bytes;
}

function rewriteMappedAuthority(range, rewrite) {
    let matches;
    try {
        matches = Memory.scanSync(range.base, range.size, rewrite.pattern);
    } catch (error) {
        reportOnce('scan-error\n' + rewrite.original + '\n' + range.base, '[错误] 扫描 SDK URL 失败：' + String(error));
        return;
    }

    for (const match of matches) {
        const address = match.address.toString();
        if (rewrittenManagedAddresses.has(address)) {
            continue;
        }

        try {
            const writableProtection = range.protection.indexOf('x') === -1 ? 'rw-' : 'rwx';
            if (!Memory.protect(match.address, rewrite.bytes.length, writableProtection))
            {
                throw new Error('Memory.protect 返回 false');
            }

            match.address.writeByteArray(rewrite.bytes);
            Memory.protect(match.address, rewrite.bytes.length, range.protection);
            rewrittenManagedAddresses.add(address);
            reportRedirect('VDEX/OAT', rewrite.original, rewrite.replacement);
        } catch (error) {
            reportOnce('write-error\n' + address, '[错误] 改写 SDK URL 失败：' + String(error));
        }
    }
}

function rewriteManagedUrlConstants() {
    if (managedRewritePasses >= MAX_MANAGED_REWRITE_PASSES || managedUrlRewrites.length === 0)
    {
        return false;
    }
    const rewrite = managedUrlRewrites[managedRewritePasses % managedUrlRewrites.length];
    managedRewritePasses++;

    let ranges;
    try {
        ranges = Process.enumerateRanges('r--').concat(Process.enumerateRanges('rw-'));
    } catch (error) {
        reportOnce('range-error', '[错误] 枚举 VDEX/OAT 内存失败：' + String(error));
        return true;
    }

    for (const range of ranges) {
        const path = range.file === null || range.file === undefined ? '' : range.file.path || '';
        if (range.size <= MAX_MANAGED_RANGE_SIZE &&(path.endsWith('.vdex') || path.endsWith('.odex') || path.endsWith('.oat')))
        {
            rewriteMappedAuthority(range, rewrite);
        }
    }
    return managedRewritePasses < MAX_MANAGED_REWRITE_PASSES;
}

function rewriteInflateOutput(base, size) {
    if (size === 0 || size > MAX_INFLATE_OUTPUT_SIZE) {
        return;
    }

    for (const rewrite of managedUrlRewrites) {
        let matches;
        try {
            matches = Memory.scanSync(base, size, rewrite.pattern);
        } catch (_) {
            continue;
        }

        for (const match of matches) {
            try {
                match.address.writeByteArray(rewrite.bytes);
                reportRedirect('zlib.inflate', rewrite.original, rewrite.replacement);
            } catch (error) {
                reportOnce('inflate-write-error\n' + match.address, '[错误] 改写 inflate 输出失败：' + String(error));
            }
        }
    }
}

function installInflateHook() {
    const inflate = Module.findGlobalExportByName('inflate');
    if (inflate === null) {
        report('[错误] 找不到 zlib.inflate');
        return;
    }

    Interceptor.attach(inflate, {
        onEnter: function (args) {
            this.stream = args[0];
            try {
                this.output = this.stream.add(TARGET.zlibStream.nextOut).readPointer();
                this.available = this.stream.add(TARGET.zlibStream.availOut).readU32();
            } catch (_) {
                this.output = null;
                this.available = 0;
            }
        },
        onLeave: function () {
            if (this.output === null || this.output.isNull() || this.available === 0)
            {
                return;
            }

            try {
                const remaining = this.stream.add(TARGET.zlibStream.availOut).readU32();
                const written = this.available - remaining;
                if (written > 0 && written <= this.available) {
                    rewriteInflateOutput(this.output, written);
                }
            } catch (_) {
                // 调用方可能已经释放 z_stream。
            }
        },
    });
    report('[就绪] zlib.inflate SDK URL 改写已启用');
}

function installEmulatedRealmLoader() {
    const nativeBridge = Process.getModuleByName('libnativebridge.so');
    const createNamespace = new NativeFunction(
        nativeBridge.getExportByName('NativeBridgeCreateNamespace'),
        'pointer',
        ['pointer', 'pointer', 'pointer', 'uint64', 'pointer', 'pointer'],
    );
    const loadLibrary = nativeBridge.getExportByName('NativeBridgeLoadLibrary');
    const loadLibraryExt = new NativeFunction(
        nativeBridge.getExportByName('NativeBridgeLoadLibraryExt'),
        'pointer',
        ['pointer', 'int', 'pointer'],
    );
    const getError = new NativeFunction(
        nativeBridge.getExportByName('NativeBridgeGetError'),
        'pointer',
        [],
    );
    const bridgeNamespace = createNamespace(
        Memory.allocUtf8String('frida-emulated'),
        Memory.allocUtf8String(EMULATED_NAMESPACE_DIRECTORY),
        Memory.allocUtf8String(EMULATED_NAMESPACE_DIRECTORY + ':/system/lib64/arm64:/system_ext/lib64/arm64'),
        0,
        Memory.allocUtf8String(EMULATED_NAMESPACE_DIRECTORY + ':/system'),
        ptr(0),
    );
    if (bridgeNamespace.isNull()) {
        throw new Error('NativeBridgeCreateNamespace 返回空指针');
    }

    nativeBridgeLoadReplacement = new NativeCallback(
        function (path, flags) {
            const handle = loadLibraryExt(path, flags, bridgeNamespace);
            if (handle.isNull()) {
                const errorPointer = getError();
                const detail = errorPointer.isNull() ? '未知错误' : errorPointer.readUtf8String();
                report('[错误] NativeBridgeLoadLibraryExt 加载 ARM64 agent 失败：' + detail);
                return ptr(0);
            }

            let requestedPath = null;
            try {
                requestedPath = path.readUtf8String();
            } catch (_) {}
            if (requestedPath === CONFIG.emulatedAgentPath) {
                report('[就绪] ARM64 Frida agent 已通过 NativeBridgeLoadLibraryExt 加载');
            }
            return handle;
        },
        'pointer',
        ['pointer', 'int'],
    );
    Interceptor.replace(loadLibrary, nativeBridgeLoadReplacement);
    reportStatus('native-bridge-ready', '[就绪] MuMu Native Bridge 兼容层已启用');
}

function rewriteJavaUrlMap(map) {
    const keys = map.keySet().toArray();
    let rewritten = 0;
    for (let index = 0; index < keys.length; index++) {
        const key = keys[index];
        const value = map.get(key);
        if (value === null) {
            continue;
        }

        const original = String(value);
        const redirected = redirectJavaUrl(original);
        if (redirected === null) {
            continue;
        }

        map.put(key, redirected);
        rewritten++;
    }
    return rewritten;
}

function rewriteComboConfigUrls() {
    const configCenter = Java.use('com.mihoyo.combo.config.ConfigCenter');
    const envConfig = Java.use('com.mihoyo.combo.config.EnvConfig');
    const concurrentHashMap = Java.use('java.util.concurrent.ConcurrentHashMap');
    const urlsField = envConfig.class.getDeclaredField('urls');
    urlsField.setAccessible(true);
    const instance = configCenter.INSTANCE.value;
    if (instance === null) {
        return 0;
    }
    const configurationCollection = instance.configurations();
    if (configurationCollection === null) {
        return 0;
    }
    const configurations = configurationCollection.toArray();
    let rewritten = 0;
    for (const config of configurations) {
        const urlsValue = urlsField.get(config);
        if (urlsValue === null) {
            continue;
        }

        const urls = Java.cast(urlsValue, concurrentHashMap);
        rewritten += rewriteJavaUrlMap(urls);
    }
    if (rewritten > 0) {
        report('[重定向] ConfigCenter.EnvConfig.urls: 已改写 ' + rewritten + ' 个地址');
    }
    return rewritten;
}

function rewritePorteInfoUrls() {
    const porteInfo = Java.use('com.mihoyo.platform.account.sdk.PorteInfo');
    let rewritten = 0;
    for (const field of PORTE_INFO_URL_FIELDS) {
        const original = String(porteInfo[field].value);
        const redirected = redirectJavaUrl(original);
        if (redirected === null) {
            continue;
        }

        porteInfo[field].value = redirected;
        reportRedirect('PorteInfo.' + field, original, redirected);
        rewritten++;
    }
    return rewritten;
}

function rewriteHotfixUrls() {
    const netClient = Java.use('com.mihoyo.hotfix.runtime.patch.http.NetClient');
    const baseUrls = netClient.BASE_URLS.value;
    if (baseUrls === null) {
        return 0;
    }
    let rewritten = 0;
    for (let index = 0; index < baseUrls.length; index++) {
        const original = String(baseUrls[index]);
        const redirected = redirectJavaUrl(original);
        if (redirected === null) {
            continue;
        }

        baseUrls[index] = CONFIG.httpUrlBase;
        reportRedirect('Hotfix.NetClient.BASE_URLS[' + index + ']', original, CONFIG.httpUrlBase);
        rewritten++;
    }
    return rewritten;
}

// 以下三个指纹函数用于判断 SDK 是否重新初始化并覆盖了已改写的地址。
// 指纹只读取当前值，成本极低；指纹变化才触发一次全量改写。

const PORTE_INFO_URL_FIELDS = [
    'loginBaseUrl',
    'cdnBaseUrl',
    'dataUploadUrl',
    'webPlatBaseUrl',
    'forgetPwdHost',
    'accountAppealUrl',
    'commonProblemUrl',
];

function porteInfoSignature() {
    const porteInfo = Java.use('com.mihoyo.platform.account.sdk.PorteInfo');
    const values = [];
    for (const field of PORTE_INFO_URL_FIELDS) {
        values.push(String(porteInfo[field].value));
    }
    return values.join('|');
}

function hotfixSignature() {
    const netClient = Java.use('com.mihoyo.hotfix.runtime.patch.http.NetClient');
    const baseUrls = netClient.BASE_URLS.value;
    if (baseUrls === null) {
        return null;
    }
    const values = [];
    for (let index = 0; index < baseUrls.length; index++) {
        values.push(String(baseUrls[index]));
    }
    return values.join('|');
}

// ConfigCenter 的地址表很大（单个环境上千条），不能每轮全量扫描。
// 用配置列表长度 + 每个 EnvConfig 的对象身份做指纹：ConfigCenter.init 重建配置时身份会变。
function comboConfigSignature() {
    const configCenter = Java.use('com.mihoyo.combo.config.ConfigCenter');
    const instance = configCenter.INSTANCE.value;
    if (instance === null) {
        return null;
    }
    const configurations = instance.configurations();
    if (configurations === null) {
        return null;
    }
    const system = Java.use('java.lang.System');
    const parts = [String(configurations.size())];
    for (const config of configurations.toArray()) {
        parts.push(String(system.identityHashCode(config)));
    }
    return parts.join('|');
}

let porteInfoSetupGuardInstalled = false;

// Porte.setup -> PorteInfo.setup 是 SDK 每次重新初始化时覆盖 URL 静态字段的唯一入口
// （客户端回到登录页时 MonoTheIndex.UpdateForceLogin -> TheBaseAccountManager.Init ->
// MiHoYoSDK.Invoke("login_init") -> Java Porte.setup）。在这里同步补一次改写，
// 消除 100ms 巡检窗口，避免初始化后紧接着发出的请求落到官方域名。
function installPorteInfoSetupGuard() {
    if (porteInfoSetupGuardInstalled) {
        return true;
    }
    try {
        const porteInfo = Java.use('com.mihoyo.platform.account.sdk.PorteInfo');
        const setup = porteInfo.setup.overload(
            'android.content.Context',
            'com.mihoyo.platform.account.sdk.PorteConfig',
        );
        setup.implementation = function (context, config) {
            const result = setup.call(this, context, config);
            try {
                const rewritten = rewritePorteInfoUrls();
                if (rewritten > 0) {
                    report('[重定向] PorteInfo.setup 覆盖地址后已立即重新改写 ' + rewritten + ' 个地址');
                }
            } catch (error) {
                reportOnce('porte-setup-rewrite-error', '[警告] PorteInfo.setup 后改写地址失败：' + String(error));
            }
            return result;
        };
        porteInfoSetupGuardInstalled = true;
        report('[就绪] PorteInfo.setup URL 守护已安装');
        return true;
    } catch (error) {
        reportOnce('porte-setup-guard-wait', '[等待] PorteInfo.setup URL 守护尚未可用：' + String(error.message || error));
        return false;
    }
}

let sdkLoginRsaBypassInstalled = false;
let sdkRsaHookInstallPending = false;
let sdkRsaHookAttemptLogged = false;
let sdkRsaHookReadyReported = false;
let sdkRsaHookLastInstallAt = 0;
const SDK_RSA_HOOK_REAPPLY_INTERVAL_MS = 100;
const SDK_LOGIN_RSA_TTL_MS = 30000;
let sdkLoginRsaBridgeInstalled = false;
let sdkPendingLoginRsaBypass = null;
const sdkRsaHookState = new Map();
const sdkRsaHookHitReported = new Set();
const sdkRsaHookLogState = new Set();

function stringifySdkRsaArgument(value) {
    if (value === null || value === undefined) {
        return '<null>';
    }
    try {
        if (value.$className === '[B') {
            let textValue = '';
            for (let index = 0; index < value.length; index++) {
                textValue += String.fromCharCode(value[index] & 0xff);
            }
            return textValue;
        }
        return String(value);
    } catch (error) {
        return '<unreadable:' + String(error) + '>';
    }
}

function installSdkLoginRsaBypass() {
    const hooks = [
        { className: 'com.mihoyo.platform.account.sdk.utils.RSAUtils', methodName: 'encryptByPublicKey(String)', overload: ['java.lang.String'], stateKey: 'com.mihoyo.platform.account.sdk.utils.RSAUtils:encryptByPublicKey(String)' },
        { className: 'com.miHoYo.support.utils.RSAUtils', methodName: 'encryptByPublicKey(String,String)', overload: ['java.lang.String', 'java.lang.String'], stateKey: 'com.miHoYo.support.utils.RSAUtils:encryptByPublicKey(String,String)' },
        { className: 'com.mihoyo.platform.account.sdk.utils.RSAUtils', methodName: 'encryptByPublicKey([B,[B)', overload: ['[B', '[B'], stateKey: 'com.mihoyo.platform.account.sdk.utils.RSAUtils:encryptByPublicKey([B,[B)' },
        { className: 'com.miHoYo.support.utils.RSAUtils', methodName: 'encryptByPublicKey([B,[B)', overload: ['[B', '[B'], stateKey: 'com.miHoYo.support.utils.RSAUtils:encryptByPublicKey([B,[B)' },
    ];
    if (sdkRsaHookInstallPending) {
        return 0;
    }
    const now = Date.now();
    if (sdkLoginRsaBypassInstalled && now - sdkRsaHookLastInstallAt < SDK_RSA_HOOK_REAPPLY_INTERVAL_MS) {
        return 1;
    }
    sdkRsaHookInstallPending = true;
    sdkRsaHookLastInstallAt = now;
    let installed = 0;
    try {
        for (const item of hooks) {
            if (sdkRsaHookState.get(item.stateKey) === true) {
                installed++;
                continue;
            }
            try {
                const rsaUtils = Java.use(item.className);
                if (!sdkRsaHookLogState.has(item.stateKey)) {
                    report('[调试] SDK RSA 类已找到: ' + item.className);
                    sdkRsaHookLogState.add(item.stateKey);
                }
                const method = rsaUtils.encryptByPublicKey.overload(...item.overload);
                method.implementation = function () {
                    const rsaArguments = Array.prototype.map.call(arguments, stringifySdkRsaArgument);
                    const rsaLog = '[RSA Bypass] ' + item.className + '.' + item.methodName + ' 参数=' + JSON.stringify(rsaArguments);
                    setTimeout(function () {
                        report(rsaLog);
                    }, 0);
                    return arguments[0];
                };
                sdkRsaHookState.set(item.stateKey, true);
                installed++;
            } catch (error) {
                reportOnce('sdk-login-rsa-bypass-install-error\n' + item.stateKey, '[等待] SDK RSA 入口尚未可用: ' + item.className + '.' + item.methodName + ' (' + String(error.message || error) + ')');
            }
        }
    } finally {
        sdkRsaHookInstallPending = false;
        sdkLoginRsaBypassInstalled = sdkRsaHookState.get('com.mihoyo.platform.account.sdk.utils.RSAUtils:encryptByPublicKey(String)') === true;
    }
    return installed;
}

function applyPendingSdkLoginRsaBypass(data, clearAfterApply) {
    const pending = sdkPendingLoginRsaBypass;
    if (pending === null) {
        return false;
    }
    if (Date.now() > pending.expiresAt) {
        sdkPendingLoginRsaBypass = null;
        return false;
    }
    if (pending.type === 'password') {
        if (!data.containsKey('account') || !data.containsKey('password')) {
            return false;
        }
        data.put('account', pending.account);
        data.put('password', pending.password);
    } else if (pending.type === 'mobileCaptcha') {
        if (!data.containsKey('area_code') || !data.containsKey('mobile') || !data.containsKey('captcha') || !data.containsKey('action_type'))
        {
            return false;
        }
        data.put('area_code', pending.areaCode);
        data.put('mobile', pending.mobile);
    } else {
        return false;
    }
    if (clearAfterApply) {
        sdkPendingLoginRsaBypass = null;
    }
    return true;
}

function installSdkLoginRsaBridge() {
    if (sdkLoginRsaBridgeInstalled) {
        return true;
    }
    try {
        const loginManager = Java.use('com.mihoyo.platform.account.sdk.login.LoginManager');
        const passwordLogin = loginManager.login.overload(
            'android.app.Activity',
            'java.lang.String',
            'java.lang.String',
            'com.mihoyo.platform.account.sdk.callback.ILoginCallback',
        );
        const mobileCaptchaLogin = loginManager.login.overload(
            'android.app.Activity',
            'java.lang.String',
            'java.lang.String',
            'java.lang.String',
            'com.mihoyo.platform.account.sdk.callback.ILoginCallback',
        );
        const requestUtils = Java.use('com.mihoyo.platform.account.sdk.network.RequestUtils');
        const createSign = requestUtils.createSign.overload('java.util.HashMap');
        const createBody = requestUtils.createBody.overload('java.util.HashMap');

        passwordLogin.implementation = function (activity, account, password, callback) {
            sdkPendingLoginRsaBypass = {
                type: 'password',
                account: String(account),
                password: String(password),
                expiresAt: Date.now() + SDK_LOGIN_RSA_TTL_MS,
            };
            const captureLog = '[RSA Bypass] Passport 登录入口已捕获待处理字段 ' + '密码登录 account=' + sdkPendingLoginRsaBypass.account + ' password=' + sdkPendingLoginRsaBypass.password;
            setTimeout(function () {
                report(captureLog);
            }, 0);
            return passwordLogin.call(this, activity, account, password, callback);
        };
        mobileCaptchaLogin.implementation = function (activity, areaCode, mobile, captcha, callback)
        {
            sdkPendingLoginRsaBypass = {
                type: 'mobileCaptcha',
                areaCode: String(areaCode),
                mobile: String(mobile),
                captcha: String(captcha),
                expiresAt: Date.now() + SDK_LOGIN_RSA_TTL_MS,
            };
            const captureLog = '[RSA Bypass] Passport 登录入口已捕获待处理字段 ' + '手机验证码登录 area_code=' + sdkPendingLoginRsaBypass.areaCode + ' mobile=' + sdkPendingLoginRsaBypass.mobile + ' captcha=' + sdkPendingLoginRsaBypass.captcha;
            setTimeout(function () {
                report(captureLog);
            }, 0);
            return mobileCaptchaLogin.call(this, activity, areaCode, mobile, captcha, callback);
        };
        createSign.implementation = function (data) {
            const pending = sdkPendingLoginRsaBypass;
            if (applyPendingSdkLoginRsaBypass(data, false)) {
                const signLog = '[RSA Bypass] Passport 登录签名前已应用原始字段 ' + (pending.type === 'password'
                    ? '密码登录 account=' + pending.account + ' password=' + pending.password
                    : '手机验证码登录 area_code=' + pending.areaCode + ' mobile=' + pending.mobile + ' captcha=' + pending.captcha);
                setTimeout(function () {
                    report(signLog);
                }, 0);
            }
            return createSign.call(this, data);
        };
        createBody.implementation = function (data) {
            const pending = sdkPendingLoginRsaBypass;
            if (applyPendingSdkLoginRsaBypass(data, true)) {
                const bodyLog = '[RSA Bypass] Passport 登录包体已应用原始字段 ' + (pending.type === 'password'
                        ? '密码登录 account=' + pending.account + ' password=' + pending.password
                        : '手机验证码登录 area_code=' + pending.areaCode + ' mobile=' + pending.mobile + ' captcha=' + pending.captcha);
                setTimeout(function () {
                    report(bodyLog);
                }, 0);
            }
            return createBody.call(this, data);
        };
        sdkLoginRsaBridgeInstalled = true;
        report('[就绪] Passport 登录 RSA Bypass Hook 已安装');
        return true;
    } catch (error) {
        reportOnce('sdk-login-rsa-bridge-error', '[等待] Passport 登录 RSA Bypass 入口尚未可用：' + String(error.message || error));
        return false;
    }
}

function installJavaUrlRedirector() {
    try {
        if (!Java.available) {
            report('[错误] 当前进程没有可用的 Java VM，跳过 Java URL 修改');
            return;
        }

        Java.perform(function () {
            try {
                // 每个目标带一个廉价指纹。SDK 每次回到登录页都会重新初始化
                // （MonoTheIndex.UpdateForceLogin -> TheBaseAccountManager.Init ->
                // MiHoYoSDK.Invoke("login_init") -> Java Porte.setup -> PorteInfo.setup），
                // 把地址覆盖回官方域名；因此巡检必须常驻，指纹变化就立即重扫。
                const rewriters = [
                    {
                        name: 'ConfigCenter',
                        rewrite: rewriteComboConfigUrls,
                        signature: comboConfigSignature,
                        signatureValue: null,
                        settled: false,
                    },
                    {
                        name: 'PorteInfo',
                        rewrite: rewritePorteInfoUrls,
                        signature: porteInfoSignature,
                        signatureValue: null,
                        settled: false,
                    },
                    {
                        name: 'Hotfix.NetClient',
                        rewrite: rewriteHotfixUrls,
                        signature: hotfixSignature,
                        signatureValue: null,
                        settled: false,
                    },
                ];
                let completionReported = false;
                setInterval(function () {
                    installPorteInfoSetupGuard();
                    for (const item of rewriters) {
                        let signature;
                        try {
                            signature = item.signature();
                        } catch (error) {
                            reportOnce('java-url-signature-error\n' + item.name, '[警告] 无法读取 ' + item.name + ' 地址指纹：' + String(error));
                            continue;
                        }
                        if (signature === null || signature === item.signatureValue) {
                            continue;
                        }

                        let rewritten;
                        try {
                            rewritten = item.rewrite();
                        } catch (error) {
                            reportOnce('java-url-error\n' + item.name, '[警告] 无法改写 ' + item.name + '：' + String(error.stack || error));
                            continue;
                        }

                        const wasSettled = item.settled;
                        item.settled = item.settled || rewritten > 0;
                        if (wasSettled && rewritten > 0) {
                            report('[重定向] ' + item.name + ' 地址被 SDK 重新初始化覆盖，已重新改写 ' + rewritten + ' 个地址');
                        }

                        try {
                            item.signatureValue = item.signature();
                        } catch (_) {
                            item.signatureValue = signature;
                        }
                    }

                    if (
                        !completionReported &&
                        rewriters.every(function (item) {
                            return item.settled;
                        })
                    ) {
                        completionReported = true;
                        report('[就绪] Java SDK URL 修改完成');
                    }
                }, JAVA_CONFIG_REWRITE_INTERVAL_MS);
                report('[就绪] Java SDK URL 修改已启用');
            } catch (error) {
                report('[错误] Java URL 修改初始化失败：' + String(error));
            }
        });
    } catch (error) {
        report('[错误] Java Bridge 启动失败，继续使用 IL2CPP Hook：' + String(error));
    }
}

function installJavaRsaBypass() {
    try {
        if (!Java.available) {
            report('[错误] 当前进程没有可用的 Java VM，跳过 SDK RSA Bypass');
            return;
        }

        Java.perform(function () {
            installSdkLoginRsaBridge();
            const poller = setInterval(function () {
                try {
                    installSdkLoginRsaBridge();
                    if (installSdkLoginRsaBypass() > 0 && !sdkRsaHookReadyReported) {
                        report('[就绪] SDK RSA Bypass Hook 安装完成');
                        sdkRsaHookReadyReported = true;
                    }
                } catch (error) {
                    reportOnce('java-rsa-bypass-error', '[警告] 无法安装 SDK RSA Bypass：' + String(error.stack || error));
                }
            }, SDK_RSA_HOOK_REAPPLY_INTERVAL_MS);
            report('[就绪] SDK RSA Bypass 已启用');
        });
    } catch (error) {
        report('[错误] SDK RSA Bypass 初始化失败：' + String(error));
    }
}

function isEmulatedArm64() {
    return CONFIG.clientArch === 'arm64-v8a' && CONFIG.emulator;
}

function executableAddress(address, name) {
    const range = Process.findRangeByAddress(address);
    if (range === null) {
        throw new Error(name + ' 的特征地址不在已映射内存中: ' + address);
    }
    if (range.protection.indexOf('x') === -1 && !isEmulatedArm64()) {
        throw new Error(name + ' 的特征地址不在可执行内存中: ' + address);
    }
    return address;
}

function signatureRanges(module) {
    const ranges = module.enumerateRanges('r-x');
    if (isEmulatedArm64()) {
        // Houdini guest ELF 在宿主 maps 中常为 r--，但其 ARM64 代码仍可被 Emulated Realm 拦截。
        ranges.push.apply(ranges, module.enumerateRanges('r--'));
    }
    return ranges;
}

function reportResolvedAddress(module, name, address) {
    report('[Address] ' + name + ': ' + address + ' (RVA: ' + address.sub(module.base) + ')');
}

function signatureAddress(module, name) {
    const definition = FUNCTION_SIGNATURES[CONFIG.clientArch][name];
    if (definition === undefined) {
        throw new Error('缺少 ' + name + ' 的特征定义');
    }

    const patterns = Array.isArray(definition) ? definition : [definition];
    const failures = [];
    for (let index = 0; index < patterns.length; index++) {
        const addresses = new Map();
        try {
            for (const range of signatureRanges(module)) {
                for (const match of Memory.scanSync(range.base, range.size, patterns[index])) {
                    addresses.set(match.address.toString(), match.address);
                }
            }
        } catch (error) {
            failures.push('候选 ' + (index + 1) + ' 无效：' + error);
            continue;
        }
        if (addresses.size > 1) {
            throw new Error(
                name + ' 的候选 ' + (index + 1) + ' 命中数为 ' +
                addresses.size + '，拒绝安装 Hook',
            );
        }
        if (addresses.size === 1) {
            const address = executableAddress(addresses.values().next().value, name);
            reportResolvedAddress(module, name, address);
            return address;
        }
        failures.push('候选 ' + (index + 1) + ' 命中数为 0');
    }

    throw new Error(name + ' 的所有特征候选均不可用（' + failures.join('；') + '）');
}

function stringConstructorAddress(module, name) {
    const exported = module.findExportByName(name) || Module.findGlobalExportByName(name);
    if (exported !== null) {
        const address = executableAddress(exported, name);
        reportResolvedAddress(module, name, address);
        return address;
    }

    return signatureAddress(module, name);
}

function hookUrlArgument(address, name) {
    Interceptor.attach(address, {
        onEnter: function (args) {
            const original = readIl2CppString(args[1]);
            const redirected = redirectUrl(original);
            if (redirected === null) {
                return;
            }
            args[1] = createIl2CppString(redirected);
            reportRedirect(name, original, redirected);
        },
    });
}

function isRedirectedGateway(ipv4, ipv6) {
    const configuredIpv4 = CONFIG.gatewayHost.trim().toLowerCase();
    const configuredIpv6 = CONFIG.gatewayIpv6.trim().toLowerCase();
    return (
        (typeof ipv4 === 'string' && ipv4.trim().toLowerCase() === configuredIpv4) ||
        (configuredIpv6.length > 0 && typeof ipv6 === 'string' && ipv6.trim().toLowerCase() === configuredIpv6)
    );
}

function redirectGatewayArguments(args, hook) {
    const originalIpv4 = readIl2CppString(args[1]);
    const originalIpv6 = readIl2CppString(args[2]);
    const originalPort = args[3].toInt32();

    // 本地 Gateway 返回的游戏服端口必须保留，不能重新覆盖成 Dispatch 端口。
    if (isRedirectedGateway(originalIpv4, originalIpv6)) {
        return;
    }

    args[1] = createIl2CppString(CONFIG.gatewayHost);
    args[2] = createIl2CppString(CONFIG.gatewayIpv6);
    args[3] = ptr(CONFIG.gatewayPort);
    reportRedirect(hook, String(originalIpv4) + ':' + originalPort, CONFIG.gatewayHost + ':' + CONFIG.gatewayPort);
}

function installHooks(module) {
    const utf8Address = stringConstructorAddress(module, 'il2cpp_string_new');
    const utf16Address = stringConstructorAddress(module, 'il2cpp_string_new_utf16');

    if (utf8Address !== null) {
        stringNewUtf8 = new NativeFunction(utf8Address, 'pointer', ['pointer']);
    }
    if (utf16Address !== null) {
        stringNewUtf16 = new NativeFunction(utf16Address, 'pointer', ['pointer']);
    }
    if (stringNewUtf8 === null && stringNewUtf16 === null) {
        throw new Error('libil2cpp.so 未导出字符串构造函数');
    }

    Interceptor.attach(signatureAddress(module, 'WebRequestUtils.MakeInitialUrl'),
        {
            onLeave: function (retval) {
                const original = readIl2CppString(retval);
                const redirected = redirectUrl(original);
                if (redirected === null) {
                    return;
                }
                retval.replace(createIl2CppString(redirected));
                reportRedirect('WebRequestUtils.MakeInitialUrl', original, redirected);
            },
        },
    );

    hookUrlArgument(signatureAddress(module, 'UnityWebRequest.set_url'), 'UnityWebRequest.set_url');

    Interceptor.attach(signatureAddress(module, 'BaseNetworkClient.LoadDefaultServerInfo'),
        {
            onEnter: function (args) {
                this.client = args[0];
            },
            onLeave: function () {
                if (this.client === null || this.client.isNull()) {
                    return;
                }

                const fields = TARGET.baseNetworkClient;
                const originalIpv4 = readIl2CppString(
                    this.client.add(fields.serverAddress).readPointer(),
                );
                const originalPort = this.client.add(fields.serverPort).readS32();
                this.client.add(fields.serverAddress).writePointer(createIl2CppString(CONFIG.gatewayHost));
                this.client.add(fields.serverAddressV6).writePointer(createIl2CppString(CONFIG.gatewayIpv6));
                this.client.add(fields.serverPort).writeS32(CONFIG.gatewayPort);
                reportRedirect('BaseNetworkClient.LoadDefaultServerInfo', String(originalIpv4) + ':' + originalPort, CONFIG.gatewayHost + ':' + CONFIG.gatewayPort);
            },
        },
    );

    Interceptor.attach(signatureAddress(module, 'BaseNetworkClient.SetNetAddrPort'),
        {
            onEnter: function (args) {
                redirectGatewayArguments(args, 'BaseNetworkClient.SetNetAddrPort');
            },
        },
    );

    Interceptor.attach(signatureAddress(module, 'NetConnetData.SetIpAddress'),
        {
            onEnter: function (args) {
                redirectGatewayArguments(args, 'NetConnetData.SetIpAddress');
            },
        },
    );

    report('[就绪] HTTP -> ' + CONFIG.httpUrlBase + '，Gateway -> ' + CONFIG.gatewayHost + ':' + CONFIG.gatewayPort);
}

function start(config) {
    CONFIG = config;
    TARGET = TARGETS[CONFIG.clientArch];
    if (TARGET === undefined) {
        report('[错误] 不支持的客户端架构：' + String(CONFIG.clientArch));
        return;
    }

    const enablePlatformRedirects = CONFIG.runtimeRole !== 'il2cpp';
    const enableIl2CppRedirects = CONFIG.runtimeRole !== 'platform';
    managedUrlRewrites = SDK_URL_AUTHORITIES.map(function (original) {
        const padding = original.length - CONFIG.httpUrlBase.length;
        if (padding < 0) {
            return null;
        }

        let replacement = CONFIG.httpUrlBase;
        if (padding > 0) {
            const schemeEnd = replacement.indexOf('://') + 3;
            const userInfo = padding === 1 ? '@' : 'a'.repeat(padding - 1) + '@';
            replacement = replacement.slice(0, schemeEnd) + userInfo + replacement.slice(schemeEnd);
        }

        return {
            original: original,
            replacement: replacement,
            pattern: asciiPattern(original),
            bytes: asciiBytes(replacement),
        };
    }).filter(function (rewrite) {
        return rewrite !== null;
    });

    if (enablePlatformRedirects && CONFIG.clientArch === 'arm64-v8a' && CONFIG.emulator)
    {
        try {
            installEmulatedRealmLoader();
        } catch (error) {
            reportStatus('native-bridge-failed', '[错误] MuMu Native Bridge 兼容层安装失败：' + String(error));
        }
    }

    const startedAt = Date.now();
    if (enablePlatformRedirects && CONFIG.useZlibHook) {
        installInflateHook();
        rewriteManagedUrlConstants();
        const managedRewritePoller = setInterval(function () {
            if (!rewriteManagedUrlConstants()) {
                clearInterval(managedRewritePoller);
            }
        }, 500);
    }

    if (enablePlatformRedirects && CONFIG.useJavaUrlModify) {
        setTimeout(function () {
            installJavaUrlRedirector();
        }, 0);
    }

    if (enablePlatformRedirects && CONFIG.useJavaBypassRsa) {
        // 必须在收到配置后立即进入 Java Bridge；spawn 恢复进程后，首次自动登录
        // 可能早于下一个事件循环，延迟调用会造成第一次请求绕过 RSA Hook。
        installJavaRsaBypass();
    }
    reportStatus('script-configured', '[就绪] Frida 配置已接收，首次 Java Hook 尝试已完成');

    if (!enableIl2CppRedirects) {
        report('[就绪] Native Realm 平台重定向已启用，架构 ' + Process.arch + '/' + Process.pointerSize * 8);
        return;
    }

    const modulePoller = setInterval(function () {
        let module;
        try {
            module = Process.getModuleByName('libil2cpp.so');
        } catch (_) {
            if (Date.now() - startedAt >= MODULE_WAIT_TIMEOUT_MS) {
                clearInterval(modulePoller);
                report('[错误] 等待 libil2cpp.so 超时');
            }
            return;
        }

        clearInterval(modulePoller);
        if (Process.arch !== TARGET.processArch || Process.pointerSize !== TARGET.pointerSize)
        {
            report('[错误] 当前 Realm 架构为 ' + Process.arch + '/' + Process.pointerSize * 8 + '，配置要求 ' + TARGET.processArch + '/' + TARGET.pointerSize * 8);
            return;
        }

        try {
            installHooks(module);
        } catch (error) {
            report('[错误] Hook 安装失败：' + String(error));
        }
    }, 100);
}

recv('config', function (message) {
    start(message.payload);
});
