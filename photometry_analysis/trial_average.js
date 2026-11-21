// Operant display ranges and trial-ending lick aligned averages.
const operant = Q.task === 'operant';
function mapLickTime(t,source,target){
  if(!finite(t))return null;
  if(t<0)return t;
  return t<=source?t*target/source:target+t-source;
}
function displayedMetric(){return $('dffMethod').value;}
const lickColor = '#8756aa';

function renderTrial(){
  const r=D.trials[current];
  const endLick=operant&&finite(r.end_lick_relative_s)?r.end_lick_relative_s:null;
  const axisEnd=Q.display_end_s;
  stack('trialPlot',D.relative_time,
    [D.matrices.signal_v[current],D.matrices.control_v[current],D.matrices[displayedMetric()][current]],
    D.trial_licks[current],[-2,axisEnd],
    [[0,'#666',true],[r.cue_relative_s,colors[0],true],[r.cue_off_relative_s,colors[0],true],
     [r.reward_relative_s,colors[1],true],[r.duration_s,'#777',false],[endLick,lickColor,true],
     [Q.median_first_lick_s,lickColor,false]],[[r.cue_relative_s,r.cue_off_relative_s]]);
  const ending=operant?` · 종료 lick ${fmt(endLick)}초`:'';
  $('trialInfo').textContent=`길이 ${fmt(r.duration_s)}초${ending} · lick ${r.lick_count}회 · ${include[current]?'평균에 포함':'평균에서 제외'}`;
  document.querySelectorAll('.trial-grid label').forEach((label,i)=>label.classList.toggle('current',i===current));
}

function interpolateTrial(values,time){
  const position=(time-D.relative_time[0])*Q.sampling_rate_hz,index=Math.floor(position),fraction=position-index;
  const left=values[index],right=values[index+1];
  if(!finite(left))return null;
  if(fraction<1e-7)return left;
  if(!finite(right))return null;
  return left+(right-left)*fraction;
}

function computeDisplayAverage(){
  const warped=operant&&$('averageMode').value==='lick_aligned';
  const selected=include.map((yes,i)=>yes&&(!warped||(finite(D.trials[i].end_lick_relative_s)&&D.trials[i].end_lick_relative_s>0)));
  const medianLick=Q.median_first_lick_s;
  let time=D.relative_time,matrix=D.matrices[displayedMetric()];
  if(warped&&finite(medianLick)){
    const steps=Math.ceil(medianLick*Q.sampling_rate_hz);
    time=[...D.relative_time.filter(t=>t<0),...Array.from({length:steps+1},(_,j)=>j/steps*medianLick),
          ...Array.from({length:Math.round(2*Q.sampling_rate_hz)},(_,j)=>medianLick+(j+1)/Q.sampling_rate_hz)];
    matrix=D.trials.map((row,i)=>{
      if(!selected[i])return time.map(()=>null);
      return time.map(t=>interpolateTrial(D.matrices[displayedMetric()][i],mapLickTime(t,medianLick,row.end_lick_relative_s)));
    });
  }
  const result=computeAverage(selected,'dff_percent',matrix),total=selected.filter(Boolean).length;
  for(let j=0;j<time.length;j++){
    const supported=finite(medianLick)?time[j]<=medianLick+2+1e-9&&result.n[j]>0:total>0&&result.n[j]===total;
    if(!supported){result.mean[j]=null;result.sem[j]=null;}
  }
  let last=0;
  for(let j=0;j<time.length;j++)if(finite(result.mean[j]))last=j;
  const axisEnd=finite(medianLick)?medianLick+2:(time[last]||D.relative_time.at(-1));
  const rows=D.trials.map((row,i)=>({...row,
    cue_relative_s:warped?mapLickTime(row.cue_relative_s,row.end_lick_relative_s,medianLick):row.cue_relative_s,
    cue_off_relative_s:warped?mapLickTime(row.cue_off_relative_s,row.end_lick_relative_s,medianLick):row.cue_off_relative_s,
    reward_relative_s:warped?mapLickTime(row.reward_relative_s,row.end_lick_relative_s,medianLick):row.reward_relative_s}));
  return {...result,time,matrix,selected,rows,medianLick,axisEnd,warped,total};
}

function meanRange(){return [-2,avg.axisEnd];}
function averageLabel(){return avg.warped?'종료 lick 정렬 시간 (초, trial별 비례 조정)':'TRIAL_START 이후 (초)';}

