"use strict";

const fs = require("node:fs");
const path = require("node:path");
const parser = require("@babel/parser");
const { Command } = require("commander");

const SCALARS = new Set([
    "double",
    "float",
    "int32",
    "uint32",
    "sint32",
    "fixed32",
    "sfixed32",
    "int64",
    "uint64",
    "sint64",
    "fixed64",
    "sfixed64",
    "bool",
    "string",
    "bytes",
]);
const MAP_KEYS = new Set([...SCALARS].filter((type) => !["double", "float", "bytes"].includes(type)));
const FUNCTIONS = new Set(["FunctionExpression", "FunctionDeclaration", "ArrowFunctionExpression"]);
const KEYWORDS = new Set([
    "syntax",
    "package",
    "import",
    "message",
    "enum",
    "service",
    "rpc",
    "returns",
    "stream",
    "option",
    "optional",
    "required",
    "repeated",
    "oneof",
    "map",
    "reserved",
    "extensions",
    "extend",
    "to",
    "max",
    "group",
    "public",
    "weak",
    ...SCALARS,
]);

function walk(node, visit, parents = []) {
    if (!node || typeof node.type !== "string" || visit(node, parents) === false) return;
    parents.push(node);
    for (const value of Object.values(node)) {
        if (Array.isArray(value)) {
            for (const child of value) if (child && typeof child.type === "string") walk(child, visit, parents);
        } else if (value && typeof value.type === "string") walk(value, visit, parents);
    }
    parents.pop();
}

function walkScope(node, visit) {
    walk(node, (child, parents) => (FUNCTIONS.has(child.type) ? false : visit(child, parents)));
}

function number(node) {
    if (node?.type === "NumericLiteral") return node.value;
    if (node?.type === "UnaryExpression" && node.operator === "-") {
        const value = number(node.argument);
        if (value !== undefined) return -value;
    }
}

function property(node) {
    if (node?.type !== "MemberExpression") return;
    if (!node.computed && node.property.type === "Identifier") return node.property.name;
    if (node.computed && node.property.type === "StringLiteral") return node.property.value;
}

function parts(node) {
    if (node?.type === "Identifier") return [node.name];
    if (node?.type === "AssignmentExpression" && node.operator === "=") return parts(node.left);
    if (node?.type !== "MemberExpression") return;
    const base = parts(node.object),
        name = property(node);
    if (base && name !== undefined) return [...base, name];
}

function tail(node) {
    return node?.type === "SequenceExpression" ? tail(node.expressions.at(-1)) : node;
}

function iife(node) {
    node = tail(node);
    return node?.type === "CallExpression" && FUNCTIONS.has(node.callee.type) ? node.callee : null;
}

function resolve(node, aliases) {
    const names = parts(node);
    if (!names || !aliases.has(names[0])) return;
    return [...aliases.get(names[0]), ...names.slice(1)].join(".");
}

function fieldAccess(node, base) {
    if (node?.type !== "MemberExpression") return;
    if (node.object.type === "Identifier" && node.object.name === base) return property(node);
    return fieldAccess(node.object, base);
}

function scalarCall(node, reader) {
    return node?.type === "CallExpression" &&
        node.callee.type === "MemberExpression" &&
        node.callee.object.type === "Identifier" &&
        node.callee.object.name === reader &&
        SCALARS.has(property(node.callee))
        ? property(node.callee)
        : undefined;
}

function decodedType(node, reader, aliases) {
    const scalar = scalarCall(node, reader);
    if (scalar) return scalar;
    if (node?.type === "CallExpression" && property(node.callee) === "decode") {
        return resolve(node.callee.object, aliases);
    }
}

function tagShift(node) {
    return (
        node?.type === "BinaryExpression" &&
        [">>>", ">>"].includes(node.operator) &&
        number(node.right) === 3 &&
        node.left.type === "Identifier"
    );
}

function tagCondition(node) {
    if (node?.type !== "BinaryExpression" || !["==", "==="].includes(node.operator)) return;
    if (tagShift(node.left)) return number(node.right);
    if (tagShift(node.right)) return number(node.left);
}

