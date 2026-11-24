import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule } from './load-module.mjs'
const response = (body, status = 200, headers = {}) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
const error = code => ({ error_code: code, message: code, details: [], request_id: 'test' })
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
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

for (const method of ['GET', 'POST', 'DELETE']) {
  for (const [code, status, notice] of [['AUTH_REQUIRED', 401, 'auth'], ['CSRF_FAILED', 403, 'csrf']]) {
    for (const valid of [false, true]) {
      test(`real client fetch: ${method} ${code} context valid=${valid}`, async () => {
        const pending = deferred(), entered = deferred(); let current = true, csrfCount = 0, identity = 'old'
        const state = await fixture(path => {
          if (path.endsWith('/csrf/')) return response({ csrf_token: 'token-' + ++csrfCount })
          if (path === '/api/v1/comments/probe/') return response(null, 204)
          entered.resolve(); return pending.promise
        })
        state.configureClient({ authRequired: () => { identity = null; state.notices.push('auth') }, csrfFailed: () => state.notices.push('csrf') })
        await state.refreshCsrf()
        const task = state.request('/api/v1/songs/42/comments/', { method }, () => current)
        const rejected = assert.rejects(task, failure => failure instanceof state.ApiError && failure.body.error_code === code)
        await entered.promise
        if (!valid) { current = false; identity = 'new'; await state.refreshCsrf() }
        const before = csrfCount
        pending.resolve(response(error(code), status)); await rejected
        assert.deepEqual(state.notices, valid ? [notice] : [])
        assert.equal(identity, valid && code === 'AUTH_REQUIRED' ? null : valid ? 'old' : 'new')
        assert.equal(csrfCount, before + (valid && code === 'CSRF_FAILED' ? 1 : 0))
        await state.request('/api/v1/comments/probe/', { method: 'DELETE' })
        assert.equal(csrfCount, before + (valid ? 1 : 0))
        assert.equal(state.calls.at(-1).init.headers.get('X-CSRFToken'), 'token-' + csrfCount)
        assert.equal(state.calls.filter(call => call.path === '/api/v1/songs/42/comments/').length, 1)
        assert.ok(state.calls.every(({ init }) => Object.keys(init).every(key => ['method', 'headers', 'credentials'].includes(key))))
      })
    }
  }
}

for (const fails of [false, true]) {
  test('context expires during CSRF recovery: no stale token or notice, failed=' + fails, async () => {
    const pending = deferred(), entered = deferred(); let count = 0, current = true
    const state = await fixture(path => {
      if (!path.endsWith('/csrf/')) return path.includes('/songs/') ? response(error('CSRF_FAILED'), 403) : response(null, 204)
      count++
      if (count === 2) { entered.resolve(); return pending.promise }
      return response({ csrf_token: count === 1 ? 'old' : 'new' })
    })
    await state.refreshCsrf()
    const rejected = assert.rejects(state.request('/api/v1/songs/42/comments/', { method: 'POST' }, () => current))
    await entered.promise; current = false
    await state.refreshCsrf()
    pending.resolve(fails ? response(error('RESPONSE_ERROR'), 500) : response({ csrf_token: 'stale' }))
    await rejected
    assert.deepEqual(state.notices, [])
    await state.request('/api/v1/comments/probe/', { method: 'DELETE' })
    assert.equal(state.calls.at(-1).init.headers.get('X-CSRFToken'), 'new'); assert.equal(count, 3)
  })
}

test('context expires during initial CSRF: no stale mutation or token commit', async () => {
  const pending = deferred(), entered = deferred(); let current = true, count = 0
  const state = await fixture(path => {
    if (!path.endsWith('/csrf/')) return response(null, 204)
    if (++count === 1) { entered.resolve(); return pending.promise }
    return response({ csrf_token: 'new' })
  })
  const rejected = assert.rejects(state.request('/api/v1/songs/42/comments/', { method: 'POST' }, () => current), failure => failure.body.error_code === 'REQUEST_ERROR')
  await entered.promise; current = false; await state.refreshCsrf()
  pending.resolve(response({ csrf_token: 'old' })); await rejected
  assert.equal(state.calls.filter(call => call.path.includes('/songs/')).length, 0)
  await state.request('/api/v1/comments/probe/', { method: 'DELETE' })
  assert.equal(state.calls.at(-1).init.headers.get('X-CSRFToken'), 'new'); assert.deepEqual(state.notices, [])
})

test('valid context still requires successful CSRF preflight before mutation', async () => {
  const state = await fixture(() => response({}, 500))
  await assert.rejects(state.request('/api/v1/songs/42/comments/', { method: 'POST' }, () => true), failure => failure.body.error_code === 'RESPONSE_ERROR')
  assert.equal(state.calls.length, 1); assert.equal(state.calls[0].path, '/api/v1/auth/csrf/')
})
