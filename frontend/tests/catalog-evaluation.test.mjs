import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const file = path => readFile(new URL(path, import.meta.url))
const bytes = await file('../src/data/sim472-seed42-v3-report.json')
const reportText = bytes.toString('utf8')
const report = JSON.parse(reportText)
const source = (await file('../src/data/catalogEvaluation.ts')).toString('utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const encoded = compiled.replace(/^import reportText from .*$/m, () => `const reportText = ${JSON.stringify(reportText)}`)
const data = await import(`data:text/javascript;base64,${Buffer.from(encoded).toString('base64')}`)
const groups = ['cold_start_0', 'light_1_9', 'regular_10_29', 'heavy_30_plus']
const methods = ['HOT', 'CONTENT', 'USER_CF', 'ITEM_CF', 'NCF', 'FIXED_4', 'ADAPTIVE_4', 'ADAPTIVE_4_RERANK', 'ADAPTIVE_NO_NCF']
const metrics = ['precision', 'recall', 'f1', 'hit', 'ndcg', 'coverage', 'diversity', 'novelty', 'unexpectedness', 'serendipity']

test('CT-ECH-005: bundled report preserves exact experiment bytes and structure', () => {
  assert.equal(createHash('sha256').update(bytes).digest('hex'), '06e1781c9efcb698c925f5b85aa4dcff065b17b59352a9b882b3878d0a35a2f0')
  assert.equal(data.reportText, reportText)
  assert.equal(report.origin, 'SIMULATED')
  assert.equal(report.seed, 42)
  assert.equal(report.configuration.k, 10)
  assert.equal(report.configuration.scene_enabled, false)
  assert.equal(report.configuration.tuned, false)
  assert.deepEqual(Object.keys(report.methods).sort(), [...methods].sort())
  assert.deepEqual(Object.keys(report.groups).sort(), [...groups].sort())
  assert.ok(groups.every(group => report.groups[group] === 50))
  assert.deepEqual([report.split.train, report.split.validation, report.split.test], [2800, 400, 800])
  assert.deepEqual([data.userCount, data.catalogSize, data.interactionCount], [200, 472, 4000])
})

test('PT-ECH-004: every method and metric keeps its original value on every view', () => {
  assert.deepEqual(Object.keys(data.cohortLabels), ['overall', ...groups])
  assert.deepEqual(Object.keys(data.metricLabels), metrics)
  for (const cohort of ['overall', ...groups]) {
    const rows = data.evaluationRows(cohort)
    assert.deepEqual(rows.map(row => row.name), methods)
    for (const { name, values } of rows) {
      assert.deepEqual(values, cohort === 'overall' ? report.methods[name].overall : report.methods[name].groups[cohort])
      assert.equal(values.users, cohort === 'overall' ? 200 : 50)
      for (const metric of metrics) {
        if (cohort === 'cold_start_0' && ['unexpectedness', 'serendipity'].includes(metric)) assert.equal(values[metric], null)
        else assert.ok(Number.isFinite(values[metric]) && values[metric] >= 0 && values[metric] <= 1)
      }
    }
  }
})

test('UT-ECH-006: missing values are not zero and fallback does not dilute route averages', () => {
  assert.equal(data.formatPercent(null), '—')
  assert.equal(data.formatPercent(0), '0.00%')
  assert.equal(data.formatPercent(report.methods.ADAPTIVE_4.overall.f1), '1.79%')
  assert.deepEqual([data.weightedUsers, data.fallbackUsers], [175, 25])
  const keys = ['content', 'user_cf', 'item_cf', 'ncf']
  const nonzero = Object.values(report.route_weights_by_user).filter(row => Object.values(row).some(value => value !== 0))
  for (const [index, key] of keys.entries()) {
    assert.ok(Math.abs(data.routeWeights[index].value - nonzero.reduce((sum, row) => sum + row[key] / 175, 0)) < 1e-12)
  }
  assert.ok(Math.abs(data.routeWeights.reduce((sum, route) => sum + route.value, 0) - 1) < 1e-12)
})
