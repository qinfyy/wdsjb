<script setup>
import { computed } from 'vue'
import { parseHexSearch } from '../packetSearch.js'

const props = defineProps({
    filter: {
        type: String,
        default: ''
    },
    contentFilter: {
        type: String,
        default: ''
    },
    contentSearchMode: {
        type: String,
        default: 'text'
    },
    useAnd: {
        type: Boolean,
        default: true
    }
})

const emit = defineEmits([
    'update:filter',
    'update:content-filter',
    'update:content-search-mode',
    'update:use-and'
])

const invalidHex = computed(() => {
    return props.contentSearchMode === 'hex'
        && props.contentFilter.trim().length > 0
        && !parseHexSearch(props.contentFilter).valid
})

const toggleUseAnd = () => {
    emit('update:use-and', !props.useAnd)
}
</script>

<template>
    <div class="filter-host">
        <input
            class="packet-filter"
            type="search"
            :value="props.filter"
            placeholder="PACKET / ID"
            aria-label="Filter packet name or id"
            @input="emit('update:filter', $event.target.value)"
        />

        <button
            type="button"
            class="orand"
            :title="props.useAnd ? 'Switch to OR' : 'Switch to AND'"
            :aria-label="props.useAnd ? 'Use AND filter' : 'Use OR filter'"
            @click="toggleUseAnd"
        >
            <span :class="{ selected: props.useAnd }">AND</span>
            <span :class="{ selected: !props.useAnd }">OR</span>
        </button>

        <div class="content-filter">
            <input
                class="content-input"
                :class="{ invalid: invalidHex }"
                type="search"
                :value="props.contentFilter"
                :placeholder="props.contentSearchMode === 'hex' ? '01 02 0A' : 'JSON / COMMAND text'"
                :aria-invalid="invalidHex"
                aria-label="Filter JSON or COMMAND content"
                @input="emit('update:content-filter', $event.target.value)"
            />

            <select
                class="content-mode-select"
                :value="props.contentSearchMode"
                aria-label="Content search mode"
                @change="emit('update:content-search-mode', $event.target.value)"
            >
                <option value="text">Text</option>
                <option value="hex">Hex</option>
            </select>
        </div>
    </div>
</template>

<style scoped>
.filter-host {
    width: 100%;
    display: flex;
    background: var(--bg-primary);
    flex-shrink: 0;
    border-bottom: 1px solid var(--border-light);
    min-width: 0;
}

.packet-filter,
.content-input {
    height: 3rem;
    background: var(--bg-primary);
    color: var(--text-primary);
    border: none;
    padding: 0 1rem;
    font-size: 1em;
    font-family: 'JetBrains Mono', monospace;
    border-radius: 0;
    outline: none;
}

.packet-filter {
    flex: 1 1 220px;
    min-width: 140px;
    border-right: 1px solid var(--border-light);
}

.content-input {
    flex: 1 1 260px;
    min-width: 120px;
}

.packet-filter:focus,
.content-input:focus {
    background: var(--bg-tertiary);
}

.content-input.invalid {
    box-shadow: inset 0 -2px #d85b5b;
}

.packet-filter::placeholder,
.content-input::placeholder {
    font-family: inherit;
    color: var(--text-tertiary);
    font-size: 0.9em;
}

.orand {
    box-sizing: border-box;
    padding: 4px 2px;
    background: var(--bg-tertiary);
    border: none;
    border-right: 1px solid var(--border-light);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 42px;
    height: 3rem;
    font-size: 0.75em;
    font-weight: 600;
    gap: 2px;
    color: inherit;
}

.orand:hover {
    background: var(--bg-secondary);
}

.orand span {
    color: var(--text-tertiary);
    font-weight: 700;
    padding: 3px 6px;
    display: block;
    border-radius: 4px;
    min-width: 28px;
    text-align: center;
    user-select: none;
    line-height: 1.2;
    transition: all 0.15s;
    width: 100%;
}

.orand span.selected {
    background: var(--primary-color);
    color: var(--text-light);
    box-shadow: 0 1px 2px rgba(37, 99, 235, 0.3);
}

.content-filter {
    min-width: 0;
    flex: 1.5 1 360px;
    display: flex;
    align-items: stretch;
}

.content-mode-select {
    box-sizing: border-box;
    flex: 0 0 48px;
    width: 48px;
    height: 3rem;
    padding: 0 2px;
    border: none;
    border-left: 1px solid var(--border-light);
    outline: none;
    color: var(--text-primary);
    background: var(--bg-primary);
    font: inherit;
    font-size: 0.62rem;
}

@media (max-width: 760px) {
    .filter-host {
        flex-wrap: wrap;
    }

    .packet-filter {
        flex-basis: calc(100% - 42px);
    }

    .content-filter {
        flex-basis: 100%;
        border-top: 1px solid var(--border-light);
    }
}
</style>
