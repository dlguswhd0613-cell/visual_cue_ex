// Operant display ranges and trial-ending lick aligned averages.
const operant = Q.task === 'operant';
const lickColor = '#8756aa';

function renderTrial(){
  const r=D.trials[current];
  const endLick=operant&&finite(r.end_lick_relative_s)?r.end_lick_relative_s:null;
  const axisEnd=operant?Math.max((endLick??r.duration_s)/.8,r.duration_s,1/Q.sampling_rate_hz):Math.max(r.duration_s,D.relative_time.at(-1));
  stack('trialPlot',D.relative_time,
    [D.matrices.signal_v[current],D.matrices.control_v[current],D.matrices.dff_percent[current]],
    D.trial_licks[current],[0,axisEnd],
    [[r.cue_relative_s,colors[0],true],[r.cue_off_relative_s,colors[0],true],
     [r.reward_relative_s,colors[1],true],[r.duration_s,'#777',false],[endLick,lickColor,false]],
    [[r.cue_relative_s,r.cue_off_relative_s]]);
  const ending=operant?` · 종료 lick ${fmt(endLick)}초`:'';
  $('trialInfo').textContent=`길이 ${fmt(r.duration_s)}초${ending} · lick ${r.lick_count}회 · 평균 dF/F ${fmt(r.mean_dff_percent)}% · ${include[current]?'평균에 포함':'평균에서 제외'}`;
  document.querySelectorAll('.trial-grid label').forEach((label,i)=>label.classList.toggle('current',i===current));
}

function interpolateTrial(values,time){
  const position=time*Q.sampling_rate_hz,index=Math.floor(position),fraction=position-index;
  const left=values[index],right=values[index+1];
  if(!finite(left))return null;
  if(fraction<1e-7)return left;
  if(!finite(right))return null;
  return left+(right-left)*fraction;
}

function computeDisplayAverage(){
  const warped=operant&&$('averageMode').value==='lick_aligned';
  const selected=include.map((yes,i)=>yes&&(!warped||(finite(D.trials[i].end_lick_relative_s)&&D.trials[i].end_lick_relative_s>0)));
  const endings=D.trials.filter((r,i)=>selected[i]&&finite(r.end_lick_relative_s)&&r.end_lick_relative_s>0).map(r=>r.end_lick_relative_s);
  const meanLick=operant&&endings.length?endings.reduce((a,b)=>a+b,0)/endings.length:null;
  let time=D.relative_time,matrix=D.matrices.dff_percent;
  const scales=D.trials.map(()=>1);
  if(warped&&finite(meanLick)){
    const steps=Math.ceil(meanLick*Q.sampling_rate_hz);
    time=Array.from({length:steps+1},(_,j)=>j/steps*meanLick);
    matrix=D.trials.map((row,i)=>{
      if(!selected[i])return time.map(()=>null);
      scales[i]=meanLick/row.end_lick_relative_s;
      return time.map(t=>interpolateTrial(D.matrices.dff_percent[i],t/scales[i]));
    });
  }
  const result=computeAverage(selected,'dff_percent',matrix),total=selected.filter(Boolean).length;
  for(let j=0;j<time.length;j++){
    const supported=finite(meanLick)?time[j]<=meanLick+1e-9&&result.n[j]>0:total>0&&result.n[j]===total;
    if(!supported){result.mean[j]=null;result.sem[j]=null;}
  }
  let last=0;
  for(let j=0;j<time.length;j++)if(finite(result.mean[j]))last=j;
  const axisEnd=finite(meanLick)?meanLick/.8:(time[last]||D.relative_time.at(-1));
  const rows=D.trials.map((row,i)=>({...row,
    cue_relative_s:finite(row.cue_relative_s)?row.cue_relative_s*scales[i]:null,
    cue_off_relative_s:finite(row.cue_off_relative_s)?row.cue_off_relative_s*scales[i]:null,
    reward_relative_s:finite(row.reward_relative_s)?row.reward_relative_s*scales[i]:null}));
  return {...result,time,matrix,selected,rows,scales,meanLick,axisEnd,warped,total,endingCount:endings.length};
}

function meanRange(){return [0,avg.axisEnd];}
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
  marker(ctx,box,xr,avg.meanLick,lickColor,false);
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
      const t=lick*avg.scales[i];
      if(t<xr[0]||t>xr[1])continue;
      ctx.beginPath();ctx.moveTo(px(t),py(ids[i])-2);ctx.lineTo(px(t),py(ids[i])+2);ctx.stroke();
    }
  }
  marker(ctx,box,xr,avg.meanLick,lickColor,false);
}

function refresh(){
  avg=computeDisplayAverage();
  const n=include.filter(Boolean).length;
  $('includedCount').textContent=`${n} / ${D.trials.length} trial 포함`;
  $('trialN').textContent=`${D.trials.length} / ${n}`;
  const selected=D.trials.filter((r,i)=>include[i]);
  const m=selected.length?selected.reduce((a,r)=>a+r.mean_dff_percent,0)/selected.length:null;
  const nonzero=avg.n.filter((x,j)=>finite(avg.mean[j]));
  const ending=operant?` · 평균 종료 lick ${fmt(avg.meanLick)}초 (${avg.endingCount} trials)` : '';
  $('meanInfo').textContent=`Trial별 평균의 평균 ${fmt(m)}% · 시각별 기여 수 ${nonzero.length?Math.min(...nonzero):0}–${nonzero.length?Math.max(...nonzero):0}${ending}`;
  if(operant)$('averageDescription').textContent=avg.warped?
    'Trial 시작을 0으로 두고 각 trial의 시간을 평균 종료 lick / 해당 trial 종료 lick 비율로 조정합니다. cue·reward·lick에도 같은 비율을 적용합니다. 실선은 같은 조정 시각의 평균, 음영은 ±SEM입니다. 종료 lick이 기록된 trial을 사용하며 보라색 선은 평균 종료 lick 시각입니다.':
    '실제 초 단위로 평균 종료 lick 시각까지 계산합니다. 각 시점에 기록이 남아 있는 trial의 평균과 ±SEM을 표시하므로 기여 trial 수가 달라집니다. 보라색 선은 평균 종료 lick 시각이며 가로축의 80% 위치입니다.';
  if(operant)$('rasterCueDescription').textContent=avg.warped?'각 행의 색 구간은 해당 trial의 시간 비율로 조정한 cue 시작–끝입니다.':'각 행의 색 구간은 해당 trial의 실제 cue 시작–끝입니다.';
  document.querySelectorAll('#trialGrid input').forEach((x,i)=>{x.checked=include[i];x.parentElement.classList.toggle('off',!include[i]);});
  $('excludeInput').value=D.trials.filter((r,i)=>!include[i]).map(r=>r.trial_id).join(',');
  renderTrial();renderAverage();renderRaster();renderComparisons();
}

function exportAverage(){
  const timeName=avg.warped?'lick_aligned_time_s':'time_from_trial_start_s';
  const rows=[`${timeName},mean_dff_percent,sem_dff_percent,n_trials`];
  for(let i=0;i<avg.time.length;i++)if(finite(avg.mean[i]))rows.push([avg.time[i],avg.mean[i],avg.sem[i]??'',avg.n[i]].join(','));
  download(avg.warped?'dff_average_lick_aligned_selected.csv':'dff_average_selected.csv',rows.join('\r\n'));
}
