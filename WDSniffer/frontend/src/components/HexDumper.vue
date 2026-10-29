<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
    decodeBase64Bytes,
    encodingOptions,
    encodeTextSearch,
    findByteMatches,
    parseHexSearch
} from '../packetSearch.js'

const props = defineProps({
    raw: {
        type: String,
        default: ''
    },
    encoding: {
        type: String,
        default: 'utf-8'
    }
})

const emit = defineEmits(['update:encoding'])

const searchMode = ref('hex')
const searchQuery = ref('')
const activeMatchIndex = ref(0)
const searchOpen = ref(false)
const scrollElement = ref(null)
const activeRowElement = ref(null)
const searchInput = ref(null)

const byteData = computed(() => decodeBase64Bytes(props.raw))
const decoder = computed(() => new TextDecoder(props.encoding, { fatal: false }))
const searchHasQuery = computed(() => {
    return searchMode.value === 'hex'
        ? searchQuery.value.trim().length > 0
        : searchQuery.value.length > 0
})

const searchDefinition = computed(() => {
    if (searchMode.value === 'hex') {
        return parseHexSearch(searchQuery.value)
    }

    return encodeTextSearch(searchQuery.value, props.encoding)
})

const searchResult = computed(() => {
    if (!searchOpen.value || !searchHasQuery.value || !searchDefinition.value.valid) {
        return { matches: [], truncated: false }
    }

    return findByteMatches(byteData.value, searchDefinition.value.bytes)
})

const searchMatches = computed(() => searchResult.value.matches)
const searchInvalid = computed(() => searchHasQuery.value && !searchDefinition.value.valid)
const activeMatch = computed(() => searchMatches.value[activeMatchIndex.value] ?? null)
const activeRowIndex = computed(() => {
    return activeMatch.value === null ? -1 : Math.floor(activeMatch.value / 16)
})

const rowMatchMasks = computed(() => {
    const masks = new Map()
    const queryLength = searchDefinition.value.bytes.length

    if (!queryLength || !searchMatches.value.length) {
        return masks
    }

    for (const start of searchMatches.value) {
        const end = start + queryLength
        let position = start

        while (position < end) {
            const rowIndex = Math.floor(position / 16)
            const rowStart = rowIndex * 16
            const rowEnd = Math.min(rowStart + 16, end)
            const state = masks.get(rowIndex) ?? { matchMask: 0, activeMask: 0 }

            for (let byteIndex = position; byteIndex < rowEnd; byteIndex += 1) {
                const bit = 1 << (byteIndex - rowStart)
                state.matchMask |= bit

                if (start === activeMatch.value) {
                    state.activeMask |= bit
                }
            }

            masks.set(rowIndex, state)
            position = rowEnd
        }
    }

    return masks
})

const buildTextCells = (chunk, state) => {
    const cells = []
    let byteOffset = 0

    while (byteOffset < chunk.length) {
        let byteLength = 1
        let value = ''

        for (let end = byteOffset + 1; end <= chunk.length; end += 1) {
            try {
                const decoded = new TextDecoder(props.encoding, { fatal: true }).decode(chunk.subarray(byteOffset, end))

                if (decoded.length) {
                    value = decoded
                    byteLength = end - byteOffset
                    break
                }
            } catch (error) {
                continue
            }
        }

        if (!value) {
            value = new TextDecoder(props.encoding, { fatal: false }).decode(chunk.subarray(byteOffset, byteOffset + 1))
        }

        let characterMask = 0

        for (let index = 0; index < byteLength; index += 1) {
            characterMask |= 1 << (byteOffset + index)
        }

        cells.push({
            value: value.replace(/[\u0000-\u001F\u007F-\u009F]/g, '.'),
            matched: Boolean(state.matchMask & characterMask),
            active: Boolean(state.activeMask & characterMask)
        })

        byteOffset += byteLength
    }

    return cells
}

const rows = computed(() => {
    const values = []
    const bytes = byteData.value

    for (let offset = 0; offset < bytes.length; offset += 16) {
        const rowIndex = offset / 16
        const chunk = bytes.subarray(offset, offset + 16)
        const state = rowMatchMasks.value.get(rowIndex)
        const decoded = decoder.value.decode(chunk)
        const row = {
            index: rowIndex,
            offset: offset.toString(16).padStart(8, '0').toUpperCase(),
            hex: Array.from(chunk, (byte) => byte.toString(16).padStart(2, '0').toUpperCase()).join(' '),
            text: decoded.replace(/[\u0000-\u001F\u007F-\u009F]/g, '.'),
            hexCells: null,
            textCells: null
        }

        if (state) {
            row.hexCells = Array.from(chunk, (byte, index) => ({
                value: byte.toString(16).padStart(2, '0').toUpperCase(),
                matched: Boolean(state.matchMask & (1 << index)),
                active: Boolean(state.activeMask & (1 << index))
            }))
            row.textCells = buildTextCells(chunk, state)
        }

        values.push(row)
    }

    return values
})

const setEncoding = (value) => {
    emit('update:encoding', value)
}

