const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

async function runPage(total, options = {}) {
  const requests = [];
  function control(value = '') { return { value, checked: true, disabled: false, hidden: false, textContent: '', handlers: {}, addEventListener(name, callback) { this.handlers[name] = callback; } }; }
  const all = control();
  const count = control();
  const start = control();
  const stop = control();
  const clear = control();
  const progress = control();
  const status = control();
  const choices = Array.from({ length: total }, (_, index) => {
    const choice = control(String(index));
    const rowStatus = control();
    const cells = Object.fromEntries(['STYLE', 'MOOD', 'SCENE'].map(kind => [kind, { replaceChildren() {}, append() {} }]));
    choice.closest = () => ({ querySelector(selector) { return selector === '[data-row-status]' ? rowStatus : cells[selector.match(/"(.*?)"/)[1]]; } });
    return choice;
  });
  const controls = [all, clear, start, stop, ...choices];
  const selectors = { '[data-select-all]': all, '[data-selection-count]': count, '[data-start]': start, '[data-stop]': stop, '[data-clear]': clear, progress, '[data-progress-status]': status, '[name="csrfmiddlewaretoken"]': control('token'), '[name="batch_id"]': control('batch') };
  const form = { action: control('minimum_analyze'), getAttribute: name => name === 'action' ? (options.action || null) : null, handlers: {}, querySelector: selector => selectors[selector], querySelectorAll: selector => selector === '[name="model_selected"]' ? choices : controls, addEventListener(name, callback) { this.handlers[name] = callback; } };
  const document = { querySelector: () => form, querySelectorAll: () => [], createElement: () => ({}) };
  const fetch = async (url, request) => {
    assert.equal(url, options.action || '/admin/batch/?batch_id=batch');
    const selected = request.body.getAll('model_selected');
    requests.push(selected);
    assert.equal(request.body.get('action'), 'minimum_analyze_chunk');
    assert.equal(request.body.get('csrfmiddlewaretoken'), 'token');
    if (options.stop) stop.handlers.click();
    if (options.networkError) throw new Error('network');
    if (options.response) return options.response;
    return { ok: true, status: 200, url, redirected: false, headers: { get: () => 'application/json' }, json: async () => ({ items: selected.map(sha256 => ({ sha256, analysis: { status: 'CANDIDATES', candidates: [] } })) }) };
  };
  const source = fs.readFileSync(path.join(__dirname, '../backend/music/static/music/batch-import.js'), 'utf8');
  vm.runInNewContext(source, { document, fetch, URLSearchParams, AbortController, setTimeout, clearTimeout, window: { location: { href: '/admin/batch/?batch_id=batch' } } });
  all.checked = false;
  all.handlers.change();
  assert.equal(choices.filter(choice => choice.checked).length, 0);
  all.checked = true;
  all.handlers.change();
  assert.equal(choices.filter(choice => choice.checked).length, total);
  await form.handlers.submit({ preventDefault() {} });
  return { requests, progress, status, start };
}

test('select all runs every song in ordered groups of five with final progress', async () => {
  const result = await runPage(12);
  assert.deepEqual(result.requests.map(chunk => chunk.length), [5, 5, 2]);
  assert.equal(result.progress.value, 12);
  assert.match(result.status.textContent, /打标签完成/);
  assert.equal(result.start.disabled, false);
});
test('stop finishes current group and never schedules the next', async () => {
  const result = await runPage(12, { stop: true });
  assert.equal(result.requests.length, 1);
  assert.equal(result.progress.value, 5);
  assert.match(result.status.textContent, /已停止/);
});
test('network failure stops without automatic retry and asks to verify persisted state', async () => {
  const result = await runPage(12, { networkError: true });
  assert.equal(result.requests.length, 1);
  assert.match(result.status.textContent, /刷新核对/);
  assert.equal(result.start.disabled, false);
});
test('explicit action attribute is used despite the named action input', async () => {
  const result = await runPage(6, { action: '/admin/explicit/' });
  assert.deepEqual(result.requests.map(chunk => chunk.length), [5, 1]);
});
for (const [status, url, expected] of [
  [200, '/admin/login/?next=/admin/batch/', /登录会话已失效/],
  [403, '/admin/batch/', /安全校验或权限/],
  [500, '/admin/batch/', /服务器或代理/],
  [502, '/admin/batch/', /服务器或代理/],
  [504, '/admin/batch/', /服务器或代理/],
  [200, '/admin/batch/', /返回了网页/],
  [404, '/admin/wrong/', /返回了网页/],
]) {
  test(`HTML ${status} at ${url} stops with a factual error, not a JSON parse error`, async () => {
    const result = await runPage(12, { response: { status, url, redirected: true, headers: { get: () => 'text/html' }, json() { assert.fail('HTML must not be parsed as JSON'); } } });
    assert.equal(result.requests.length, 1);
    assert.match(result.status.textContent, new RegExp(`HTTP ${status}`));
    assert.match(result.status.textContent, expected);
    assert.match(result.status.textContent, /刷新核对/);
    assert.equal(result.start.disabled, false);
  });
}
test('JSON server error keeps the specific reason without retrying', async () => {
  const result = await runPage(12, { response: { ok: false, status: 400, headers: { get: () => 'application/json' }, json: async () => ({ error: '批次不属于当前账户' }) } });
  assert.equal(result.requests.length, 1);
  assert.match(result.status.textContent, /批次不属于当前账户/);
});
