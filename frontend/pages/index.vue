<script setup lang="ts">
import { CarFront, FileText, Paperclip, Search, X } from '@lucide/vue'
import type {
  BatchMatchResponse,
  DatabaseStatus,
  ExtractionMode,
  MatchResponse,
} from '~/types/api'

const api = useMatcherApi()
const query = ref('')
const mode = ref<ExtractionMode>('HYBRID')
const isSearching = ref(false)
const result = ref<MatchResponse | null>(null)
const batchResult = ref<BatchMatchResponse | null>(null)
const searchError = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const selectedFileLines = ref(0)
const databaseStatus = ref<DatabaseStatus>({
  connected: false,
  database: null,
  host: null,
  catalogue_records: 0,
  catalogue_loaded: false,
})

const modes: Array<{ label: string, value: ExtractionMode }> = [
  { label: 'NLP', value: 'NLP' },
  { label: 'LLM', value: 'LLM' },
  { label: 'Hybrid', value: 'HYBRID' },
]

const canSearch = computed(() => (
  Boolean(query.value.trim()) || selectedFile.value !== null
) && !isSearching.value)

function openFilePicker() {
  if (isSearching.value) return
  if (fileInput.value) fileInput.value.value = ''
  fileInput.value?.click()
}

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  try {
    const text = await file.text()
    const lineCount = text.split(/\r?\n/).filter(line => line.trim()).length
    if (!lineCount) throw new Error('The query file contains no non-empty lines.')

    selectedFile.value = file
    selectedFileLines.value = lineCount
    query.value = ''
    result.value = null
    batchResult.value = null
    searchError.value = null
  }
  catch (error) {
    clearSelectedFile()
    searchError.value = error instanceof Error ? error.message : 'Could not read the query file.'
  }
}

function clearSelectedFile() {
  selectedFile.value = null
  selectedFileLines.value = 0
  if (fileInput.value) fileInput.value.value = ''
}

async function refreshDatabaseStatus() {
  try {
    databaseStatus.value = await api.getDatabaseStatus()
  }
  catch {
    databaseStatus.value = {
      connected: false,
      database: null,
      host: null,
      catalogue_records: 0,
      catalogue_loaded: false,
    }
  }
}

async function submitSearch() {
  const cleanedQuery = query.value.trim()
  if ((!cleanedQuery && !selectedFile.value) || isSearching.value) return

  isSearching.value = true
  searchError.value = null
  result.value = null
  batchResult.value = null

  try {
    if (selectedFile.value) {
      batchResult.value = await api.matchFile(selectedFile.value, mode.value)
    }
    else {
      result.value = await api.matchVehicle({
        query: cleanedQuery,
        mode: mode.value,
      })
    }
  }
  catch (error) {
    searchError.value = error instanceof Error
      ? error.message
      : 'Vehicle matching failed.'
  }
  finally {
    isSearching.value = false
  }
}