function renderAverage(){
  const {ctx,w,h}=prepare('averagePlot'),xr=meanRange(),box={l:78,t:27,w:w-98,h:h-82};
  const values=[];
  for(let j=0;j<avg.time.length;j++)if(finite(avg.mean[j]))values.push(avg.mean[j]-(avg.sem[j]||0),avg.mean[j]+(avg.sem[j]||0));
  if($('showTraces').checked)for(let i=0;i<avg.selected.length;i++)if(avg.selected[i]){
    for(let j=0;j<avg.time.length;j++)if(avg.time[j]<=xr[1]&&finite(avg.matrix[i][j]))values.push(avg.matrix[i][j]);
  }
  const yr=domain(values),[px,py]=axes(ctx,box,xr,yr,'dF/F (%)',averageLabel());
  const rows=avg.rows.filter((r,i)=>avg.selected[i]);
  cueSpan(ctx,box,xr,...medianCue(rows));
  if(!avg.total){ctx.fillText('평균에 사용할 trial이 없습니다.',box.l+160,box.t+60);return;}
  if($('showTraces').checked)for(let i=0;i<avg.selected.length;i++)if(avg.selected[i])line(ctx,avg.time,avg.matrix[i],box,xr,yr,'#aebfd13d',.7);
  ctx.fillStyle='#537fb940';
  let start=0;
  while(start<avg.time.length){
    while(start<avg.time.length&&!finite(avg.sem[start]))start++;
    if(start===avg.time.length)break;
    let end=start;
    while(end+1<avg.time.length&&finite(avg.sem[end+1]))end++;
    ctx.beginPath();
    for(let j=start;j<=end;j++){
      const x=px(avg.time[j]),y=py(avg.mean[j]+avg.sem[j]);
      if(j===start)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }
    for(let j=end;j>=start;j--)ctx.lineTo(px(avg.time[j]),py(avg.mean[j]-avg.sem[j]));
    ctx.closePath();ctx.fill();start=end+1;
  }
  line(ctx,avg.time,avg.mean,box,xr,yr,colors[2],2);
  marker(ctx,box,xr,medianCue(rows)[0],colors[0]);
  marker(ctx,box,xr,medianCue(rows)[1],colors[0]);
  marker(ctx,box,xr,median(rows.map(r=>r.reward_relative_s)),colors[1]);
  marker(ctx,box,xr,avg.medianLick,lickColor,false);
}

function renderRaster(){
  const {ctx,w,h}=prepare('rasterPlot'),ids=D.trials.map(r=>r.trial_id);
  const box={l:78,t:25,w:w-98,h:h-75},xr=meanRange(),yr=[Math.max(...ids)+.5,Math.min(...ids)-.5];
  const [px,py]=axes(ctx,box,xr,yr,'Trial ID',averageLabel());
  ctx.strokeStyle=colors[3];ctx.lineWidth=1;
  for(let i=0;i<avg.selected.length;i++){
    if(!avg.selected[i])continue;
    const row=avg.rows[i],top=py(ids[i]-.45),bottom=py(ids[i]+.45);
    cueSpan(ctx,{...box,t:top,h:bottom-top},xr,row.cue_relative_s,row.cue_off_relative_s);
    for(const lick of D.trial_licks[i]){
      const t=avg.warped?mapLickTime(lick,row.end_lick_relative_s,avg.medianLick):lick;
      if(t<xr[0]||t>xr[1])continue;
      ctx.beginPath();ctx.moveTo(px(t),py(ids[i])-2);ctx.lineTo(px(t),py(ids[i])+2);ctx.stroke();
    }
  }
  marker(ctx,box,xr,avg.medianLick,lickColor,false);
}

function refresh(){
  avg=computeDisplayAverage();
  const n=include.filter(Boolean).length;
  $('includedCount').textContent=`${n} / ${D.trials.length} trial 포함`;
  $('trialN').textContent=`${D.trials.length} / ${n}`;
  const nonzero=avg.n.filter((x,j)=>finite(avg.mean[j]));
  const ending=operant?` · 세션 첫 lick 중앙값 ${fmt(avg.medianLick)}초 (trial 시작 기준), 보상 후 지연 중앙값 ${fmt(Q.median_reward_to_lick_s)}초`:'';
  $('meanInfo').textContent=`시각별 기여 trial 수 ${nonzero.length?Math.min(...nonzero):0}–${nonzero.length?Math.max(...nonzero):0}${ending}`;
  if(operant)$('averageDescription').textContent=avg.warped?
    '0초부터 첫 lick까지 각 trial을 세션 중앙값에 맞춥니다. 시작 전과 lick 이후는 실제 초 단위입니다. 보라색 선은 중앙값입니다.':
    '보라색 선은 세션의 보상 후 첫 lick 시각 중앙값입니다. 각 시점에 기록된 trial로 평균과 SEM을 계산합니다.';
  if(operant)$('rasterCueDescription').textContent=avg.warped?'각 행의 색 구간은 해당 trial의 시간 비율로 조정한 cue 시작–끝입니다.':'각 행의 색 구간은 해당 trial의 실제 cue 시작–끝입니다.';
  document.querySelectorAll('#trialGrid input').forEach((x,i)=>{x.checked=include[i];x.parentElement.classList.toggle('off',!include[i]);});
  $('excludeInput').value=D.trials.filter((r,i)=>!include[i]).map(r=>r.trial_id).join(',');
  renderTrial();renderAverage();renderRaster();renderComparisons();
}

function exportAverage(){
  const timeName=avg.warped?'lick_aligned_time_s':'time_from_trial_start_s';
  const rows=[`${timeName},mean_dff_percent,sem_dff_percent,n_trials`];
  for(let i=0;i<avg.time.length;i++)if(finite(avg.mean[i]))rows.push([avg.time[i],avg.mean[i],avg.sem[i]??'',avg.n[i]].join(','));
  download(displayedMetric()+'_'+(avg.warped?'lick_aligned':'real')+'_selected.csv',rows.join('\r\n'));
}
