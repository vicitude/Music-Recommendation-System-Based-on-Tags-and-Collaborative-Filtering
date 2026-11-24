import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, nextTick, ref } from 'vue'

const require = createRequire(import.meta.url)
const vueUrl = pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href
const asUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
let serial = 0
globalThis.__pageMocks = new Map()
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null, patchProp() {} })
export const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }
export async function mountPage(filename, request, path = '/daily', props = {}, options = {}) {
  const id = ++serial, calls = [], routes = []
  const state = { calls, routes, user: ref(options.user === undefined ? { id: 1, onboarding_completed: false } : options.user), ready: ref(options.ready ?? false), notice: ref(''), async request(...args) { if (filename === 'components/SongList.vue' && args[0].startsWith('/api/v1/favorites/?') && !options.loadFavorites) return { count: 0, page: 1, page_size: 100, results: [] }; calls.push(args); return request(...args) }, currentPath: () => path }
  globalThis.__pageMocks.set(id, state)
  const access = 'globalThis.__pageMocks.get(' + id + ')'
  const client = asUrl('export class ApiError extends Error { constructor(body, retryAfter=0) { const resolved=typeof body === "string" ? {error_code:body,message:body,details:[],request_id:""} : body; super(resolved.message); this.name="ApiError"; this.body=resolved; this.retryAfter=retryAfter } }; export const configureClient=()=>{}; export const request=(...args)=>' + access + '.request(...args)')
  const session = asUrl('export const initialize=async()=>{}; export const ready=' + access + '.ready; export const user=' + access + '.user; export const notice=' + access + '.notice; export const message=error=>error.message || "failure"')
  const router = asUrl('export const routeName=()=>{const path=' + access + '.currentPath(); return /^\\/users\\/\\d+$/.test(path) ? "user" : /^\\/users\\/\\d+\\/(following|followers)$/.test(path) ? "user-connections" : path.slice(1)}; export const currentPath=()=>' + access + '.currentPath(); export const navigate=path=>' + access + '.routes.push(path)')
  const player = asUrl('export const playerKey=Symbol("test-player")')
  const stub = asUrl('export default {}')
  const mapImport = source => source === 'vue' ? vueUrl : source.endsWith('/api/client') ? client : source.endsWith('/session') ? session : source.endsWith('/router') ? router : source.endsWith('/player-context') ? player : source.endsWith('.vue') ? stub : null
  function transform(source, extra = {}) {
    return ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace(/from (["'])([^"']+)\1/g, (match, _quote, name) => { const url = extra[name] || mapImport(name); if (!url) throw Error('Unmapped import: ' + name); return 'from ' + JSON.stringify(url) })
  }
  const resource = asUrl(transform(await readFile(new URL('../src/use-resource.ts', import.meta.url), 'utf8')) + '\nexport const testInstance = ' + id)
  const source = await readFile(new URL('../src/' + filename, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'page-test-' + id })
  const component = (await import(asUrl(transform(compiled.content, { '../use-resource': resource })))).default
  component.render = () => null
  const playerMock = { playSong: async () => {} }
  const app = renderer.createApp(component, filename.startsWith('components/') ? { songs: [{ id: 1, title: 'track' }], ...props } : props)
  app.provide((await import(player)).playerKey, playerMock)
  const proxy = app.mount({})
  await flush()
  return { ...state, vm: proxy.$.setupState, ApiError: (await import(client)).ApiError, async setProps(props) { Object.assign(proxy.$.props, props); await flush() }, close() { app.unmount(); globalThis.__pageMocks.delete(id) } }
}
