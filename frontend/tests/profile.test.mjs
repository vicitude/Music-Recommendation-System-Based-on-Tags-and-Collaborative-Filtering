import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { mountPage, flush } from './page-harness.mjs'
import { loadModule } from './load-module.mjs'

const history = (page = 1, id = page) => ({ items: [{ song: { id, title: '歌曲' + id, artist: '歌手', tags: [], playable: true, current_rating: 4 }, last_played_at: '2026-11-11T02:03:00Z' }], total: 21, page, page_size: 20 })

test('profile loads server ordered full songs, refreshes same page and bounds pagination', async () => {
  const state = await mountPage('pages/ProfilePage.vue', async path => history(Number(new URL(path, 'http://localhost').searchParams.get('page'))))
  try {
    assert.equal(state.calls[0][0], '/api/v1/me/history/?page=1')
    assert.equal(state.vm.songs[0], state.vm.data.items[0].song)
    assert.equal(state.vm.songs[0].current_rating, 4)
    state.vm.turn(-1); assert.equal(state.calls.length, 1)
    state.vm.turn(1); state.vm.turn(1); await flush()
    assert.equal(state.vm.page, 2); assert.equal(state.calls.length, 2)
    state.vm.turn(1); assert.equal(state.calls.length, 2)
    await state.vm.load(); assert.equal(state.calls.at(-1)[0], '/api/v1/me/history/?page=2')
    assert.equal(state.vm.songs.length, 1)
    const expected = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date('2026-11-11T02:03:00Z'))
    assert.equal(state.vm.localDate(state.vm.playedAt[2]), expected)
    assert.ok(state.calls.every(([, init]) => !init?.method))
  } finally { state.close() }
})

test('profile exposes loading, errors, retry and true empty history without fabricated songs', async () => {
  let resolve, fail = false
  const state = await mountPage('pages/ProfilePage.vue', () => fail ? Promise.reject(Error('历史加载失败')) : new Promise(accept => { resolve = accept }))
  try {
    assert.equal(state.vm.loading, true); assert.equal(state.vm.data, null)
    resolve({ items: [], total: 0, page: 1, page_size: 20 }); await flush()
    assert.deepEqual(state.vm.songs, []); assert.equal(state.vm.loading, false)
    fail = true; await state.vm.load(); assert.equal(state.vm.error, '历史加载失败')
    fail = false; const retry = state.vm.load(); assert.equal(state.vm.error, '')
    resolve(history()); await retry; assert.equal(state.vm.songs[0].id, 1)
  } finally { state.close() }
})

test('profile rejects old refresh responses after page change', async () => {
  const pending = []
  let defer = false
  const state = await mountPage('pages/ProfilePage.vue', path => defer ? new Promise(resolve => pending.push({ path, resolve })) : history())
  try {
    defer = true
    const older = state.vm.load()
    const newer = state.vm.load()
    pending[1].resolve(history(1, 11)); await newer
    state.vm.turn(1)
    pending[2].resolve(history(2, 22)); await flush()
    pending[0].resolve(history(1, 10)); await older
    assert.equal(state.vm.data.page, 2); assert.equal(state.vm.songs[0].id, 22)
    state.vm.turn(-1); pending[3].resolve(history(1, 11)); await flush()
    assert.equal(state.vm.page, 1); assert.equal(state.vm.songs[0].id, 11)
  } finally { state.close() }
})

test('profile clears history synchronously on account switch and ignores old success and failure after logout', async () => {
  const pending = []
  const state = await mountPage('pages/ProfilePage.vue', () => new Promise((resolve, reject) => pending.push({ resolve, reject })))
  try {
    pending[0].resolve(history()); await flush()
    const oldRefresh = state.vm.load()
    state.user.value = { id: 2, username: 'second', onboarding_completed: true }
    assert.equal(state.vm.data, null); assert.equal(state.vm.page, 1)
    pending[2].resolve(history(1, 200)); await flush()
    pending[1].resolve(history(1, 100)); await oldRefresh
    assert.equal(state.vm.songs[0].id, 200)
    const beforeLogout = state.vm.load()
    state.user.value = null
    assert.equal(state.vm.data, null); assert.equal(state.vm.loading, false)
    pending[3].reject(Error('old account failure')); await beforeLogout
    assert.equal(state.vm.error, ''); assert.deepEqual(state.vm.songs, [])
    await state.vm.load(); assert.equal(state.calls.length, 4)
  } finally { state.close() }
})

test('profile ignores a response after unmount', async () => {
  let resolve
  const state = await mountPage('pages/ProfilePage.vue', () => new Promise(accept => { resolve = accept }))
  state.close(); resolve(history()); await flush()
  assert.equal(state.vm.data, null)
})

test('interest editing saves and clearing show manual refresh notice, never request daily refresh', async () => {
  const state = await mountPage('pages/OnboardingPage.vue', async (path, init) => init ? { onboarding_completed: true } : path.endsWith('/tags/') ? [] : { tag_ids: [1, 2, 3] }, '/onboarding', {}, { user: { id: 1, onboarding_completed: true } })
  try {
    await state.vm.save()
    assert.deepEqual(state.routes, ['/profile'])
    assert.match(state.notice.value, /主动刷新每日推荐后应用新偏好/)
    await state.vm.save(true)
    assert.deepEqual(JSON.parse(state.calls.at(-1)[1].body), { tag_ids: [] })
    assert.ok(state.calls.every(([path]) => !path.includes('/recommendations/')))
  } finally { state.close() }
})

