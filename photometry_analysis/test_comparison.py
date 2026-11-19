import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import numpy as np
from scipy.signal import butter, filtfilt
from align_photometry import average_trials
from trial_comparison import stage_labels, comparison_curves
from data_import import preprocess_data, PreprocessingError


class ComparisonTests(unittest.TestCase):
    def test_fixed_thirds_before_exclusions_and_shared_support(self):
        labels=stage_labels(100)
        self.assertEqual(list(labels[:33]),['early']*33)
        self.assertEqual(list(labels[33:66]),['middle']*33)
        self.assertEqual(list(labels[66:]),['late']*34)
        values=np.tile(np.arange(100.)[:,None],(1,5))
        values[3,-1]=np.nan
        selected=np.ones(100,bool)
        selected[0]=False
        curves,support=comparison_curves(values,selected,labels,average_trials)
        np.testing.assert_array_equal(support,[True]*4+[False])
        self.assertEqual(curves['early'][3],32)
        self.assertAlmostEqual(curves['early'][0][0],16.5)
        self.assertAlmostEqual(curves['middle'][0][0],49.0)
        self.assertAlmostEqual(curves['late'][0][0],82.5)
        self.assertTrue(all(np.isnan(c[0][-1]) for c in curves.values()))

    def test_empty_groups_are_not_zero_curves(self):
        values=np.ones((2,3));include=np.array([False,True])
        curves,support=comparison_curves(values,include,stage_labels(2),average_trials)
        self.assertTrue(np.isnan(curves['early'][0]).all())
        self.assertTrue(np.isnan(curves['middle'][0]).all())
        self.assertTrue(np.isnan(curves['late'][1]).all())
        curves,support=comparison_curves(values,np.zeros(2,bool),stage_labels(2),average_trials)
        self.assertFalse(support.any())

    def test_optional_components_preserve_calculation_and_sample_rate(self):
        fs=130;t=np.arange(120*fs)/fs
        control=1+.4*np.exp(-t/300)+.1*np.sin(t*3)
        signal=2+.8*np.exp(-t/300)+.07*np.sin(t*3)+.01*np.cos(t*6)
        kwargs=dict(signal=signal,control=control,sampling_rate=fs,low_pass=20)
        original=preprocess_data(**kwargs)
        components=preprocess_data(**kwargs,return_components=True)
        np.testing.assert_array_equal(original,components['signal_norm'])
        self.assertEqual(components['signal_expfit'].shape,t.shape)
        np.testing.assert_allclose(original,100*components['signal_mc']/components['signal_expfit'])

    def test_control_fit_matches_filtered_regression_without_exponential(self):
        fs=130
        t=np.arange(10*fs)/fs
        control=1+.1*np.sin(t)
        signal=2+3*control+.05*np.cos(4*t)
        b,a=butter(2,20,btype='low',fs=fs)
        control_filt=filtfilt(b,a,control)
        signal_filt=filtfilt(b,a,signal)
        design=np.column_stack((np.ones(len(t)),control_filt))
        reference=design@np.linalg.lstsq(design,signal_filt,rcond=None)[0]
        with patch('data_import._fit_exponential',side_effect=AssertionError('No exponential fit')), tempfile.TemporaryDirectory() as folder:
            fig=Path(folder)/'diagnostic.png'
            result=preprocess_data(signal=signal,control=control,sampling_rate=fs,
                                   low_pass=20,method='control_fit',return_components=True,fig_path=fig)
            self.assertTrue(fig.exists())
        self.assertIsNone(result['signal_expfit'])
        np.testing.assert_allclose(result['est_motion'],reference,atol=1e-12)
        np.testing.assert_allclose(result['signal_norm'],100*(signal_filt-reference)/reference,atol=1e-12)

    def test_control_fit_rejects_nonpositive_reference(self):
        control=1+np.sin(np.arange(1300)/130)*.1
        with self.assertRaisesRegex(PreprocessingError,'denominator must be finite and positive'):
            preprocess_data(signal=-2*control,control=control,sampling_rate=130,
                            method='control_fit',normalisation='dF/F')

if __name__=='__main__':
    unittest.main()
