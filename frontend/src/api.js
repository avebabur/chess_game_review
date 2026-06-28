import axios from 'axios'

/** Dev: Vite on :5173, API on :8000. Desktop / production build: same origin /api */
export const API = import.meta.env.DEV
  ? 'http://127.0.0.1:8000/api'
  : '/api'

const RETRY_STATUS = new Set([502, 503, 504])
const MAX_RETRIES = 3
const RETRY_DELAY_MS = 400
// POSTs that are safe to repeat. Job-starting POSTs (/analyze, /reanalyze)
// must NOT be retried — a flaky network reply would double-start the job.
const IDEMPOTENT_POST_PATHS = [
  /^\/evaluate$/,
]

function canRetry(config) {
  const method = (config.method || 'get').toLowerCase()
  if (method === 'get' || method === 'head') return true
  if (method === 'post') {
    const path = (config.url || '').replace(API, '')
    return IDEMPOTENT_POST_PATHS.some(re => re.test(path))
  }
  return false
}

/** Shared client — retries transient server/network errors on safe requests. */
export const api = axios.create({ baseURL: API })

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config
    if (!config) return Promise.reject(error)

    const retryCount = config.__retryCount ?? 0
    if (retryCount >= MAX_RETRIES) return Promise.reject(error)

    const status = error.response?.status
    const networkError = !error.response
      && (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED')

    if ((!networkError && !RETRY_STATUS.has(status)) || !canRetry(config)) {
      return Promise.reject(error)
    }

    config.__retryCount = retryCount + 1
    await new Promise((resolve) => {
      setTimeout(resolve, RETRY_DELAY_MS * config.__retryCount)
    })
    return api(config)
  },
)
