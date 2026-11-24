import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { mountPage, flush } from './page-harness.mjs'
import { loadModule } from './load-module.mjs'

const summary = (extra = {}) => ({ id: 2, username: '听友', following_count: 4, follower_count: 7, is_following: false, is_self: false, ...extra })
const listing = (extra = {}) => ({ count: 21, page: 1, page_size: 20, results: [{ id: 3, username: '另一位听友', is_following: false, is_self: false }], ...extra })
const deferred = () => { let resolve, reject; const promise = new Promise((accept, fail) => { resolve = accept; reject = fail }); return { promise, resolve, reject } }
const pageFile = 'pages/UserPage.vue', listFile = 'pages/UserConnectionsPage.vue'

test('homepage fetches only public summary with current context', async () => {
  const state = await mountPage(pageFile, async () => summary(), '/users/2')
  try {
    assert.deepEqual(state.vm.data, summary())
    assert.equal(state.calls.length, 1)
    assert.equal(state.calls[0][0], '/api/v1/users/2/')
    assert.equal(state.calls[0][2](), true)
  } finally { state.close() }
})

test('self homepage cannot follow itself', async () => {
  const state = await mountPage(pageFile, async () => summary({ id: 1, is_self: true }), '/users/1')
  try { await state.vm.toggleFollow(); assert.equal(state.calls.length, 1) } finally { state.close() }
})

test('follow and unfollow use authoritative summary, never a follow-up read', async () => {
  const state = await mountPage(pageFile, async (_path, init) => init?.method === 'PUT' ? summary({ is_following: true, follower_count: 42 }) : init?.method === 'DELETE' ? summary({ follower_count: 19 }) : summary(), '/users/2')
  try {
    await state.vm.toggleFollow()
    assert.equal(state.vm.data.follower_count, 42); assert.equal(state.vm.data.is_following, true)
    await state.vm.toggleFollow()
    assert.equal(state.vm.data.follower_count, 19); assert.equal(state.vm.data.is_following, false)
    assert.deepEqual(state.calls.map(([, init]) => init.method ?? 'GET'), ['GET', 'PUT', 'DELETE'])
    assert.equal(state.calls[1][1].body, undefined); assert.equal(state.vm.actionError, '')
  } finally { state.close() }
})

test('pending write rejects duplicate clicks and refresh attempts', async () => {
  const pending = deferred()
  const state = await mountPage(pageFile, async (_path, init) => init?.method ? pending.promise : summary(), '/users/2')
  try {
    const writing = state.vm.toggleFollow()
    assert.equal(state.vm.busy, true)
    await state.vm.toggleFollow(); await state.vm.load()
    assert.equal(state.calls.length, 2)
    pending.resolve(summary({ is_following: true })); await writing
    assert.equal(state.vm.busy, false)
  } finally { state.close() }
})

test('unknown write failure locks further writes until read-only verification succeeds', async () => {
  let reads = 0
  const state = await mountPage(pageFile, async (_path, init) => {
    if (init?.method) throw Error('网络连接失败')
    reads++; return summary({ is_following: reads > 1 })
  }, '/users/2')
  try {
    await state.vm.toggleFollow(); await state.vm.toggleFollow()
    assert.equal(state.calls.length, 2); assert.equal(state.vm.uncertain, true)
    assert.match(state.vm.actionError, /刷新状态核实/)
    await state.vm.load()
    assert.equal(state.calls.length, 3); assert.equal(state.vm.uncertain, false)
    assert.equal(state.vm.data.is_following, true)
    assert.equal(state.calls[2][1].method, undefined)
  } finally { state.close() }
})

test('failed verification does not unlock an uncertain write', async () => {
  let first = true
  const state = await mountPage(pageFile, async () => { if (first) { first = false; return summary() } throw Error('断网') }, '/users/2')
  try {
    await state.vm.toggleFollow(); await state.vm.load(); await state.vm.toggleFollow()
    assert.equal(state.vm.uncertain, true); assert.equal(state.vm.data, null); assert.equal(state.calls.length, 3)
  } finally { state.close() }
})

