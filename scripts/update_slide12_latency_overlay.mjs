import fs from "node:fs";

const files = [
  "/Users/faisalbh/qym/outputs/insightor_eval_ar_titles/Insightor Content and Latency Analysis AR.html",
  "/Users/faisalbh/qym/outputs/insightor_eval_ar_titles/Insightor Content and Latency Analysis AR (standalone).html",
];

const sectionLabel =
  '<section data-screen-label="15 Overall latency without SQL"';
const nextSectionLabel =
  '<section data-screen-label="16 Question-average component latency stability"';

const chartHead = `      <div class="ls-chart-head">
        <div><h3>توزيع متوسط الزمن قبل طرح تنفيذ الاستعلامات وبعده</h3><p>118 تجربة تقييم · توزيعان على المحور نفسه للمقارنة المباشرة</p></div>
        <div class="ls-legend"><span class="original"><i></i>الزمن الكلي</span><span class="adjusted"><i></i>بعد طرح تنفيذ الاستعلامات</span></div>
      </div>
      <svg id="lsOverallComparisonChart" viewBox="0 0 1640 610" aria-label="مقارنة توزيع متوسط زمن الإجابة قبل طرح تنفيذ الاستعلامات وبعده"></svg>`;

const comparisonFunction = `
  function drawOverallComparison(){
    var svg=document.getElementById('lsOverallComparisonChart');
    if(!svg) return;
    clear(svg);
    var sql=DATA.components.find(function(row){return row.label==='Run SQL';});
    if(!sql) return;
    var original=DATA.overall.values.map(function(row){return row.value;});
    var adjusted=original.map(function(value,index){return value-sql.values[index];});
    var W=1640,H=610,L=92,R=38,T=96,B=92,x0=64,x1=102,binWidth=1;
    function X(value){return L+(W-L-R)*(value-x0)/(x1-x0);}
    function makeBins(values){
      var bins=Array.from({length:Math.ceil((x1-x0)/binWidth)},function(){return 0;});
      values.forEach(function(value){
        var index=Math.max(0,Math.min(bins.length-1,Math.floor((value-x0)/binWidth)));
        bins[index]+=1;
      });
      return bins;
    }
    var originalBins=makeBins(original);
    var adjustedBins=makeBins(adjusted);
    var peak=Math.max.apply(null,originalBins.concat(adjustedBins));
    function Y(value){return T+(H-T-B)*(1-value/(peak*1.13));}
    [0,5,10,15,20,25].forEach(function(tick){
      if(tick>peak) return;
      add(svg,'line',{x1:L,x2:W-R,y1:Y(tick),y2:Y(tick),stroke:LINE,'stroke-width':1});
      add(svg,'text',{x:L-16,y:Y(tick)+6,'text-anchor':'end','font-family':MONO,'font-size':17,'font-weight':650,fill:SUB},String(tick));
    });
    originalBins.forEach(function(count,index){
      if(!count) return;
      var left=X(x0+index*binWidth)+3;
      var right=X(x0+(index+1)*binWidth)-3;
      add(svg,'rect',{x:left,y:Y(count),width:Math.max(2,right-left),height:Y(0)-Y(count),rx:4,fill:'rgba(82,109,158,.26)',stroke:BLUE,'stroke-width':1.6});
    });
    adjustedBins.forEach(function(count,index){
      if(!count) return;
      var left=X(x0+index*binWidth)+7;
      var right=X(x0+(index+1)*binWidth)-7;
      add(svg,'rect',{x:left,y:Y(count),width:Math.max(2,right-left),height:Y(0)-Y(count),rx:4,fill:'rgba(211,107,74,.34)',stroke:'#D36B4A','stroke-width':1.8});
    });
    var originalMean=DATA.overall.mean;
    var adjustedMean=DATA.diagnostic.withoutRecordedSql.mean;
    add(svg,'line',{x1:X(originalMean),x2:X(originalMean),y1:T-10,y2:H-B,stroke:BLUE,'stroke-width':4});
    add(svg,'text',{x:X(originalMean),y:34,'text-anchor':'middle','font-family':AR,'font-size':19,'font-weight':800,fill:BLUE},'متوسط الزمن الكلي');
    add(svg,'text',{x:X(originalMean),y:59,'text-anchor':'middle','font-family':MONO,'font-size':19,'font-weight':850,fill:BLUE},originalMean.toFixed(1)+' ث');
    add(svg,'line',{x1:X(adjustedMean),x2:X(adjustedMean),y1:T-10,y2:H-B,stroke:'#D36B4A','stroke-width':4});
    add(svg,'text',{x:X(adjustedMean),y:34,'text-anchor':'middle','font-family':AR,'font-size':19,'font-weight':800,fill:'#D36B4A'},'المتوسط بعد الطرح');
    add(svg,'text',{x:X(adjustedMean),y:59,'text-anchor':'middle','font-family':MONO,'font-size':19,'font-weight':850,fill:'#D36B4A'},adjustedMean.toFixed(1)+' ث');
    add(svg,'line',{x1:L,x2:W-R,y1:H-B,y2:H-B,stroke:LINE,'stroke-width':1.5});
    [64,66,68,70,72,74,76,78,80,82,84,86,88,90,92,94,96,98,100,102].forEach(function(tick){
      add(svg,'line',{x1:X(tick),x2:X(tick),y1:H-B,y2:H-B+7,stroke:LINE,'stroke-width':1.4});
      add(svg,'text',{x:X(tick),y:H-49,'text-anchor':'middle','font-family':MONO,'font-size':16,'font-weight':650,fill:SUB},String(tick));
    });
    add(svg,'text',{x:24,y:(T+H-B)/2,'text-anchor':'middle','font-family':AR,'font-size':20,'font-weight':700,fill:SUB,transform:'rotate(-90 24 '+((T+H-B)/2)+')'},'عدد تجارب التقييم');
    add(svg,'text',{x:(L+W-R)/2,y:H-10,'text-anchor':'middle','font-family':AR,'font-size':19,'font-weight':700,fill:SUB},'متوسط زمن السؤال في تجربة التقييم (ثانية)');
  }
`;