function enumValues(node) {
    const values = new Map();
    walkScope(node, (child) => {
        if (child.type !== "AssignmentExpression" || child.left.type !== "MemberExpression") return;
        const value = number(child.right),
            left = child.left;
        if (
            value !== undefined &&
            left.computed &&
            left.property.type === "AssignmentExpression" &&
            left.property.right.type === "StringLiteral"
        ) {
            values.set(left.property.right.value, value);
        } else if (value !== undefined && property(left) !== undefined) {
            values.set(property(left), value);
        } else if (child.right.type === "StringLiteral" && left.computed && number(left.property) !== undefined) {
            values.set(child.right.value, number(left.property));
        }
    });
    return [...values].map(([name, value]) => ({ name, value }));
}

function extractFile(source, relative) {
    const ast = parser.parse(source, { sourceType: "unambiguous", attachComment: false });
    const aliases = new Map(),
        records = new Map();
    walkScope(ast.program, (node) => {
        if (node.type !== "VariableDeclarator" || node.id.type !== "Identifier" || !node.init) return;
        let root = false;
        walkScope(node.init, (child) => {
            if (property(child) === "roots") root = true;
        });
        if (root) aliases.set(node.id.name, []);
    });
    if (!aliases.size) return [];

    function record(name, kind) {
        if (!records.has(name))
            records.set(name, {
                name,
                kind,
                source: relative,
                methods: {},
                defaults: new Map(),
                oneofs: new Map(),
                fields: [],
            });
        const value = records.get(name);
        if (value.kind !== kind) throw new Error(`Conflicting declaration: ${name}`);
        return value;
    }

    function scope(body, bindings, owner) {
        const local = new Map(bindings);
        // Bind the returned namespace object/constructor before visiting minified assignments.
        let returned = body.type === "SequenceExpression" && tail(body)?.type === "Identifier" ? tail(body).name : null;
        walkScope(body, (node) => {
            if (node.type === "ReturnStatement" && tail(node.argument)?.type === "Identifier") {
                returned = tail(node.argument).name;
            }
        });
        if (owner && returned) local.set(returned, owner.split("."));
        if (
            owner &&
            returned &&
            body.body?.some((node) => node.type === "FunctionDeclaration" && node.id?.name === returned)
        ) {
            record(owner, "message");
        }
        walkScope(body, (node) => {
            if (node.type === "CallExpression" && parts(node.callee)?.join(".") === "Object.defineProperty") {
                const [target, key, descriptor] = node.arguments;
                const names = parts(target);
                if (names?.at(-1) === "prototype" && key?.type === "StringLiteral") {
                    const name = resolve(target.object, local);
                    if (records.get(name)?.kind === "message") {
                        walkScope(descriptor, (child) => {
                            if (child.type !== "CallExpression" || property(child.callee) !== "oneOfGetter") return;
                            const arg = child.arguments[0];
                            const array = arg?.type === "AssignmentExpression" ? arg.right : arg;
                            if (
                                array?.type === "ArrayExpression" &&
                                array.elements.every((item) => item?.type === "StringLiteral")
                            ) {
                                records.get(name).oneofs.set(
                                    key.value,
                                    array.elements.map((item) => item.value),
                                );
                            }
                        });
                    }
                }
            }
            if (node.type !== "AssignmentExpression" || node.operator !== "=") return;
            const name = resolve(node.left, local);
            if (!name) return;
            const names = name.split("."),
                method = names.at(-1),
                parent = names.slice(0, -1).join(".");
            if (FUNCTIONS.has(node.right.type) && ["encode", "decode", "fromObject", "toObject"].includes(method)) {
                record(parent, "message").methods[method] = { fn: node.right, aliases: new Map(local) };
                return;
            }
            const prototypeIndex = names.indexOf("prototype");
            if (prototypeIndex >= 0 && prototypeIndex === names.length - 2) {
                const type = names.slice(0, prototypeIndex).join(".");
                if (records.get(type)?.kind === "message") records.get(type).defaults.set(method, node.right);
                return;
            }
            const fn = iife(node.right);
            const final = tail(node.right);
            if (!fn && node.right.type === "SequenceExpression" && final?.type === "Identifier") {
                let wrapper = false;
                walkScope(node.right, (child) => {
                    if (
                        child.type === "AssignmentExpression" &&
                        property(child.left) === "Enum" &&
                        parts(child.left.object)?.[0] === final.name
                    )
                        wrapper = true;
                });
                if (wrapper) {
                    record(name, "message");
                    scope(node.right, local, name);
                    return false;
                }
            }
            const values = enumValues(fn ? fn.body : node.right);
            if (values.length) {
                // Namespace and message IIFEs contain child enums; only leaf enum tables belong here.
                let children = false;
                if (fn && fn.body.body.some((child) => child.type === "FunctionDeclaration")) children = true;
                if (fn)
                    walkScope(fn.body, (child) => {
                        if (
                            child.type === "AssignmentExpression" &&
                            (iife(child.right) || FUNCTIONS.has(child.right.type))
                        )
                            children = true;
                    });
                if (!children && !FUNCTIONS.has(node.right.type)) {
                    record(name, "enum").values = values;
                    return;
                }
            }
            if (fn) scope(fn.body, local, name);
        });
    }
    scope(ast.program, aliases, null);
    for (const value of records.values()) {
        if (value.kind === "message") extractFields(value);
    }
    return [...records.values()].map((value) => {
        delete value.methods;
        delete value.defaults;
        value.oneofs = Object.fromEntries(value.oneofs);
        return value;
    });
}