for (const outcome of ['success', 'failure']) {
  test('interest save ignores late ' + outcome + ' after page unmount', async () => {
    let resolve, reject
    const state = await mountPage('pages/OnboardingPage.vue', (path, init) => init ? new Promise((accept, fail) => { resolve = accept; reject = fail }) : path.endsWith('/tags/') ? [] : { tag_ids: [1, 2, 3] }, '/onboarding', {}, { user: { id: 1, onboarding_completed: true } })
    const saving = state.vm.save()
    assert.equal(state.vm.busy, true)
    state.close()
    state.notice.value = '离页后的提示'
    const identity = state.user.value
    if (outcome === 'success') resolve({ onboarding_completed: true }); else reject(Error('迟到的保存错误'))
    await saving
    assert.deepEqual(state.routes, [])
    assert.equal(state.notice.value, '离页后的提示')
    assert.equal(state.user.value, identity)
    assert.equal(state.vm.feedback, '')
    await state.vm.save()
    assert.equal(state.calls.filter(([, init]) => init?.method === 'PUT').length, 1)
  })
  for (const change of ['switch', 'logout', 'return']) {
    test('interest save ignores late ' + outcome + ' after identity ' + change, async () => {
      let resolve, reject
      const state = await mountPage('pages/OnboardingPage.vue', (path, init) => init ? new Promise((accept, fail) => { resolve = accept; reject = fail }) : path.endsWith('/tags/') ? [] : { tag_ids: [1, 2, 3] }, '/onboarding', {}, { user: { id: 1, onboarding_completed: true } })
      try {
        const saving = state.vm.save()
        state.user.value = change === 'switch' ? { id: 2, onboarding_completed: false } : null
        if (change === 'return') state.user.value = { id: 1, onboarding_completed: false }
        state.notice.value = '当前账号提示'
        const identity = state.user.value
        if (outcome === 'success') resolve({ onboarding_completed: true }); else reject(Error('旧账号保存失败'))
        await saving
        assert.deepEqual(state.routes, [])
        assert.equal(state.notice.value, '当前账号提示')
        assert.equal(state.user.value, identity)
        assert.equal(state.vm.feedback, '')
        assert.equal(state.vm.busy, false)
      } finally { state.close() }
    })
  }
}

test('interest save still reports a current page failure and allows retry', async () => {
  let fail = true
  const state = await mountPage('pages/OnboardingPage.vue', async (path, init) => {
    if (init) { if (fail) throw Error('保存失败'); return { onboarding_completed: true } }
    return path.endsWith('/tags/') ? [] : { tag_ids: [1, 2, 3] }
  }, '/onboarding', {}, { user: { id: 1, onboarding_completed: true } })
  try {
    await state.vm.save()
    assert.equal(state.vm.feedback, '保存失败'); assert.equal(state.vm.busy, false)
    assert.deepEqual(state.routes, []); assert.equal(state.notice.value, '')
    fail = false; await state.vm.save()
    assert.equal(state.vm.feedback, ''); assert.deepEqual(state.routes, ['/profile'])
    assert.match(state.notice.value, /主动刷新每日推荐后应用新偏好/)
  } finally { state.close() }
})

test('profile ASCII route resolves and App guard redirects guests including ready initial state', async () => {
  const previous = globalThis.window
  globalThis.window = { location: { hash: '#/profile' }, addEventListener() {}, removeEventListener() {} }
  try {
    const router = await loadModule('../src/router.ts')
    assert.equal(router.routeName(), 'profile')
    for (const ready of [false, true]) {
      const state = await mountPage('App.vue', async () => {}, '/profile', {}, { user: null, ready })
      try {
        assert.equal(state.vm.protectedPage, true)
        if (!ready) { assert.deepEqual(state.routes, []); state.ready.value = true; await flush() }
        assert.deepEqual(state.routes, ['/login'])
      } finally { state.close() }
    }
    const state = await mountPage('App.vue', async () => {}, '/profile', {}, { ready: true })
    try { assert.deepEqual(state.routes, []); state.user.value = null; await flush(); assert.deepEqual(state.routes, ['/login']) } finally { state.close() }
  } finally { globalThis.window = previous }
})

test('STATIC profile markup wires retry, page queue, dates and existing destinations', async () => {
  const profile = await readFile(new URL('../src/pages/ProfilePage.vue', import.meta.url), 'utf8')
  const app = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const list = await readFile(new URL('../src/components/SongList.vue', import.meta.url), 'utf8')
  assert.match(profile, /<LoadState[^>]*@retry="load"/)
  assert.match(profile, /<SongList :songs="songs"/)
  assert.match(profile, /<time :datetime=/)
  assert.ok(profile.includes("navigate('/favorites')"))
  assert.ok(profile.includes("navigate('/onboarding')"))
  assert.ok(app.includes('@click="navigate(\'/profile\')">{{ user.username }}'))
  assert.ok(list.includes('playQueue(songs, index)'))
  assert.match(list, /<slot name="metadata" :song="song"/)
})
