"""Run with: python -m unittest test_alignment -v"""
import unittest
from pathlib import Path
import json
import hashlib
import importlib.util
import io
from contextlib import redirect_stdout
import tempfile
from argparse import Namespace
from unittest.mock import patch
import numpy as np
import pandas as pd
from align_photometry import average_trials, assign_trials, fit_sync, parse_exclusions, load_exclusions, run


class AlignmentTests(unittest.TestCase):
    def test_selection_is_bound_to_input_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ppd,events,selection=root/'recording.ppd',root/'events.csv',root/'selection.json'
            ppd.write_bytes(b'recording one')
            events.write_bytes(b'events one')
            selection.write_text(json.dumps({
                'ppd_sha256':hashlib.sha256(ppd.read_bytes()).hexdigest(),
                'events_sha256':hashlib.sha256(events.read_bytes()).hexdigest(),
                'exclude_trials':[3,7]}))
            args=Namespace(ppd=ppd,events=events,selection_json=selection,exclude_trials='')
            self.assertEqual(load_exclusions(args),{3,7})
            events.write_bytes(b'events two')
            with self.assertRaisesRegex(ValueError,'different input files'):
                load_exclusions(args)
            events.write_bytes(b'events one')
            ppd.write_bytes(b'recording two')
            with self.assertRaisesRegex(ValueError,'different input files'):
                load_exclusions(args)

    @unittest.skipUnless(importlib.util.find_spec('tkinter'), 'tkinter is not installed')
    def test_file_picker_uses_new_paths_and_exclusions_each_time(self):
        from select_analysis import choose_and_run
        with tempfile.TemporaryDirectory() as directory, patch('tkinter.Tk'), \
                patch('tkinter.filedialog.askopenfilename', side_effect=[
                    '/tmp/first recording.ppd','/tmp/first events.csv','/tmp/second.ppd','/tmp/second.csv']), \
                patch('tkinter.filedialog.askdirectory',return_value=directory), \
                patch('tkinter.simpledialog.askstring',side_effect=['3,7','']), \
                patch('tkinter.messagebox.showinfo'), patch('webbrowser.open'), \
                patch('align_photometry.run') as process:
            self.assertEqual(choose_and_run(),0)
            self.assertEqual(choose_and_run(),0)
            first,second=[call.args[0] for call in process.call_args_list]
            self.assertEqual(first.ppd,'/tmp/first recording.ppd')
            self.assertEqual(first.events,'/tmp/first events.csv')
            self.assertEqual(first.exclude_trials,'3,7')
            self.assertEqual(second.ppd,'/tmp/second.ppd')
            self.assertEqual(second.exclude_trials,'')
            self.assertNotEqual(first.out,second.out)
            self.assertEqual(Path(first.out).parent,Path(directory))

    def test_affine_sync_recovers_shift_and_drift(self):
        t = np.array([20,25,53,58,91,96], dtype=float)
        ev = pd.DataFrame({'Arduino_ms': t*1000, 'Event': ['CUE_TRIGGER_ON','REWARD_TRIGGER_ON']*3,
                           'Source': ['arduino']*6, 'Value': ['1','1','2','2','3','3']})
        a,b,pairs = fit_sync(ev, t*1.0007-8, 130)
        self.assertAlmostEqual(a, 1.0007)
        self.assertAlmostEqual(b, -8)
        self.assertLess(np.max(np.abs(pairs.residual_ms)), 1e-8)
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            fit_sync(ev, t[:-1], 130)
        wrong = t*1.0007-8
        wrong[2] += .1
        with self.assertRaisesRegex(ValueError, 'reliable affine'):
            fit_sync(ev, wrong, 130)

    def test_lick_at_trial_end_belongs_to_that_trial_but_iti_does_not(self):
        result = assign_trials(np.array([0,1,2,2.1,3,4,5,np.nan]),
                               np.array([1,3]), np.array([2,4]), np.array([1,2]))
        np.testing.assert_array_equal(result, [0,1,1,0,2,2,0,0])

    def test_excluded_trial_and_variable_length_are_not_zero_filled(self):
        x = np.array([[1,2,np.nan],[3,4,5],[100,100,100]], dtype=float)
        mean,sem,n = average_trials(x, np.array([True,True,False]))
        np.testing.assert_allclose(mean,[2,3,5])
        np.testing.assert_allclose(sem[:2],[1,1])
        self.assertTrue(np.isnan(sem[-1]))
        np.testing.assert_array_equal(n,[2,2,1])
        mean,sem,n = average_trials(x, np.array([False,False,False]))
        self.assertTrue(np.isnan(mean).all() and np.isnan(sem).all())
        self.assertTrue((n==0).all())
        self.assertEqual(parse_exclusions('3, 7,12–15'), {3,7,12,13,14,15})
        with self.assertRaises(ValueError):
            parse_exclusions('5-2')

    def test_pipeline_crops_preserves_samples_and_aligns_licks_and_reward(self):
        fs=130
        time=np.arange(40*fs)/fs
        a,b=1.0007,2.0
        triggers=np.array([10.9,15.9,25.9,30.9])
        data={'sampling_rate':fs,'time':time*1000,'subject_ID':'synthetic',
              'pulse_times_1':(a*triggers+b)*1000,
              'analog_1':1+.01*time,'analog_2':2+.02*time,
              'digital_1':np.zeros(len(time),dtype=int),'digital_2':np.zeros(len(time),dtype=int)}
        dff=np.sin(time)+time*.1
        rows=[(1000,'SESSION_START',1),(10000,'TRIAL_START',1),
              (10900,'CUE_TRIGGER_ON',1),(11000,'CUE_ON',1),(13000,'CUE_OFF',1),
              (15900,'REWARD_TRIGGER_ON',1),(16000,'REWARD_ON',1),
              (20000,'LICK',1),(20000,'TRIAL_END',1),(22123,'LICK',2),
              (25000,'TRIAL_START',2),(25900,'CUE_TRIGGER_ON',2),
              (26000,'CUE_ON',2),(28000,'CUE_OFF',2),
              (30900,'REWARD_TRIGGER_ON',2),(31000,'REWARD_ON',2),
              (35000,'LICK',3),(35000,'TRIAL_END',2),(35000,'SESSION_END',1)]
        events=pd.DataFrame(rows,columns=['Arduino_ms','Event','Value'])
        events['Source']='arduino'
        events.loc[len(events)]=[np.nan,'COMMAND','STOP','host']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ppd,csv,out=root/'synthetic.ppd',root/'events.csv',root/'results'
            ppd.write_bytes(b'synthetic input; reader replaced for this test')
            events.to_csv(csv,index=False)
            args=Namespace(ppd=ppd,events=csv,out=out,digital=1,signal='analog_2',
                           control='analog_1',low_pass=20,exclude_trials='2',
                           selection_json=None,sync_pairs=None)
            crop=(time>=a+b)&(time<=a*35+b)
            def preprocess(cropped, **kwargs):
                # The pre-start and post-end samples must never enter any fit.
                np.testing.assert_array_equal(cropped['time'],data['time'][crop])
                np.testing.assert_array_equal(cropped['analog_2'],data['analog_2'][crop])
                self.assertTrue(kwargs['return_components'])
                return {'signal_norm':dff[crop], 'signal_expfit':np.full(crop.sum(),2.)}
            with patch('align_photometry.import_ppd',return_value=data), \
                    patch('align_photometry.preprocess_data',side_effect=preprocess), redirect_stdout(io.StringIO()):
                qc=run(args)
            self.assertEqual(qc['matched_ttl_count'],4)
            self.assertEqual(qc['complete_behavior_trials'],2)
            self.assertEqual(qc['included_trials'],1)
            self.assertEqual(qc['lick_events_in_session'],3)
            self.assertEqual(qc['lick_events_in_trials'],2)
            self.assertEqual(qc['missing_start_photometry_s'],0)
            with np.load(out/'processed_data.npz') as raw:
                idx=raw['ppd_sample_index']
                np.testing.assert_array_equal(raw['dff_percent'],dff[idx])
                self.assertNotIn('original_ppd_dff_percent',raw.files)
                np.testing.assert_array_equal(raw['f0_v'],np.full(crop.sum(),2.))
                self.assertGreaterEqual(raw['time_ppd_s'][0],a+b)
                np.testing.assert_allclose(raw['time_ppd_s'],idx/fs)
                np.testing.assert_allclose(raw['time_session_s'],raw['time_ppd_s']-(a+b))
                self.assertLessEqual(raw['time_ppd_s'][-1],a*35+b)
                self.assertEqual(raw['lick_count'].sum(),3)
                expected=np.rint((a*np.array([20,22.123,35])+b)*fs).astype(int)
                np.testing.assert_array_equal(idx[raw['lick_count']>0],expected)
            licks=pd.read_csv(out/'lick_events.csv')
            np.testing.assert_array_equal(licks.trial_id,[1,0,2])
            np.testing.assert_allclose(licks.time_ppd_s,a*np.array([20,22.123,35])+b)
            aligned=pd.read_csv(out/'events_aligned.csv')
            reward=aligned[aligned.Event=='REWARD_ON'].time_ppd_s.to_numpy()
            ttl=aligned[aligned.Event=='REWARD_TRIGGER_ON'].time_ppd_s.to_numpy()
            np.testing.assert_allclose(reward-ttl,.1*a,atol=1e-7)
            self.assertTrue(aligned.loc[aligned.Source=='host','time_ppd_s'].isna().all())
            avg=pd.read_csv(out/'dff_average.csv')
            self.assertTrue((avg.n_trials==1).all())
            self.assertTrue(avg.sem_dff_percent.isna().all())
            with np.load(out/'trial_data.npz') as trials:
                np.testing.assert_allclose(avg.mean_dff_percent,trials['dff_percent'][0,:len(avg)],rtol=1e-7,atol=1e-8)
            report=(out/'review.html').read_text(encoding='utf-8')
            self.assertNotIn('__ANALYSIS_DATA__',report)
            self.assertIn('window.reviewAPI',report)
            self.assertNotIn('__COMPARISON_SCRIPT__',report)
            self.assertTrue((out/'early_middle_late.csv').exists())


if __name__=='__main__':
    unittest.main()
