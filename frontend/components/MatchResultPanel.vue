<script setup lang="ts">
import { CheckCircle2, CircleAlert, CircleDollarSign, Clock3, Database, Route } from '@lucide/vue'
import { VEHICLE_FIELDS, type MatchResponse, type VehicleField } from '~/types/api'

const props = defineProps<{
  result: MatchResponse
}>()

const fieldLabels: Record<VehicleField, string> = {
  make: 'Make',
  model: 'Model',
  badge: 'Badge',
  transmission_type: 'Transmission',
  fuel_type: 'Fuel',
  drive_type: 'Drive',
}

const isMatched = computed(() => props.result.vehicle_id !== null)
const confidencePercent = computed(() => {
  const score = Math.min(10, Math.max(0, props.result.confidence))
  return score * 10
})
const confidenceColor = computed(() => {
  if (props.result.confidence >= 8) return 'success'
  if (props.result.confidence >= 5) return 'warning'
  return 'error'
})
const statusLabel = computed(() => props.result.status.replaceAll('_', ' '))
</script>

<template>
  <section class="result-panel" aria-live="polite">
    <div class="result-summary">
      <div class="result-identity">
        <div class="result-status-row">
          <VChip
            :color="isMatched ? 'success' : 'warning'"
            size="small"
            variant="tonal"
          >
            <CheckCircle2 v-if="isMatched" :size="15" aria-hidden="true" />
            <CircleAlert v-else :size="15" aria-hidden="true" />
            <span>{{ statusLabel }}</span>
          </VChip>
          <span class="result-source">{{ result.source }}</span>
          <span class="result-source">{{ result.model_name }}</span>
        </div>
        <p class="result-label">Vehicle ID</p>
        <p class="vehicle-id" :class="{ 'vehicle-id-empty': !isMatched }">
          {{ result.vehicle_id ?? 'No catalogue match' }}
        </p>
      </div>

      <div class="confidence-block">
        <p class="result-label">Confidence</p>
        <div class="confidence-value">
          <strong>{{ result.confidence }}</strong>
          <span>/ 10</span>
        </div>
        <VProgressLinear
          :color="confidenceColor"
          :model-value="confidencePercent"
          height="7"
          rounded
        />
      </div>
    </div>

    <div class="result-meta">
      <span>
        <CheckCircle2 :size="16" aria-hidden="true" />
        {{ result.is_complete ? 'Extraction complete' : 'Extraction incomplete' }}
      </span>
      <span>
        <Route :size="16" aria-hidden="true" />
        {{ result.is_decisive ? 'Decisive match' : 'Review required' }}
      </span>
      <span>
        <Clock3 :size="16" aria-hidden="true" />
        {{ result.latency_ms.toFixed(1) }} ms
      </span>
      <span v-if="typeof result.llm_cost_usd === 'number'">
        <CircleDollarSign :size="16" aria-hidden="true" />
        ${{ result.llm_cost_usd.toFixed(6) }} USD
      </span>
    </div>

    <div class="field-grid">
      <div v-for="field in VEHICLE_FIELDS" :key="field" class="field-item">
        <span>{{ fieldLabels[field] }}</span>
        <strong :class="{ 'field-empty': !result.fields[field] }">
          {{ result.fields[field] ?? 'Not detected' }}
        </strong>
      </div>
    </div>

    <div class="catalogue-source">
      <Database :size="16" aria-hidden="true" />
      <span>PostgreSQL catalogue</span>
    </div>
  </section>
</template>
