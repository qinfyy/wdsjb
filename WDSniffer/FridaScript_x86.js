'use strict';

// BH2 x86 应用层 Hook；Python 控制器加载前会替换此占位符。
const MAX_PACKET_BYTES = __MAX_PACKET_BYTES__;
const EXPECTED_ARCH = 'ia32';
const BYTE_ARRAY_LENGTH_OFFSET = 0x0c;
const BYTE_ARRAY_DATA_OFFSET = 0x10;
// 每条特征均在已验证的 x86 客户端中唯一命中。
const FUNCTION_SIGNATURES = {
    // public static int Pack(BaseNormalPacket mpoUserLoad, byte[] apBuffer, int alBuffLen);
    'GeneralPackage.Pack': {
        pattern: '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 00 80 bb ?? ?? 5e 00 00 75 1d 8b 83 ?? ?? fb ff 8b 00 8d 64 24 f4 50 e8 ?? ?? ?? f8 8d 64 24 10 c6 83 ?? ?? 5e 00 01 8b 7d 10 8b 75 08 8d 64 24 f8 6a 00 68 ?? 0e 00 00',
    },
    // public static int UnPack(BaseNormalPacket mpoUserLoad, byte[] apBuffer, int alBuffLen);
    'GeneralPackage.UnPack': {
        pattern: '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 00 80 bb ?? ?? 5e 00 00 75 1d 8b 83 ?? ?? fb ff 8b 00 8d 64 24 f4 50 e8 ?? ?? ?? f8 8d 64 24 10 c6 83 ?? ?? 5e 00 01 8b 75 10 8b 7d 08 8d 64 24 f8 6a 00 68 ?? 85 00 00',
    },
    // public static bool UnPackProtoBufPacket(byte[] apData, ref Type type, ref object msg);
    'NetworkOperation.UnPackProtoBufPacket': {
        pattern: '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 81 c3 ?? ?? ?? 03 80 bb ?? ?? 5d 00 00 75 1d 8b 83 ?? ?? fe ff 8b 00 8d 64 24 f4 50 e8 ?? ?? ?? fb 8d 64 24 10 c6 83 ?? ?? 5d 00 01 8b 75 10 8b 7d 08 8d 64 24 f8 6a 00 68 ?? 8f 00 00',
    },
    // public bool SendProtoBufPacket<T>(T aoPack, short cmd);
    'BaseNetworkClient.SendProtoBufPacket<Object>': {
        pattern: '55 89 e5 53 57 56 83 e4 f0 8d 64 24 e0 e8 00 00 00 00 5b 8b 75 08 81 c3 ?? ?? ?? 06 80 bb ?? ?? 47 00 00 75 1d 8b 83 ?? ?? ec ff 8b 00 8d 64 24 f4 50 e8 ?? ?? ?? fe 8d 64 24 10 c6 83 ?? ?? 47 00 01 85 f6 0f 84 13 04',
    },
    // public bool SendProtoBufPacketUshort<T>(T aoPack, ushort cmd);
    'BaseNetworkClient.SendProtoBufPacketUshort<Object>': {
        pattern: '55 89 e5 53 57 56 83 e4 f0 8d 64 24 f0 e8 00 00 00 00 5b 8b 45 08 81 c3 ?? ?? ?? 06 85 c0 74 26 8b 4d 14 0f b7 55 10 8b',
    },
    // public override void SendTo(byte[] buffer, int length, string name = null);
    'SocketClient.SendTo': {
        pattern: '55 8d 2c 24 53 56 83 e4 f0 e8 00 00 00 00 5b 8b 75 08 81 c3 ?? ?? ?? 04 8d 64 24 f8 6a 00 56 e8 ?? ?? 16 fe 8d 64 24 10',
    },
};

// SendProtoBufPacket<T> 内部调用 SocketClient.SendTo 后的返回地址。
// 特征从 E8 之后的第一条指令开始，命中地址可直接与 returnAddress 比较。
const PROTOBUF_SEND_TO_RETURN_SIGNATURE = '8d 64 24 20 8b 45 08 8d 4c 24 18 8b 40 08 89 01 8d 64 24 f8 31 ff 57 51';

