import type { BehaviorEvent, Song } from './api/types'

export type AudioPort = { src: string; currentTime: number; duration: number; paused: boolean; seeking: boolean; play(): Promise<void>; pause(): void; load(): void }
export type PlaybackMode = 'list' | 'single' | 'order' | 'random'
type Session = { song: Song; id: string; listened: number; since: number | null; played: boolean; terminal: boolean; failed: boolean; cancelled: boolean; started: Promise<boolean> | null }
export type PlaybackDeps = { now: () => number; uuid: () => string; send: (event: BehaviorEvent) => Promise<unknown>; delay: (ms: number) => Promise<void>; createUrl: (file: File) => string; revokeUrl: (url: string) => void; notify: (text: string) => void; changed: () => void }

export class PlaybackController {
  mode: PlaybackMode = 'list'
  queue: Song[] = []
  queueIndex = -1
  session: Session | null = null
  localUrl = ''
  title = '还没有播放音乐'
  artist = '选择一首歌，或打开本地音频'
  private switching = false
  private localPending = false
  private generation = 0
  private sessions = new Set<Session>()
  constructor(readonly audio: AudioPort, readonly deps: PlaybackDeps) {}
  private createSession(song: Song): Session {
    const state: Session = { song, id: this.deps.uuid(), listened: 0, since: null, played: false, terminal: false, failed: false, cancelled: false, started: null }
    this.sessions.add(state)
    return state
  }
  freeze(): void { const state = this.session; if (state?.since != null) { state.listened += Math.max(0, this.deps.now() - state.since); state.since = null } this.deps.changed() }
  listenedMs(): number { const state = this.session; return state ? Math.floor(state.listened + (state.since == null ? 0 : Math.max(0, this.deps.now() - state.since))) : 0 }
  private async send(state: Session, event: BehaviorEvent): Promise<boolean> {
    for (let attempt = 0; attempt < 4; attempt++) {
      if (state.cancelled) return false
      try { await this.deps.send(event); return !state.cancelled }
      catch (error) {
        if (state.cancelled) return false
        const failure = error as { body?: { error_code?: string }; message?: string }
        if (failure.body?.error_code !== 'NETWORK_ERROR' || attempt === 3) { this.deps.notify(failure.message ?? '行为未记录，不计入有效收听'); return false }
        await this.deps.delay(1000 * 2 ** attempt)
      }
    }
    return false
  }
  playing(): void {
    let state = this.session
    if (state?.terminal && !state.failed && !state.cancelled) { state = this.createSession(state.song); this.session = state }
    if (state && !state.terminal && !state.failed && !state.cancelled) {
      if (state.since == null) state.since = this.deps.now()
      if (!state.played) {
        state.played = true
        state.started = this.send(state, { event_id: this.deps.uuid(), song_id: state.song.id, listening_session_id: state.id, kind: 'PLAY', position_ms: 0, listened_ms: 0 }).then(ok => { if (!ok) state.failed = true; return ok })
      }
    }
    this.deps.changed()
  }
  private async terminate(mediaFailed = false): Promise<void> {
    this.freeze()
    const state = this.session
    if (!state || state.terminal) return
    state.terminal = true
    try {
      if (!state.played || state.failed || mediaFailed || state.cancelled) return
      const position = Math.max(0, Math.min(state.song.duration_ms, Math.floor(this.audio.currentTime * 1000) || 0))
      const listened = Math.min(86400000, Math.floor(state.listened))
      const threshold = Math.ceil(state.song.duration_ms * 0.8)
      const event: BehaviorEvent = { event_id: this.deps.uuid(), song_id: state.song.id, listening_session_id: state.id, kind: position >= threshold && listened >= threshold ? 'COMPLETE' : 'SKIP', position_ms: position, listened_ms: listened }
      if (state.started && await state.started) await this.send(state, event)
    } finally { this.sessions.delete(state) }
  }
  private clearMedia(): void {
    this.audio.pause()
    this.session = null
    if (this.localUrl) { this.deps.revokeUrl(this.localUrl); this.localUrl = '' }
    this.audio.src = ''
    this.audio.load()
    this.title = '还没有播放音乐'
    this.artist = '选择一首歌，或打开本地音频'
    this.deps.changed()
  }
  setMode(mode: PlaybackMode): void {
    if (!['list', 'single', 'order', 'random'].includes(mode)) return
    this.mode = mode; this.deps.changed()
  }
  async playSong(song: Song): Promise<void> { await this.playQueue([song], 0) }
  async playQueue(songs: Song[], index: number): Promise<void> {
    if (this.switching) return
    const selected = songs[index]
    if (!selected || !this.playable(selected)) { this.deps.notify('这首歌暂不可播放'); return }
    const ids = new Set<number>()
    this.queue = songs.filter(song => this.playable(song) && !ids.has(song.id) && !!ids.add(song.id)).map(song => ({ ...song }))
    this.queueIndex = this.queue.findIndex(song => song.id === selected.id)
    await this.startSong(this.queue[this.queueIndex]!)
  }
  private playable(song: Song): boolean { return song.playable && !!song.stream_url && /^\/api\/v1\/songs\/\d+\/stream\/$/.test(song.stream_url) }
  private nextIndex(direction: number, natural = false): number {
    if (!this.queue.length || this.queueIndex < 0) return -1
    if (natural && this.mode === 'single') return this.queueIndex
    if (this.mode === 'random') {
      if (this.queue.length === 1) return 0
      return (this.queueIndex + 1 + Math.floor(Math.random() * (this.queue.length - 1))) % this.queue.length
    }
    const index = this.queueIndex + direction
    if (this.mode === 'order' && (index < 0 || index >= this.queue.length)) return -1
    return (index + this.queue.length) % this.queue.length
  }
  async skip(direction: number): Promise<void> {
    if (this.switching || this.localUrl) return
    const index = this.nextIndex(direction)
    if (index < 0) return
    this.queueIndex = index; await this.startSong(this.queue[index]!)
  }
  private async startSong(song: Song): Promise<void> {
    if (this.switching) return
    if (!song.playable || !song.stream_url || !/^\/api\/v1\/songs\/\d+\/stream\/$/.test(song.stream_url)) { this.deps.notify('这首歌暂不可播放'); return }
    this.switching = true
    const generation = ++this.generation
    try {
      this.pause(); await this.terminate()
      if (generation !== this.generation) return
      this.clearMedia(); this.session = this.createSession(song); this.title = song.title; this.artist = song.artist; this.audio.src = song.stream_url; this.audio.load()
      try { await this.audio.play() } catch { if (generation === this.generation) this.deps.notify('浏览器未允许自动播放，请点击播放器的播放按钮') }
    } finally { this.switching = false; this.deps.changed() }
  }
  async selectLocal(file: File): Promise<void> {
    if (this.switching) return
    this.queue = []; this.queueIndex = -1
    this.switching = true
    this.localPending = true
    const generation = ++this.generation
    try {
      this.pause(); await this.terminate()
      if (generation !== this.generation) return
      this.clearMedia(); this.localUrl = this.deps.createUrl(file); this.title = file.name; this.artist = '本地文件 · 不上传、不记录推荐行为'; this.audio.src = this.localUrl; this.audio.load()
      try { await this.audio.play() } catch { if (generation === this.generation) this.deps.notify('请点击播放按钮播放本地文件') }
    } finally { this.switching = false; this.localPending = false; this.deps.changed() }
  }
  pause(): void { this.freeze(); this.audio.pause() }
  seek(positionMs: number): void {
    if (!Number.isFinite(positionMs)) return
    this.freeze()
    const limit = this.session?.song.duration_ms ?? (Number.isFinite(this.audio.duration) ? this.audio.duration * 1000 : Infinity)
    this.audio.currentTime = Math.min(limit, Math.max(0, positionMs)) / 1000
  }
  async ended(): Promise<void> {
    if (this.switching) return
    if (this.localUrl) {
      if (this.mode === 'list' || this.mode === 'single') {
        this.audio.currentTime = 0
        try { await this.audio.play() } catch { this.deps.notify('请点击播放按钮继续播放本地文件') }
      }
      return
    }
    const state = this.session, generation = this.generation
    if (!state || state.terminal || state.failed || state.cancelled) return
    await this.terminate()
    if (generation !== this.generation || this.session !== state || this.switching) return
    const index = this.nextIndex(1, true)
    if (index >= 0) { this.queueIndex = index; await this.startSong(this.queue[index]!) }
    this.deps.changed()
  }
  mediaError(): void {
    if (!this.session && !this.localUrl) return
    this.freeze()
    if (this.session) { this.session.failed = true; this.session.terminal = true; this.sessions.delete(this.session) }
    this.deps.notify('音频加载失败，未补记听完行为'); this.deps.changed()
  }
  async stop(): Promise<void> { const generation = ++this.generation; this.queue = []; this.queueIndex = -1; this.pause(); await this.terminate(); if (generation === this.generation) this.clearMedia() }
  cancelOnline(): void {
    this.generation++
    this.queue = []; this.queueIndex = -1
    for (const state of this.sessions) state.cancelled = true
    this.sessions.clear()
    if (this.session) { this.pause(); this.clearMedia() }
  }
  leaveLocal(): void { if (this.localUrl) { this.generation++; this.clearMedia() } else if (this.localPending) this.generation++ }
}
