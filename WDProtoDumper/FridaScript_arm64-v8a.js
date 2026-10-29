'use strict';

const PTR = 8, ARRAY_LENGTH = 0x18, ARRAY_DATA = 0x20;
const SAMPLE_STRING = 'WD_PROTO_SAMPLE';
// 当前 ARM64 libil2cpp.so 的公共 API RVA，不依赖 Native Bridge 导出符号。
const IL2CPP_RVAS = {
    il2cpp_domain_get: 0x029BE708,
    il2cpp_domain_get_assemblies: 0x029BE714,
    il2cpp_thread_attach: 0x029BE9C0,
    il2cpp_thread_detach: 0x029BE9C4,
    il2cpp_assembly_get_image: 0x029BE37C,
    il2cpp_image_get_name: 0x029BEB20,
    il2cpp_image_get_class_count: 0x029BEB2C,
    il2cpp_image_get_class: 0x029BEB30,
    il2cpp_class_get_name: 0x029BE3D4,
    il2cpp_class_get_namespace: 0x029BE3D8,
    il2cpp_class_get_declaring_type: 0x029BE3E0,
    il2cpp_class_get_type: 0x029BE410,
    il2cpp_class_from_il2cpp_type: 0x029BE3A0,
    il2cpp_class_get_flags: 0x029BE3F8,
    il2cpp_class_is_enum: 0x029BE424,
    il2cpp_class_is_assignable_from: 0x029BE390,
    il2cpp_class_get_methods: 0x029BE3CC,
    il2cpp_class_get_fields: 0x029BE3B4,
    il2cpp_class_get_nested_types: 0x029BE3B8,
    il2cpp_method_get_name: 0x029BE878,
    il2cpp_method_get_param_count: 0x029BE888,
    il2cpp_method_get_param: 0x029BE88C,
    il2cpp_field_get_name: 0x029BE7F0,
    il2cpp_field_get_type: 0x029BE800,
    il2cpp_field_get_flags: 0x029BE7F4,
    il2cpp_field_get_offset: 0x029BE7FC,
    il2cpp_field_get_value_object: 0x029BE808,
    il2cpp_field_set_value: 0x029BE810,
    il2cpp_type_get_name: 0x029BEA24,
    il2cpp_type_get_class_or_element_class: 0x029BEA20,
    il2cpp_object_get_class: 0x029BE908,
    il2cpp_object_new: 0x029BE914,
    il2cpp_object_unbox: 0x029BE938,
    il2cpp_runtime_invoke: 0x029BE974,
    il2cpp_string_new: 0x029BE9A4,
    il2cpp_gchandle_new: 0x029BE83C,
    il2cpp_gchandle_free: 0x029BE858,
    il2cpp_free: 0x029BE354,
};
const SCALARS = {
    'System.Boolean': 'bool', 'System.String': 'string',
    'System.Int32': 'int32', 'System.UInt32': 'uint32',
    'System.Int64': 'int64', 'System.UInt64': 'uint64',
    'System.Single': 'float', 'System.Double': 'double',
    'Google.Protobuf.ByteString': 'bytes',
};
let api, moduleInfo, thread, serializer, byteStringFactory;
let settings = {}, finished = false, sequence = 0, pending = [], position = 0;
let messageCount = 0, fieldCount = 0, failedCount = 0;
const classes = new Map(), names = new Map(), methods = new Map(), fields = new Map();
const emittedEnums = new Set();
const queued = new Set();
const nonSchemaMessages = [];

function emit(payload) { send(Object.assign({ seq: ++sequence }, payload)); }
function cString(p) { return p.isNull() ? '' : p.readCString(); }

function bind(module, name, result, args) {
    if (!(name in IL2CPP_RVAS)) throw new Error('缺少 IL2CPP API RVA：' + name);
    return new NativeFunction(module.base.add(IL2CPP_RVAS[name]), result, args);
}

