import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileTemplate } from '@vue/compiler-sfc'
import { mountPage, flush } from './page-harness.mjs'

const item = (id = 1, extra = {}) => ({ id, song_id: 42, author: { id: 1, username: '听众' }, content: '<img src=x onerror=alert(1)>\n第二行', created_at: '2026-11-11T08:00:00Z', can_delete: true, ...extra })
const listing = (page = 1, items = [item()], total = 41) => ({ items, total, page, page_size: 20 })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const mount = (request = async () => listing(), options = {}) => mountPage('components/SongComments.vue', request, '/songs/42', { songId: 42 }, options)
const notFoundBody = (details = []) => ({ error_code: 'NOT_FOUND', message: '资源不存在或不可访问', details, request_id: 'comments-test-request' })

test('Unicode count accepts 500 emoji, rejects 501 and sends the trimmed string unchanged', async () => {
  const state = await mount(async (_path, init) => init?.method ? item() : listing())
  try {
    state.vm.content = ' 😀 \n'
    assert.equal(state.vm.characterCount, 1); assert.equal(state.vm.canSubmit, true)
    const content = '😀'.repeat(500)
    state.vm.content = ' \n' + content + ' \t'
    assert.equal(state.vm.characterCount, 500); assert.equal(state.vm.canSubmit, true)
    await state.vm.submit()
    assert.deepEqual(state.calls[1].slice(0, 2), ['/api/v1/songs/42/comments/', { method: 'POST', body: JSON.stringify({ content }) }])
    state.vm.content = '😀'.repeat(501)
    assert.equal(state.vm.characterCount, 501); assert.equal(state.vm.canSubmit, false)
    const count = state.calls.length; await state.vm.submit(); assert.equal(state.calls.length, count)
  } finally { state.close() }
})

test('DELETE final item: real NOT_FOUND page error reloads page one', async () => {
  let deleted = false, state
  state = await mount(async (path, init) => {
    if (init?.method) { deleted = true; return }
    const page = Number(path.split('=').pop())
    if (deleted && page > 1) throw new state.ApiError(notFoundBody(['page']))
    return listing(page, [item()], deleted ? 20 : 21)
  })
  try {
    state.vm.turn(1); await flush(); state.vm.askDelete(item()); await state.vm.remove(item())
    assert.deepEqual(state.calls.map(([path]) => path), ['/api/v1/songs/42/comments/?page=1', '/api/v1/songs/42/comments/?page=2', '/api/v1/comments/1/', '/api/v1/songs/42/comments/?page=2', '/api/v1/songs/42/comments/?page=1'])
    assert.equal(state.vm.page, 1); assert.equal(state.vm.error, ''); assert.equal(state.vm.loading, false)
  } finally { state.close() }
})

for (const details of [[], ['song_id']]) {
  test('unavailable song NOT_FOUND does not fallback: ' + JSON.stringify(details), async () => {
    let fail = false, state
    state = await mount(async () => { if (fail) throw new state.ApiError(notFoundBody(details)); return listing() })
    try {
      fail = true; await state.vm.load(2)
      assert.equal(state.calls.length, 2); assert.equal(state.vm.page, 2)
      assert.equal(state.vm.error, '资源不存在或不可访问'); assert.equal(state.vm.loading, false)
    } finally { state.close() }
  })
}

test('NOT_FOUND page fallback stops if page one also fails', async () => {
  let fail = false, state
  state = await mount(async () => { if (fail) throw new state.ApiError(notFoundBody(['page'])); return listing() })
  try {
    fail = true; await state.vm.load(2)
    assert.equal(state.calls.length, 3); assert.equal(state.vm.page, 1)
    assert.equal(state.vm.error, '资源不存在或不可访问'); assert.equal(state.vm.loading, false)
  } finally { state.close() }
})

test('stale NOT_FOUND page error cannot start a fallback request', async () => {
  const pending = deferred(); let delay = false
  const state = await mount(async () => delay ? pending.promise : listing())
  try {
    delay = true; const task = state.vm.load(2); delay = false
    state.user.value = { id: 2 }; await flush()
    const count = state.calls.length
    pending.reject(new state.ApiError(notFoundBody(['page']))); await task
    assert.equal(state.calls.length, count); assert.equal(state.vm.page, 1); assert.equal(state.vm.error, '')
  } finally { state.close() }
})