onMounted(refreshDatabaseStatus)
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand-lockup">
        <CarFront :size="20" aria-hidden="true" />
        <strong>AutoMatch</strong>
      </div>

      <div class="header-actions">
        <VTooltip
          :text="databaseStatus.connected ? 'PostgreSQL connected' : 'PostgreSQL offline'"
          location="bottom"
        >
          <template #activator="{ props: tooltipProps }">
            <span
              v-bind="tooltipProps"
              :aria-label="databaseStatus.connected ? 'PostgreSQL connected' : 'PostgreSQL offline'"
              :class="['status-dot', { connected: databaseStatus.connected }]"
              role="status"
            />
          </template>
        </VTooltip>
      </div>
    </header>

    <main :class="['matcher-main', { 'has-result': result || batchResult || searchError }]">
      <section class="search-console" aria-labelledby="app-title">
        <h1 id="app-title">
          <span class="sr-only">AutoMatch</span>
          <svg
            aria-hidden="true"
            class="matcher-logo"
            fill="none"
            height="24"
            viewBox="0 0 168 24"
            width="168"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              clip-rule="evenodd"
              d="M38.404 15.53c-.34-1.23-.884-2.21-1.584-3.115-.866-1.125-1.953-1.916-3.214-2.474a7.64 7.64 0 0 0-3.771-.629 7.97 7.97 0 0 0-4.352 1.732c-1.77 1.41-2.84 3.247-3.155 5.541-.021.163-.085.207-.22.207h-5.35c-.199 0-.216-.095-.242-.238l-.01-.052c-.28-1.45-.819-2.795-1.728-3.938-1.231-1.551-2.772-2.615-4.692-3.059-1.825-.421-3.566-.206-5.252.624-2.136 1.055-3.537 2.76-4.31 5.046a.35.35 0 0 1-.165.21c-.179-.421-.344-.843-.344-1.31q-.001-.792-.008-1.587C0 11.312-.009 10.136.023 8.96c.043-1.476.93-2.452 2.285-2.724q1.19-.24 2.378-.474 1.473-.289 2.942-.59c.569-.118 1.028-.47 1.444-.874 2.102-2.053 4.547-3.41 7.405-3.982 1.248-.25 2.497-.373 3.753-.29 2.985.202 5.716 1.187 8.127 3.032.423.324.819.69 1.214 1.057q.251.235.506.464c.625.562 1.415.692 2.2.821q.279.045.551.097.59.115 1.179.22c.93.17 1.861.34 2.775.58 1.354.356 2.017 1.393 2.046 2.826.018.861.015 1.723.012 2.584q-.005.922.001 1.846a4.3 4.3 0 0 1-.433 1.973zm-2.11 2.177c.031 3.217-2.532 5.765-5.709 5.71-3.299-.061-5.65-2.368-5.688-5.736-.04-2.954 2.281-5.934 6.25-5.645 2.594.186 5.221 2.48 5.148 5.67m-22.168.008c.056-2.954-2.213-5.79-5.727-5.674l-.004-.004c-3.156-.178-5.52 2.677-5.658 5.25-.195 3.594 2.576 6.172 5.645 6.141 3.164-.03 5.68-2.188 5.744-5.713M116.877 2.4q-3.063 0-5.354 1.325l.003-.008q-2.29 1.325-3.525 3.718c-.823 1.596-1.234 3.465-1.234 5.547q-.001 3.123 1.249 5.53 1.249 2.409 3.479 3.732 2.23 1.325 5.115 1.325 2.261 0 3.911-.921 1.65-.92 2.542-2.23v2.974h2.944v-11.39h-9.041v2.885h5.769v.505q-.119 2.437-1.799 3.805c-1.118.914-2.513 1.37-4.177 1.37q-1.962 0-3.435-.966-1.472-.967-2.261-2.677-.788-1.709-.788-3.94-.001-2.23.802-3.939.804-1.71 2.275-2.677 1.473-.966 3.435-.965 2.142.001 3.614 1.13t1.978 3.123h3.389q-.537-3.328-2.915-5.292T116.877 2.4m-60.446.18h-.156v-.003c-1.178 0-2.23.732-2.643 1.834l-7.105 18.983h3.538l1.933-5.143h8.535l1.964 5.143h3.657L59.077 4.416a2.83 2.83 0 0 0-2.646-1.836m-.18 3.684 3.331 9.069h-6.63zm20.765 17.132h3.182l.005-.002V8.169H76.99v7.553q0 2.349-1.04 3.701-1.041 1.353-2.885 1.353-1.753 0-2.646-1.16-.892-1.156-.892-3.389V8.17h-3.213v8.386q0 3.688 1.664 5.354 1.665 1.667 4.341 1.666 2.974 0 4.697-2.112zm51.301 0v-11.09q0-2.11.997-3.123.996-1.011 3.167-1.01h3.092v2.825h-2.438q-.864 0-1.218.37-.357.374-.356 1.264v10.766h-3.244M82.447 3.92v4.251h-.002v11.092c0 1.41.333 2.448.996 3.123q.998 1.009 3.168 1.01h3.092v-2.825h-2.438q-.861 0-1.218-.37-.357-.372-.356-1.264v-7.94h3.656V8.17h-3.656V3.92zm8.564 15.952q-.966-1.77-.965-4.088c0-1.546.32-2.88.965-4.06a6.8 6.8 0 0 1 2.736-2.75q1.77-.982 4.06-.982t4.06.982a6.83 6.83 0 0 1 2.735 2.75q.967 1.77.966 4.06c0 1.527-.321 2.91-.966 4.088a6.7 6.7 0 0 1-2.735 2.736q-1.77.966-4.06.967t-4.06-.967a6.73 6.73 0 0 1-2.736-2.736m11.285-4.088q.001-2.23-1.234-3.642-1.234-1.413-3.255-1.412-2.023 0-3.241 1.412t-1.218 3.642 1.218 3.642 3.24 1.411q2.023 0 3.256-1.411 1.235-1.412 1.234-3.642m48.734 7.612h-.003v-2.788h-.623q-1.01 0-1.01-1.071V13.53q0-2.678-1.664-4.105-1.665-1.428-4.728-1.428-2.885 0-4.669 1.262-1.785 1.261-2.023 3.553h3.151q.18-1.013 1.086-1.622.905-.609 2.304-.609 1.576 0 2.469.73.892.727.892 2.006v.923h-3.836q-3.184 0-4.848 1.263t-1.664 3.614q-.001 2.081 1.546 3.271t4.105 1.19q3.3-.001 5.025-2.618 0 1.187.654 1.813.654.623 2.141.623h1.692v.007zm-8.802-6.78q-1.487 0-2.29.582-.803.58-.803 1.709 0 .98.758 1.576.757.595 2.068.595 1.994.001 3.106-1.072 1.116-1.069 1.145-2.853v-.536zm25.301-.832q-.001-2.411-.923-4.164c-.614-1.168-1.466-2.068-2.557-2.69q-1.635-.938-3.717-.938-3.123 0-4.936 2.438V2.58h-3.212v20.816h3.182v-2.2a5.5 5.5 0 0 0 2.022 1.74q1.25.64 2.944.64 2.082-.001 3.717-.982 1.635-.98 2.557-2.75c.616-1.18.923-2.453.923-4.06m-4.506-3.642q1.234 1.412 1.234 3.642v.002q0 2.26-1.234 3.673-1.235 1.413-3.227 1.412-1.995 0-3.212-1.428c-.812-.952-1.218-2.2-1.218-3.688q0-2.23 1.218-3.627 1.22-1.399 3.212-1.398 1.992 0 3.227 1.412"
              fill="#fff"
              fill-rule="evenodd"
            />
          </svg>
          <span aria-hidden="true" class="matcher-logo-bang">!</span>
        </h1>

        <form class="search-form" @submit.prevent="submitSearch">
          <VTextField
            v-model="query"
            aria-label="Vehicle description"
            autocomplete="off"
            class="search-input"
            :clearable="!selectedFile"
            :disabled="Boolean(selectedFile)"
            hide-details
            :placeholder="selectedFile ? 'Query file attached' : 'Describe a vehicle'"
          >
            <template #prepend-inner>
              <Search :size="20" aria-hidden="true" />
            </template>
            <template #append-inner>
              <VTooltip text="Attach query file" location="top">
                <template #activator="{ props: tooltipProps }">
                  <button
                    v-bind="tooltipProps"
                    aria-label="Attach query file"
                    class="attachment-button"
                    :disabled="isSearching"
                    type="button"
                    @click="openFilePicker"
                  >
                    <Paperclip :size="19" aria-hidden="true" />
                  </button>
                </template>
              </VTooltip>
            </template>
          </VTextField>

          <input
            ref="fileInput"
            accept=".txt,text/plain"
            class="sr-only"
            type="file"
            @change="selectFile"
          >

          <div v-if="selectedFile" class="selected-file" role="status">
            <FileText :size="16" aria-hidden="true" />
            <span>{{ selectedFile.name }}</span>
            <small>{{ selectedFileLines.toLocaleString() }} queries</small>
            <button
              aria-label="Remove attached file"
              :disabled="isSearching"
              type="button"
              @click="clearSelectedFile"
            >
              <X :size="15" aria-hidden="true" />
            </button>
          </div>

          <VRadioGroup
            v-model="mode"
            aria-label="Matching mode"
            class="mode-radios"
            hide-details
            inline
          >
            <VRadio
              v-for="item in modes"
              :key="item.value"
              color="primary"
              :label="item.label"
              :value="item.value"
            />
          </VRadioGroup>

          <ElectricMatchButton
            :disabled="!canSearch"
            :loading="isSearching"
          />
        </form>
      </section>

      <VAlert
        v-if="searchError"
        class="search-error"
        closable
        type="error"
        variant="tonal"
        @click:close="searchError = null"
      >
        {{ searchError }}
      </VAlert>

      <MatchResultPanel v-if="result" :result="result" />
      <BatchResultPanel v-if="batchResult" :result="batchResult" />
    </main>

  </div>
</template>