for (const outcome of ['success', 'failure']) {
  for (const change of ['unmount', 'switch', 'same-id', 'logout-return', 'path']) {
    test(`write ignores late ${outcome} after ${change}, including auth callbacks`, async () => {
      const pending = deferred()
      const state = await mountPage(pageFile, async (_path, init) => init?.method ? pending.promise : summary(), '/users/2')
      const writing = state.vm.toggleFollow(), valid = state.calls[1][2]
      try {
        if (change === 'unmount') state.close()
        if (change === 'switch') state.user.value = { id: 3 }
        if (change === 'same-id') state.user.value = { id: 1 }
        if (change === 'logout-return') { state.user.value = null; state.user.value = { id: 1 } }
        if (change === 'path') globalThis.__pageMocks.get([...globalThis.__pageMocks.keys()].at(-1)).currentPath = () => '/users/3'
        await flush()
        assert.equal(valid(), false)
        const before = state.vm.data
        if (outcome === 'success') pending.resolve(summary({ follower_count: 999 })); else pending.reject(new state.ApiError({ error_code: 'CSRF_FAILED', message: '旧校验失败', details: [], request_id: '' }))
        await writing
        assert.equal(state.vm.data, before); assert.equal(state.vm.actionError, '')
        assert.equal(state.notice.value, '')
      } finally { if (change !== 'unmount') state.close() }
    })
  }
}

test('superseded homepage read cannot overwrite latest refresh', async () => {
  const pending = deferred(); let reads = 0
  const state = await mountPage(pageFile, async () => ++reads === 1 ? pending.promise : summary({ username: '最新' }), '/users/2')
  try {
    await state.vm.load(); assert.equal(state.calls[0][2](), false)
    pending.resolve(summary({ username: '旧值' })); await flush()
    assert.equal(state.vm.data.username, '最新')
  } finally { state.close() }
})

test('homepage missing target reports explicit inaccessible state and retries', async () => {
  const state = await mountPage(pageFile, async () => summary(), '/users/2')
  try {
    const mock = globalThis.__pageMocks.get([...globalThis.__pageMocks.keys()].at(-1))
    mock.request = async () => { throw new state.ApiError('NOT_FOUND') }
    await state.vm.load(); assert.equal(state.vm.data, null); assert.match(state.vm.error, /不可访问/)
    mock.request = async () => summary(); await state.vm.load(); assert.equal(state.vm.error, '')
  } finally { state.close() }
})

for (const direction of ['following', 'followers']) {
  test(`${direction} list loads owner, fixed pages and navigation without writes`, async () => {
    const state = await mountPage(listFile, async path => path.includes('?') ? listing({ page: path.endsWith('2') ? 2 : 1 }) : summary(), '/users/2/' + direction)
    try {
      assert.equal(state.vm.owner.username, '听友'); assert.equal(state.vm.totalPages, 2)
      state.vm.turn(1); await flush()
      assert.equal(state.vm.page, 2); assert.equal(state.vm.data.page, 2)
      assert.ok(state.calls.some(([path]) => path === `/api/v1/users/2/${direction}/?page=2`))
      assert.ok(state.calls.every(([, init]) => !init.method))
      state.vm.turn(1); await flush(); assert.equal(state.vm.page, 2)
    } finally { state.close() }
  })
}

test('list failure keeps requested page and allows retry', async () => {
  let failing = true
  const state = await mountPage(listFile, async path => {
    if (!path.includes('?')) return summary()
    if (path.endsWith('2') && failing) throw Error('加载失败')
    return listing({ page: path.endsWith('2') ? 2 : 1 })
  }, '/users/2/following')
  try {
    state.vm.turn(1); await flush(); assert.equal(state.vm.error, '加载失败'); assert.equal(state.vm.page, 2); assert.equal(state.vm.data, null)
    failing = false; await state.vm.load(); assert.equal(state.vm.data.page, 2); assert.equal(state.vm.error, '')
  } finally { state.close() }
})

for (const reason of ['empty', 'page-error', 'target-error']) {
  test(`list reset distinguishes ${reason} and never retries missing target`, async () => {
    const state = await mountPage(listFile, async path => path.includes('?') ? listing() : summary(), '/users/2/followers')
    try {
      const mock = globalThis.__pageMocks.get([...globalThis.__pageMocks.keys()].at(-1)), pages = []
      mock.request = async path => {
        if (!path.includes('?')) return summary()
        pages.push(path)
        if (path.endsWith('2')) {
          if (reason === 'empty') return listing({ page: 2, results: [] })
          throw new state.ApiError({ error_code: 'NOT_FOUND', message: '未找到', details: reason === 'page-error' ? ['page'] : [], request_id: '' })
        }
        return listing({ count: 0, results: [] })
      }
      await state.vm.load(2)
      assert.equal(pages.length, reason === 'target-error' ? 1 : 2)
      if (reason === 'target-error') assert.match(state.vm.error, /不可访问/)
      else { assert.equal(state.vm.page, 1); assert.equal(state.vm.data.count, 0) }
    } finally { state.close() }
  })
}

