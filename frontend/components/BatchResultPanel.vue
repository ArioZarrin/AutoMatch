<script setup lang="ts">
import {
  Activity,
  Clock3,
  Download,
  FileText,
  Gauge,
  Rows3,
  WalletCards,
} from '@lucide/vue'
import { VEHICLE_FIELDS } from '~/types/api'
import type { BatchMatchRecord, BatchMatchResponse } from '~/types/api'

const props = defineProps<{
  result: BatchMatchResponse
}>()

const previewLimit = 200
const previewRecords = computed(() => props.result.records.slice(0, previewLimit))
const statusEntries = computed(() => Object.entries(props.result.statistics.status_counts))
const sourceEntries = computed(() => Object.entries(props.result.statistics.source_counts))
const modelEntries = computed(() => Object.entries(props.result.statistics.model_counts))

const fieldLabels: Record<string, string> = {
  make: 'Make',
  model: 'Model',
  badge: 'Badge',
  transmission_type: 'Transmission',
  fuel_type: 'Fuel',
  drive_type: 'Drive',
}

function csvValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function flattenRecord(record: BatchMatchRecord): Record<string, unknown> {
  return {
    row_number: record.row_number,
    query: record.query,
    requested_mode: record.mode,
    source: record.source,
    model_name: record.model_name,
    components_used: record.components_used,
    status: record.status,
    vehicle_id: record.vehicle_id,
    confidence_score: record.confidence,
    is_complete: record.is_complete,
    is_decisive: record.is_decisive,
    make: record.fields.make,
    model: record.fields.model,
    badge: record.fields.badge,
    transmission_type: record.fields.transmission_type,
    fuel_type: record.fields.fuel_type,
    drive_type: record.fields.drive_type,
    latency_ms: record.latency_ms,
    llm_cost_usd: record.llm_cost_usd,
    llm_input_tokens: record.llm_input_tokens,
    llm_output_tokens: record.llm_output_tokens,
    llm_batch_number: record.llm_batch_number,
    llm_batch_size: record.llm_batch_size,
    error: record.error,
  }
}