let sequence = 0;
let installed = false;
let il2cppApi = null;
let protobufSendToReturnAddress = null;
const protobufSendContexts = new Map();

function emit(payload, data) {
    const now = Date.now();
    payload.seq = ++sequence;
    payload.ts_ms = now;
    if (data === undefined || data === null) {
        send(payload);
        return;
    }
    send(payload, data);
}

function emitStatus(event, details) {
    emit(Object.assign({ event: event }, details || {}));
}

function pointerText(value) {
    return value === undefined || value === null ? null : value.toString();
}

function readCString(value) {
    if (value === undefined || value === null || value.isNull()) {
        return '';
    }
    return value.readCString() || '';
}

function findIl2CppExport(module, name) {
    // Frida 16 从 Module 暴露该接口，较新版本也提供全局查询；libil2cpp
    // 直接导出了这些 API。
    try {
        if (typeof module.findExportByName === 'function') {
            const address = module.findExportByName(name);
            if (address !== null) {
                return address;
            }
        }
    } catch (_) {
        // 继续尝试下方的全局查询。
    }

    try {
        if (typeof Module.findGlobalExportByName === 'function') {
            return Module.findGlobalExportByName(name);
        }
    } catch (_) {
        // 由调用方统一上报一次元数据不可用状态。
    }
    return null;
}

function installIl2CppApi(module) {
    try {
        const objectGetClass = findIl2CppExport(
            module,
            'il2cpp_object_get_class',
        );
        const classGetName = findIl2CppExport(module, 'il2cpp_class_get_name');
        const classGetNamespace = findIl2CppExport(
            module,
            'il2cpp_class_get_namespace',
        );
        if (
            objectGetClass === null ||
            classGetName === null ||
            classGetNamespace === null
        ) {
            throw new Error(
                'one or more IL2CPP class metadata exports are unavailable',
            );
        }
        il2cppApi = {
            objectGetClass: new NativeFunction(objectGetClass, 'pointer', [
                'pointer',
            ]),
            classGetName: new NativeFunction(classGetName, 'pointer', [
                'pointer',
            ]),
            classGetNamespace: new NativeFunction(
                classGetNamespace,
                'pointer',
                ['pointer'],
            ),
        };
    } catch (error) {
        il2cppApi = null;
        emitStatus('metadata_unavailable', { error: String(error) });
    }
}

function describeManagedObject(instance) {
    if (
        il2cppApi === null ||
        instance === undefined ||
        instance === null ||
        instance.isNull()
    ) {
        return null;
    }
    try {
        const klass = il2cppApi.objectGetClass(instance);
        if (klass.isNull()) {
            return null;
        }
        const namespaceName = readCString(il2cppApi.classGetNamespace(klass));
        const name = readCString(il2cppApi.classGetName(klass));
        if (name.length === 0) {
            return null;
        }
        return {
            namespace: namespaceName,
            name: name,
            full_name:
                namespaceName.length === 0 ? name : namespaceName + '.' + name,
        };
    } catch (error) {
        return { error: String(error), pointer: pointerText(instance) };
    }
}

function readManagedByteArray(array, requestedLength) {
    if (array === undefined || array === null || array.isNull()) {
        return { error: 'null_byte_array' };
    }
    try {
        const arrayLength = array.add(BYTE_ARRAY_LENGTH_OFFSET).readU32();
        let captureLength = arrayLength;
        if (requestedLength !== undefined && requestedLength !== null) {
            if (requestedLength < 0) {
                return {
                    error: 'negative_requested_length',
                    array_length: arrayLength,
                    requested_length: requestedLength,
                };
            }
            captureLength = Math.min(arrayLength, requestedLength);
        }
        if (captureLength > MAX_PACKET_BYTES) {
            return {
                error: 'capture_length_exceeds_limit',
                array_length: arrayLength,
                capture_length: captureLength,
                limit: MAX_PACKET_BYTES,
            };
        }

        return {
            array_length: arrayLength,
            capture_length: captureLength,
            data:
                captureLength === 0
                    ? new ArrayBuffer(0)
                    : array
                          .add(BYTE_ARRAY_DATA_OFFSET)
                          .readByteArray(captureLength),
        };
    } catch (error) {
        return { error: String(error) };
    }
}