function extractFields(record) {
    const decode = record.methods.decode;
    if (!decode) {
        if (record.defaults.size) throw new Error(`Missing decode method: ${record.name}`);
        return;
    }
    const reader = decode.fn.params[0]?.name;
    let result;
    walkScope(decode.fn.body, (node) => {
        if (
            node.type === "VariableDeclarator" &&
            node.id.type === "Identifier" &&
            node.init?.type === "NewExpression" &&
            resolve(node.init.callee, decode.aliases) === record.name
        )
            result = node.id.name;
    });
    if (!reader || !result) throw new Error(`Cannot locate decoder reader/message: ${record.name}`);
    const fields = new Map();

    function decodeField(nodes, tag) {
        const candidates = new Map();
        for (const body of nodes)
            walkScope(body, (node) => {
                if (node.type === "AssignmentExpression") {
                    const name = fieldAccess(node.left, result);
                    if (!name) return;
                    const type = decodedType(node.right, reader, decode.aliases);
                    if (type) candidates.set(name, { name, tag, type, repeated: false });
                    if (
                        node.left.computed &&
                        node.left.object.type === "MemberExpression" &&
                        node.left.object.object.type === "Identifier" &&
                        node.left.object.object.name === result &&
                        node.left.property.type === "Identifier" &&
                        node.right.type === "Identifier"
                    ) {
                        const keyVariable = node.left.property.name,
                            valueVariable = node.right.name;
                        let keyType, valueType;
                        for (const body of nodes)
                            walkScope(body, (child) => {
                                if (child.type !== "AssignmentExpression" || child.left.type !== "Identifier") return;
                                const decoded = decodedType(child.right, reader, decode.aliases);
                                if (child.left.name === keyVariable && decoded) keyType = decoded;
                                if (child.left.name === valueVariable && decoded) valueType = decoded;
                            });
                        if (!MAP_KEYS.has(keyType) || !valueType)
                            throw new Error(`Cannot recover map: ${record.name}.${name}`);
                        candidates.set(name, { name, tag, type: valueType, keyType, repeated: false });
                    }
                }
                if (node.type === "CallExpression" && property(node.callee) === "push") {
                    const name = fieldAccess(node.callee.object, result);
                    const type = decodedType(node.arguments[0], reader, decode.aliases);
                    if (name && type) candidates.set(name, { name, tag, type, repeated: true });
                }
            });
        if (!candidates.size) throw new Error(`Cannot recover field ${tag}: ${record.name}`);
        if (candidates.size !== 1) throw new Error(`Ambiguous decoder field ${tag}: ${record.name}`);
        const field = [...candidates.values()][0];
        if (!Number.isInteger(tag) || tag <= 0 || tag > 536870911 || (tag >= 19000 && tag <= 19999)) {
            throw new Error(`Invalid field number: ${record.name}.${field.name} = ${tag}`);
        }
        const existing = fields.get(tag);
        if (existing && JSON.stringify(existing) !== JSON.stringify(field))
            throw new Error(`Conflicting field ${tag}: ${record.name}`);
        fields.set(tag, field);
    }

    walkScope(decode.fn.body, (node) => {
        if (node.type === "SwitchStatement" && tagShift(node.discriminant)) {
            for (const item of node.cases) {
                const tag = number(item.test);
                if (tag !== undefined) decodeField(item.consequent, tag);
            }
            return false;
        }
        if (node.type === "IfStatement") {
            const tag = tagCondition(node.test);
            if (tag !== undefined) {
                decodeField([node.consequent], tag);
                if (node.alternate?.type === "IfStatement")
                    walkScope(node.alternate, (nested) => {
                        if (nested.type === "IfStatement" && tagCondition(nested.test) !== undefined) {
                            decodeField([nested.consequent], tagCondition(nested.test));
                        }
                    });
                return false;
            }
        }
    });
    record.fields = [...fields.values()].sort((a, b) => a.tag - b.tag);
    for (const name of record.defaults.keys()) {
        if (name !== "toJSON" && !record.fields.some((field) => field.name === name)) {
            throw new Error(`Prototype field missing from schema: ${record.name}.${name}`);
        }
    }

    const converter = record.methods.toObject;
    if (converter)
        walkScope(converter.fn.body, (node) => {
            if (node.type !== "MemberExpression" || !node.computed) return;
            const name = fieldAccess(node.property, converter.fn.params[0]?.name);
            const enumType = resolve(node.object, converter.aliases);
            const field = record.fields.find((field) => field.name === name);
            if (field && enumType) field.type = enumType;
        });

    const encode = record.methods.encode;
    if (encode) {
        const message = encode.fn.params[0]?.name,
            writer = encode.fn.params[1]?.name;
        walkScope(encode.fn.body, (node, parents) => {
            if (node.type !== "CallExpression" || !SCALARS.has(property(node.callee))) return;
            const field = record.fields.find((field) => field.name === fieldAccess(node.arguments[0], message));
            if (!field || !field.repeated || ["string", "bytes"].includes(field.type)) return;
            function encodingTag(root) {
                let found;
                walkScope(root, (child) => {
                    if (child.type !== "CallExpression" || property(child.callee) !== "uint32") return;
                    const tag = number(child.arguments[0]);
                    let base = child.callee.object;
                    while (base?.type === "CallExpression" && base.callee.type === "MemberExpression")
                        base = base.callee.object;
                    if (
                        base?.type === "Identifier" &&
                        base.name === writer &&
                        tag !== undefined &&
                        Math.floor(tag / 8) === field.tag
                    ) {
                        found = tag;
                    }
                });
                return found;
            }
            let tag = encodingTag(node);
            for (let i = parents.length - 1; tag === undefined && i >= 0; i--) {
                if (["IfStatement", "ForStatement", "BlockStatement"].includes(parents[i].type))
                    tag = encodingTag(parents[i]);
            }
            if (tag !== undefined) field.packed = (tag & 7) === 2;
        });
    }
    for (const field of record.fields) {
        if (field.repeated && !["string", "bytes"].includes(field.type) && !SCALARS.has(field.type)) continue;
        if (field.repeated && !["string", "bytes"].includes(field.type) && field.packed === undefined) {
            throw new Error(`Cannot recover packed encoding: ${record.name}.${field.name}`);
        }
    }
}

