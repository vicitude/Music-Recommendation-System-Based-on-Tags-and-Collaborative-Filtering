import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule } from './load-module.mjs'
const response = (body, status = 200, headers = {}) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
const error = code => ({ error_code: code, message: code, details: [], request_id: 'test' })
async function fixture(handler) {
  const client = await loadModule('../src/api/client.ts'), calls = [], notices = []
  client.configureClient({ authRequired: () => notices.push('auth'), csrfFailed: () => notices.push('csrf') })
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return handler(path, init, calls.length) }
  return { ...client, calls, notices }
}
test('mutations use CSRF and same-origin credentials; 204 is empty', async () => {
  const state = await fixture(path => path.endsWith('/csrf/') ? response({ csrf_token: 'token' }) : response(null, 204))
  assert.equal(await state.request('/api/v1/favorites/1/', { method: 'PUT' }), undefined)
  assert.equal(state.calls[1].init.headers.get('X-CSRFToken'), 'token'); assert.equal(state.calls[1].init.headers.get('Content-Type'), 'application/json')
  assert.ok(state.calls.every(call => call.init.credentials === 'same-origin'))
})
test('login rotates token before following mutations', async () => {
  let count = 0
  const state = await fixture(path => path.endsWith('/csrf/') ? response({ csrf_token: 'token-' + ++count }) : response({ id: 1 }))
  await state.request('/api/v1/auth/login/', { method: 'POST', body: '{}' }); await state.request('/api/v1/favorites/1/', { method: 'PUT' })
  assert.equal(state.calls.at(-1).init.headers.get('X-CSRFToken'), 'token-2')
})
test('successful login survives immediate token refresh failure', async () => {
  let count = 0
  const state = await fixture(path => path.endsWith('/csrf/') ? ++count === 1 ? response({ csrf_token: 'before' }) : response(null, 500) : response({ id: 1 }))
  assert.deepEqual(await state.request('/api/v1/auth/login/', { method: 'POST' }), { id: 1 }); assert.deepEqual(state.notices, ['csrf'])
})
test('CSRF errors refresh token without repeating mutation', async () => {
  const state = await fixture(path => path.endsWith('/csrf/') ? response({ csrf_token: 'token' }) : response(error('CSRF_FAILED'), 403))
  await assert.rejects(state.request('/api/v1/favorites/1/', { method: 'PUT' }), failure => failure.body.error_code === 'CSRF_FAILED')
  assert.equal(state.calls.filter(call => call.path.includes('/favorites/')).length, 1); assert.deepEqual(state.notices, ['csrf'])
})
test('protected 401 expires identity, AUTH_FAILED does not', async () => {
  const state = await fixture(path => path.endsWith('/csrf/') ? response({ csrf_token: 'token' }) : response(error(path.includes('/login/') ? 'AUTH_FAILED' : 'AUTH_REQUIRED'), 401))
  await assert.rejects(state.request('/api/v1/auth/login/', { method: 'POST' })); assert.deepEqual(state.notices, [])
  await assert.rejects(state.request('/api/v1/me/')); assert.deepEqual(state.notices, ['auth'])
})
test('429 exposes Retry-After seconds', async () => {
  const state = await fixture(() => response(error('RATE_LIMITED'), 429, { 'Retry-After': '42' }))
  await assert.rejects(state.request('/api/v1/recommendations/daily/'), failure => failure.retryAfter === 42)
})
test('network disconnect becomes NETWORK_ERROR', async () => {
  const state = await fixture(() => { throw Error('disconnected') })
  await assert.rejects(state.request('/api/v1/songs/'), failure => failure.body.error_code === 'NETWORK_ERROR')
})
test('malformed error responses are readable', async () => {
  for (const invalid of [() => new Response('<html>error</html>', { status: 500 }), () => response(null, 500)]) {
    const state = await fixture(invalid)
    await assert.rejects(state.request('/api/v1/songs/'), failure => failure.body.error_code === 'RESPONSE_ERROR')
  }
})
test('invalid CSRF prevents mutation', async () => {
  const state = await fixture(() => new Response('invalid', { status: 200 }))
  await assert.rejects(state.request('/api/v1/favorites/1/', { method: 'PUT' }), failure => failure.body.error_code === 'RESPONSE_ERROR')
  assert.equal(state.calls.length, 1)
})
test('concurrent CSRF loads share one request', async () => {
  const state = await fixture(() => response({ csrf_token: 'token' }))
  assert.deepEqual(await Promise.all([state.refreshCsrf(), state.refreshCsrf()]), ['token', 'token']); assert.equal(state.calls.length, 1)
})
test('foreign endpoint is rejected before network access', async () => {
  const state = await fixture(() => response({}))
  await assert.rejects(state.request('https://example.com/'), failure => failure.body.error_code === 'REQUEST_ERROR'); assert.equal(state.calls.length, 0)
})
