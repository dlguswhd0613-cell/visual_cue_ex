// Cue identity is fixed before selection; exclusions never refit fluorescence.
const conditionColors={'CS+':'#c05832','CS-':'#326fba',unknown:'#808080'};
function cueLabel(r){return r.cue_condition==='unknown'?'미분류':r.cue_condition;}
function analysisSelection(){
  const condition=$('conditionFilter').value;
  return include.map((yes,i)=>yes&&(condition==='all'||D.trials[i].cue_condition===condition));
}
function conditionEnd(condition){
  const rows=D.trials.filter(r=>r.cue_condition===condition);
  const lick=operant?median(rows.map(r=>r.end_lick_relative_s)):null;
  return finite(lick)?lick+2:rows.length?Math.max(...rows.map(r=>r.duration_s)):Q.display_end_s;
}
function computeConditionAverages(metric=displayedMetric()){
  const groups={};
  for(const condition of ['CS+','CS-','unknown']){
    if(!D.trials.some(r=>r.cue_condition===condition))continue;
    const selected=include.map((yes,i)=>yes&&D.trials[i].cue_condition===condition);
    const result=computeAverage(selected,metric),end=conditionEnd(condition);
    for(let j=0;j<D.relative_time.length;j++)if(D.relative_time[j]>end+1e-9){result.mean[j]=null;result.sem[j]=null;}
    groups[condition]={...result,time:D.relative_time,window:[-2,end],
      trial_ids:D.trials.filter((r,i)=>selected[i]).map(r=>r.trial_id),total:selected.filter(Boolean).length,
      color:conditionColors[condition]};
  }
  return groups;
}
function renderConditions(){
  const groups=computeConditionAverages(),curves=Object.values(groups);
  const right=Math.max(...curves.map(c=>c.window[1]));
  plotComparison('conditionPlot',curves,displayedMetric(),[-2,right]);
  $('conditionInfo').textContent=Object.entries(groups).map(([name,c])=>{
    const counts=c.n.filter((n,j)=>finite(c.mean[j]));
    return `${name==='unknown'?'미분류':name}: 포함 ${c.total} / 전체 ${D.trials.filter(r=>r.cue_condition===name).length} · 시점별 N ${counts.length?Math.min(...counts):0}–${counts.length?Math.max(...counts):0}`;
  }).join(' · ');
}
function exportConditions(){
  const rows=['cue_condition,metric,time_from_trial_start_s,mean,sem,n_trials,included_trials'];
  for(const [condition,c]of Object.entries(computeConditionAverages()))for(let j=0;j<c.time.length;j++){
    if(c.time[j]<=c.window[1]+1e-9)rows.push([condition,displayedMetric(),c.time[j],c.mean[j]??'',c.sem[j]??'',c.n[j],c.total].join(','));
  }
  download('condition_averages_selected.csv',rows.join('\r\n'));
}
