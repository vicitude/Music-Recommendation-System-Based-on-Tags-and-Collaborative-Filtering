import type { InjectionKey } from 'vue'
import type { Song } from './api/types'

export type PlayerHandle = {
  playSong: (song: Song) => Promise<void>
  playQueue: (songs: Song[], index: number) => Promise<void>
  selectLocal: (file: File) => Promise<void>
  pause: () => void
  seek: (positionMs: number) => void
  stop: () => Promise<void>
  leaveLocal: () => void
}

export const playerKey: InjectionKey<PlayerHandle> = Symbol('single-player')