const moveMatch = (direction) => {
    if (!searchMatches.value.length) {
        return
    }

    const count = searchMatches.value.length
    activeMatchIndex.value = (activeMatchIndex.value + direction + count) % count
}

const handleSearchKeydown = (event) => {
    if (event.key === 'Escape') {
        closeSearch()
        return
    }

    if (event.key !== 'Enter') {
        return
    }

    event.preventDefault()
    moveMatch(event.shiftKey ? -1 : 1)
}

const setActiveRowElement = (element) => {
    activeRowElement.value = element
}

const toggleSearch = async () => {
    if (searchOpen.value) {
        closeSearch()
        return
    }

    searchOpen.value = !searchOpen.value

    if (searchOpen.value) {
        await nextTick()
        searchInput.value?.focus()
    }
}

const closeSearch = () => {
    searchOpen.value = false
    activeMatchIndex.value = 0
}

const scrollToActiveMatch = async () => {
    await nextTick()

    if (!scrollElement.value || !activeRowElement.value) {
        return
    }

    const row = activeRowElement.value
    const container = scrollElement.value
    container.scrollTop = Math.max(0, row.offsetTop - (container.clientHeight - row.offsetHeight) / 2)
}

watch([searchQuery, searchMode, () => props.raw, () => props.encoding], () => {
    activeMatchIndex.value = 0
})

watch(activeRowIndex, () => {
    scrollToActiveMatch()
})
</script>

<template>
    <section class="hex-dumper">
        <header class="hex-toolbar">
            <span class="byte-count">{{ byteData.length }} bytes</span>

            <div class="toolbar-actions">
                <label class="encoding-label">
                    <span>Encoding</span>
                    <select :value="props.encoding" aria-label="Text encoding" @change="setEncoding($event.target.value)">
                        <option v-for="option in encodingOptions" :key="option.value" :value="option.value">
                            {{ option.label }}
                        </option>
                    </select>
                </label>
                <button
                    type="button"
                    class="search-toggle"
                    :class="{ active: searchOpen }"
                    :aria-expanded="searchOpen"
                    aria-label="Search raw bytes"
                    title="Search raw bytes"
                    @click="toggleSearch"
                >
                    <span class="search-icon" aria-hidden="true"></span>
                </button>
            </div>
        </header>

        <div v-if="searchOpen" class="hex-search-panel" role="search">
            <select v-model="searchMode" class="search-mode-select" aria-label="Search mode">
                <option value="text">Text</option>
                <option value="hex">Hex</option>
            </select>
            <div class="search-controls">
                <input
                    ref="searchInput"
                    v-model="searchQuery"
                    class="search-input"
                    :class="{ invalid: searchInvalid }"
                    type="search"
                    :placeholder="searchMode === 'hex' ? '01 02 0A' : 'Search text'"
                    :aria-invalid="searchInvalid"
                    aria-label="Search raw bytes"
                    @keydown="handleSearchKeydown"
                />
                <span v-if="searchInvalid" class="search-status invalid-status">Invalid hex</span>
                <span v-else-if="searchMatches.length" class="search-status" aria-live="polite">
                    {{ activeMatchIndex + 1 }} / {{ searchMatches.length }}{{ searchResult.truncated ? '+' : '' }}
                </span>
                <span v-else-if="searchHasQuery" class="search-status" aria-live="polite">0 / 0</span>
                <button type="button" class="search-button" aria-label="Previous match" title="Previous match" @click="moveMatch(-1)">
                    &#9650;
                </button>
                <button type="button" class="search-button" aria-label="Next match" title="Next match" @click="moveMatch(1)">
                    &#9660;
                </button>
            </div>
            <button type="button" class="close-search" aria-label="Close search" title="Close search" @click="closeSearch">&times;</button>
        </div>

        <div ref="scrollElement" class="hex-scroll">
            <div class="hex-header" aria-hidden="true">
                <span class="offset-column">Offset</span>
                <span class="hex-column">00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F</span>
                <span class="text-column">Text</span>
            </div>

            <div v-if="rows.length" class="hex-rows">
                <div
                    v-for="row in rows"
                    :key="row.offset"
                    :ref="row.index === activeRowIndex ? setActiveRowElement : null"
                    class="hex-row"
                    :class="{ 'search-active-row': row.index === activeRowIndex }"
                >
                    <span class="offset-column">{{ row.offset }}</span>
                    <span class="hex-column">
                        <template v-if="row.hexCells">
                            <template v-for="(cell, index) in row.hexCells" :key="index">
                                <span class="hex-byte" :class="{ 'search-match': cell.matched, 'search-active': cell.active }">{{ cell.value }}</span><span v-if="index < row.hexCells.length - 1" class="hex-gap"> </span>
                            </template>
                        </template>
                        <template v-else>{{ row.hex }}</template>
                    </span>
                    <span class="text-column">
                        <template v-if="row.textCells">
                            <span v-for="(cell, index) in row.textCells" :key="index" class="text-cell" :class="{ 'search-match': cell.matched, 'search-active': cell.active }">{{ cell.value }}</span>
                        </template>
                        <template v-else>{{ row.text }}</template>
                    </span>
                </div>
            </div>

            <p v-else class="empty-raw">No raw bytes available</p>
        </div>
    </section>