function installApi(module) {
    const definitions = {
        il2cpp_domain_get: ['pointer', []],
        il2cpp_domain_get_assemblies: ['pointer', ['pointer', 'pointer']],
        il2cpp_thread_attach: ['pointer', ['pointer']],
        il2cpp_thread_detach: ['void', ['pointer']],
        il2cpp_assembly_get_image: ['pointer', ['pointer']],
        il2cpp_image_get_name: ['pointer', ['pointer']],
        il2cpp_image_get_class_count: ['uint64', ['pointer']],
        il2cpp_image_get_class: ['pointer', ['pointer', 'uint64']],
        il2cpp_class_get_name: ['pointer', ['pointer']],
        il2cpp_class_get_namespace: ['pointer', ['pointer']],
        il2cpp_class_get_declaring_type: ['pointer', ['pointer']],
        il2cpp_class_get_type: ['pointer', ['pointer']],
        il2cpp_class_from_il2cpp_type: ['pointer', ['pointer']],
        il2cpp_class_get_flags: ['uint32', ['pointer']],
        il2cpp_class_is_enum: ['bool', ['pointer']],
        il2cpp_class_is_assignable_from: ['bool', ['pointer', 'pointer']],
        il2cpp_class_get_methods: ['pointer', ['pointer', 'pointer']],
        il2cpp_class_get_fields: ['pointer', ['pointer', 'pointer']],
        il2cpp_class_get_nested_types: ['pointer', ['pointer', 'pointer']],
        il2cpp_method_get_name: ['pointer', ['pointer']],
        il2cpp_method_get_param_count: ['uint32', ['pointer']],
        il2cpp_method_get_param: ['pointer', ['pointer', 'uint32']],
        il2cpp_field_get_name: ['pointer', ['pointer']],
        il2cpp_field_get_type: ['pointer', ['pointer']],
        il2cpp_field_get_flags: ['uint32', ['pointer']],
        il2cpp_field_get_offset: ['uint32', ['pointer']],
        il2cpp_field_get_value_object: ['pointer', ['pointer', 'pointer']],
        il2cpp_field_set_value: ['void', ['pointer', 'pointer', 'pointer']],
        il2cpp_type_get_name: ['pointer', ['pointer']],
        il2cpp_type_get_class_or_element_class: ['pointer', ['pointer']],
        il2cpp_object_get_class: ['pointer', ['pointer']],
        il2cpp_object_new: ['pointer', ['pointer']],
        il2cpp_object_unbox: ['pointer', ['pointer']],
        il2cpp_runtime_invoke: ['pointer', ['pointer', 'pointer', 'pointer', 'pointer']],
        il2cpp_string_new: ['pointer', ['pointer']],
        il2cpp_gchandle_new: ['uint32', ['pointer', 'bool']],
        il2cpp_gchandle_free: ['void', ['uint32']],
        il2cpp_free: ['void', ['pointer']],
    };
    const result = {};
    for (const [name, signature] of Object.entries(definitions))
        result[name] = bind(module, name, signature[0], signature[1]);
    return result;
}

function typeName(type) {
    const p = api.il2cpp_type_get_name(type);
    try { return cString(p).replace(/\+/g, '/'); }
    finally { if (!p.isNull()) api.il2cpp_free(p); }
}

function classInfo(klass) {
    const key = klass.toString();
    if (names.has(key)) return names.get(key);
    const name = cString(api.il2cpp_class_get_name(klass));
    const namespace = cString(api.il2cpp_class_get_namespace(klass));
    const declaring = api.il2cpp_class_get_declaring_type(klass);
    const parent = declaring.isNull() ? null : classInfo(declaring);
    const fullName = parent ? parent.full_name + '/' + name : (namespace ? namespace + '.' : '') + name;
    const result = { name, namespace: parent ? parent.namespace : namespace,
        full_name: fullName, declaring_full_name: parent ? parent.full_name : null };
    names.set(key, result);
    return result;
}

function enumerate(klass, apiName) {
    const iterator = Memory.alloc(PTR);
    iterator.writePointer(NULL);
    const result = [];
    for (;;) {
        const item = api[apiName](klass, iterator);
        if (item.isNull()) return result;
        result.push(item);
    }
}

function getMethods(klass) {
    const key = klass.toString();
    if (!methods.has(key)) methods.set(key, enumerate(klass, 'il2cpp_class_get_methods').map(p => ({
        pointer: p, name: cString(api.il2cpp_method_get_name(p)),
        params: Array.from({ length: api.il2cpp_method_get_param_count(p) }, (_, i) => api.il2cpp_method_get_param(p, i)),
    })));
    return methods.get(key);
}

function method(klass, name, parameters) {
    const result = getMethods(klass).filter(m => m.name === name && m.params.length === parameters.length &&
        m.params.every((p, i) => typeName(p) === parameters[i]));
    if (result.length !== 1) throw new Error(classInfo(klass).full_name + '::' + name + ' 匹配数=' + result.length);
    return result[0].pointer;
}