function readValidatedFrameLength(array) {
    if (array === undefined || array === null || array.isNull()) {
        return null;
    }
    try {
        const arrayLength = array.add(BYTE_ARRAY_LENGTH_OFFSET).readU32();
        if (arrayLength < 4) {
            return null;
        }
        const data = array.add(BYTE_ARRAY_DATA_OFFSET);
        const declaredLength =
            data.readU8() * 0x1000000 +
            data.add(1).readU8() * 0x10000 +
            data.add(2).readU8() * 0x100 +
            data.add(3).readU8();
        if (
            declaredLength < 42 ||
            declaredLength > arrayLength ||
            declaredLength > MAX_PACKET_BYTES
        ) {
            return null;
        }
        return declaredLength;
    } catch (_) {
        return null;
    }
}

function readFrameCommandId(array) {
    if (array === undefined || array === null || array.isNull()) {
        return null;
    }
    try {
        const arrayLength = array.add(BYTE_ARRAY_LENGTH_OFFSET).readU32();
        if (arrayLength < 6) {
            return null;
        }
        const data = array.add(BYTE_ARRAY_DATA_OFFSET);
        return (data.add(4).readU8() << 8) | data.add(5).readU8();
    } catch (_) {
        return null;
    }
}

function readOutPointer(pointer) {
    if (pointer === undefined || pointer === null || pointer.isNull()) {
        return null;
    }
    try {
        const value = pointer.readPointer();
        return value.isNull() ? null : value;
    } catch (_) {
        return null;
    }
}

function normalizeU16(value) {
    return value.toInt32() & 0xffff;
}

function pushProtobufSendContext(packet, commandId, method) {
    const threadId = Process.getCurrentThreadId();
    let stack = protobufSendContexts.get(threadId);
    if (stack === undefined) {
        stack = [];
        protobufSendContexts.set(threadId, stack);
    }
    const context = {
        packet: packet,
        command_id: commandId,
        method: method,
    };
    stack.push(context);
    return context;
}

function popProtobufSendContext(context) {
    if (context === undefined || context === null) {
        return;
    }
    const threadId = Process.getCurrentThreadId();
    const stack = protobufSendContexts.get(threadId);
    if (stack === undefined) {
        return;
    }
    const contextIndex = stack.lastIndexOf(context);
    if (contextIndex !== -1) {
        stack.splice(contextIndex, 1);
    }
    if (stack.length === 0) {
        protobufSendContexts.delete(threadId);
    }
}

function currentProtobufSendContext() {
    const stack = protobufSendContexts.get(Process.getCurrentThreadId());
    return stack === undefined || stack.length === 0
        ? null
        : stack[stack.length - 1];
}

function isProtobufSendToCallSite(returnAddress) {
    return (
        protobufSendToReturnAddress !== null &&
        returnAddress !== undefined &&
        returnAddress !== null &&
        returnAddress.equals(protobufSendToReturnAddress)
    );
}

function emitBusinessPacket(
    direction,
    stage,
    method,
    packet,
    array,
    requestedLength,
    protocolHint,
    extraMetadata,
) {
    const runtimeClass = describeManagedObject(packet);
    const managedType =
        runtimeClass !== null && typeof runtimeClass.full_name === 'string'
            ? runtimeClass.full_name
            : null;
    const result = readManagedByteArray(array, requestedLength);
    const packetMetadata = {
        event: 'business_packet',
        direction: direction,
        stage: stage,
        method: method,
        protocol_hint: protocolHint,
        command_id: readFrameCommandId(array),
        packet_pointer: pointerText(packet),
        // 传统 COMMAND 的对象类型不参与 Protobuf 的运行时分派。
        managedType: managedType,
        runtime_class: runtimeClass,
        array: {
            pointer: pointerText(array),
            array_length:
                result.array_length === undefined ? null : result.array_length,
            requested_length:
                requestedLength === undefined ? null : requestedLength,
            capture_length:
                result.capture_length === undefined
                    ? null
                    : result.capture_length,
            error: result.error === undefined ? null : result.error,
        },
    };
    if (extraMetadata !== undefined && extraMetadata !== null) {
        Object.keys(extraMetadata).forEach(function (key) {
            packetMetadata[key] = extraMetadata[key];
        });
    }
    if (result.error !== undefined) {
        emitStatus('packet_capture_error', {
            direction: direction,
            stage: stage,
            method: method,
            protocol_hint: protocolHint,
            command_id: packetMetadata.command_id,
            packet_pointer: pointerText(packet),
            managedType: managedType,
            runtime_class: runtimeClass,
            array: packetMetadata.array,
        });
        return;
    }
    emit(packetMetadata, result.data);
}