test('public GET, empty state data, Chinese date and anonymous write guard', async () => {
  const state = await mount(async () => listing(1, [], 0), { user: null })
  try {
    assert.deepEqual(state.calls.map(([path]) => path), ['/api/v1/songs/42/comments/?page=1'])
    assert.equal(state.vm.data.items.length, 0)
    assert.equal(state.vm.loading, false)
    state.vm.content = '评论'; await state.vm.submit()
    assert.equal(state.calls.length, 1)
    assert.equal(state.vm.canDelete(item()), false)
    assert.match(state.vm.localDate(item().created_at), /2026年11月11日/)
    assert.equal(state.vm.localDate('invalid'), '时间未知')
  } finally { state.close() }
})

test('loading, failure, retry and page boundaries', async () => {
  const initial = deferred(); let count = 0
  const state = await mount(async path => { if (++count === 1) return initial.promise; return listing(Number(path.split('=').pop())) })
  try {
    assert.equal(state.vm.loading, true)
    state.vm.turn(1); assert.equal(count, 1)
    initial.reject(Error('读取失败')); await flush()
    assert.equal(state.vm.error, '读取失败'); assert.equal(state.vm.loading, false)
    await state.vm.load(); assert.equal(state.vm.error, '')
    state.vm.turn(-1); assert.equal(count, 2)
    state.vm.turn(1); await flush(); assert.equal(state.vm.page, 2)
    state.vm.turn(1); await flush(); assert.equal(state.vm.page, 3)
    state.vm.turn(1); assert.equal(count, 4)
  } finally { state.close() }
})

test('trim validation, 500 boundary, POST pending and failure preserves input', async () => {
  const pending = deferred()
  const state = await mount(async (_path, init) => init?.method ? pending.promise : listing())
  try {
    for (const value of ['', ' \n\t ', '字'.repeat(501)]) { state.vm.content = value; assert.equal(state.vm.canSubmit, false); await state.vm.submit() }
    assert.equal(state.calls.length, 1)
    state.vm.content = ' ' + '字'.repeat(500) + ' \n'
    assert.equal(state.vm.canSubmit, true)
    const task = state.vm.submit(); await state.vm.submit()
    assert.equal(state.vm.submitting, true); assert.equal(state.calls.length, 2)
    assert.deepEqual(state.calls[1].slice(0, 2), ['/api/v1/songs/42/comments/', { method: 'POST', body: JSON.stringify({ content: '字'.repeat(500) }) }])
    pending.reject(Error('发表失败')); await task
    assert.equal(state.vm.content, ' ' + '字'.repeat(500) + ' \n'); assert.equal(state.vm.actionError, '发表失败'); assert.equal(state.vm.submitting, false)
  } finally { state.close() }
})

test('successful POST clears input and reloads first page without other behavior APIs', async () => {
  const state = await mount(async (path, init) => init?.method ? item() : listing(Number(path.split('=').pop())))
  try {
    state.vm.turn(1); await flush(); assert.equal(state.vm.page, 2)
    state.vm.content = ' 好听 '; await state.vm.submit()
    assert.equal(state.vm.content, ''); assert.equal(state.vm.page, 1); assert.equal(state.vm.submitting, false)
    assert.equal(state.calls.at(-1)[0], '/api/v1/songs/42/comments/?page=1')
    assert.ok(state.calls.every(([path]) => path.includes('/comments/')))
  } finally { state.close() }
})

test('delete requires owner permission and explicit confirmation; cancellation makes no request', async () => {
  const state = await mount()
  try {
    for (const other of [item(2, { can_delete: false }), item(3, { author: { id: 2, username: '别人' } })]) {
      assert.equal(state.vm.canDelete(other), false); state.vm.askDelete(other); await state.vm.remove(other)
    }
    await state.vm.remove(item()); assert.equal(state.calls.length, 1)
    state.vm.askDelete(item()); assert.equal(state.vm.confirming, 1)
    state.vm.cancelDelete(); assert.equal(state.vm.confirming, null)
    await state.vm.remove(item()); assert.equal(state.calls.length, 1)
  } finally { state.close() }
})

