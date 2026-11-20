import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import numpy as np
from scipy.signal import butter, filtfilt
from align_photometry import average_trials
from trial_comparison import stage_labels, comparison_curves
from data_import import preprocess_data, PreprocessingError, _bisquare_fit


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
        kwargs=dict(signal=signal,control=control,sampling_rate=fs,low_pass=20,method='exponential')
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

    def test_bisquare_recovers_line_in_presence_of_transients(self):
        # At each control level the inlier residuals are symmetric about a known line.
        x = np.repeat([1., 2., 3.], 100)
        sample = np.random.default_rng(372).normal(scale=.04, size=50)
        noise = np.tile(np.r_[sample, -sample], 3)
        y = 1.5 + .8 * x + noise
        x = np.r_[x, np.full(10, 3.)]
        y = np.r_[y, np.full(10, 6.)]
        slope, intercept, iterations = _bisquare_fit(x, y, 1.4)
        self.assertGreater(iterations, 1)
        np.testing.assert_allclose([slope, intercept], [.8, 1.5], atol=1e-7)
        self.assertGreater(np.polyfit(x, y, 1)[0] - slope, .05)

    def test_irls_default_filter_percent_and_tuning(self):
        fs = 130
        t = np.arange(30 * fs) / fs
        control = 1 + .1 * np.sin(t) + .02 * np.cos(2 * np.pi * 15 * t)
        signal = 1.5 + .8 * control + .035 * np.sin(2 * t) + .2 * (np.sin(t) > .98)
        args = dict(signal=signal, control=control, sampling_rate=fs, return_components=True)
        with patch('data_import._fit_exponential', side_effect=AssertionError('unexpected bleaching fit')):
            result = preprocess_data(**args)
            explicit = preprocess_data(**args, method='irls', low_pass=3, tuning_constant=1.4)
            less_aggressive = preprocess_data(**args, tuning_constant=4.685)
        np.testing.assert_array_equal(result['signal_norm'], explicit['signal_norm'])
        self.assertGreater(np.max(np.abs(result['est_motion'] - less_aggressive['est_motion'])), .001)
        b, a = butter(2, 3, fs=fs)
        fitted = result['regression_intercept'] + result['regression_slope'] * filtfilt(b, a, control)
        np.testing.assert_allclose(result['normalisation_f0'], fitted)
        np.testing.assert_allclose(result['signal_norm'], 100 * (filtfilt(b, a, signal) - fitted) / fitted)

    def test_irls_validates_degenerate_inputs_and_fits_an_exact_line(self):
        x = np.arange(100.)
        y = 2 + 5 * x
        np.testing.assert_allclose(_bisquare_fit(x, y, 1.4)[:2], [5., 2.], atol=1e-12)
        for c in (0., -1., np.nan, np.inf):
            with self.subTest(c=c), self.assertRaisesRegex(ValueError, 'tuning constant'):
                _bisquare_fit(x, y, c)
        with self.assertRaisesRegex(PreprocessingError, 'constant control'):
            _bisquare_fit(np.ones_like(x), y, 1.4)
        y[0] = np.nan
        with self.assertRaisesRegex(PreprocessingError, 'finite'):
            _bisquare_fit(x, y, 1.4)

if __name__=='__main__':
    unittest.main()