function getFields(klass) {
    const key = klass.toString();
    if (!fields.has(key)) fields.set(key, enumerate(klass, 'il2cpp_class_get_fields').map(p => ({
        pointer: p, name: cString(api.il2cpp_field_get_name(p)),
        type: api.il2cpp_field_get_type(p), flags: api.il2cpp_field_get_flags(p),
        offset: api.il2cpp_field_get_offset(p),
    })));
    return fields.get(key);
}

function invoke(methodInfo, object, values) {
    const exception = Memory.alloc(PTR);
    exception.writePointer(NULL);
    let args = NULL;
    if (values.length) {
        args = Memory.alloc(values.length * PTR);
        values.forEach((p, i) => args.add(i * PTR).writePointer(p));
    }
    const result = api.il2cpp_runtime_invoke(methodInfo, object, args, exception);
    const thrown = exception.readPointer();
    if (!thrown.isNull()) throw new Error('托管异常：' + classInfo(api.il2cpp_object_get_class(thrown)).full_name);
    return result;
}

function root(object, handles) {
    if (object.isNull()) throw new Error('托管对象为空');
    handles.push(api.il2cpp_gchandle_new(object, 0));
    return object;
}

function instance(klass, handles) {
    const object = root(api.il2cpp_object_new(klass), handles);
    invoke(method(klass, '.ctor', []), object, []);
    return object;
}

function isMessage(klass) {
    return api.il2cpp_class_is_assignable_from(classes.get('Google.Protobuf.IMessage'), klass) &&
        !(api.il2cpp_class_get_flags(klass) & 0x80);
}

function value(type, handles) {
    const name = typeName(type), klass = api.il2cpp_class_from_il2cpp_type(type);
    const storage = Memory.alloc(8), isEnum = api.il2cpp_class_is_enum(klass);
    if (isEnum || ['System.Int32', 'System.UInt32'].includes(name)) {
        storage.writeS32(isEnum ? 1 : name === 'System.UInt32' ? 37 : -37);
        return { argument: storage, storage, type: name, is_enum: isEnum };
    }
    if (['System.Int64', 'System.UInt64'].includes(name)) {
        storage.writeS64(name === 'System.UInt64' ? 37 : -37);
        return { argument: storage, storage, type: name, is_enum: false };
    }
    if (name === 'System.Boolean') storage.writeU8(1);
    else if (name === 'System.Single') storage.writeFloat(12.5);
    else if (name === 'System.Double') storage.writeDouble(12.5);
    else {
        let object;
        if (name === 'System.String') object = root(api.il2cpp_string_new(Memory.allocUtf8String(SAMPLE_STRING)), handles);
        else if (name === 'Google.Protobuf.ByteString') {
            const s = root(api.il2cpp_string_new(Memory.allocUtf8String(SAMPLE_STRING)), handles);
            object = root(invoke(byteStringFactory, NULL, [s]), handles);
        } else if (isMessage(klass)) {
            const fullName = classInfo(klass).full_name;
            if (!queued.has(fullName)) {
                queued.add(fullName);
                pending.push(klass);
            }
            object = instance(klass, handles);
        }
        else throw new Error('非 protobuf 字段类型：' + name);
        storage.writePointer(object);
        return { argument: object, storage, type: name, is_enum: false };
    }
    return { argument: storage, storage, type: name, is_enum: false };
}

function bytesOf(array) {
    const size = array.add(ARRAY_LENGTH).readU64().toNumber();
    if (size > 1048576) throw new Error('样本序列化结果超过 1 MiB');
    return new Uint8Array(array.add(ARRAY_DATA).readByteArray(size));
}

function hex(bytes) { return Array.from(bytes, v => v.toString(16).padStart(2, '0')).join(''); }

function varintAt(bytes, start) {
    let value = 0n, offset = start;
    for (let shift = 0n; shift < 70n; shift += 7n) {
        if (offset >= bytes.length) throw new Error('截断的 varint');
        const byte = bytes[offset++];
        value |= BigInt(byte & 127) << shift;
        if (!(byte & 128)) return { value, offset };
    }
    throw new Error('varint 超长');
}

