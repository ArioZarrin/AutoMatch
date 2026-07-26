import type {
  BatchMatchResponse,
  DatabaseStatus,
  ExtractionMode,
  MatchRequest,
  MatchResponse,
} from '~/types/api'

interface ApiErrorShape {
  data?: {
    message?: string
    detail?: string
  }
  message?: string
}

function readableApiError(error: unknown, fallback: string): Error {
  const apiError = error as ApiErrorShape
  const message =
    apiError?.data?.message
    ?? apiError?.data?.detail
    ?? apiError?.message
    ?? fallback

  return new Error(message)
}

function requireJsonObject<T>(value: unknown, message: string): T {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(message)
  }

  return value as T
}

export function useMatcherApi() {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase.replace(/\/$/, '')
  const endpoint = (path: string) => `${apiBase}${path}`

  async function matchVehicle(payload: MatchRequest): Promise<MatchResponse> {
    try {
      const response = await $fetch<unknown>(endpoint('/api/match'), {
        method: 'POST',
        body: payload,
      })
      return requireJsonObject<MatchResponse>(response, 'Invalid match response.')
    }
    catch (error) {
      throw readableApiError(error, 'Vehicle matching failed.')
    }
  }

  async function matchFile(file: File, mode: ExtractionMode): Promise<BatchMatchResponse> {
    const body = new FormData()
    body.append('mode', mode)
    body.append('file', file, file.name)

    try {
      const response = await $fetch<unknown>(endpoint('/api/match/file'), {
        method: 'POST',
        body,
      })
      return requireJsonObject<BatchMatchResponse>(response, 'Invalid batch response.')
    }
    catch (error) {
      throw readableApiError(error, 'Query file matching failed.')
    }
  }

  async function getDatabaseStatus(): Promise<DatabaseStatus> {
    try {
      const response = await $fetch<unknown>(endpoint('/api/status/database'))
      return requireJsonObject<DatabaseStatus>(response, 'Invalid database status response.')
    }
    catch (error) {
      throw readableApiError(error, 'Database status is unavailable.')
    }
  }

  return {
    getDatabaseStatus,
    matchFile,
    matchVehicle,
  }
}