test('current target 404 clears previously loaded owner, unlike pagination errors', async () => {
  const state = await mountPage(listFile, async path => path.includes('?') ? listing() : summary(), '/users/2/following')
  try {
    assert.equal(state.vm.owner.username, '听友')
    const mock = globalThis.__pageMocks.get([...globalThis.__pageMocks.keys()].at(-1))
    mock.request = async () => { throw new state.ApiError({ error_code: 'NOT_FOUND', message: '未找到', details: ['page'], request_id: '' }) }
    await state.vm.load()
    assert.equal(state.vm.owner.username, '听友')
    mock.request = async () => { throw new state.ApiError({ error_code: 'NOT_FOUND', message: '未找到', details: [], request_id: '' }) }
    await state.vm.load()
    assert.equal(state.vm.owner, null)
    assert.equal(state.vm.data, null)
    assert.match(state.vm.error, /不可访问/)
  } finally { state.close() }
})

test('stale target 404 cannot clear owner from a newer list load', async () => {
  const pending = deferred()
  const state = await mountPage(listFile, async path => path.includes('?') ? listing() : summary(), '/users/2/following')
  try {
    const mock = globalThis.__pageMocks.get([...globalThis.__pageMocks.keys()].at(-1))
    mock.request = async () => pending.promise
    const stale = state.vm.load()
    mock.request = async path => path.includes('?') ? listing() : summary({ username: '最新用户名' })
    await state.vm.load()
    pending.reject(new state.ApiError({ error_code: 'NOT_FOUND', message: '未找到', details: [], request_id: '' }))
    await stale
    assert.equal(state.vm.owner.username, '最新用户名')
    assert.equal(state.vm.error, '')
  } finally { state.close() }
})

for (const change of ['unmount', 'same-id', 'logout', 'page']) {
  test(`list ignores stale response and invalidates request after ${change}`, async () => {
    const pending = deferred(); let reads = 0
    const state = await mountPage(listFile, async path => path.includes('?') ? ++reads === 1 ? pending.promise : listing({ count: 0, results: [] }) : summary(), '/users/2/following')
    const valid = state.calls[1][2]
    try {
      if (change === 'unmount') state.close()
      if (change === 'same-id') state.user.value = { id: 1 }
      if (change === 'logout') state.user.value = null
      if (change === 'page') await state.vm.load(2)
      await flush(); assert.equal(valid(), false)
      const before = state.vm.data; pending.resolve(listing({ count: 999 })); await flush()
      assert.equal(state.vm.data, before)
    } finally { if (change !== 'unmount') state.close() }
  })
}

test('guests make no social requests and App protects both new routes', async () => {
  const previous = globalThis.window
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  try {
  for (const filename of [pageFile, listFile]) {
    const state = await mountPage(filename, async () => {}, '/users/2/following', {}, { user: null })
    try { assert.equal(state.calls.length, 0) } finally { state.close() }
  }
  for (const path of ['/users/2', '/users/2/following', '/users/2/followers']) {
    const state = await mountPage('App.vue', async () => {}, path, {}, { user: null, ready: true })
    try { assert.equal(state.vm.protectedPage, true); assert.deepEqual(state.routes, ['/login']); assert.ok(state.vm.component) } finally { state.close() }
  }
  } finally { globalThis.window = previous }
})

test('router recognizes only supported social paths', async () => {
  const previous = globalThis.window
  globalThis.window = { location: { hash: '' } }
  try {
    const router = await loadModule('../src/router.ts')
    for (const [path, expected] of [['/users/2', 'user'], ['/users/2/following', 'user-connections'], ['/users/2/followers', 'user-connections'], ['/users/x', 'not-found'], ['/users/2/private', 'not-found'], ['/profile', 'profile']]) {
      globalThis.window.location.hash = '#' + path; assert.equal(router.routeName(), expected)
    }
  } finally { globalThis.window = previous }
})

test('STATIC minimal entries, author ID, self guard and touch sizes preserve single player', async () => {
  const source = async file => readFile(new URL('../src/' + file, import.meta.url), 'utf8')
  const [profile, comments, home, list, app] = await Promise.all(['pages/ProfilePage.vue', 'components/SongComments.vue', pageFile, listFile, 'App.vue'].map(source))
  for (const text of ['我的主页', '我的关注', '粉丝']) assert.ok(profile.includes(text))
  assert.ok(comments.includes("navigate('/users/' + item.author.id)"))
  assert.match(home, /v-if="!data.is_self"/); assert.match(home, /:disabled="busy \|\| uncertain"/)
  assert.ok(list.includes("navigate('/users/' + person.id)")); assert.ok(!list.includes('toggleFollow'))
  assert.match(home, /min-height: 44px/); assert.match(list, /min-height: 44px/)
  assert.equal((app.match(/<AudioPlayer\b/g) ?? []).length, 1)
  assert.ok(app.includes(":key=\"(user?.id ?? 'guest') + path\""))
})