function parseWire(bytes) {
    let offset = 0;
    const result = [];
    while (offset < bytes.length) {
        const start = offset, decoded = varintAt(bytes, offset), key = Number(decoded.value);
        offset = decoded.offset;
        const tag = Math.floor(key / 8), wire = key & 7;
        if (!tag || ![0, 1, 2, 5].includes(wire)) throw new Error('不支持的 protobuf tag/wire：' + key);
        const item = { tag, wire };
        if (wire === 0) {
            const v = varintAt(bytes, offset);
            item.value = v.value;
            offset = v.offset;
        } else {
            let length = wire === 1 ? 8 : 4;
            if (wire === 2) {
                const v = varintAt(bytes, offset);
                length = Number(v.value);
                offset = v.offset;
            }
            if (offset + length > bytes.length) throw new Error('截断的 protobuf 字段');
            item.payload = bytes.slice(offset, offset + length);
            offset += length;
        }
        item.raw = hex(bytes.slice(start, offset));
        result.push(item);
    }
    return result;
}

function serialize(object) { return bytesOf(invoke(serializer, NULL, [object])); }

function changedField(before, after) {
    const old = new Map(parseWire(before).map(f => [f.tag, f.raw]));
    const changed = parseWire(after).filter(f => old.get(f.tag) !== f.raw);
    const tags = [...new Set(changed.map(f => f.tag))];
    if (tags.length === 0) return null;
    if (tags.length !== 1) throw new Error('逐字段样本改变了多个 tag：' + tags.join(','));
    return changed[0];
}

function scalarType(info, wire, repeated, fixedSize = 0) {
    let kind = SCALARS[info.type];
    let actualWire = wire.wire, raw = wire.value;
    if (repeated && actualWire === 2 && (info.is_enum || kind && !['string', 'bytes'].includes(kind))) {
        actualWire = kind === 'float' || fixedSize === 4 ? 5 : kind === 'double' || fixedSize === 8 ? 1 : 0;
        if (actualWire === 0) raw = varintAt(wire.payload, 0).value;
    }
    if (info.is_enum) {
        if (actualWire !== 0 || raw !== 1n) throw new Error('枚举样本值不匹配');
        return { type: info.type, is_enum: true };
    }
    if (!kind) {
        if (actualWire !== 2) throw new Error('消息不是 length-delimited');
        parseWire(wire.payload);
        return { type: info.type, is_enum: false };
    }
    if (['string', 'bytes'].includes(kind)) {
        const expected = hex(Uint8Array.from(SAMPLE_STRING, c => c.charCodeAt(0)));
        if (actualWire !== 2 || hex(wire.payload) !== expected) throw new Error('字符串/字节样本内容不匹配');
    } else if (kind === 'bool') {
        if (actualWire !== 0 || raw !== 1n) throw new Error('布尔样本值不匹配');
    } else if (['float', 'double'].includes(kind)) {
        const size = kind === 'float' ? 4 : 8, expectedWire = size === 4 ? 5 : 1;
        if (actualWire !== expectedWire || wire.payload.length !== size) throw new Error('浮点样本编码不匹配');
        const view = new DataView(wire.payload.buffer, wire.payload.byteOffset, wire.payload.byteLength);
        if ((size === 4 ? view.getFloat32(0, true) : view.getFloat64(0, true)) !== 12.5)
            throw new Error('浮点样本值不匹配');
    }
    if (kind === 'int32' || kind === 'int64') {
        if (actualWire === 5) kind = 'sfixed32';
        else if (actualWire === 1) kind = 'sfixed64';
        else if (actualWire !== 0) throw new Error('有符号整数 wire 不匹配');
        else if (raw === 73n) kind = kind === 'int32' ? 'sint32' : 'sint64';
        else if (raw !== BigInt.asUintN(64, -37n) && raw !== BigInt.asUintN(32, -37n))
            throw new Error('有符号样本编码无法解释：' + String(raw));
    } else if (['uint32', 'uint64'].includes(kind)) {
        if (kind === 'uint32' && actualWire === 5) kind = 'fixed32';
        else if (kind === 'uint64' && actualWire === 1) kind = 'fixed64';
        else if (actualWire !== 0 || raw !== 37n) throw new Error('无符号整数样本值不匹配');
    }
    if (/^s?fixed/.test(kind)) {
        const size = kind.endsWith('32') ? 4 : 8;
        if (wire.payload.length !== size) throw new Error('定长整数样本长度不匹配');
        const view = new DataView(wire.payload.buffer, wire.payload.byteOffset, wire.payload.byteLength);
        const actual = size === 4 ? BigInt(view.getUint32(0, true)) :
            BigInt(view.getUint32(0, true)) | BigInt(view.getUint32(4, true)) << 32n;
        const expected = BigInt.asUintN(size * 8, kind.startsWith('s') ? -37n : 37n);
        if (actual !== expected) throw new Error('定长整数样本值不匹配');
    }
    return { type: kind, is_enum: false };
}

