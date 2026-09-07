/* Exercise the shipped controller with deliberately reordered network replies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(process.argv[2], 'packages/platform/qym_platform/_static/dashboard/run_details.js'), 'utf8');

function harness() {
  const calls = [];
  let active = 0;
  let maximum = 0;
  const context = { window: {}, AbortController, fetch(url, options) {
    active++;
    maximum = Math.max(maximum, active);
    return new Promise((resolve, reject) => {
      const call = { url, body: JSON.parse(options.body), options, settled: false };
      const finish = callback => {
        if (call.settled) return;
        call.settled = true;
        active--;
        callback();
      };
      call.reply = (data, status = 200) => finish(() => resolve({ ok: status === 200, status, json: async () => data }));
      call.fail = () => finish(() => reject(new Error('network failed')));
      const onAbort = () => finish(() => reject(new Error('aborted')));
      if (options.signal.aborted) onAbort();
      else options.signal.addEventListener('abort', onAbort, { once: true });
      calls.push(call);
    });
  } };
  vm.runInNewContext(source, context);
  return { calls, maximum: () => maximum, create(options = {}) {
    return context.window.QymRunDetails.create({ runId: 'run/1', apiUrl: value => '/' + value, ...options });
  } };
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const compact = id => ({ item_id: String(id), compare_item_id: 'aligned-' + id, alignment_source: 'dataset',
  metric_values: [id], metric_meta: { accuracy: { explanation: '', modified: false } },
  pass_metric_meta: { accuracy: [{ explanation: '', label: 'keep' }] },
  pass_attempts: [{ output: '', pass_number: 1, status: 'completed' }], __details_loaded: false });
const full = id => ({ item_id: String(id), compare_item_id: 'wrong-' + id, alignment_source: 'wrong',
  input: 'question ' + id, output_full: 'answer ' + id, metric_values: [id],
  metric_meta: { accuracy: { explanation: 'judge ' + id, modified: true } },
  pass_metric_meta: { accuracy: [{ explanation: 'pass judge ' + id, label: 'keep' }] },
  pass_attempts: [{ output: 'attempt ' + id, pass_number: 1, status: 'completed' }] });
const replyRows = call => call.reply({ rows: call.body.item_ids.map(full) });

async function deduplicationAndEviction() {
  const h = harness();
  const controller = h.create({ maxLoaded: 2 });
  const rows = Array.from({ length: 5 }, (_, i) => compact(i));
  const first = controller.ensureRows(rows.slice(0, 2));
  const overlapping = controller.ensureRows(rows.slice(1, 3));
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[0].body.item_ids, ['0', '1']);
  assert.deepEqual(h.calls[1].body.item_ids, ['2']);
  assert.match(h.calls[0].url, /run%2F1\/items\/details$/);
  replyRows(h.calls[1]);
  replyRows(h.calls[0]);
  await Promise.all([first, overlapping]);
  assert.equal(rows[0].compare_item_id, 'aligned-0');
  assert.equal(rows[0].alignment_source, 'dataset');
  controller.releaseExcept([rows[1]]);
  assert.equal(rows[0].__details_loaded, false);
  assert.equal(rows[0].output_full, undefined);
  assert.equal(rows[0].metric_meta.accuracy.explanation, '');
  assert.equal(rows[0].metric_meta.accuracy.modified, true);
  assert.equal(rows[0].pass_metric_meta.accuracy[0].explanation, '');
  assert.equal(rows[0].pass_metric_meta.accuracy[0].label, 'keep');
  assert.equal(rows[0].pass_attempts[0].output, '');
  assert.equal(rows[0].pass_attempts[0].status, 'completed');
  const reload = controller.ensureRows([rows[0]]);
  replyRows(h.calls.at(-1));
  await reload;
  assert.equal(rows[0].output_full, 'answer 0');
  assert.equal(controller.ensureRows([rows[0]]), null);
  const edited = { ...rows[0], metric_values: [99] };
  controller.adoptRow(edited, rows[0]);
  controller.releaseExcept([]);
  assert.deepEqual(edited.metric_values, [99]);
  assert.equal(edited.output_full, undefined);
  controller.stop();
}

async function batchingAndRetention() {
  const h = harness();
  const controller = h.create({ maxLoaded: 20 });
  const rows = Array.from({ length: 251 }, (_, i) => compact(i));
  const completion = controller.ensureRows(rows, { retainAll: true });
  for (let index = 0; index < 3; index++) {
    await flush();
    assert.equal(h.calls.length, index + 1);
    assert.ok(h.calls[index].body.item_ids.length <= 100);
    replyRows(h.calls[index]);
  }
  await completion;
  assert.equal(rows.filter(row => row.__details_loaded).length, 251);
  controller.releaseExcept(rows.slice(-20));
  assert.equal(rows.filter(row => row.__details_loaded).length, 20);
  assert.equal(rows.at(-1).output_full, 'answer 250');
}

async function globalConcurrencyAndAbort() {
  const h = harness();
  const controllers = Array.from({ length: 9 }, () => h.create());
  const rows = controllers.map((_, id) => compact(id));
  const promises = controllers.map((controller, id) => controller.ensureRows([rows[id]]));
  const completion = Promise.allSettled(promises);
  assert.equal(h.calls.length, 3);
  controllers[8].stop(); // A queued request must also respect cancellation.
  for (let i = 0; i < 8; i++) {
    await flush();
    replyRows(h.calls[i]);
  }
  const result = await completion;
  assert.equal(result.filter(item => item.status === 'fulfilled').length, 8);
  assert.equal(result[8].status, 'rejected');
  assert.equal(h.maximum(), 3);
  assert.equal(rows[8].__details_loaded, false);
  assert.equal(controllers[8].ensureRows([rows[8]]), null);
  assert.equal(controllers[8].ensureSearch([{ field: 'output', value: 'answer' }]), null);
  const active = h.create();
  const row = compact(42);
  const pending = active.ensureRows([row]);
  active.stop();
  await assert.rejects(pending, /aborted/);
  assert.equal(row.__details_loaded, false);
}

async function searchRacesAndFailures() {
  const h = harness();
  const controller = h.create({ passNumber: 2 });
  const older = { field: 'content', value: 'Older' };
  const newer = { field: 'output', value: 'Newer' };
  const first = controller.ensureSearch([older]);
  const duplicate = controller.ensureSearch([{ ...older, value: 'OLDER' }]);
  const second = controller.ensureSearch([newer]);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].body.pass_number, 2);
  h.calls[1].reply({ matches: { 0: ['2'] } });
  await second;
  h.calls[0].reply({ matches: { 0: ['1'] } });
  await Promise.all([first, duplicate]);
  assert.equal(controller.matches(older, compact(1)), true);
  assert.equal(controller.matches(newer, compact(1)), false);
  assert.equal(controller.matches(newer, compact(2)), true);
  assert.equal(controller.ensureSearch([older, newer]), null);

  const conditions = Array.from({ length: 65 }, (_, i) => ({ field: 'all', value: 'term ' + i }));
  const batches = controller.ensureSearch(conditions);
  for (let i = 0; i < 3; i++) {
    await flush();
    const call = h.calls[2 + i];
    assert.ok(call.body.conditions.length <= 32);
    call.reply({ matches: Object.fromEntries(call.body.conditions.map(c => [c.id, ['7']])) });
  }
  await batches;
  assert.ok(conditions.every(c => controller.matches(c, compact(7))));

  const invalid = { field: 'all', value: 'invalid' };
  const missing = controller.ensureSearch([invalid]);
  h.calls.at(-1).reply({ matches: {} });
  await assert.rejects(missing, /Incomplete/);
  const retry = controller.ensureSearch([invalid]);
  h.calls.at(-1).reply({ matches: { 0: ['8'] } });
  await retry;
  assert.equal(controller.matches(invalid, compact(8)), true);

  const row = compact(9);
  const failure = controller.ensureRows([row]);
  h.calls.at(-1).reply({ error: 'unavailable' }, 503);
  await assert.rejects(failure, /503/);
  const absent = controller.ensureRows([row]);
  h.calls.at(-1).reply({ rows: [] });
  await assert.rejects(absent, /no longer available/);
  assert.equal(row.__details_loaded, false);
  const repaired = controller.ensureRows([row]);
  replyRows(h.calls.at(-1));
  await repaired;
  assert.equal(row.output_full, 'answer 9');
}

(async () => {
  await deduplicationAndEviction();
  await batchingAndRetention();
  await globalConcurrencyAndAbort();
  await searchRacesAndFailures();
  process.stdout.write('Run details contracts passed: deduplication, batches, LRU, edits, global concurrency, aborts, races, retry, missing patches.\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
