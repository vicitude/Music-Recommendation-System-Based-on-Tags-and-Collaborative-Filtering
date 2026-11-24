<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  catalogSize, cohortLabels, evaluationRows, fallbackUsers, formatPercent, groupSizes,
  interactionCount, metricLabels, report, reportText, routeWeights, userCount, weightedUsers,
  type Cohort, type Metric,
} from '../data/catalogEvaluation'

echarts.use([BarChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const cohort = ref<Cohort>('overall')
const metric = ref<Metric>('f1')
const rows = computed(() => evaluationRows(cohort.value))
const targetUsers = computed(() => rows.value[0].values.users)
const hasMetric = computed(() => rows.value.some(row => row.values[metric.value] !== null))
const groupsPanel = ref<HTMLElement | null>(null)
const weightsPanel = ref<HTMLElement | null>(null)
const methodsPanel = ref<HTMLElement | null>(null)
const charts: echarts.ECharts[] = []
let methodsChart: echarts.ECharts | undefined
const initial = report.methods.ADAPTIVE_4.overall
const reranked = report.methods.ADAPTIVE_4_RERANK.overall

function initChart(panel: HTMLElement) {
  const chart = echarts.init(panel)
  charts.push(chart)
  return chart
}

function updateMethods() {
  methodsChart?.setOption({
    tooltip: { trigger: 'item', valueFormatter: (value: unknown) => typeof value === 'number' ? formatPercent(value) : '—' },
    grid: { left: 8, right: 24, top: 8, bottom: 10, containLabel: true },
    xAxis: { type: 'value', min: 0, max: hasMetric.value ? undefined : 1, axisLabel: { formatter: formatPercent } },
    yAxis: { type: 'category', inverse: true, data: rows.value.map(row => row.label), axisLabel: { width: 114, overflow: 'break' } },
    series: [{ type: 'bar', data: rows.value.map(row => ({
      value: row.values[metric.value] ?? '-',
      itemStyle: { color: row.name === 'ADAPTIVE_4' ? '#d97855' : row.name === 'ADAPTIVE_4_RERANK' ? '#608d82' : '#9c7bb5' },
    })) }],
  }, { notMerge: true })
}

function resizeCharts() { charts.forEach(chart => chart.resize()) }

function exportReport() {
  const link = document.createElement('a')
  const url = URL.createObjectURL(new Blob([reportText], { type: 'application/json' }))
  link.href = url
  link.download = 'sim472-seed42-v3-report.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

onMounted(() => {
  if (groupsPanel.value) initChart(groupsPanel.value).setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 人（{d}%）' },
    legend: { bottom: 0 },
    series: [{ type: 'pie', radius: ['34%', '65%'], center: ['50%', '39%'], data: groupSizes, label: { formatter: '{c} 人' } }],
  })
  if (weightsPanel.value) initChart(weightsPanel.value).setOption({
    tooltip: { trigger: 'item', valueFormatter: (value: unknown) => typeof value === 'number' ? formatPercent(value) : '—' },
    grid: { left: 8, right: 18, top: 18, bottom: 48, containLabel: true },
    legend: { bottom: 0 },
    xAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: formatPercent } },
    yAxis: { type: 'category', data: ['平均权重'], show: false },
    series: routeWeights.map(({ name, value }) => ({ name, type: 'bar', stack: 'weight', barMaxWidth: 40, data: [value ?? '-'] })),
  })
  if (methodsPanel.value) methodsChart = initChart(methodsPanel.value)
  updateMethods()
  window.addEventListener('resize', resizeCharts)
})
watch([cohort, metric], updateMethods)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  charts.forEach(chart => chart.dispose())
})
</script>

