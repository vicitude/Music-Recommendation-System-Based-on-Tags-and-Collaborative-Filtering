export type ApiErrorBody = {
  error_code: string
  message: string
  details: string[]
  request_id: string
}

let csrfToken = ''
let csrfPending: Promise<string> | null = null
let authRequired = () => {}
let csrfFailed = () => {}

export function configureClient(handlers: { authRequired: () => void; csrfFailed: () => void }): void {
  authRequired = handlers.authRequired
  csrfFailed = handlers.csrfFailed
}

export class ApiError extends Error {
  readonly body: ApiErrorBody

  constructor(body: ApiErrorBody, readonly retryAfter = 0) {
    super(body.message)
    this.name = 'ApiError'
    this.body = body
  }
}

async function fetchSafe(path: string, init: RequestInit): Promise<Response> {
  try { return await fetch(path, { ...init, credentials: 'same-origin' }) }
  catch { throw new ApiError({ error_code: 'NETWORK_ERROR', message: '网络连接失败，请手工重试', details: [], request_id: '' }) }
}

async function fetchCsrfToken(): Promise<string> {
  const response = await fetchSafe('/api/v1/auth/csrf/', {})
  let body: { csrf_token?: string } | null = null
  try { body = await response.json() as { csrf_token?: string } | null } catch {}
  if (!response.ok || !body || typeof body.csrf_token !== 'string' || !body.csrf_token) throw new ApiError({ error_code: 'RESPONSE_ERROR', message: '无法取得请求校验信息', details: [], request_id: '' })
  return body.csrf_token
}

export async function refreshCsrf(isCurrent?: () => boolean): Promise<string> {
  if (isCurrent) {
    const token = await fetchCsrfToken()
    if (isCurrent()) csrfToken = token
    return token
  }
  if (!csrfPending) csrfPending = fetchCsrfToken().then(token => { csrfToken = token; return token }).finally(() => { csrfPending = null })
  return csrfPending
}

export async function request<T = void>(path: string, init: RequestInit = {}, isCurrent?: () => boolean): Promise<T> {
  if (!path.startsWith('/api/v1/')) throw new ApiError({ error_code: 'REQUEST_ERROR', message: '仅允许请求本项目接口', details: [], request_id: '' })
  const method = (init.method ?? 'GET').toUpperCase()
  const active = () => !isCurrent || isCurrent()
  const requireCurrent = () => { if (!active()) throw new ApiError({ error_code: 'REQUEST_ERROR', message: '请求上下文已失效', details: [], request_id: '' }) }
  requireCurrent()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    if (!csrfToken) await refreshCsrf(isCurrent)
    requireCurrent()
    headers.set('X-CSRFToken', csrfToken)
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetchSafe(path, { ...init, headers })
  if (response.status === 204) {
    if (active() && path === '/api/v1/auth/logout/') csrfToken = ''
    return undefined as T
  }
  let body: T | ApiErrorBody
  try { body = await response.json() as T | ApiErrorBody }
  catch { throw new ApiError({ error_code: 'RESPONSE_ERROR', message: '服务响应异常，请稍后重试', details: [], request_id: '' }) }
  if (!response.ok) {
    const candidate = (body && typeof body === 'object' ? body : {}) as Partial<ApiErrorBody>
    const error = typeof candidate.error_code === 'string' && typeof candidate.message === 'string'
      ? new ApiError(candidate as ApiErrorBody, Number(response.headers.get('Retry-After')) || 0)
      : new ApiError({ error_code: 'RESPONSE_ERROR', message: '服务响应异常，请稍后重试', details: [], request_id: '' })
    if (active() && response.status === 401 && candidate.error_code !== 'AUTH_FAILED') { csrfToken = ''; authRequired() }
    if (active() && candidate.error_code === 'CSRF_FAILED') { csrfToken = ''; try { await refreshCsrf(isCurrent) } catch {} if (active()) csrfFailed() }
    throw error
  }
  if (active() && path === '/api/v1/auth/login/') { csrfToken = ''; try { await refreshCsrf(isCurrent) } catch { if (active()) csrfFailed() } }
  return body as T
}
