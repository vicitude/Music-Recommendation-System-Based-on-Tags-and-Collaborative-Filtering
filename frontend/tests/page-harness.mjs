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
export async function mountPage(filename, request, path = '/daily', props = {}) {
  const id = ++serial, calls = [], routes = []
  const state = { calls, routes, user: ref({ id: 1, onboarding_completed: false }), notice: ref(''), async request(...args) { calls.push(args); return request(...args) }, currentPath: () => path }
  globalThis.__pageMocks.set(id, state)
  const access = 'globalThis.__pageMocks.get(' + id + ')'
  const client = asUrl('export class ApiError extends Error { constructor(code, retryAfter=0) { super(code); this.body={error_code:code}; this.retryAfter=retryAfter } }; export const request=(...args)=>' + access + '.request(...args)')
  const session = asUrl('export const user=' + access + '.user; export const notice=' + access + '.notice; export const message=error=>error.message || "failure"')
  const router = asUrl('export const currentPath=()=>' + access + '.currentPath(); export const navigate=path=>' + access + '.routes.push(path)')
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
  return { ...state, vm: proxy.$.setupState, ApiError: (await import(client)).ApiError, close() { app.unmount(); globalThis.__pageMocks.delete(id) } }
}