function executableAddress(address, name) {
    const range = Process.findRangeByAddress(address);
    if (range === null || range.protection.indexOf('x') === -1) {
        throw new Error(
            name +
                ' is not executable at ' +
                address +
                ' (' +
                (range === null ? 'unmapped' : range.protection) +
                ')',
        );
    }
    return address;
}

function signatureAddress(module, name) {
    const signature = FUNCTION_SIGNATURES[name];
    if (signature === undefined) {
        throw new Error('missing signature for ' + name);
    }

    const matches = new Map();
    for (const range of module.enumerateRanges('r-x')) {
        for (const match of Memory.scanSync(
            range.base,
            range.size,
            signature.pattern,
        )) {
            matches.set(match.address.toString(), match.address);
        }
    }
    if (matches.size !== 1) {
        throw new Error(
            name + ' signature matched ' + matches.size + ' addresses',
        );
    }
    return executableAddress(matches.values().next().value, name);
}

function resolveProtobufSendToReturnAddress(module) {
    const matches = new Map();
    for (const range of module.enumerateRanges('r-x')) {
        for (const match of Memory.scanSync(
            range.base,
            range.size,
            PROTOBUF_SEND_TO_RETURN_SIGNATURE,
        )) {
            matches.set(match.address.toString(), match.address);
        }
    }
    if (matches.size !== 1) {
        throw new Error(
            'protobuf SendTo return signature matched ' +
                matches.size +
                ' addresses',
        );
    }
    return executableAddress(
        matches.values().next().value,
        'BaseNetworkClient.SendProtoBufPacket<T> SendTo return',
    );
}

function hook(module, name, callbacks) {
    const address = signatureAddress(module, name);
    Interceptor.attach(address, callbacks);
    emitStatus('hook_ready', {
        hook: name,
        rva: '0x' + address.sub(module.base).toString(16),
        address: address.toString(),
    });
}