<template>
  <section class="evaluation-page">
    <section class="hero-card evaluation-hero">
      <div>
        <p class="hero-kicker">实验看板 · 模拟数据</p>
        <h2>推荐算法实验看板</h2>
        <p class="hero-copy">基于 {{ catalogSize }} 首冻结曲库和 {{ userCount }} 名模拟用户的离线对照。用户行为和时间由程序生成，不代表真实用户效果。</p>
      </div>
      <div class="evaluation-hero-actions">
        <span class="simulation-badge">模拟实验 · 固定种子 {{ report.seed }}</span>
        <button type="button" class="primary-button" @click="exportReport">导出原始模拟报告</button>
      </div>
    </section>
    <section class="evaluation-summary">
      <article><strong>{{ userCount }}</strong><span>模拟用户</span></article>
      <article><strong>{{ catalogSize }}</strong><span>曲库歌曲</span></article>
      <article><strong>{{ interactionCount }}</strong><span>模拟交互</span></article>
      <article><strong>{{ targetUsers }}</strong><span>当前视图的测试目标用户</span></article>
    </section>
    <section class="evaluation-visual-grid">
      <article class="content-card visual-card">
        <h2>模拟用户分组</h2>
        <div ref="groupsPanel" class="echarts-panel" role="img" :aria-label="groupSizes.map(group => `${group.name}：${group.value} 人`).join('；')"></div>
        <p class="visual-caption">按每人在训练窗口中的正反馈条数分组。</p>
      </article>
      <article class="content-card visual-card">
        <h2>自适应融合平均权重</h2>
        <div ref="weightsPanel" class="echarts-panel" role="img" :aria-label="routeWeights.map(route => `${route.name}：${formatPercent(route.value)}`).join('；')"></div>
        <p class="visual-caption">按使用融合的 {{ weightedUsers }} 人等权平均，排除 {{ fallbackUsers }} 名仅使用热门兜底的用户。</p>
      </article>
    </section>
    <section class="content-card evaluation-card">
      <div class="section-heading">
        <div><p class="section-kicker">方法对比</p><h2>九种推荐方法 · {{ metricLabels[metric] }}</h2></div>
        <div class="evaluation-filters">
          <label>用户分组 <select v-model="cohort"><option v-for="(label, key) in cohortLabels" :key="key" :value="key">{{ label }}</option></select></label>
          <label>实验指标 <select v-model="metric"><option v-for="(label, key) in metricLabels" :key="key" :value="key">{{ label }}</option></select></label>
        </div>
      </div>
      <p v-if="!hasMetric" class="muted" role="status">该分组没有此指标的数据。</p>
      <div ref="methodsPanel" class="echarts-panel method-echarts" role="img" :aria-label="`${cohortLabels[cohort]} · ${metricLabels[metric]}方法对比柱状图`"></div>
    </section>
    <section class="content-card evaluation-card">
      <div class="section-heading">
        <h2>实验指标汇总 · {{ cohortLabels[cohort] }}</h2>
        <span class="muted">训练 {{ report.split.train }} · 验证 {{ report.split.validation }} · 测试 {{ report.split.test }}</span>
      </div>
      <div class="evaluation-table-wrap">
        <table class="evaluation-table catalog-evaluation-table">
          <thead><tr><th scope="col">方法</th><th v-for="(label, key) in metricLabels" :key="key" scope="col">{{ label }}</th></tr></thead>
          <tbody><tr v-for="row in rows" :key="row.name" :class="{ 'highlight-row': row.name === 'ADAPTIVE_4' }">
            <th scope="row">{{ row.label }}</th><td v-for="(_, key) in metricLabels" :key="key">{{ formatPercent(row.values[key]) }}</td>
          </tr></tbody>
        </table>
      </div>
      <p class="visual-caption">「—」表示没有可计算的数据，不等于 0%。零历史组没有训练历史，无法计算意外度和惊喜度。</p>
    </section>
    <section class="content-card evaluation-note">
      <h2>如何解读本次实验</h2>
      <p>全体用户重排前后，多样性从 {{ formatPercent(initial.diversity) }} 升至 {{ formatPercent(reranked.diversity) }}，覆盖率从 {{ formatPercent(initial.coverage) }} 升至 {{ formatPercent(reranked.coverage) }}；F1 从 {{ formatPercent(initial.f1) }} 降至 {{ formatPercent(reranked.f1) }}，排序质量从 {{ formatPercent(initial.ndcg) }} 降至 {{ formatPercent(reranked.ndcg) }}。这是本轮模拟里的取舍，不是普遍提升。</p>
      <p>自动标签作为带噪输入，不是人工真值；本轮关闭场景调权，验证集未用于调参。意外度基于与训练历史的标签差异，惊喜度同时考虑测试命中，两者都不代表用户的主观感受。</p>
    </section>
  </section>
</template>
