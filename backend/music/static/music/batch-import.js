(() => {
  const form = document.querySelector('[data-analysis-form]');
  if (!form) return;
  const choices = [...form.querySelectorAll('[name="model_selected"]')];
  const selectAll = form.querySelector('[data-select-all]');
  const count = form.querySelector('[data-selection-count]');
  const start = form.querySelector('[data-start]');
  const stop = form.querySelector('[data-stop]');
  const progress = form.querySelector('progress');
  const status = form.querySelector('[data-progress-status]');
  let running = false;
  let stopping = false;
  function updateCount() {
    const selected = choices.filter(choice => choice.checked).length;
    count.textContent = `已选 ${selected} / ${choices.length} 首`;
    selectAll.checked = choices.length > 0 && selected === choices.length;
    selectAll.indeterminate = selected > 0 && selected < choices.length;
    start.disabled = running || selected === 0;
  }
  selectAll.addEventListener('change', () => {
    choices.forEach(choice => { choice.checked = selectAll.checked; });
    updateCount();
  });
  form.querySelector('[data-clear]').addEventListener('click', () => {
    choices.forEach(choice => { choice.checked = false; });
    updateCount();
  });
  choices.forEach(choice => choice.addEventListener('change', updateCount));
  stop.hidden = true;
  stop.addEventListener('click', () => {
    stopping = true;
    stop.disabled = true;
    status.textContent = '将在当前组完成后停止，已保存的结果不会丢失。';
  });
  function render(row, analysis) {
    row.querySelector('[data-row-status]').textContent = analysis.status === 'CANDIDATES' ? '标签已生成（尚未入库）' : `未完成：${(analysis.reasons || []).join('；') || analysis.status}`;
    ['STYLE', 'MOOD', 'SCENE'].forEach(kind => {
      const cell = row.querySelector(`[data-kind="${kind}"]`);
      cell.replaceChildren();
      (analysis.candidates || []).filter(tag => tag.kind === kind).forEach(tag => {
        const badge = document.createElement('span');
        badge.className = 'batch-tag';
        badge.textContent = tag.name + (tag.evidence_level === 'LOW_FALLBACK' ? ' ★低把握' : '') + (kind === 'SCENE' ? '（建议）' : '');
        cell.append(badge);
      });
    });
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (running) return;
    const selected = choices.filter(choice => choice.checked);
    if (!selected.length) return;
    running = true;
    stopping = false;
    let completed = 0;
    let failed = 0;
    const controls = [...form.querySelectorAll('input, button')];
    controls.forEach(control => { control.disabled = true; });
    stop.hidden = false;
    stop.disabled = false;
    document.querySelectorAll('[data-other-action]').forEach(control => { control.disabled = true; });
    progress.hidden = false;
    progress.max = selected.length;
    progress.value = 0;
    try {
      for (let offset = 0; offset < selected.length && !stopping; offset += 5) {
        const chunk = selected.slice(offset, offset + 5);
        chunk.forEach(choice => { choice.closest('tr').querySelector('[data-row-status]').textContent = '正在打标签…'; });
        status.textContent = `正在处理 ${offset + 1}–${offset + chunk.length} / ${selected.length} 首，请保持页面打开。`;
        const body = new URLSearchParams();
        body.set('csrfmiddlewaretoken', form.querySelector('[name="csrfmiddlewaretoken"]').value);
        body.set('batch_id', form.querySelector('[name="batch_id"]').value);
        body.set('action', 'minimum_analyze_chunk');
        chunk.forEach(choice => body.append('model_selected', choice.value));
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 210000);
        try {
          const endpoint = form.getAttribute('action') || window.location.href;
          const response = await fetch(endpoint, { method: 'POST', body, credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } });
          const contentType = response.headers.get('content-type') || '';
          if (!contentType.includes('application/json')) {
            const code = `HTTP ${response.status}`;
            if ((response.url || '').includes('/admin/login/')) throw new Error(`${code}：后台登录会话已失效，请重新登录后刷新批次。`);
            if (response.status === 403) throw new Error(`${code}：请求被安全校验或权限检查拒绝，请刷新页面后核对权限。`);
            if (response.status >= 500) throw new Error(`${code}：服务器或代理处理失败，请查看后端窗口的报错。`);
            throw new Error(`${code}：打标接口返回了网页而非分析结果，请核对访问地址和后端版本。`);
          }
          const result = await response.json();
          if (!response.ok || !Array.isArray(result.items)) throw new Error(result.error || `HTTP ${response.status}：打标接口响应格式异常，请刷新核对批次。`);
          const indexed = new Map(result.items.map(item => [item.sha256, item.analysis]));
          for (const choice of chunk) {
            const analysis = indexed.get(choice.value);
            if (!analysis) throw new Error('返回结果不完整，请刷新核对已保存状态。');
            render(choice.closest('tr'), analysis);
            if (analysis.status !== 'CANDIDATES') failed += 1;
          }
        } catch (error) {
          failed += chunk.length;
          const reason = error.name === 'AbortError' ? '等待分析结果超时。' : error.message;
          chunk.forEach(choice => { choice.closest('tr').querySelector('[data-row-status]').textContent = `本组状态待核对：${reason}`; });
          stopping = true;
          status.textContent = `${reason} 后续已停止。服务器可能已保存部分结果，请刷新核对再重试，不会自动重复请求。`;
        } finally {
          clearTimeout(timer);
        }
        completed += chunk.length;
        progress.value = completed;
      }
      if (!failed) status.textContent = `${stopping ? '已停止' : '打标签完成'}：已处理 ${completed} / ${selected.length} 首。结果已保存在批次中，尚未写入曲库。`;
      else if (!stopping) status.textContent = `已处理 ${completed} 首，其中 ${failed} 首未生成标签，可查看原因后重新勾选重试。`;
    } finally {
      running = false;
      controls.forEach(control => { control.disabled = false; });
      document.querySelectorAll('[data-other-action]').forEach(control => { control.disabled = false; });
      stop.hidden = true;
      updateCount();
    }
  });
  updateCount();
})();
