import { readFile } from 'node:fs/promises'
import ts from 'typescript'

let revision = 0
export async function loadModule(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const result = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } })
  return import('data:text/javascript;base64,' + Buffer.from(result.outputText + '\nexport const __testRevision = ' + revision++).toString('base64'))
}