</template>

<style scoped>
.hex-dumper {
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    color: var(--text-primary);
    background: var(--bg-primary);
    font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
}

.hex-toolbar {
    min-height: 42px;
    padding: 0 12px;
    border-bottom: 1px solid var(--border-light);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-family: inherit;
    font-size: 0.75rem;
}

.byte-count,
.search-status {
    color: var(--text-tertiary);
    white-space: nowrap;
}

.toolbar-actions {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.search-toggle,
.close-search {
    position: relative;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    padding: 0;
    color: var(--text-secondary);
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    cursor: pointer;
}

.search-toggle:hover,
.search-toggle.active,
.close-search:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border-color: var(--border-light);
}

.search-icon {
    position: absolute;
    top: 6px;
    left: 6px;
    width: 9px;
    height: 9px;
    border: 2px solid currentColor;
    border-radius: 50%;
}

.search-icon::after {
    position: absolute;
    width: 7px;
    height: 2px;
    right: -6px;
    bottom: -4px;
    content: '';
    background: currentColor;
    transform: rotate(45deg);
    transform-origin: left center;
}

.hex-search-panel {
    min-height: 38px;
    padding: 5px 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--bg-primary);
    border-bottom: 1px solid var(--border-light);
    font-family: inherit;
    font-size: 0.75rem;
}

.search-controls {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 4px;
    flex: 1;
}

.search-input,
.search-button,
.encoding-label select {
    height: 26px;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    font: inherit;
    font-size: 0.72rem;
    outline: none;
}

.encoding-label select {
    padding: 0 6px;
}

.search-input:focus,
.search-button:focus,
.encoding-label select:focus {
    border-color: var(--accent-color, #4f8cff);
}

.search-input {
    min-width: 100px;
    flex: 1 1 160px;
    padding: 0 7px;
    border-radius: 3px;
}

.search-input.invalid {
    border-color: #d85b5b;
}

.search-status {
    padding: 0 4px;
}

.invalid-status {
    color: #e07878;
}

.search-button {
    width: 26px;
    padding: 0;
    border-radius: 3px;
    cursor: pointer;
}

.search-button:hover {
    background: var(--bg-tertiary);
}

.search-mode-select {
    box-sizing: border-box;
    width: 48px;
    height: 26px;
    flex: 0 0 48px;
    padding: 0 2px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-light);
    border-radius: 3px;
    color: var(--text-primary);
    font: inherit;
    font-size: 0.62rem;
    outline: none;
}

.encoding-label {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    color: var(--text-secondary);
    white-space: nowrap;
}

.encoding-label select {
    min-width: 104px;
    border-radius: 3px;
}

.close-search {
    color: var(--text-tertiary);
    font-size: 1.15rem;
    line-height: 1;
}

.hex-scroll {
    min-height: 0;
    flex: 1;
    overflow: auto;
    padding: 8px 0;
}

.hex-header,
.hex-row {
    display: grid;
    grid-template-columns: 84px 48ch minmax(120px, 1fr);
    column-gap: 16px;
    min-width: 690px;
    padding: 0 12px;
    line-height: 1.7;
    font-size: 0.76rem;
}

.hex-header {
    position: sticky;
    top: -8px;
    z-index: 1;
    padding-top: 2px;
    padding-bottom: 3px;
    color: var(--text-tertiary);
    background: var(--bg-primary);
    border-bottom: 1px solid var(--border-light);
    font-size: 0.69rem;
}

.hex-row:hover {
    background: var(--hover-bg);
}

.search-active-row {
    background: rgba(79, 140, 255, 0.1);
}

.offset-column {
    color: var(--text-tertiary);
}

.hex-column {
    white-space: pre;
    color: var(--text-primary);
}

.hex-byte {
    display: inline-block;
    width: 2ch;
    border-radius: 2px;
}

.hex-gap {
    display: inline-block;
    width: 1ch;
}

.hex-byte.search-match {
    background: rgba(220, 155, 61, 0.38);
}

.hex-byte.search-active {
    color: #fff;
    background: var(--accent-color, #4f8cff);
}

.text-cell {
    border-radius: 2px;
}

.text-cell.search-match {
    background: rgba(220, 155, 61, 0.38);
}

.text-cell.search-active {
    color: #fff;
    background: var(--accent-color, #4f8cff);
}

.text-column {
    min-width: 0;
    overflow: hidden;
    color: var(--text-secondary);
    white-space: pre;
    text-overflow: clip;
}

.empty-raw {
    margin: 18px 12px;
    color: var(--text-tertiary);
    font-family: inherit;
    font-size: 0.78rem;
}

@media (max-width: 800px) {
    .hex-toolbar {
        min-height: 48px;
        flex-wrap: wrap;
        padding: 5px 12px;
    }

    .hex-search-panel {
        flex-wrap: wrap;
    }

    .search-controls {
        min-width: 220px;
    }
}
</style>