test('DELETE pending blocks repeats; 404 failure retains item and permits retry', async () => {
  const pending = deferred(); let writes = 0
  const state = await mount(async (_path, init) => { if (!init?.method) return listing(); if (++writes === 1) return pending.promise })
  try {
    state.vm.askDelete(item()); const task = state.vm.remove(item()); await state.vm.remove(item()); state.vm.cancelDelete()
    assert.equal(writes, 1); assert.equal(state.vm.deleting, 1); assert.equal(state.vm.confirming, 1)
    pending.reject(Error('404')); await task
    assert.equal(state.vm.data.items[0].id, 1); assert.equal(state.vm.actionError, '404'); assert.equal(state.vm.deleting, null)
    await state.vm.remove(item()); assert.equal(writes, 2); assert.equal(state.vm.actionError, '')
  } finally { state.close() }
})

for (const empty of [false, true]) {
  test('successful DELETE reloads current page; empty final page fallback: ' + empty, async () => {
    let deleted = false
    const state = await mount(async (path, init) => { if (init?.method) { deleted = true; return }; const page = Number(path.split('=').pop()); return listing(page, deleted && empty && page === 2 ? [] : [item()], deleted ? 20 : 21) })
    try {
      state.vm.turn(1); await flush(); state.vm.askDelete(item()); await state.vm.remove(item())
      assert.deepEqual(state.calls[2].slice(0, 2), ['/api/v1/comments/1/', { method: 'DELETE' }])
      assert.equal(state.calls[3][0], '/api/v1/songs/42/comments/?page=2')
      assert.equal(state.vm.page, empty ? 1 : 2)
      if (empty) assert.equal(state.calls[4][0], '/api/v1/songs/42/comments/?page=1')
    } finally { state.close() }
  })
}

test('newer pagination GET wins over stale success (mock API/setup only, no real DOM)', async () => {
  const older = deferred(), newer = deferred(); let count = 0
  const state = await mount(async () => ++count === 1 ? listing() : count === 2 ? older.promise : newer.promise)
  try {
    const oldTask = state.vm.load(2), newTask = state.vm.load(3)
    newer.resolve(listing(3, [item(30)])); await newTask
    older.resolve(listing(2, [item(20)])); await oldTask
    assert.equal(state.vm.data.items[0].id, 30); assert.equal(state.vm.page, 3)
  } finally { state.close() }
})

for (const method of ['POST', 'DELETE']) {
  test(`successful ${method} followed by reload failure exposes independent retry`, async () => {
    let failReload = false
    const state = await mount(async (_path, init) => {
      if (init?.method) { failReload = true; return item() }
      if (failReload) throw Error('列表刷新失败')
      return listing()
    })
    try {
      if (method === 'POST') { state.vm.content = '评论'; await state.vm.submit(); assert.equal(state.vm.content, '') }
      else { state.vm.askDelete(item()); await state.vm.remove(item()) }
      assert.equal(state.vm.error, '列表刷新失败'); assert.equal(state.vm.actionError, '')
      assert.equal(state.vm.submitting, false); assert.equal(state.vm.deleting, null)
      failReload = false; await state.vm.load(); assert.equal(state.vm.error, '')
    } finally { state.close() }
  })
}

test('comments GET failure does not change the shared session notice', async () => {
  const state = await mount(async () => { throw Error('评论暂不可用') })
  try { assert.equal(state.vm.error, '评论暂不可用'); assert.equal(state.notice.value, '') } finally { state.close() }
})

