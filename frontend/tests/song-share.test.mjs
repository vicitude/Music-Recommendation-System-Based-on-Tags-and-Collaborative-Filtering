import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { mountPage, flush } from './page-harness.mjs'

async function fixture(clipboard, location = { origin: 'https://music.example', pathname: '/' }, request = async () => ({ id: 42, audio_url: '/private/audio.mp3' })) {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { location } })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { clipboard } })
  const state = await mountPage('pages/SongPage.vue', request, '/songs/5', {}, { user: null })
  let closed = false
  return { ...state, unmount() { if (!closed) { state.close(); closed = true } }, close() {
    this.unmount()
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow); else delete globalThis.window
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator); else delete globalThis.navigator
  } }
}

for (const [name, location, expected] of [
  ['root', { origin: 'https://music.example', pathname: '/' }, 'https://music.example/#/songs/42'],
  ['subdirectory', { origin: 'https://music.example:8443', pathname: '/music/app/index.html', search: '?password=secret', hash: '#/songs/5?audio_url=file:///private' }, 'https://music.example:8443/music/app/index.html#/songs/42'],
  ['local', { origin: 'http://127.0.0.1:5173', pathname: '/music/' }, 'http://127.0.0.1:5173/music/#/songs/42'],
]) {
  test('share URL uses actual origin/path and server ID: ' + name, async () => {
    const links = []
    const state = await fixture({ writeText: async link => links.push(link) }, location)
    try {
      await state.vm.copySongLink()
      assert.deepEqual(links, [expected])
      assert.equal(state.vm.shareFeedback, '已复制歌曲链接')
      assert.equal(state.vm.manualLink, '')
      assert.equal(state.vm.copying, false)
      assert.deepEqual(state.calls.map(call => call[0]), ['/api/v1/songs/5/'])
    } finally { state.close() }
  })
}

for (const failure of ['rejected', 'missing clipboard', 'missing writeText', 'synchronous failure']) {
  test('share offers manual copy without claiming success: ' + failure, async () => {
    const clipboard = failure === 'missing clipboard' ? undefined : failure === 'missing writeText' ? {} : { writeText: () => { if (failure === 'synchronous failure') throw Error('blocked'); return Promise.reject(Error('denied')) } }
    const state = await fixture(clipboard)
    try {
      await state.vm.copySongLink()
      assert.equal(state.vm.manualLink, 'https://music.example/#/songs/42')
      assert.match(state.vm.shareFeedback, /请选中下方链接并手动复制/)
      assert.doesNotMatch(state.vm.shareFeedback, /已复制/)
      assert.equal(state.vm.copying, false)
    } finally { state.close() }
  })
}

test('share ignores concurrent clicks, waits for success and supports retry', async () => {
  let resolveCopy, rejectCopy, count = 0
  const state = await fixture({ writeText: () => { count++; return new Promise((resolve, reject) => { resolveCopy = resolve; rejectCopy = reject }) } })
  try {
    const first = state.vm.copySongLink()
    await state.vm.copySongLink()
    assert.equal(count, 1); assert.equal(state.vm.copying, true)
    assert.equal(state.vm.shareFeedback, '')
    rejectCopy(Error('denied')); await first
    assert.ok(state.vm.manualLink)
    const retry = state.vm.copySongLink()
    assert.equal(state.vm.manualLink, ''); assert.equal(state.vm.shareFeedback, '')
    resolveCopy(); await retry
    assert.equal(count, 2); assert.equal(state.vm.shareFeedback, '已复制歌曲链接')
    assert.equal(state.vm.copying, false)
  } finally { state.close() }
})

for (const outcome of ['success', 'failure']) {
  test('late clipboard ' + outcome + ' cannot change unmounted page feedback', async () => {
    let resolveCopy, rejectCopy, count = 0
    const state = await fixture({ writeText: () => { count++; return new Promise((resolve, reject) => { resolveCopy = resolve; rejectCopy = reject }) } })
    try {
      const pending = state.vm.copySongLink()
      state.unmount()
      if (outcome === 'success') resolveCopy(); else rejectCopy(Error('denied'))
      await pending
      assert.equal(state.vm.shareFeedback, ''); assert.equal(state.vm.manualLink, '')
      assert.equal(state.notice.value, '')
      await state.vm.copySongLink(); assert.equal(count, 1)
    } finally { state.close() }
  })
}

test('share is unavailable during loading and after missing or unpublished detail failure', async () => {
  let rejectLoad, copied = 0
  const state = await fixture({ writeText: async () => { copied++ } }, undefined, () => new Promise((_resolve, reject) => { rejectLoad = reject }))
  try {
    assert.equal(state.vm.loading, true)
    await state.vm.copySongLink(); assert.equal(copied, 0)
    rejectLoad(Error('歌曲不存在或已下架')); await flush()
    assert.equal(state.vm.data, null); assert.ok(state.vm.error)
    await state.vm.copySongLink(); assert.equal(copied, 0)
    assert.equal(state.vm.shareFeedback, ''); assert.equal(state.vm.manualLink, '')
  } finally { state.close() }
})

test('STATIC share markup gates controls, provides selectable fallback and states deployment limits', async () => {
  const source = await readFile(new URL('../src/pages/SongPage.vue', import.meta.url), 'utf8')
  assert.match(source, /<template v-if="data && !loading && !error">[^]*class="song-share"/)
  assert.match(source, /:disabled="copying" @click="copySongLink"/)
  assert.match(source, /<label v-if="manualLink"[^]*<input :value="manualLink" type="text" readonly @focus=/)
  assert.ok(source.includes('本机地址仅在当前电脑可打开；其他人访问需部署可访问地址'))
  assert.match(source, /flex-wrap: wrap/)
  assert.doesNotMatch(source, /execCommand/)
})

test('STATIC share button stays independent of the mobile-hidden profile button', async () => {
  const source = await readFile(new URL('../src/pages/SongPage.vue', import.meta.url), 'utf8')
  const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8')
  const button = source.match(/<button[^>]*@click="copySongLink"[^>]*>/)?.[0]
  assert.ok(button)
  assert.match(button, /class="share-button"/)
  assert.doesNotMatch(button, /profile-button/)
  assert.match(styles, /@media \(max-width: 720px\)[^]*?\.profile-button\s*\{\s*display: none;/)
  assert.match(source, /\.share-button\s*\{[^}]*display: inline-block;[^}]*min-height: 44px;/)
  assert.doesNotMatch(styles, /\.share-button/)
})
