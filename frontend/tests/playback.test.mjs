import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule } from './load-module.mjs'
const { PlaybackController } = await loadModule('../src/playback.ts')
const song = { id: 1, title: 'Track', artist: 'Artist', duration_ms: 100000, playable: true, stream_url: '/api/v1/songs/1/stream/' }
const network = () => Object.assign(new Error('offline'), { body: { error_code: 'NETWORK_ERROR' } })
const settle = () => new Promise(resolve => setImmediate(resolve))
function fixture(options = {}) {
  let clock = 0, serial = 0
  const events = [], delays = [], notices = [], revoked = []
  const audio = { src: '', currentTime: 0, duration: 100, paused: true, seeking: false, async play() { if (options.rejectPlay) throw Error('blocked'); this.paused = false }, pause() { this.paused = true }, load() { this.currentTime = 0 } }
  const controller = new PlaybackController(audio, { now: () => clock, uuid: () => 'uuid-' + ++serial, send: async event => { events.push(event); if (options.send) await options.send(event, events.length) }, delay: async ms => { delays.push(ms); if (options.delay) await options.delay(ms) }, createUrl: () => 'blob:local', revokeUrl: url => revoked.push(url), notify: text => notices.push(text), changed: () => {} })
  return { controller, audio, events, delays, notices, revoked, advance(ms) { clock += ms } }
}
test('PLAY follows playing only, once across pause/resume', async () => {
  const state = fixture(); await state.controller.playSong(song)
  assert.equal(state.events.length, 0)
  state.controller.playing(); state.advance(10000); state.controller.pause(); state.advance(30000)
  assert.equal(state.controller.listenedMs(), 10000)
  state.controller.playing(); state.advance(5000)
  assert.equal(state.controller.listenedMs(), 15000)
  assert.deepEqual(state.events.map(event => event.kind), ['PLAY'])
})
test('waiting and seeking freeze time; seek is clamped', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(10000)
  state.controller.freeze(); state.advance(50000); state.controller.seek(999999)
  assert.equal(state.audio.currentTime, 100); assert.equal(state.controller.listenedMs(), 10000)
  state.controller.seek(-100); assert.equal(state.audio.currentTime, 0)
  state.controller.seek(NaN); assert.equal(state.audio.currentTime, 0)
})
test('80 percent position and elapsed time yield one COMPLETE', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(80000); state.audio.currentTime = 80
  await state.controller.ended(); await state.controller.ended()
  assert.deepEqual(state.events.map(event => event.kind), ['PLAY', 'COMPLETE'])
  assert.equal(state.events[1].listened_ms, 80000)
})
test('seeking to the end cannot fabricate completion', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(1000); state.controller.seek(100000); await state.controller.ended()
  assert.equal(state.events[1].kind, 'SKIP'); assert.equal(state.events[1].listened_ms, 1000)
})
test('long listen with low position is SKIP', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(85000); state.audio.currentTime = 20; await state.controller.stop()
  assert.equal(state.events[1].kind, 'SKIP')
})
test('song switch closes old session before new PLAY', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(5000); state.audio.currentTime = 5
  await state.controller.playSong({ ...song, id: 2, stream_url: '/api/v1/songs/2/stream/' }); state.controller.playing()
  assert.deepEqual(state.events.map(event => [event.song_id, event.kind]), [[1, 'PLAY'], [1, 'SKIP'], [2, 'PLAY']])
  assert.notEqual(state.events[0].listening_session_id, state.events[2].listening_session_id)
})
test('network retries reuse exact event at 1/2/4 seconds', async () => {
  const state = fixture({ send: (_event, count) => { if (count <= 3) throw network() } }); await state.controller.playSong(song); state.controller.playing(); await settle()
  assert.deepEqual(state.delays, [1000, 2000, 4000]); assert.equal(state.events.length, 4)
  assert.ok(state.events.every(event => event === state.events[0]))
})
test('failed PLAY is bounded and prevents terminal event', async () => {
  const state = fixture({ send: () => { throw network() } }); await state.controller.playSong(song); state.controller.playing(); state.advance(100000); await state.controller.ended()
  assert.equal(state.events.length, 4); assert.ok(state.events.every(event => event.kind === 'PLAY')); assert.equal(state.notices.length, 1)
})
test('validation errors are not retried', async () => {
  const state = fixture({ send: () => { throw Object.assign(new Error('invalid'), { body: { error_code: 'VALIDATION_ERROR' } }) } }); await state.controller.playSong(song); state.controller.playing(); await state.controller.stop()
  assert.equal(state.events.length, 1); assert.deepEqual(state.delays, [])
})
test('terminal waits for PLAY acceptance', async () => {
  let accept
  const state = fixture({ send: event => event.kind === 'PLAY' ? new Promise(resolve => { accept = resolve }) : undefined })
  await state.controller.playSong(song); state.controller.playing(); state.advance(1000)
  const stopped = state.controller.stop(); await settle(); assert.equal(state.events.length, 1)
  accept(); await stopped; assert.equal(state.events[1].kind, 'SKIP')
})
test('logout cancels pending retries and stale switch', async () => {
  let release
  const state = fixture({ send: () => { throw network() }, delay: () => new Promise(resolve => { release = resolve }) })
  await state.controller.playSong(song); state.controller.playing(); await settle()
  const switching = state.controller.playSong({ ...song, id: 2, stream_url: '/api/v1/songs/2/stream/' })
  state.controller.cancelOnline(); release(); await switching
  assert.equal(state.events.length, 1); assert.equal(state.controller.session, null); assert.equal(state.audio.src, '')
})
test('native replay creates another listening session', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(100000); state.audio.currentTime = 100; await state.controller.ended()
  state.audio.currentTime = 0; state.controller.playing()
  assert.deepEqual(state.events.map(event => event.kind), ['PLAY', 'COMPLETE', 'PLAY'])
  assert.notEqual(state.events[0].listening_session_id, state.events[2].listening_session_id)
})
test('local files send no events and release URL on leaving', async () => {
  const state = fixture(); await state.controller.selectLocal({ name: 'private.wav' }); state.controller.playing(); state.advance(100000); await state.controller.ended(); state.controller.leaveLocal()
  assert.equal(state.events.length, 0); assert.deepEqual(state.revoked, ['blob:local']); assert.equal(state.audio.src, '')
})
test('local to online revokes local URL', async () => {
  const state = fixture(); await state.controller.selectLocal({ name: 'private.wav' }); await state.controller.playSong(song)
  assert.deepEqual(state.revoked, ['blob:local']); assert.equal(state.audio.src, song.stream_url)
})
test('autoplay rejection sends no PLAY', async () => {
  const state = fixture({ rejectPlay: true }); await state.controller.playSong(song); await state.controller.stop()
  assert.equal(state.events.length, 0); assert.equal(state.notices.length, 1)
})
test('media error never manufactures COMPLETE', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); state.advance(100000); state.audio.currentTime = 100; state.controller.mediaError(); await state.controller.ended()
  assert.deepEqual(state.events.map(event => event.kind), ['PLAY'])
})
test('unavailable and external media are rejected', async () => {
  const state = fixture(); await state.controller.playSong({ ...song, playable: false }); await state.controller.playSong({ ...song, stream_url: 'https://example.com/a.mp3' })
  assert.equal(state.audio.src, ''); assert.equal(state.events.length, 0); assert.equal(state.notices.length, 2)
})
test('navigation leaves online session and audio intact', async () => {
  const state = fixture(); await state.controller.playSong(song); state.controller.playing(); const session = state.controller.session
  state.controller.leaveLocal()
  assert.equal(state.controller.session, session); assert.equal(state.audio.src, song.stream_url)
})
test('navigation cancels a pending local selection after online termination', async () => {
  let accept
  const state = fixture({ send: event => event.kind === 'PLAY' ? new Promise(resolve => { accept = resolve }) : undefined })
  await state.controller.playSong(song); state.controller.playing()
  const selection = state.controller.selectLocal({ name: 'local.wav' }); state.controller.leaveLocal(); accept(); await selection
  assert.equal(state.controller.localUrl, ''); assert.notEqual(state.audio.src, 'blob:local')
})
