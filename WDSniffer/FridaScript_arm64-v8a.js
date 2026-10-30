'use strict';

const MAX_PACKET_BYTES = __MAX_PACKET_BYTES__;
// ARM64 函数入口特征；地址、分支距离和 IFix 补丁编号使用通配符。
const NETWORK_SIGNATURES = {
    // MoleMole.NetPacket, public bool serialize(ref System.IO.MemoryStream ms);
    serialize: 'f8 5f bc a9 f6 57 01 a9 f4 4f 02 a9 fd 7b 03 a9 fd c3 00 91 ?? ?? ?? ?? ?? ?? ?? 39 f3 03 01 aa f4 03 00 aa ?? ?? ?? 37 ?? ?? ?? ?? ?? ?? ?? f9 00 01 40 b9 ?? ?? ?? 9? e8 03 00 32 ?? ?? ?? 39 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? ?? ?? ?? 36 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? f5 03 00 aa ?? ?? ?? b5 ?? ?? ?? 9? e0 03 15 aa e1 03 14 aa e2 03 13 aa fd 7b 43 a9 f4 4f 42 a9 f6 57 41 a9 e3 03 1f aa f8 5f c4 a8 ?? ?? ?? 1? 60 02 40 f9 ?? ?? ?? b4 88 12 40 f9 ?? ?? ?? b4 08 00 40 f9',
    // MoleMole.NetPacket, public bool serializeSec(ref System.IO.MemoryStream ms, ref byte[] session_key);
    serializeSec: 'f9 0f 1b f8 f8 5f 01 a9 f6 57 02 a9 f4 4f 03 a9 fd 7b 04 a9 fd 03 01 91 ?? ?? ?? ?? ?? ?? ?? 39 f4 03 02 aa f3 03 01 aa f5 03 00 aa ?? ?? ?? 37 ?? ?? ?? ?? ?? ?? ?? f9 00 01 40 b9 ?? ?? ?? 9? e8 03 00 32 ?? ?? ?? 39 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? ?? ?? ?? 36 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? f6 03 00 aa ?? ?? ?? b5 ?? ?? ?? 9? e0 03 16 aa e1 03 15 aa e2 03 13 aa e3 03 14 aa fd 7b 44 a9 f4 4f 43 a9 f6 57 42 a9 f8 5f 41 a9 e4 03 1f aa f9 07 45 f8 ?? ?? ?? 1? 60 02 40 f9',
    // MoleMole.NetPacket, public MoleMole.PacketStatus deserialize(ref byte[] buf);
    deserialize: 'ff 03 02 d1 fc 6f 02 a9 fa 67 03 a9 f8 5f 04 a9 f6 57 05 a9 f4 4f 06 a9 fd 7b 07 a9 fd c3 01 91 ?? ?? ?? ?? ?? ?? ?? 39 f3 03 01 aa f4 03 00 aa ?? ?? ?? 37 ?? ?? ?? ?? ?? ?? ?? f9 00 01 40 b9 ?? ?? ?? 9? e8 03 00 32 ?? ?? ?? 39 ?? ?? ?? 52 e1 03 1f aa ff 3b 00 79 ff 33 00 79 ff 2b 00 79 ?? ?? ?? 9? ?? ?? ?? 36 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? f5 03 00 aa ?? ?? ?? b5 ?? ?? ?? 9? e0 03 15 aa e1 03 14 aa e2 03 13 aa e3 03 1f aa ?? ?? ?? 9? ?? ?? ?? 1? 95 12 40 f9 ?? ?? ?? b5',
    // MoleMole.NetPacket, public MoleMole.PacketStatus deserializeSec(ref byte[] buf, ref byte[] session_key);
    deserializeSec: 'ff 03 02 d1 fc 6f 02 a9 fa 67 03 a9 f8 5f 04 a9 f6 57 05 a9 f4 4f 06 a9 fd 7b 07 a9 fd c3 01 91 ?? ?? ?? ?? ?? ?? ?? 39 f5 03 02 aa f4 03 01 aa f3 03 00 aa ?? ?? ?? 37 ?? ?? ?? ?? ?? ?? ?? f9 00 01 40 b9 ?? ?? ?? 9? e8 03 00 32 ?? ?? ?? 39 ?? ?? ?? 52 e1 03 1f aa ff 3b 00 79 ff 33 00 79 ff 2b 00 79 ff 23 00 79 ?? ?? ?? 9? ?? ?? ?? 36 ?? ?? ?? 52 e1 03 1f aa ?? ?? ?? 9? f6 03 00 aa ?? ?? ?? b5 ?? ?? ?? 9? e0 03 16 aa e1 03 13 aa e2 03 14 aa e3 03 15 aa e4 03 1f aa ?? ?? ?? 9?',
};
const LAYOUT = {
    packetCmdId: 0x10, // MoleMole.NetPacket._cmdId_k__BackingField
    packetBody: 0x20, // MoleMole.NetPacket.Body
    streamBuffer: 0x28, // System.IO.MemoryStream._buffer
    streamOrigin: 0x30, // System.IO.MemoryStream._origin
    streamLength: 0x38, // System.IO.MemoryStream._length
    arrayLength: 0x18, // Il2CppArray.max_length
    arrayData: 0x20, // Il2CppArraySize.vector
};
const listeners = [];
let sequence = 0;

