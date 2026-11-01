export type RouteName = 'login' | 'register' | 'onboarding' | 'discover' | 'song' | 'favorites' | 'playlists' | 'playlist' | 'daily' | 'not-found'

const routes: Record<string, RouteName> = {
  '/login': 'login',
  '/register': 'register',
  '/onboarding': 'onboarding',
  '/discover': 'discover',
  '/favorites': 'favorites',
  '/playlists': 'playlists',
  '/daily': 'daily',
}

export function currentPath(): string {
  return window.location.hash.slice(1).split('?')[0] || '/daily'
}

export function routeName(): RouteName {
  const path = currentPath()
  if (routes[path]) return routes[path]
  if (/^\/songs\/\d+$/.test(path)) return 'song'
  if (/^\/playlists\/\d+$/.test(path)) return 'playlist'
  return 'not-found'
}

export function navigate(path: string): void {
  window.location.hash = path
}