for (const file of files) {
  let html = fs.readFileSync(file, "utf8");
  const sectionStart = html.indexOf(sectionLabel);
  const sectionEnd = html.indexOf(nextSectionLabel, sectionStart);
  if (sectionStart < 0 || sectionEnd < 0) {
    throw new Error(`Could not locate slide 12 in ${file}`);
  }

  let section = html.slice(sectionStart, sectionEnd);
  const headStart = section.indexOf('      <div class="ls-chart-head">');
  const svgStart = section.indexOf("      <svg", headStart);
  const svgEnd = section.indexOf("</svg>", svgStart);
  if (headStart < 0 || svgStart < 0 || svgEnd < 0) {
    throw new Error(`Could not locate slide 12 chart in ${file}`);
  }
  section =
    section.slice(0, headStart) +
    chartHead +
    section.slice(svgEnd + "</svg>".length);
  html = html.slice(0, sectionStart) + section + html.slice(sectionEnd);

  if (!html.includes("function drawOverallComparison(){")) {
    const insertionPoint = html.indexOf("  function drawComponents(){");
    if (insertionPoint < 0) {
      throw new Error(`Could not locate latency chart script in ${file}`);
    }
    html =
      html.slice(0, insertionPoint) +
      comparisonFunction +
      "\n" +
      html.slice(insertionPoint);
  }
  if (!html.includes("  drawOverallComparison();")) {
    html = html.replace(
      "  drawOverall();\n",
      "  drawOverall();\n  drawOverallComparison();\n",
    );
  }

  if (!html.includes(".ls-legend .adjusted i")) {
    html = html.replace(
      "  .ls-legend .range i { background:rgba(82,109,158,.10); border:1px dashed #526D9E; }",
      "  .ls-legend .range i { background:rgba(82,109,158,.10); border:1px dashed #526D9E; }\n  .ls-legend .adjusted i { background:rgba(211,107,74,.28); border-color:#D36B4A; }",
    );
  }

  fs.writeFileSync(file, html);
}