function repeatedFixedSize(klass, field) {
    const codec = getFields(klass).find(f => f.name === '_repeated_' + field.name.replace(/_$/, '') + '_codec');
    if (!codec) throw new Error('找不到重复字段的 FieldCodec：' + field.name);
    const object = api.il2cpp_field_get_value_object(codec.pointer, NULL);
    const codecClass = api.il2cpp_object_get_class(object);
    const fixed = getFields(codecClass).find(f => /FixedSize.*BackingField/.test(f.name));
    if (!fixed) throw new Error('FieldCodec 缺少 FixedSize 元数据');
    return object.add(fixed.offset).readS32();
}

function emitEnum(klass) {
    if (!api.il2cpp_class_is_enum(klass)) return;
    const info = classInfo(klass);
    if (info.name === 'CmdId' || emittedEnums.has(info.full_name)) return;
    emittedEnums.add(info.full_name);
    const values = getFields(klass).filter(f => f.flags & 0x40).map(f => {
        const object = api.il2cpp_field_get_value_object(f.pointer, NULL);
        return { name: f.name, value: api.il2cpp_object_unbox(object).readS32() };
    });
    emit(Object.assign({ event: 'record', kind: 'enum', values, is_proto_contract: true }, info));
}

function dumpField(klass, field) {
    const handles = [];
    try {
        const object = instance(klass, handles), before = serialize(object), rawType = typeName(field.type);
        const result = { name: field.name.replace(/_$/, ''), wire_name: field.name.replace(/_$/, ''),
            offset: field.offset, clr_type: rawType, source: 'runtime_write_to' };
        let sampleInfo, repetition = false, mapInfo = null, fixedSize = 0;
        if (rawType.startsWith('Google.Protobuf.Collections.RepeatedField<')) {
            repetition = true;
            const collection = api.il2cpp_field_get_value_object(field.pointer, object);
            const collectionClass = api.il2cpp_object_get_class(collection);
            const add = getMethods(collectionClass).find(m => m.name === 'Add' && m.params.length === 1 &&
                !typeName(m.params[0]).startsWith('System.Collections.Generic.IEnumerable'));
            if (!add) throw new Error('RepeatedField.Add(T) 不存在');
            sampleInfo = value(add.params[0], handles);
            invoke(add.pointer, collection, [sampleInfo.argument]);
            fixedSize = repeatedFixedSize(klass, field);
            if (sampleInfo.is_enum) emitEnum(api.il2cpp_class_from_il2cpp_type(add.params[0]));
        } else if (rawType.startsWith('Google.Protobuf.Collections.MapField<')) {
            const collection = api.il2cpp_field_get_value_object(field.pointer, object);
            const add = getMethods(api.il2cpp_object_get_class(collection)).find(m => m.name === 'Add' && m.params.length === 2);
            if (!add) throw new Error('MapField.Add(K,V) 不存在');
            const key = value(add.params[0], handles), val = value(add.params[1], handles);
            invoke(add.pointer, collection, [key.argument, val.argument]);
            mapInfo = { key, val };
            if (val.is_enum) emitEnum(api.il2cpp_class_from_il2cpp_type(add.params[1]));
        } else {
            sampleInfo = value(field.type, handles);
            // 此版本引用类型直接传对象；值类型传存储地址。
            api.il2cpp_field_set_value(object, field.pointer, sampleInfo.argument);
            if (sampleInfo.is_enum) emitEnum(api.il2cpp_class_from_il2cpp_type(field.type));
        }
        const after = serialize(object), observed = changedField(before, after);
        if (observed === null) return null;
        result.tag = observed.tag;
        result.wire_type = observed.wire;
        result.sample_hex = hex(after);
        if (mapInfo) {
            if (observed.wire !== 2) throw new Error('map 不是 length-delimited');
            const entries = parseWire(observed.payload);
            const keyWire = entries.find(e => e.tag === 1), valWire = entries.find(e => e.tag === 2);
            if (!keyWire || !valWire) throw new Error('map 样本缺少 key/value');
            result.map_key_type = scalarType(mapInfo.key, keyWire, false).type;
            const val = scalarType(mapInfo.val, valWire, false);
            result.map_value_type = val.type;
            result.type = 'map';
            result.is_enum = val.is_enum;
        } else {
            Object.assign(result, scalarType(sampleInfo, observed, repetition, fixedSize));
            result.repeated = repetition;
            result.packed = repetition && observed.wire === 2 && !['string', 'bytes'].includes(result.type) &&
                (result.is_enum || Object.values(SCALARS).includes(result.type) || /^(s?fixed|sint)/.test(result.type));
        }
        return result;
    } finally { for (const handle of handles.reverse()) api.il2cpp_gchandle_free(handle); }
}

