import type reportShape from './sim472-seed42-v3-report.json'
import reportText from './sim472-seed42-v3-report.json?raw'

export { reportText }
export const report = JSON.parse(reportText) as typeof reportShape
export const catalogSize = 472

export const cohortLabels = {
  overall: '全体用户', cold_start_0: '零历史（0 条）', light_1_9: '轻度（1–9 条）',
  regular_10_29: '常规（10–29 条）', heavy_30_plus: '重度（30 条及以上）',
}
export const methodLabels = {
  HOT: '热门推荐', CONTENT: '内容推荐', USER_CF: '用户协同', ITEM_CF: '歌曲协同', NCF: '神经协同（NCF）',
  FIXED_4: '固定融合', ADAPTIVE_4: '自适应融合', ADAPTIVE_4_RERANK: '自适应融合＋重排', ADAPTIVE_NO_NCF: '自适应融合（无 NCF）',
}
export const metricLabels = {
  precision: '精确率@10', recall: '召回率@10', f1: 'F1@10', hit: '命中率@10', ndcg: '排序质量 NDCG@10',
  coverage: '覆盖率', diversity: '多样性', novelty: '新颖性', unexpectedness: '意外度', serendipity: '惊喜度',
}
export const routeLabels = { content: '标签内容', user_cf: '用户协同', item_cf: '歌曲协同', ncf: '神经协同' }

export type Cohort = keyof typeof cohortLabels
export type Method = keyof typeof methodLabels
export type Metric = keyof typeof metricLabels
type Route = keyof typeof routeLabels
type Metrics = Record<Metric, number | null> & { users: number }

export function evaluationRows(cohort: Cohort): Array<{ name: Method; label: string; values: Metrics }> {
  return (Object.keys(methodLabels) as Method[]).map(name => {
    const method = report.methods[name]
    return { name, label: methodLabels[name], values: cohort === 'overall' ? method.overall : method.groups[cohort] }
  })
}

export function formatPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`
}

export const groupSizes = (Object.entries(report.groups) as [Exclude<Cohort, 'overall'>, number][])
  .map(([key, value]) => ({ key, name: cohortLabels[key], value }))
  .sort((a, b) => Object.keys(cohortLabels).indexOf(a.key) - Object.keys(cohortLabels).indexOf(b.key))
export const userCount = groupSizes.reduce((sum, group) => sum + group.value, 0)
export const interactionCount = report.split.train + report.split.validation + report.split.test

const routeKeys = Object.keys(routeLabels) as Route[]
const weightRows = Object.values(report.route_weights_by_user)
const personalized = weightRows.filter(row => routeKeys.some(key => row[key] > 0))
export const weightedUsers = personalized.length
export const fallbackUsers = weightRows.length - weightedUsers
export const routeWeights = routeKeys.map(key => ({
  name: routeLabels[key],
  value: weightedUsers ? personalized.reduce((sum, row) => sum + row[key], 0) / weightedUsers : null,
}))
