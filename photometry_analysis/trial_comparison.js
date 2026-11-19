// Trial progression and equal-weight, fixed-stage comparisons.
const metricNames={dff_percent:'dF/F (%)',f0_v:'F₀ (V)',signal_v:'Signal (V)'};
const stageColors={early:'#18755f',middle:'#b47720',late:'#8756aa'};
let comparison=null;
function commonAverage(selected,metric,window,supportSelection=selected){
  const result=computeAverage(selected,metric), total=supportSelection.filter(Boolean).length;
  for(let j=0;j<D.relative_time.length;j++){
    const t=D.relative_time[j];
    const available=total>0&&supportSelection.every((yes,i)=>!yes||finite(D.matrices[metric][i][j]));
    if(!available||t<window[0]-1e-9||t>window[1]+1e-9){result.mean[j]=null;result.sem[j]=null;}
  }
  result.trial_ids=D.trials.filter((r,i)=>selected[i]).map(r=>r.trial_id);
  result.total=result.trial_ids.length;
  return result;
}
function comparisonSettings(){
  const metric=$('compareMetric').value, first=Number($('compareFirst').value),last=Number($('compareLast').value);
  const start=Number($('compareStart').value),end=Number($('compareEnd').value);
  if(!finite(first)||!finite(last)||first>last||!Number.isInteger(first)||!Number.isInteger(last))throw Error('trial 번호 범위를 확인하세요.');
  if(!finite(start)||!finite(end)||start<0||end<=start||end>D.relative_time.at(-1)+1e-8)throw Error('trial 내 시간 범위를 확인하세요.');
  return{metric,first,last,window:[start,end]};
}
function computeComparison(settings){
  const {metric,first,last,window}=settings;
  const selected=include.map((yes,i)=>yes&&D.trials[i].trial_id>=first&&D.trials[i].trial_id<=last);
  const groups={};
  for(const stage of ['early','middle','late'])groups[stage]=commonAverage(include.map((yes,i)=>yes&&D.trials[i].stage===stage),metric,window,include);
  const indices=D.relative_time.map((t,j)=>t>=window[0]-1e-9&&t<=window[1]+1e-9?j:-1).filter(j=>j>=0);
  const trend=D.trials.map((r,i)=>{
    const values=indices.map(j=>D.matrices[metric][i][j]);
    const covered=values.length>0&&window[1]<=r.duration_s+1e-9&&values.every(finite);
    return{trial_id:r.trial_id,stage:r.stage,included:include[i],covered,n_samples:covered?values.length:0,
      mean:covered?values.reduce((a,b)=>a+b,0)/values.length:null};
  });
  return {settings,selected:commonAverage(selected,metric,window),groups,trend};
}
function plotComparison(id,curves,metric,window){
  const {ctx,w,h}=prepare(id),box={l:78,t:28,w:w-98,h:h-82},values=[];
  for(const c of curves)for(let j=0;j<c.mean.length;j++)if(finite(c.mean[j]))values.push(c.mean[j]-(c.sem[j]||0),c.mean[j]+(c.sem[j]||0));
  const yr=domain(values),[px,py]=axes(ctx,box,window,yr,metricNames[metric],'TRIAL_START 이후 (초)');
  if(!values.length){ctx.textAlign='left';ctx.fillText('선택한 trial들의 공통 데이터 구간이 없습니다.',box.l+12,box.t+30);return;}
  for(const c of curves){
    ctx.fillStyle=c.color+'25';let j=0;
    while(j<c.mean.length){
      while(j<c.mean.length&&(!finite(c.mean[j])||!finite(c.sem[j])))j++;
      const begin=j;while(j<c.mean.length&&finite(c.mean[j])&&finite(c.sem[j]))j++;
      if(j===begin)continue;
      ctx.beginPath();for(let k=begin;k<j;k++){const x=px(D.relative_time[k]),y=py(c.mean[k]+c.sem[k]);if(k===begin)ctx.moveTo(x,y);else ctx.lineTo(x,y);}
      for(let k=j-1;k>=begin;k--)ctx.lineTo(px(D.relative_time[k]),py(c.mean[k]-c.sem[k]));ctx.closePath();ctx.fill();
    }
    line(ctx,D.relative_time,c.mean,box,window,yr,c.color,2);
  }
}
function renderComparisons(){
  try{comparison=computeComparison(comparisonSettings());$('compareError').textContent='';}
  catch(e){comparison=null;$('compareError').textContent=e.message;return;}
  const {settings,selected,groups,trend}=comparison;
  plotComparison('selectedRangePlot',[{...selected,color:'#375ca8'}],settings.metric,settings.window);
  plotComparison('stagePlot',Object.entries(groups).map(([name,c])=>({...c,color:stageColors[name]})),settings.metric,settings.window);
  $('selectedRangeInfo').textContent=`Trial ${settings.first}–${settings.last} · 포함 ${selected.total}개 · 실선 평균, 음영 ±SEM`;
  $('stageInfo').textContent=Object.entries(groups).map(([name,c])=>{
    const ids=D.trials.filter(r=>r.stage===name).map(r=>r.trial_id);
    return `${name}: ${ids.length?ids[0]+'–'+ids.at(-1):'없음'}번 / 포함 ${c.total}개`;
  }).join(' · ');
  const {ctx,w,h}=prepare('progressionPlot'),box={l:78,t:28,w:w-98,h:h-82};
  const shown=trend.filter(r=>r.included&&finite(r.mean)),yr=domain(shown.map(r=>r.mean));
  const ids=D.trials.map(r=>r.trial_id),xr=[ids[0]-.5,ids.at(-1)+.5];
  const [px,py]=axes(ctx,box,xr,yr,metricNames[settings.metric],'Trial 번호');
  for(const r of shown){ctx.fillStyle=stageColors[r.stage];ctx.beginPath();ctx.arc(px(r.trial_id),py(r.mean),3,0,2*Math.PI);ctx.fill();}
  $('progressionInfo').textContent=`각 점 = trial 내 ${settings.window[0]}–${settings.window[1]}초 평균 · 표시 ${shown.length}개. 해당 시간 구간을 모두 기록하지 못한 trial은 점을 표시하지 않습니다.`;
}
function exportComparison(){
  if(!comparison)return;
  const {settings,selected,groups}=comparison;
  const rows=['group,metric,trial_window_start_s,trial_window_end_s,time_from_trial_start_s,mean,sem,n_trials,trial_ids'];
  for(const [name,c]of Object.entries({selected,...groups}))for(let j=0;j<c.mean.length;j++)if(finite(c.mean[j]))rows.push([name,settings.metric,...settings.window,D.relative_time[j],c.mean[j],c.sem[j]??'',c.n[j],c.trial_ids.join(';')].join(','));
  download('trial_comparison.csv',rows.join('\r\n'));
}
function renderWindowMean(){
  const {start_s,fs,prefix}=D.session_means, size=prefix.dff_percent.length-1;
  const first=Math.max(0,Math.min(size,Math.ceil((range[0]-start_s)*fs-1e-7)));
  const end=Math.max(0,Math.min(size,Math.floor((range[1]-start_s)*fs+1e-7)+1));
  const n=Math.max(0,end-first),means={};
  for(const key of Object.keys(metricNames))means[key]=n?(prefix[key][end]-prefix[key][first])/n:null;
  $('windowMean').textContent=`표시 구간 ${fmt(range[0])}–${fmt(range[1])}초의 실제 샘플 ${n}개 평균: `+Object.entries(means).map(([k,v])=>`${metricNames[k]} = ${fmt(v,6)}`).join(' · ');
  return{start:range[0],end:range[1],n,...means};
}
function initComparison(){
  $('compareFirst').value=D.trials[0].trial_id;$('compareLast').value=D.trials.at(-1).trial_id;
  const shortest=Math.min(...D.trials.filter(r=>r.photometry_complete).map(r=>r.duration_s));
  const commonEnd=finite(shortest)?Math.floor(shortest*Q.sampling_rate_hz)/Q.sampling_rate_hz:D.relative_time.at(-1);
  $('compareEnd').value=String(commonEnd);$('compareEnd').max=String(D.relative_time.at(-1));
  $('compareApply').onclick=renderComparisons;$('compareMetric').onchange=renderComparisons;
  $('compareDownload').onclick=exportComparison;
  $('trendDownload').onclick=()=>{if(!comparison)return;const rows=['trial_id,stage,included,window_complete,metric,start_s,end_s,n_samples,mean'];for(const r of comparison.trend)rows.push([r.trial_id,r.stage,r.included,r.covered,comparison.settings.metric,...comparison.settings.window,r.n_samples,r.mean??''].join(','));download('trial_progression.csv',rows.join('\r\n'));};
  $('windowDownload').onclick=()=>{const r=renderWindowMean();download('session_window_mean.csv','start_session_s,end_session_s,n_samples,dff_percent,f0_v,signal_v\r\n'+[r.start,r.end,r.n,r.dff_percent??'',r.f0_v??'',r.signal_v??''].join(','));};
}