function verifyAuxiliaryField(klass, field, type) {
    const handles = [];
    try {
        const object = instance(klass, handles), before = serialize(object);
        let sample = NULL;
        if (type === 'System.DateTime') {
            sample = Memory.alloc(8);
            sample.writeU64(37);
        } else {
            const collectionClass = api.il2cpp_class_from_il2cpp_type(field.type);
            sample = instance(collectionClass, handles);
            const add = getMethods(collectionClass).find(m => m.name === 'Add' && m.params.length === 1);
            if (!add) throw new Error('辅助集合缺少 Add(T)，不能验证排除');
            invoke(add.pointer, sample, [value(add.params[0], handles).argument]);
        }
        api.il2cpp_field_set_value(object, field.pointer, sample);
        if (hex(before) !== hex(serialize(object))) throw new Error('辅助字段改变了序列化输出，不能排除');
    } finally { for (const handle of handles.reverse()) api.il2cpp_gchandle_free(handle); }
}

function dumpMessage(klass) {
    const info = classInfo(klass), collected = [], excluded = [], errors = [];
    emit(Object.assign({ event: 'dumping', kind: 'message', index: position, total: pending.length }, info));
    for (const field of getFields(klass)) {
        const type = typeName(field.type);
        if (field.flags & (0x10 | 0x40) || type === 'Google.Protobuf.UnknownFieldSet') continue;
        try {
            if (type === 'System.DateTime' || type.startsWith('System.Collections.')) {
                verifyAuxiliaryField(klass, field, type);
                excluded.push({ name: field.name, type, reason: '已验证：修改辅助字段不改变序列化输出' });
                continue;
            }
            const result = dumpField(klass, field);
            if (result) collected.push(result);
            else excluded.push({ name: field.name, type, reason: '修改样本不改变序列化输出' });
        } catch (error) {
            errors.push({ field: field.name, type, error: error.stack || String(error) });
            emit({ event: 'warning', stage: 'field', full_name: info.full_name, field: field.name, error: error.stack || String(error) });
        }
    }
    if (new Set(collected.map(f => f.tag)).size !== collected.length) errors.push({ error: '重复字段 tag' });
    fieldCount += collected.length;
    messageCount++;
    if (errors.length) failedCount++;
    emit(Object.assign({ event: 'record', kind: 'message', fields: collected,
        excluded_fields: excluded, errors, extraction_failed: errors.length > 0 }, info));
    // CmdId 属于命令元数据，不能当作消息 wire 字段。
    for (const owner of enumerate(klass, 'il2cpp_class_get_nested_types'))
        for (const child of [owner, ...enumerate(owner, 'il2cpp_class_get_nested_types')]) {
            if (api.il2cpp_class_is_enum(child) && classInfo(child).name === 'CmdId') {
                const command = getFields(child).find(f => ['CmdId', 'CMD_ID'].includes(f.name) && (f.flags & 0x40));
                if (command) {
                    const v = api.il2cpp_field_get_value_object(command.pointer, NULL);
                    emit({ event: 'command', full_name: info.full_name, name: info.name, namespace: info.namespace,
                        cmd_id: api.il2cpp_object_unbox(v).readS32() });
                }
            } else emitEnum(child);
        }
}

