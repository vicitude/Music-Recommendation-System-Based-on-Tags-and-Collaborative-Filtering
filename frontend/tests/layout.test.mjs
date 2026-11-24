import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import postcss from 'postcss'
import { parse } from '@vue/compiler-sfc'

const css = postcss.parse(await readFile(new URL('../src/styles.css', import.meta.url), 'utf8'))
function value(selector, property, media) {
  let result
  css.walkRules(selector, rule => {
    const condition = rule.parent.type === 'atrule' ? rule.parent.params : undefined
    if (condition !== media) return
    rule.walkDecls(property, declaration => { result = declaration.value })
  })
  return result
}

test('LAYOUT-001 desktop uses a wider compact canvas without shrinking song text', () => {
  assert.equal(value('.page-container', 'width'), 'min(1440px, calc(100% - 64px))')
  assert.equal(value('.page-container', 'padding'), '24px 0 112px')
  assert.equal(value('.topbar', 'min-height'), '64px')
  assert.equal(value('h1', 'font-size'), '32px')
  assert.equal(value('.daily-hero', 'padding'), '20px 24px')
  assert.equal(value('.daily-results', 'margin-top'), '16px')
  assert.equal(value('.song-row', 'padding'), '12px 0')
  assert.equal(value('.song-title', 'font-size'), '16px')
  assert.equal(value('.song-row', 'height'), undefined)
  assert.equal(value('.song-info .explanation', 'max-height'), undefined)
  assert.equal(value('.auth-card', 'max-width'), '480px')
  assert.equal(value('.playlist-tile', 'min-height'), '136px')
  assert.equal(value('.player-bar', 'padding'), '12px 32px')
})

test('LAYOUT-002 mobile retains touch targets, wrapping and bottom player clearance', () => {
  const mobile = '(max-width: 760px)'
  assert.equal(value('.page-container', 'width', mobile), '92vw')
  assert.equal(value('.page-container', 'padding-bottom', mobile), '220px')
  assert.equal(value('.daily-hero', 'flex-direction', mobile), 'column')
  assert.equal(value('.song-row', 'flex-wrap', mobile), 'wrap')
  assert.equal(value('.player-bar audio', 'width', mobile), '100%')
  assert.equal(value('button, .tag-chip, .local-button', 'min-height', mobile), '44px')
  assert.equal(value('.song-row', 'flex-wrap', '(min-width: 761px) and (max-width: 1023px)'), 'wrap')
})

test('LAYOUT-003 daily intro removes oversized decoration and keeps accessible optional details', async () => {
  const source = await readFile(new URL('../src/pages/DailyPage.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(source)
  assert.deepEqual(errors, [])
  const template = descriptor.template.content
  assert.doesNotMatch(template, /hero-orbit/)
  assert.match(template, /<h2>为你精选<\/h2>/)
  assert.match(template, /<details class="recommendation-help"><summary>推荐如何产生？<\/summary>/)
  assert.doesNotMatch(template, /<details[^>]*\sopen(?:\s|>)/)
  assert.match(template, /调整兴趣标签/)
  assert.match(template, /data.daily.revision/)
  assert.match(template, /<SongList :songs="data.tracks"/)
})

test('REC-FAV-001 daily list never subscribes to collection reload events', async () => {
  const source = await readFile(new URL('../src/pages/DailyPage.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const list = descriptor.template.content.match(/<SongList\b[^>]*\/>/)[0]
  assert.doesNotMatch(list, /@changed|favorite-mode/)
})

test('PLAYER-MODE-003 list passes queue and global player exposes four modes with one audio', async () => {
  const list = await readFile(new URL('../src/components/SongList.vue', import.meta.url), 'utf8')
  const player = await readFile(new URL('../src/components/AudioPlayer.vue', import.meta.url), 'utf8')
  const app = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(list, /playQueue\(songs, index\)/)
  assert.match(app, /playQueue: async \(songs, index\)/)
  assert.equal((player.match(/<audio\b/g) || []).length, 1)
  for (const mode of ['list', 'single', 'order', 'random']) assert.ok(player.includes('value="' + mode + '"'))
  assert.match(player, /aria-label="播放模式"/)
  assert.match(player, /controller\?\.skip\(-1\)/)
  assert.match(player, /controller\?\.skip\(1\)/)
})