function downloadCsv() {
  const rows = props.result.records.map(flattenRecord)
  const firstRow = rows[0]
  if (!firstRow) return
  const columns = Object.keys(firstRow)
  const csv = [
    columns.map(csvValue).join(','),
    ...rows.map(row => columns.map(column => csvValue(row[column])).join(',')),
  ].join('\r\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  const baseName = props.result.file_name.replace(/\.[^.]+$/, '') || 'automatch-results'
  anchor.href = url
  anchor.download = `${baseName}-automatch-results.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="batch-result-panel" aria-labelledby="batch-result-title">
    <header class="batch-result-header">
      <div class="batch-file-name">
        <FileText :size="20" aria-hidden="true" />
        <div>
          <span>Batch result</span>
          <strong id="batch-result-title">{{ result.file_name }}</strong>
        </div>
      </div>
      <button class="csv-download-button" type="button" @click="downloadCsv">
        <Download :size="17" aria-hidden="true" />
        Download CSV
      </button>
    </header>

    <div class="batch-stat-grid">
      <div class="batch-stat">
        <Rows3 :size="17" aria-hidden="true" />
        <span>Total queries</span>
        <strong>{{ result.statistics.total_queries.toLocaleString() }}</strong>
      </div>
      <div class="batch-stat">
        <Activity :size="17" aria-hidden="true" />
        <span>Matched</span>
        <strong>{{ result.statistics.matched_queries.toLocaleString() }}</strong>
        <small>{{ result.statistics.match_rate_percent.toFixed(2) }}%</small>
      </div>
      <div class="batch-stat">
        <Gauge :size="17" aria-hidden="true" />
        <span>Average confidence</span>
        <strong>{{ result.statistics.average_confidence.toFixed(2) }}</strong>
        <small>/ 10</small>
      </div>
      <div class="batch-stat">
        <Clock3 :size="17" aria-hidden="true" />
        <span>Total processing</span>
        <strong>{{ (result.statistics.processing_ms / 1000).toFixed(2) }}</strong>
        <small>seconds</small>
      </div>
      <div class="batch-stat">
        <Clock3 :size="17" aria-hidden="true" />
        <span>Average latency</span>
        <strong>{{ result.statistics.average_record_latency_ms.toFixed(1) }}</strong>
        <small>ms</small>
      </div>
      <div class="batch-stat">
        <WalletCards :size="17" aria-hidden="true" />
        <span>LLM cost</span>
        <strong>${{ result.statistics.total_llm_cost_usd.toFixed(6) }}</strong>
        <small>USD</small>
      </div>
      <div class="batch-stat">
        <Activity :size="17" aria-hidden="true" />
        <span>Complete</span>
        <strong>{{ result.statistics.complete_queries.toLocaleString() }}</strong>
        <small>{{ result.statistics.complete_percent.toFixed(2) }}%</small>
      </div>
      <div class="batch-stat">
        <Activity :size="17" aria-hidden="true" />
        <span>Decisive</span>
        <strong>{{ result.statistics.decisive_queries.toLocaleString() }}</strong>
        <small>{{ result.statistics.decisive_percent.toFixed(2) }}%</small>
      </div>
      <div class="batch-stat">
        <Rows3 :size="17" aria-hidden="true" />
        <span>LLM requests</span>
        <strong>{{ result.statistics.llm_requests.toLocaleString() }}</strong>
        <small>up to 50 rows each</small>
      </div>
      <div class="batch-stat">
        <Rows3 :size="17" aria-hidden="true" />
        <span>LLM tokens</span>
        <strong>{{ (result.statistics.llm_input_tokens + result.statistics.llm_output_tokens).toLocaleString() }}</strong>
        <small>{{ result.statistics.error_queries }} errors</small>
      </div>
    </div>

    <div class="batch-breakdown-grid">
      <section class="batch-breakdown">
        <h3>Status</h3>
        <div v-for="([label, count]) in statusEntries" :key="label">
          <span>{{ label }}</span>
          <strong>{{ count.toLocaleString() }}</strong>
        </div>
      </section>
      <section class="batch-breakdown">
        <h3>Source</h3>
        <div v-for="([label, count]) in sourceEntries" :key="label">
          <span>{{ label }}</span>
          <strong>{{ count.toLocaleString() }}</strong>
        </div>
      </section>
      <section class="batch-breakdown">
        <h3>Model</h3>
        <div v-for="([label, count]) in modelEntries" :key="label">
          <span>{{ label }}</span>
          <strong>{{ count.toLocaleString() }}</strong>
        </div>
      </section>
    </div>

    <section class="batch-coverage">
      <h3>Field coverage</h3>
      <div class="coverage-grid">
        <div v-for="field in VEHICLE_FIELDS" :key="field">
          <span>{{ fieldLabels[field] }}</span>
          <strong>{{ result.statistics.field_coverage_percent[field].toFixed(2) }}%</strong>
        </div>
      </div>
    </section>

    <section class="batch-records">
      <header>
        <h3>Records</h3>
        <span>{{ previewRecords.length.toLocaleString() }} / {{ result.records.length.toLocaleString() }}</span>
      </header>
      <div class="batch-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Line</th>
              <th>Query</th>
              <th>Vehicle ID</th>
              <th>Confidence</th>
              <th>Model</th>
              <th>Source</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in previewRecords" :key="record.row_number">
              <td>{{ record.row_number }}</td>
              <td class="batch-query-cell" :title="record.query">{{ record.query }}</td>
              <td>{{ record.vehicle_id ?? '—' }}</td>
              <td>{{ record.confidence.toFixed(1) }}</td>
              <td>{{ record.model_name }}</td>
              <td>{{ record.source }}</td>
              <td :class="`status-${record.status.toLowerCase()}`">{{ record.status }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
