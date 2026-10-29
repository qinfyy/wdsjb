import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";

// Build options

// true:
//   忽略 OBFUSCATE_FILES，混淆 bundle 中全部 .js
//
// false:
//   只混淆 OBFUSCATE_FILES 中指定的文件
const OBFUSCATE_ALL = false;

// 要混淆的 bundle 文件路径。
// 只有 OBFUSCATE_ALL = false 时生效。
const OBFUSCATE_FILES = [
    "/FridaScript.js",
];

// 是否打印每个文件的处理结果
const VERBOSE = true;

// Paths

const root = process.cwd();

const inputBundle = resolve(root, "dist/FridaScript.js");

const distDir = resolve(root, "dist");

const workDir = resolve(root, ".build");

const outputBundle = resolve(root, "dist/FridaScript.js");

const obfuscationConfig = resolve(root, "obfuscator.json");

// Prepare directories

// 先清空 dist，确保 npm run build 之后 dist 干净
rmSync(distDir, {recursive: true, force: true});

mkdirSync(distDir, {recursive: true});

// 临时工作目录
rmSync(workDir, {recursive: true, force: true});

mkdirSync(workDir, {recursive: true});

// Command execution
function quoteCmdArg(arg) {
    const value = String(arg);

    if (/^[A-Za-z0-9_./\\:=+-]+$/.test(value)) {
        return value;
    }

    return `"${value.replace(/%/g, "%%").replace(/"/g, '\\"')}"`;
}

function run(command, args) {
    console.log(`\n> ${command} ${args.join(" ")}`);

    if (process.platform === "win32") {
        const executable = `${command}.cmd`;
        const commandLine = [executable, ...args.map(quoteCmdArg)].join(" ");
        execFileSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", commandLine], {cwd: root, stdio: "inherit"});
        return;
    }

    execFileSync(command, args, {cwd: root, stdio: "inherit"});
}

// Frida bundle constants

const FRIDA_MARKER = Buffer.from("📦\n", "utf8");

const FRIDA_SEPARATOR = Buffer.from("\n✄\n", "utf8");

// Parse Frida bundle

function parseBundle(buffer) {
    if (buffer.subarray(0, FRIDA_MARKER.length).compare(FRIDA_MARKER) !== 0) {
        throw new Error("Invalid Frida bundle: missing 📦 marker");
    }

    const headerSeparatorOffset = buffer.indexOf(FRIDA_SEPARATOR, FRIDA_MARKER.length);

    if (headerSeparatorOffset === -1) {
        throw new Error("Invalid Frida bundle: missing header separator ✄");
    }

    const header = buffer.subarray(FRIDA_MARKER.length, headerSeparatorOffset).toString("utf8");
    const lines = header.split("\n");
    const records = [];
    let current = null;

    for (const line of lines) {
        if (!line) {
            continue;
        }

        const fileMatch = /^(\d+) (.+)$/.exec(line);

        if (fileMatch) {
            if (current !== null) {
                records.push(current);
            }

            current = {
                size: Number(fileMatch[1]),
                path: fileMatch[2],
                metadata: [],
                content: null,
            };

            continue;
        }

        if (line.startsWith("↻ ")) {
            if (current === null) {
                throw new Error(`Alias appears before a file record: ${line}`);
            }

            current.metadata.push(line);
            continue;
        }

        throw new Error(`Unknown Frida bundle header line: ${line}`);
    }

    if (current !== null) {
        records.push(current);
    }

    if (records.length === 0) {
        throw new Error(
            "Invalid Frida bundle: no file records"
        );
    }

    // Parse body by recorded byte sizes
    let offset = headerSeparatorOffset + FRIDA_SEPARATOR.length;

    for (let i = 0; i < records.length; i++) {
        const record = records[i];

        const end = offset + record.size;

        if (end > buffer.length) {
            throw new Error(`Unexpected end of bundle while reading ${record.path}`);
        }

        const contentBuffer = buffer.subarray(offset, end);

        record.content = contentBuffer.toString("utf8");
        offset = end;
        if (i !== records.length - 1) {
            const separatorEnd = offset + FRIDA_SEPARATOR.length;

            if (separatorEnd > buffer.length) {
                throw new Error(`Missing separator after ${record.path}`);
            }

            const separator = buffer.subarray(offset, separatorEnd);

            if (separator.compare(FRIDA_SEPARATOR) !== 0) {
                throw new Error(`Invalid separator after ${record.path}`);
            }

            offset = separatorEnd;
        }
    }

    if (offset !== buffer.length) {
        throw new Error(`Unexpected trailing data: ${buffer.length - offset} bytes`);
    }

    return records;
}

