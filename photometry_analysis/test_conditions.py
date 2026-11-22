import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from contextlib import redirect_stdout
import io
from unittest.mock import patch

import numpy as np
import pandas as pd
from cue_conditions import classify_trials, condition_average
from align_photometry import average_trials, run, preprocess_data


def write_fixture(root):
    """Real binary PPD, four mixed Operant trials; host cue labels have no board clock."""
    fs = 130
    t = np.arange(60 * fs) / fs
    control = 1 + .001*t + .02*np.sin(t*.7)
    signal = 2 + .6*(control-1) + .01*np.sin(t*2)
    rows = [(0, 'LICK_END_CAPS', 1), (1000, 'SESSION_START', 4)]
    pulses = []
    for trial, start, end, label in [(1,4,10.2,'CS+'),(2,14,24,'CS-'),(3,28,35.2,'CS+'),(4,40,50,'CS-')]:
        rows += [(start*1000,'TRIAL_START',trial), ((start+.9)*1000,'CUE_TRIGGER_ON',trial),
                 ((start+1)*1000,'CUE_ON',trial), ((start+3)*1000,'CUE_OFF',trial)]
        pulses.append(start+.9)
        if label == 'CS+':
            rows += [((start+5.9)*1000,'REWARD_TRIGGER_ON',trial), ((start+6)*1000,'REWARD_ON',trial),
                     (end*1000,'LICK',trial)]
            pulses.append(start+5.9)
        else:
            rows += [((start+6)*1000,'NO_REWARD',trial)]
        rows += [(end*1000,'TRIAL_END',trial)]
    rows.append((50000,'SESSION_END',4))
    events = pd.DataFrame(rows,columns=['Arduino_ms','Event','Value']).sort_values('Arduino_ms',kind='stable')
    events['Source'] = 'arduino'
    host = pd.DataFrame([(np.nan,'CS_PLUS_ON',1,'host'),(np.nan,'CS_MINUS_ON',2,'host'),
                         (np.nan,'CS_PLUS_ON',3,'host'),(np.nan,'CS_MINUS_ON',4,'host')],columns=events.columns)
    events = pd.concat([events,host],ignore_index=True)
    events.to_csv(root/'events.csv',index=False)
    digital = np.zeros(len(t),dtype=np.uint16)
    for pulse in pulses:
        digital[round(pulse*fs):round(pulse*fs)+3]=1
    raw = np.empty(len(t)*2,dtype='<u2')
    raw[::2]=(np.rint(control/.0001).astype(np.uint16)<<1)|digital
    raw[1::2]=np.rint(signal/.0001).astype(np.uint16)<<1
    header=json.dumps(dict(sampling_rate=fs,volts_per_division=[.0001,.0001],subject_ID='synthetic_CS',
                           version='1.0',mode='2EX_2EM_continuous',n_analog_signals=2,n_digital_signals=2)).encode()
    (root/'recording.ppd').write_bytes(len(header).to_bytes(2,'little')+header+raw.tobytes())
    return Namespace(ppd=root/'recording.ppd',events=root/'events.csv',out=root/'results',digital=1,
                     signal='analog_2',control='analog_1',low_pass=3,method='irls',exclude_trials='3',
                     selection_json=None,sync_pairs=None)


class ConditionTests(unittest.TestCase):
    def test_explicit_host_labels_and_legacy_unknown(self):
        events=pd.DataFrame({'Event':['CS_PLUS_ON','CS_MINUS_ON','REWARD_ON','NO_REWARD'], 'Value':['1','2','3','4']})
        labels,_=classify_trials(events,[1,2,3,4])
        self.assertEqual(labels.cue_condition.tolist(),['CS+','CS-','unknown','unknown'])
        with self.assertRaisesRegex(ValueError,'conflicting'):
            classify_trials(pd.concat([events,pd.DataFrame({'Event':['CS_MINUS_ON'],'Value':['1']})]),[1,2])

    def test_schedule_fallback_and_conflict(self):
        events=pd.DataFrame({'Event':['CS_PLUS_ON'],'Value':['1']})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'schedule.csv'
            path.write_text('Trial,Rewarded,Cue\n1,1,CS+\n2,0,CS-\n')
            labels,digest=classify_trials(events,[1,2,3],path)
            self.assertEqual(labels.cue_source.tolist(),['events','schedule','unavailable'])
            self.assertEqual(labels.cue_condition.tolist(),['CS+','CS-','unknown'])
            self.assertEqual(len(digest),64)
            path.write_text('Trial,Rewarded,Cue\n1,0,CS-\n')
            with self.assertRaisesRegex(ValueError,'conflicting'):
                classify_trials(events,[1,2],path)

    def test_exclusions_missing_samples_and_condition_time_end(self):
        trials=pd.DataFrame({'cue_condition':['CS+','CS+','CS-','CS-'],
                            'end_lick_relative_s':[6,8,np.nan,np.nan], 'duration_s':[6,8,10,10]})
        matrix=np.array([[1,2,np.nan],[99,99,99],[3,4,5],[5,6,np.nan]],float)
        time=np.array([0,9,10])
        include=np.array([True,False,True,True])
        mean,sem,n,end,_=condition_average(matrix,include,trials,time,'CS+','operant',average_trials)
        self.assertEqual(end,9)  # Median is fixed before exclusions.
        np.testing.assert_allclose(mean[:2],[1,2])
        self.assertTrue(np.isnan(mean[-1]))
        mean,sem,n,end,_=condition_average(matrix,include,trials,time,'CS-','operant',average_trials)
        np.testing.assert_allclose(mean,[4,5,5])
        np.testing.assert_allclose(sem[:2],[1,1])
        self.assertTrue(np.isnan(sem[-1]))
        np.testing.assert_array_equal(n,[2,2,1])
        self.assertEqual(end,10)

    def test_complete_pipeline_with_real_ppd(self):
        with tempfile.TemporaryDirectory() as folder:
            args=write_fixture(Path(folder))
            with patch('align_photometry.preprocess_data',wraps=preprocess_data) as process, redirect_stdout(io.StringIO()):
                qc=run(args)
            self.assertEqual(process.call_count,1)
            self.assertEqual(qc['cue_counts'],{'CS+':2,'CS-':2})
            self.assertEqual(qc['matched_ttl_count'],6)
            trials=pd.read_csv(args.out/'trial_summary.csv')
            self.assertEqual(trials.cue_condition.tolist(),['CS+','CS-','CS+','CS-'])
            with np.load(args.out/'trial_data.npz') as raw:
                self.assertEqual(raw['cue_conditions'].tolist(),['CS+','CS-','CS+','CS-'])
                output=pd.read_csv(args.out/'condition_averages.csv')
                plus=output[(output.cue_condition=='CS+')&(output.metric=='dff_percent')]
                np.testing.assert_allclose(plus['mean'],raw['dff_percent'][0,:len(plus)],rtol=1e-7,atol=1e-8)
                self.assertTrue((plus.n_trials==1).all())
                minus=output[(output.cue_condition=='CS-')&(output.metric=='dff_percent')]
                self.assertGreater(minus.time_from_trial_start_s.max(),9.9)
            report=(args.out/'review.html').read_text()
            self.assertNotIn('__CONDITION_SCRIPT__',report)
            self.assertIn('conditionFilter',report)
            self.assertTrue((args.out/'dff_percent_by_condition.png').is_file())
            with np.load(args.out/'processed_data.npz') as raw:
                self.assertIn('CS-',raw['cue_condition'])


if __name__=='__main__':
    unittest.main()