function finish(error) {
    if (finished) return;
    finished = true;
    if (thread && !thread.isNull()) api.il2cpp_thread_detach(thread);
    if (error) emit({ event: 'error', stage: 'runtime', error: String(error) });
    else emit({ event: 'done', messages: messageCount, fields: fieldCount, enums: emittedEnums.size,
        failed_messages: failedCount, engine: 'google_protobuf_runtime_write_to', arch: Process.arch,
        non_schema_messages: nonSchemaMessages,
        module: { path: moduleInfo.path, base: moduleInfo.base.toString(), size: moduleInfo.size } });
}

function next() {
    try {
        if (position >= pending.length) return finish();
        dumpMessage(pending[position++]);
        setImmediate(next);
    } catch (error) { finish(error.stack || error); }
}

function start(module) {
    try {
        if (Process.arch !== 'arm64' || Process.pointerSize !== PTR) throw new Error('需要 ARM64 Emulated Realm，实际为 ' + Process.arch);
        moduleInfo = module;
        api = installApi(module);
        const domain = api.il2cpp_domain_get();
        if (domain.isNull()) return setTimeout(() => start(module), 1000);
        thread = api.il2cpp_thread_attach(domain);
        const count = Memory.alloc(PTR);
        count.writeU64(0);
        const assemblies = api.il2cpp_domain_get_assemblies(domain, count);
        for (let i = 0; i < count.readU64().toNumber(); i++) {
            const image = api.il2cpp_assembly_get_image(assemblies.add(i * PTR).readPointer());
            const imageName = cString(api.il2cpp_image_get_name(image));
            const classCount = api.il2cpp_image_get_class_count(image).toNumber();
            for (let j = 0; j < classCount; j++) {
                const klass = api.il2cpp_image_get_class(image, j);
                if (klass.isNull()) continue;
                const info = classInfo(klass);
                if (!classes.has(info.full_name)) classes.set(info.full_name, klass);
                info.assembly = imageName;
            }
        }
        const descriptors = [...classes.keys()].filter(n => /^Google\.Protobuf\.Reflection\./.test(n));
        if (!classes.has('Google.Protobuf.IMessage')) throw new Error('没有 Google.Protobuf.IMessage');
        serializer = method(classes.get('Google.Protobuf.MessageExtensions'), 'ToByteArray', ['Google.Protobuf.IMessage']);
        byteStringFactory = method(classes.get('Google.Protobuf.ByteString'), 'CopyFromUtf8', ['System.String']);
        const prefixes = (settings.namespacePrefix || '').split(',').filter(Boolean);
        const filter = settings.messageFilter ? new Set(settings.messageFilter.split(',')) : null;
        for (const [name, klass] of classes) {
            const info = classInfo(klass);
            if (info.assembly !== 'Assembly-CSharp.dll' || name.includes(String.fromCharCode(96)) || !isMessage(klass)) continue;
            if (prefixes.length && !prefixes.some(p => info.namespace === p || info.namespace.startsWith(p + '.'))) continue;
            if (filter && !filter.has(name) && !filter.has(info.name)) continue;
            if (['Pb.TsMessageReq', 'Pb.TsMessageRsp'].includes(name)) {
                nonSchemaMessages.push({ full_name: name, reason: 'TypeScript 原始字节包装器，不是 protobuf wire 消息' });
                continue;
            }
            queued.add(name);
            pending.push(klass);
        }
        pending.sort((a, b) => classInfo(a).full_name.localeCompare(classInfo(b).full_name));
        emit({ event: 'started', module: { path: module.path }, classes: classes.size, messages: pending.length,
            descriptor_types: descriptors, imessage_methods: getMethods(classes.get('Google.Protobuf.IMessage')).map(m => m.name),
            arch: Process.arch });
        if (!pending.length) throw new Error('筛选后没有消息类型');
        if (settings.inspectOnly) return finish();
        for (const [name, klass] of classes) {
            const info = classInfo(klass);
            if (info.assembly !== 'Assembly-CSharp.dll') continue;
            if (prefixes.length && !prefixes.some(p => info.namespace === p || info.namespace.startsWith(p + '.'))) continue;
            if (api.il2cpp_class_is_enum(klass)) emitEnum(klass);
        }
        next();
    } catch (error) { finish(error.stack || error); }
}

function waitForModule() {
    const module = Process.findModuleByName('libil2cpp.so');
    if (module === null) return setTimeout(waitForModule, 500);
    setTimeout(() => start(module), settings.startupDelayMs || 0);
}

recv('start', message => { settings = message.payload || {}; waitForModule(); });
