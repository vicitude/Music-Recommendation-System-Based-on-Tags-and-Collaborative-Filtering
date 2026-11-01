import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { transform } from 'esbuild'

test('development proxy forwards admin assets and fixes the trusted frontend port', async () => {
  const source = await readFile(new URL('../vite.config.ts', import.meta.url), 'utf8')
  const compiled = await transform(source, { loader: 'ts', format: 'esm' })
  const program = compiled.code.replace(/import .* from "vite";/, 'const defineConfig = config => config;').replace(/import .* from "@vitejs\/plugin-vue";/, 'const vue = () => ({});')
  const config = (await import('data:text/javascript;base64,' + Buffer.from(program).toString('base64'))).default
  assert.equal(config.server.host, '127.0.0.1')
  assert.equal(config.server.port, 5173)
  assert.equal(config.server.strictPort, true)
  for (const path of ['/api', '/admin', '/static']) assert.equal(config.server.proxy[path], 'http://127.0.0.1:8000')
})
