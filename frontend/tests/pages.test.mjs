import test from 'node:test'
import assert from 'node:assert/strict'
import { mountPage, flush } from './page-harness.mjs'

test('daily retains API rank/explanation and refresh sends no body', async () => {
  const daily = { day: '2026-10-30', revision: 1, next_refresh_at: '2000-01-01T00:00:00Z', items: [{ song_id: 3, rank: 7, explanation: 'server reason' }], empty_reason: null }
  const state = await mountPage('pages/DailyPage.vue', async path => path.includes('/songs/') ? { id: 3, title: 'track' } : daily)
  try {
    assert.equal(state.vm.ranks[3], 7); assert.equal(state.vm.explanations[3], 'server reason'); assert.equal(state.vm.data.tracks[0].id, 3)
    await state.vm.refresh()
    const mutation = state.calls.find(([, init]) => init?.method === 'POST')
    assert.equal(mutation[0], '/api/v1/recommendations/daily/refresh/'); assert.equal(mutation[1].body, undefined)
  } finally { state.close() }
})
test('daily 429 sets countdown and blocks another refresh', async () => {
  let failure
  const state = await mountPage('pages/DailyPage.vue', async (_path, init) => { if (init?.method === 'POST') throw failure; return { next_refresh_at: '2000-01-01T00:00:00Z', items: [] } })
  try {
    failure = new state.ApiError('RATE_LIMITED', 60); await state.vm.refresh(); await state.vm.refresh()
    assert.ok(state.vm.remaining >= 59); assert.equal(state.calls.filter(([, init]) => init?.method === 'POST').length, 1)
  } finally { state.close() }
})
test('interest selection caps five and persists exact selected IDs', async () => {
  const state = await mountPage('pages/OnboardingPage.vue', async (path, init) => init ? { onboarding_completed: true } : path.endsWith('/tags/') ? [] : { tag_ids: [1, 2, 3] })
  try {
    state.vm.toggle(4); state.vm.toggle(5); state.vm.toggle(6); assert.deepEqual([...state.vm.selected], [1, 2, 3, 4, 5])
    await state.vm.save(); const write = state.calls.find(([, init]) => init?.method === 'PUT')
    assert.deepEqual(JSON.parse(write[1].body), { tag_ids: [1, 2, 3, 4, 5] }); assert.equal(state.user.value.onboarding_completed, true); assert.deepEqual(state.routes, ['/daily'])
  } finally { state.close() }
})
test('discover uses encoded search and tag filters', async () => {
  const state = await mountPage('pages/DiscoverPage.vue', async path => path.endsWith('/tags/') ? [] : { results: [], count: 0, page: 1, page_size: 20 })
  try {
    state.vm.query = ' A&B '; state.vm.tag = '9'; state.vm.search(); await flush()
    const url = new URL(state.calls.at(-1)[0], 'http://localhost')
    assert.equal(url.searchParams.get('q'), 'A&B'); assert.equal(url.searchParams.get('tag_id'), '9'); assert.equal(url.searchParams.get('page'), '1')
  } finally { state.close() }
})
test('song list favorites and playlist membership use correct verbs', async () => {
  const state = await mountPage('components/SongList.vue', async path => path === '/api/v1/playlists/' ? [{ id: 2, name: 'list' }] : undefined)
  try {
    const track = { id: 3, title: 'track' }
    await state.vm.action(track, 'favorite'); await state.vm.action(track, 'unfavorite'); await state.vm.action(track, 'lists'); state.vm.selectedList = '2'; await state.vm.addToList()
    assert.deepEqual(state.calls.map(([path, init]) => [path, init?.method || 'GET']), [['/api/v1/favorites/3/', 'PUT'], ['/api/v1/favorites/3/', 'DELETE'], ['/api/v1/playlists/', 'GET'], ['/api/v1/playlists/2/songs/3/', 'PUT']])
  } finally { state.close() }
})
test('playlist create waits for server ID before navigation', async () => {
  const state = await mountPage('pages/PlaylistsPage.vue', async (_path, init) => init ? { id: 8 } : [])
  try { state.vm.name = ' New mix '; await state.vm.create(); assert.deepEqual(JSON.parse(state.calls.at(-1)[1].body), { name: 'New mix' }); assert.deepEqual(state.routes, ['/playlists/8']) } finally { state.close() }
})
test('playlist detail renames and deletes via owned playlist URL', async () => {
  const state = await mountPage('pages/PlaylistPage.vue', async () => ({ id: 4, name: 'mix', songs: [] }), '/playlists/4')
  try {
    state.vm.name = 'Renamed'; await state.vm.mutate(); await state.vm.mutate(true)
    assert.deepEqual(state.calls.filter(([, init]) => init).map(([path, init]) => [path, init.method]), [['/api/v1/playlists/4/', 'PATCH'], ['/api/v1/playlists/4/', 'DELETE']]); assert.deepEqual(state.routes, ['/playlists'])
  } finally { state.close() }
})
test('song detail rejects dangerous source links', async () => {
  const state = await mountPage('pages/SongPage.vue', async () => ({ id: 5 }), '/songs/5')
  try { assert.equal(state.vm.safeLink('javascript:alert(1)'), undefined); assert.equal(state.vm.safeLink('file:///private'), undefined); assert.equal(state.vm.safeLink('https://example.com/license'), 'https://example.com/license'); assert.equal(state.calls[0][0], '/api/v1/songs/5/') } finally { state.close() }
})
test('login posts credentials then routes incomplete user to interests', async () => {
  const state = await mountPage('pages/LoginPage.vue', async () => ({ id: 7, onboarding_completed: false }))
  try { state.vm.username = 'tester'; state.vm.password = 'test-password'; await state.vm.submit(); assert.equal(state.calls[0][0], '/api/v1/auth/login/'); assert.equal(state.vm.password, ''); assert.deepEqual(state.routes, ['/onboarding']) } finally { state.close() }
})
test('registration password mismatch sends no request', async () => {
  const state = await mountPage('pages/RegisterPage.vue', async () => ({}))
  try { state.vm.password = 'test-password'; state.vm.confirm = 'mismatch'; await state.vm.submit(); assert.equal(state.calls.length, 0); assert.ok(state.vm.error) } finally { state.close() }
})
test('favorites recovers when last page disappears after removal', async () => {
  let missing = false, Failure
  const state = await mountPage('pages/FavoritesPage.vue', async path => {
    const page = Number(new URL(path, 'http://localhost').searchParams.get('page'))
    if (missing && page > 1) throw new Failure('NOT_FOUND')
    return { count: missing ? 20 : 21, page, page_size: 20, results: [] }
  })
  try {
    Failure = state.ApiError; state.vm.turn(1); await flush(); assert.equal(state.vm.page, 2)
    missing = true; await state.vm.load(); assert.equal(state.vm.page, 1); assert.equal(state.vm.data.page, 1); assert.equal(state.vm.error, '')
  } finally { state.close() }
})
test('failed favorite does not claim success or mutate data', async () => {
  const state = await mountPage('components/SongList.vue', async () => { throw Error('write rejected') })
  try { await state.vm.action({ id: 1 }, 'favorite'); assert.equal(state.vm.feedback, 'write rejected'); assert.equal(state.vm.busy, false) } finally { state.close() }
})
test('daily hides a stale removed song without inventing metadata', async () => {
  let Failure, missing = false
  const state = await mountPage('pages/DailyPage.vue', async path => { if (missing && path.includes('/songs/')) throw new Failure('NOT_FOUND'); return path.includes('/songs/') ? { id: 1 } : { items: [{ song_id: 1, rank: 1, explanation: 'reason' }] } })
  try {
    Failure = state.ApiError; missing = true
    const result = await state.vm.hydrate({ items: [{ song_id: 2, rank: 8, explanation: 'original' }] })
    assert.equal(result.tracks.length, 0); assert.equal(result.daily.items[0].rank, 8)
  } finally { state.close() }
})
test('resource ignores out-of-order loads', async () => {
  const pending = []
  const state = await mountPage('pages/PlaylistsPage.vue', () => new Promise(resolve => pending.push(resolve)))
  try {
    const next = state.vm.load(); pending[1]([{ id: 2, name: 'new' }]); await next
    pending[0]([{ id: 1, name: 'old' }]); await flush()
    assert.equal(state.vm.data[0].id, 2)
  } finally { state.close() }
})
test('favorite-mode and playlist-member removal use DELETE without bodies', async () => {
  const state = await mountPage('components/SongList.vue', async () => undefined, '/favorites', { favoriteMode: true, playlistId: 9 })
  try {
    await state.vm.action({ id: 2 }, 'favorite'); await state.vm.action({ id: 2 }, 'remove')
    assert.deepEqual(state.calls.map(([path, init]) => [path, init.method, init.body]), [['/api/v1/favorites/2/', 'DELETE', undefined], ['/api/v1/playlists/9/songs/2/', 'DELETE', undefined]])
  } finally { state.close() }
})
test('duplicate submissions are blocked until server response', async () => {
  let accept
  const state = await mountPage('components/SongList.vue', () => new Promise(resolve => { accept = resolve }))
  try {
    const first = state.vm.action({ id: 1 }, 'favorite'); await state.vm.action({ id: 2 }, 'favorite')
    assert.equal(state.calls.length, 1); assert.equal(state.vm.busy, true); accept(); await first; assert.equal(state.vm.busy, false)
  } finally { state.close() }
})