function identifier(name) {
    let value = name.replace(/[^A-Za-z0-9_]/g, "_");
    if (!/^[A-Za-z_]/.test(value)) value = `_${value}`;
    return KEYWORDS.has(value) ? `${value}_` : value;
}

function protoName(name) {
    return name.split(".").map(identifier).join(".");
}

function buildUnits(files) {
    const types = new Map(),
        units = [];
    for (const file of files) {
        const packages = new Map();
        for (const record of file.records) {
            if (types.has(record.name))
                throw new Error(`Duplicate type ${record.name}: ${types.get(record.name).source}, ${record.source}`);
            types.set(record.name, record);
        }
        for (const record of file.records) {
            let parent = record.name.split(".").slice(0, -1).join(".");
            while (types.get(parent)?.kind === "message") parent = parent.split(".").slice(0, -1).join(".");
            record.package = parent;
            if (!packages.has(parent)) packages.set(parent, []);
            packages.get(parent).push(record);
        }
        for (const [pkg, records] of packages) {
            const suffix = packages.size > 1 ? `.${pkg || "global"}` : "";
            const output = file.relative.replace(/\.js$/i, `${suffix}.proto`);
            const unit = { package: pkg, output, records, imports: new Set(), source: file.relative };
            for (const record of records) record.unit = unit;
            units.push(unit);
        }
    }
    for (const record of types.values()) {
        for (const field of record.fields) {
            if (SCALARS.has(field.type)) continue;
            const target = types.get(field.type);
            if (!target)
                throw new Error(
                    `Unresolved type ${field.type} in ${record.name}.${field.name}; include its JS directory with --input`,
                );
            if (target.unit !== record.unit) record.unit.imports.add(target.unit.output);
            if (target.kind === "enum" && field.repeated && field.packed === undefined) {
                throw new Error(`Cannot recover enum packing: ${record.name}.${field.name}`);
            }
        }
    }
    return { types, units };
}

