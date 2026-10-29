export const encodingOptions = [
    { value: 'utf-8', label: 'UTF-8' },
    { value: 'us-ascii', label: 'ASCII' },
    { value: 'utf-16le', label: 'UTF-16 LE' },
    { value: 'utf-16be', label: 'UTF-16 BE' },
];

export const MAX_SEARCH_MATCHES = 10000;

function normalizeBase64(raw) {
    const normalized = raw.trim().replace(/-/g, '+').replace(/_/g, '/');

    return normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
}

export function bytesToBinaryString(bytes) {
    let value = '';
    const chunkSize = 8192;

    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        value += String.fromCharCode(
            ...bytes.subarray(offset, offset + chunkSize),
        );
    }

    return value;
}

export function decodeBase64Bytes(raw) {
    if (!raw) {
        return new Uint8Array();
    }

    try {
        const binary = window.atob(normalizeBase64(raw));
        const bytes = new Uint8Array(binary.length);

        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }

        return bytes;
    } catch (error) {
        return new Uint8Array();
    }
}

export function parseHexSearch(value) {
    const trimmed = value.trim();

    if (!trimmed) {
        return { bytes: new Uint8Array(), valid: true };
    }

    const tokens = trimmed.split(/\s+/);
    const bytes = new Uint8Array(tokens.length);

    for (let index = 0; index < tokens.length; index += 1) {
        if (!/^[0-9a-fA-F]{1,2}$/.test(tokens[index])) {
            return { bytes: new Uint8Array(), valid: false };
        }

        bytes[index] = Number.parseInt(tokens[index], 16);
    }

    return { bytes, valid: true };
}

export function encodeTextSearch(value, encoding) {
    if (!value) {
        return { bytes: new Uint8Array(), valid: true };
    }

    if (encoding === 'utf-8') {
        return { bytes: new TextEncoder().encode(value), valid: true };
    }

    if (encoding === 'us-ascii') {
        const characters = Array.from(value);
        const bytes = new Uint8Array(characters.length);

        for (let index = 0; index < characters.length; index += 1) {
            const codePoint = characters[index].codePointAt(0);

            if (codePoint > 0x7f) {
                return { bytes: new Uint8Array(), valid: false };
            }

            bytes[index] = codePoint;
        }

        return { bytes, valid: true };
    }

    const bytes = new Uint8Array(value.length * 2);

    for (let index = 0; index < value.length; index += 1) {
        const codeUnit = value.charCodeAt(index);
        const offset = index * 2;

        if (encoding === 'utf-16be') {
            bytes[offset] = codeUnit >> 8;
            bytes[offset + 1] = codeUnit & 0xff;
        } else {
            bytes[offset] = codeUnit & 0xff;
            bytes[offset + 1] = codeUnit >> 8;
        }
    }

    return { bytes, valid: true };
}

export function findByteMatches(bytes, query, maxMatches = MAX_SEARCH_MATCHES) {
    const matches = [];

    if (!query.length || query.length > bytes.length) {
        return { matches, truncated: false };
    }

    for (let start = 0; start <= bytes.length - query.length; start += 1) {
        let matched = true;

        for (let offset = 0; offset < query.length; offset += 1) {
            if (bytes[start + offset] !== query[offset]) {
                matched = false;
                break;
            }
        }

        if (!matched) {
            continue;
        }

        matches.push(start);

        if (matches.length === maxMatches) {
            return { matches, truncated: true };
        }
    }

    return { matches, truncated: false };
}

export function base64ContainsBytes(raw, query) {
    if (!raw || !query.length) {
        return false;
    }

    try {
        const queryBinary =
            typeof query === 'string' ? query : bytesToBinaryString(query);
        return window.atob(normalizeBase64(raw)).includes(queryBinary);
    } catch (error) {
        return false;
    }
}