function installHooks(module) {
    installIl2CppApi(module);
    protobufSendToReturnAddress = resolveProtobufSendToReturnAddress(module);

    hook(module, 'GeneralPackage.Pack', {
        onEnter(args) {
            this.packet = args[0];
            this.buffer = args[1];
        },
        onLeave(retval) {
            try {
                const written = retval.toInt32();
                if (written <= 0) {
                    return;
                }
                emitBusinessPacket(
                    'tx',
                    'GeneralPackage.Pack.return',
                    'GeneralPackage.Pack',
                    this.packet,
                    this.buffer,
                    written,
                    'command',
                );
            } catch (error) {
                emitStatus('hook_callback_error', {
                    hook: 'GeneralPackage.Pack',
                    error: String(error),
                });
            }
        },
    });

    // GeneralPackage 只处理传统 BaseNormalPacket / COMMAND。
    hook(module, 'GeneralPackage.UnPack', {
        onEnter(args) {
            try {
                emitBusinessPacket(
                    'rx',
                    'GeneralPackage.UnPack.enter',
                    'GeneralPackage.UnPack',
                    args[0],
                    args[1],
                    args[2].toInt32(),
                    'command',
                );
            } catch (error) {
                emitStatus('hook_callback_error', {
                    hook: 'GeneralPackage.UnPack',
                    error: String(error),
                });
            }
        },
    });

    // apData 是完整业务帧；仅在函数成功时，它才被客户端判定为 Protobuf。
    hook(module, 'NetworkOperation.UnPackProtoBufPacket', {
        onEnter(args) {
            this._bh2Frame = args[0];
            this._bh2TypeOut = args[1];
            this._bh2MessageOut = args[2];
        },
        onLeave(retval) {
            try {
                if (retval.toInt32() === 0) {
                    return;
                }
                const resolvedType = readOutPointer(this._bh2TypeOut);
                const message = readOutPointer(this._bh2MessageOut);
                // 收包缓冲区可大于当前帧，按 ProtocolHead 的长度截取真实帧。
                const frameLength = readValidatedFrameLength(this._bh2Frame);
                emitBusinessPacket(
                    'rx',
                    'NetworkOperation.UnPackProtoBufPacket.return',
                    'NetworkOperation.UnPackProtoBufPacket',
                    message,
                    this._bh2Frame,
                    frameLength === null ? undefined : frameLength,
                    'protobuf',
                    {
                        protobuf_frame_length: frameLength,
                        protobuf_type_pointer: pointerText(resolvedType),
                        protobuf_message_pointer: pointerText(message),
                    },
                );
            } catch (error) {
                emitStatus('hook_callback_error', {
                    hook: 'NetworkOperation.UnPackProtoBufPacket',
                    error: String(error),
                });
            }
        },
    });

    // 发送入口只有对象和 cmd；序列化后的完整帧会在同线程的 SendTo 中出现。
    hook(module, 'BaseNetworkClient.SendProtoBufPacket<Object>', {
        onEnter(args) {
            this._bh2ProtobufSendContext = pushProtobufSendContext(
                args[1],
                normalizeU16(args[2]),
                'BaseNetworkClient.SendProtoBufPacket<Object>',
            );
        },
        onLeave() {
            popProtobufSendContext(this._bh2ProtobufSendContext);
        },
    });

    hook(module, 'BaseNetworkClient.SendProtoBufPacketUshort<Object>', {
        onEnter(args) {
            this._bh2ProtobufSendContext = pushProtobufSendContext(
                args[1],
                normalizeU16(args[2]),
                'BaseNetworkClient.SendProtoBufPacketUshort<Object>',
            );
        },
        onLeave() {
            popProtobufSendContext(this._bh2ProtobufSendContext);
        },
    });

    hook(module, 'SocketClient.SendTo', {
        onEnter(args) {
            try {
                if (!isProtobufSendToCallSite(this.returnAddress)) {
                    return;
                }
                const context = currentProtobufSendContext();
                if (context === null) {
                    return;
                }
                const frameCommandId = readFrameCommandId(args[1]);
                if (
                    frameCommandId === null ||
                    frameCommandId !== context.command_id
                ) {
                    return;
                }
                emitBusinessPacket(
                    'tx',
                    'SocketClient.SendTo.enter',
                    context.method,
                    context.packet,
                    args[1],
                    args[2].toInt32(),
                    'protobuf',
                    {
                        protobuf_send_cmd_id: context.command_id,
                    },
                );
            } catch (error) {
                emitStatus('hook_callback_error', {
                    hook: 'SocketClient.SendTo',
                    error: String(error),
                });
            }
        },
    });
}

const poller = setInterval(function () {
    if (installed) {
        return;
    }

    let module;
    try {
        module = Process.getModuleByName('libil2cpp.so');
    } catch (_) {
        return;
    }

    if (Process.arch !== EXPECTED_ARCH || Process.pointerSize !== 4) {
        clearInterval(poller);
        emitStatus('unsupported_runtime', {
            expected_arch: EXPECTED_ARCH,
            actual_arch: Process.arch,
            pointer_size: Process.pointerSize,
            module_path: module.path,
        });
        return;
    }

    try {
        installHooks(module);
        installed = true;
        clearInterval(poller);
        emitStatus('sniffer_ready', {
            process_arch: Process.arch,
            pointer_size: Process.pointerSize,
            module: {
                name: module.name,
                base: module.base.toString(),
                size: module.size,
                path: module.path,
            },
            max_packet_bytes: MAX_PACKET_BYTES,
        });
    } catch (error) {
        clearInterval(poller);
        emitStatus('hook_install_error', { error: String(error) });
    }
}, 100);

emitStatus('sniffer_started', {
    expected_arch: EXPECTED_ARCH,
    process_arch: Process.arch,
    pointer_size: Process.pointerSize,
    max_packet_bytes: MAX_PACKET_BYTES,
});