function emit(payload, data) { send(Object.assign({ seq: ++sequence }, payload), data); }

function capture(packet, hook, direction) {
    if (packet.isNull()) throw new Error('NetPacket 为空');
    const stream = packet.add(LAYOUT.packetBody).readPointer();
    if (stream.isNull()) throw new Error('NetPacket.Body 为空');
    const origin = stream.add(LAYOUT.streamOrigin).readS32();
    const end = stream.add(LAYOUT.streamLength).readS32();
    const length = end - origin;
    if (origin < 0 || length < 0) throw new Error('MemoryStream 长度无效');
    if (length > MAX_PACKET_BYTES) {
        emit({ event: 'packet_skipped', hook: hook, length: length, error: '明文包超过 max-packet-bytes，未截断' });
        return;
    }
    let data = new ArrayBuffer(0);
    if (length > 0) {
        const buffer = stream.add(LAYOUT.streamBuffer).readPointer();
        if (buffer.isNull() || end > buffer.add(LAYOUT.arrayLength).readU64().toNumber()) {
            throw new Error('MemoryStream 超出底层 byte[] 边界');
        }
        data = buffer.add(LAYOUT.arrayData + origin).readByteArray(length);
    }
    emit({
        event: 'business_packet', direction: direction, protocol_hint: 'protobuf',
        command_id: packet.add(LAYOUT.packetCmdId).readU16(),
        payload_length: length, hook: hook, ts_ms: Date.now(),
    }, data);
}

async function findTarget(module, name, pattern) {
    const matches = new Map();
    let ranges = module.enumerateRanges('r-x');
    // Native Bridge 的 ARM64 代码通常是宿主只读映射，不带 x86 执行权限。
    if (ranges.length === 0) ranges = module.enumerateRanges('r--').filter(range => range.protection === 'r--');
    for (const range of ranges) {
        await new Promise(function (resolve, reject) {
            Memory.scan(range.base, range.size, pattern, {
                onMatch(address) {
                    if (address.and(3).isNull()) matches.set(address.toString(), address);
                    if (matches.size > 1) return 'stop';
                },
                onError(error) { reject(new Error(name + ' 扫描失败: ' + error)); },
                onComplete() { resolve(); },
            });
        });
        if (matches.size > 1) break;
    }
    if (matches.size !== 1) {
        throw new Error('NetPacket.' + name + ' 特征码命中 ' + matches.size + ' 处，需要重新定位');
    }
    return matches.values().next().value;
}

async function install(module) {
    try {
        const targets = [];
        for (const [name, pattern] of Object.entries(NETWORK_SIGNATURES)) {
            targets.push([name, await findTarget(module, name, pattern)]);
        }
        for (const [name, address] of targets) {
            const direction = name.startsWith('deserialize') ? 'rx' : 'tx';
            listeners.push(Interceptor.attach(address, {
                onEnter(args) {
                    this.packet = args[0];
                },
                onLeave(result) {
                    // bool 成功和 PACKET_CORRECT 都是 1；不捕获残帧或失败包。
                    if (result.toInt32() !== 1) return;
                    try {
                        capture(this.packet, name, direction);
                    } catch (error) {
                        emit({ event: 'hook_callback_error', hook: name, error: String(error) });
                    }
                },
            }));
            emit({ event: 'hook_ready', hook: 'NetPacket.' + name, rva: address.sub(module.base).toString() });
        }
        emit({ event: 'sniffer_ready', arch: Process.arch, base: module.base.toString() });
    } catch (error) {
        for (const listener of listeners) listener.detach();
        emit({ event: 'hook_install_error', error: String(error) });
    }
}

if (Process.arch !== 'arm64' || Process.pointerSize !== 8) {
    emit({ event: 'unsupported_runtime', error: '需要 ARM64 realm，当前为 ' + Process.arch });
} else {
    const timer = setInterval(function () {
        const module = Process.findModuleByName('libil2cpp.so');
        if (module === null) return;
        clearInterval(timer);
        install(module);
    }, 100);
    emit({ event: 'waiting_runtime', error: '等待 libil2cpp.so 加载' });
}