// Build Frida bundle

function buildBundle(files) {
    const headerLines = [];
    const contentBuffers = [];

    for (const file of files) {
        const contentBuffer =
            Buffer.from(file.content, "utf8");

        headerLines.push(`${contentBuffer.length} ${file.path}`);

        for (const metadata of file.metadata) {
            headerLines.push(metadata);
        }

        contentBuffers.push(
            contentBuffer
        );
    }

    const headerBuffer = Buffer.from(headerLines.join("\n"), "utf8");

    const parts = [FRIDA_MARKER, headerBuffer, FRIDA_SEPARATOR];

    for (let i = 0; i < contentBuffers.length; i++) {
        parts.push(contentBuffers[i]);

        if (i !== contentBuffers.length - 1) {
            parts.push(FRIDA_SEPARATOR);
        }
    }

    return Buffer.concat(parts);
}

// Decide whether file should be obfuscated

function shouldObfuscate(file) {
    if (!file.path.toLowerCase().endsWith(".js")) {
        return false;
    }

    if (OBFUSCATE_ALL) {
        return true;
    }

    return OBFUSCATE_FILES.includes(
        file.path
    );
}

// Obfuscate source

function obfuscateSource(source,filePath) {
    const safeName = filePath.replace(/^\/+/, "").replace(/[^A-Za-z0-9._-]/g, "_");
    const tempInput = resolve(workDir, `${safeName}.input.js`);
    const tempOutput = resolve(workDir, `${safeName}.output.js`);

    writeFileSync(tempInput, source,"utf8");

    try {
        run("javascript-obfuscator", [tempInput, "--output", tempOutput, "--config", obfuscationConfig]);
        return readFileSync(tempOutput,"utf8");
    } finally {
        rmSync(tempInput, {force: true});
        rmSync(tempOutput, {force: true});
    }
}

// Build

console.log("Frida Agent production build");

console.log(`Obfuscation mode: ${OBFUSCATE_ALL ? "ALL JS" : "SELECTED FILES"}`);

if (!OBFUSCATE_ALL) {
    console.log(`Selected files: ${OBFUSCATE_FILES.join(", ") || "(none)"}`);
}

try {
    console.log("\nRunning npm run build");

    run("npm", ["run", "build"]);

    const bundleBuffer = readFileSync(inputBundle);

    const files = parseBundle(bundleBuffer);

    console.log(`\nBundle contains ${files.length} files:\n`);

    let obfuscatedCount = 0;

    for (const file of files) {
        const should = shouldObfuscate(file);

        if (VERBOSE) {
            console.log(`[${should ? "OBF" : "KEEP"}] ${file.path}`);
        }

        if (!should) {
            continue;
        }

        const originalSize = Buffer.byteLength(file.content, "utf8");

        file.content = obfuscateSource(file.content, file.path);

        const obfuscatedSize =Buffer.byteLength(file.content, "utf8");

        console.log(`    ${originalSize.toLocaleString()} → ${obfuscatedSize.toLocaleString()} bytes`);

        obfuscatedCount++;
    }

    const finalBundle = buildBundle(files);

    writeFileSync(outputBundle, finalBundle);

    console.log(`\n✓ Obfuscated files: ${obfuscatedCount}`);

    console.log(`✓ Output: ${outputBundle}`);

    console.log(`✓ Bundle size: ${finalBundle.length.toLocaleString()} bytes`);

    console.log("✓ Source preserved");

    console.log("✓ dist contains only FridaScript.js");
} finally {
    rmSync(workDir,{recursive: true, force: true});
}
