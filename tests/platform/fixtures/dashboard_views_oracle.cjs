// Run the shipped browser reducers as an independent oracle for server views.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2];
const source = fs.readFileSync(path.join(root, 'packages/platform/qym_platform/_static/dashboard/dashboard.js'), 'utf8');
const metrics = fs.readFileSync(path.join(root, 'packages/platform/qym_platform/_static/dashboard/metrics.js'), 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function extract(name) {
  const start = source.indexOf(`  function ${name}(`);
  if (start < 0) throw Error(name);
  const end = source.indexOf('\n  }', start);
  return source.slice(start, end + 4);
}
const names = ['stripModelProvider','hasReasoningTraceStats','runHasReasoning','getModelVariantKey','parseModelVariantKey','getRunModelKey','compareModelVariantKeys','flattenRuns','computeAggregations','computeChartData','buildDashboardChartData'];
const results = input.map(test => {
  const NativeDate = Date;
  class FixedDate extends NativeDate {
    constructor(...args) { super(...(args.length ? args : [test.now])); }
  }
  const context = vm.createContext({window:{},Date:FixedDate,state:{dashboardOverview:{chart_data:test.computed.chart_data},chartHistory:new Map()}});
  vm.runInContext(metrics,context);
  vm.runInContext(names.map(extract).join('\n'),context);
  const flatten = rows => rows.map(row => ({...row,_date:new FixedDate(row.timestamp)}));
  context.globalRows = flatten(test.unfiltered);
  context.filteredRows = flatten(test.filtered);
  const result = vm.runInContext(`({aggregations:computeAggregations(globalRows),chart_data:computeChartData(filteredRows),normalized:buildDashboardChartData()})`,context);
  const typePayload = {tasks:{}};
  for(const row of test.unfiltered) {
    (((typePayload.tasks[row.task_name] ||= {})[row.model_name] ||= [])).push(row);
  }
  context.typePayload = typePayload;
  result.metric_types = vm.runInContext('flattenRuns(typePayload).metricTypes',context);
  for(const chart of [result.chart_data,result.normalized]) {
    delete chart.model_frequency;
    for(const combo of chart.combos) { delete combo.revision; }
    for(const combo of chart.combos) for(const data of Object.values(combo.models)) {
      data.runsList = [];
      delete data.medianLatencyValues;
    }
  }
  return result;
});
process.stdout.write(JSON.stringify(results));