for (const context of ['account', 'song', 'unmount', 'page']) {
  for (const method of ['POST', 'DELETE', 'GET']) {
    for (const outcome of ['success', 'failure']) {
      test(`stale ${method} ${outcome} cannot affect ${context} context (mock runtime)`, async () => {
        const pending = deferred(); let delayed = false
        const state = await mount(async (_path, init) => delayed && (init?.method ?? 'GET') === method ? pending.promise : listing())
        let closed = false
        try {
          delayed = true
          let task
          if (method === 'POST') { state.vm.content = '旧输入'; task = state.vm.submit() }
          else if (method === 'DELETE') { state.vm.askDelete(item()); task = state.vm.remove(item()) }
          else task = state.vm.load(2)
          const guard = state.calls.at(-1)[2]
          assert.equal(typeof guard, 'function'); assert.equal(guard(), true)
          delayed = false
          if (context === 'account') { state.user.value = { id: 2, username: '新账号' }; await flush() }
          if (context === 'song') await state.setProps({ songId: 99 })
          if (context === 'page') await state.vm.load(3)
          if (context === 'unmount') { state.close(); closed = true }
          assert.equal(guard(), false)
          state.vm.content = '新输入'
          const before = { count: state.calls.length, data: state.vm.data, page: state.vm.page, error: state.vm.error, actionError: state.vm.actionError, submitting: state.vm.submitting, deleting: state.vm.deleting }
          if (outcome === 'success') pending.resolve(method === 'GET' ? listing(2, [item(999)]) : item()); else pending.reject(Error('过期错误'))
          await task; await flush()
          assert.equal(state.vm.content, '新输入'); assert.equal(state.calls.length, before.count)
          for (const field of ['data', 'page', 'error', 'actionError', 'submitting', 'deleting']) assert.equal(state.vm[field], before[field], field)
          assert.equal(state.notice.value, '')
        } finally { if (!closed) state.close() }
      })
    }
  }
}

test('account reset clears private draft, permissions and confirmation synchronously', async () => {
  const pending = deferred(); let count = 0
  const state = await mount(async () => ++count === 1 ? listing() : pending.promise)
  try {
    state.vm.content = '私密草稿'; state.vm.askDelete(item()); state.vm.actionError = '旧错误'
    state.user.value = null
    assert.equal(state.vm.content, ''); assert.equal(state.vm.confirming, null); assert.equal(state.vm.data, null); assert.equal(state.vm.actionError, '')
    assert.equal(state.vm.canSubmit, false); assert.equal(state.vm.canDelete(item()), false)
    pending.resolve(listing(1, [], 0)); await flush()
  } finally { state.close() }
})

test('static wiring, template compilation, plain text/XSS and wrapping controls (not DOM/visual verification)', async () => {
  const source = await readFile(new URL('../src/components/SongComments.vue', import.meta.url), 'utf8')
  const song = await readFile(new URL('../src/pages/SongPage.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'SongComments.vue', id: 'comments-test' }).errors, [])
  assert.match(song, /import SongComments from '\.\.\/components\/SongComments.vue'/)
  assert.match(song, /<template v-if="data && !loading && !error">[\s\S]*<SongComments :key="data.id" :song-id="data.id" \/><\/template>/)
  assert.match(source, /\{\{ item.content \}\}/); assert.match(source, /\{\{ item.author.username \}\}/)
  assert.doesNotMatch(source, /v-html|innerHTML|window.confirm|mobile-hidden|profile-button|Audio\(|playerKey|behaviors|recommendations|X-CSRFToken|fetch\(/)
  assert.match(source, /white-space: pre-wrap/); assert.match(source, /overflow-wrap: anywhere/)
  assert.match(source, /flex-wrap: wrap/); assert.match(source, /min-height: 44px/)
  assert.match(source, /@media \(max-width: 600px\)/)
  assert.match(source, /@retry="load\(\)"/); assert.match(source, /@click="navigate\('\/login'\)"/)
  assert.match(source, /@click="cancelDelete"/); assert.match(source, /v-if="canDelete\(item\)"/)
  assert.match(source, /:disabled="submitting"/); assert.match(source, /role="alert"/)
  assert.match(source, /\{\{ characterCount \}\} \/ 500字/)
  assert.match(source, /'comment-invalid': characterCount > 500/)
  assert.doesNotMatch(source, /trimmed\.length/)
})