function renderUnit(unit, types) {
    const lines = [`// JsProtoDumper: ${unit.source}`, "// Written by Cyt", 'syntax = "proto3";', ""];
    if (unit.package) lines.push(`package ${protoName(unit.package)};`, "");
    for (const imported of [...unit.imports].sort()) lines.push(`import ${JSON.stringify(imported)};`);
    if (unit.imports.size) lines.push("");
    const children = new Map(),
        occupied = new Map();
    for (const record of unit.records) {
        const parent = record.name.split(".").slice(0, -1).join(".");
        if (!children.has(parent)) children.set(parent, []);
        children.get(parent).push(record);
        if (!occupied.has(parent)) occupied.set(parent, new Set());
        occupied.get(parent).add(identifier(record.name.split(".").at(-1)));
    }

    function render(record, indent) {
        const pad = " ".repeat(indent),
            name = identifier(record.name.split(".").at(-1));
        lines.push(`${pad}${record.kind} ${name} {`);
        if (record.kind === "enum") {
            const values = [...record.values];
            if (!values.some((value) => value.value === 0))
                values.unshift({ name: `${name}_UNSPECIFIED`, value: 0, synthetic: true });
            const zero = values.findIndex((value) => value.value === 0);
            values.unshift(...values.splice(zero, 1));
            if (new Set(values.map((value) => value.value)).size !== values.length)
                lines.push(`${pad}    option allow_alias = true;`);
            const parent = record.name.split(".").slice(0, -1).join(".");
            const used = occupied.get(parent) || new Set();
            occupied.set(parent, used);
            for (const value of values) {
                let member = identifier(value.name);
                if (used.has(member)) member = `${name}_${member}`;
                const base = member;
                for (let suffix = 2; used.has(member); suffix++) member = `${base}_${suffix}`;
                used.add(member);
                const notes = [];
                if (member !== value.name) notes.push(`JS name: ${value.name}`);
                if (value.synthetic) notes.push("Synthetic zero value for proto3");
                lines.push(`${pad}    ${member} = ${value.value};${notes.length ? ` // ${notes.join("; ")}` : ""}`);
            }
        } else {
            for (const nested of children.get(record.name) || []) render(nested, indent + 4);
            const oneofFields = new Set(Object.values(record.oneofs).flat());
            function renderField(field, fieldIndent, inOneof = false) {
                const scalar = SCALARS.has(field.type),
                    target = types.get(field.type);
                const type = scalar ? field.type : `.${protoName(field.type)}`;
                let declaration = field.keyType
                    ? `map<${field.keyType}, ${type}>`
                    : `${field.repeated ? "repeated " : ""}${type}`;
                const options = [];
                if (
                    field.repeated &&
                    !["string", "bytes"].includes(field.type) &&
                    (scalar || target?.kind === "enum")
                ) {
                    options.push(`packed = ${field.packed}`);
                }
                if (inOneof && (field.repeated || field.keyType))
                    throw new Error(`Invalid oneof field: ${record.name}.${field.name}`);
                declaration += ` ${identifier(field.name)} = ${field.tag}${options.length ? ` [${options.join(", ")}]` : ""};`;
                lines.push(
                    `${" ".repeat(fieldIndent)}${declaration}${identifier(field.name) !== field.name ? ` // JS name: ${field.name}` : ""}`,
                );
            }
            for (const field of record.fields) if (!oneofFields.has(field.name)) renderField(field, indent + 4);
            for (const [name, names] of Object.entries(record.oneofs)) {
                lines.push(`${pad}    oneof ${identifier(name)} {`);
                for (const fieldName of names) {
                    const field = record.fields.find((field) => field.name === fieldName);
                    if (!field) throw new Error(`Missing oneof field: ${record.name}.${fieldName}`);
                    renderField(field, indent + 8, true);
                }
                lines.push(`${pad}    }`);
            }
        }
        lines.push(`${pad}}`);
    }
    for (const record of children.get(unit.package) || []) {
        render(record, 0);
        lines.push("");
    }
    return lines.join("\n");
}

function collectFiles(input, output) {
    const files = [];
    function visit(directory) {
        for (const entry of fs
            .readdirSync(directory, { withFileTypes: true })
            .sort((a, b) => a.name.localeCompare(b.name, "en"))) {
            const full = path.join(directory, entry.name);
            if (entry.isDirectory() && !["node_modules", ".git"].includes(entry.name) && full !== output) visit(full);
            else if (entry.isFile() && entry.name.toLowerCase().endsWith(".js")) files.push(full);
        }
    }
    const stat = fs.statSync(input);
    if (stat.isDirectory()) visit(input);
    else if (stat.isFile() && input.toLowerCase().endsWith(".js")) files.push(input);
    else throw new Error(`Input must be a JS file or directory: ${input}`);
    return files;
}

function argumentsFrom(argv) {
    const program = new Command()
        .name("index.js")
        .description("Recover .proto files from protobufjs static JavaScript")
        .requiredOption("--input <path>", "Input JS file or directory; repeatable", (value, previous = []) => [
            ...previous,
            path.resolve(value),
        ])
        .requiredOption("--output <path>", "Output directory for .proto files", (value) => path.resolve(value))
        .showHelpAfterError()
        .parse(argv, { from: "user" });
    const { input, output } = program.opts();
    return { inputs: [...new Set(input)], output };
}

function main(argv) {
    const options = argumentsFrom(argv);
    const files = [],
        errors = [],
        skipped = [],
        seen = new Set();
    const prefixes = options.inputs.map((input) => path.basename(input, ".js"));
    if (options.inputs.length > 1 && new Set(prefixes).size !== prefixes.length)
        throw new Error("Input directory names must be unique");
    for (let i = 0; i < options.inputs.length; i++) {
        const input = options.inputs[i],
            base = fs.statSync(input).isDirectory() ? input : path.dirname(input);
        for (const filename of collectFiles(input, options.output)) {
            if (seen.has(filename)) continue;
            seen.add(filename);
            let relative = path.relative(base, filename);
            if (options.inputs.length > 1) relative = path.join(prefixes[i], relative);
            relative = relative.split(path.sep).join("/");
            try {
                const records = extractFile(fs.readFileSync(filename, "utf8"), relative);
                if (records.length) files.push({ relative, records });
                else skipped.push(relative);
            } catch (error) {
                errors.push({ file: relative, error: error.message });
                console.error(`[ERROR] ${relative}: ${error.message}`);
            }
        }
    }
    fs.mkdirSync(options.output, { recursive: true });
    const report = { files: seen.size, skipped, errors, outputs: [], messages: 0, enums: 0, fields: 0 };
    try {
        const { types, units } = buildUnits(files);
        // Render everything before writing so unresolved types do not leave half-written schemas.
        const rendered = units.map((unit) => ({ unit, content: renderUnit(unit, types) }));
        for (const { unit, content } of rendered) {
            const filename = path.join(options.output, unit.output);
            fs.mkdirSync(path.dirname(filename), { recursive: true });
            fs.writeFileSync(filename, content, "utf8");
            report.outputs.push(unit.output);
        }
        for (const record of types.values()) {
            report[record.kind === "enum" ? "enums" : "messages"]++;
            report.fields += record.fields.length;
        }
    } catch (error) {
        errors.push({ file: null, error: error.message });
        console.error(`[ERROR] ${error.message}`);
    }
    if (!report.outputs.length && !errors.length)
        errors.push({ file: null, error: "No protobufjs declarations found" });
    fs.writeFileSync(path.join(options.output, "report.json"), `${JSON.stringify(report, null, 4)}\n`, "utf8");
    console.log(
        `JS: ${report.files}; proto: ${report.outputs.length}; messages: ${report.messages}; enums: ${report.enums}; fields: ${report.fields}; skipped: ${skipped.length}; errors: ${errors.length}`,
    );
    if (errors.length) process.exitCode = 1;
}

if (require.main === module) {
    try {
        main(process.argv.slice(2));
    } catch (error) {
        console.error(error.message);
        process.exitCode = 1;
    }
}
