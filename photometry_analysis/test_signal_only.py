import unittest
import numpy as np
from scipy.ndimage import uniform_filter1d
from signal_only import signal_only_dff


class SignalOnlyTests(unittest.TestCase):
    def test_session_line_trial_baselines_and_percent(self):
        fs = 100
        t = np.arange(2000)/fs
        signal = 2 + .05*t + .02*np.cos(3*t)
        starts = np.array([.25,5.,15.])
        offsets = np.arange(-100,201)/fs
        query = starts[:,None]+offsets
        values, f0, qc = signal_only_dff(signal,t,starts,fs,1.4,query)
        self.assertEqual(qc['smoothing_samples'],5)
        self.assertTrue(np.isnan(values[0]).all())
        f = uniform_filter1d(signal,5) - (qc['intercept_v'] + qc['slope_v_per_s']*t)
        raw_baselines = [np.mean(f[(t>=start-1)&(t<start)]) for start in starts[1:]]
        np.testing.assert_allclose(f0[1:],raw_baselines)
        self.assertAlmostEqual(qc['f0_average_v'],np.mean(raw_baselines))
        np.testing.assert_allclose(values[1],100*(np.interp(query[1],t,f)-f0[1])/np.mean(raw_baselines))
        self.assertEqual(qc['valid_baselines'],2)

    def test_zero_residual_reference(self):
        t = np.arange(100)/10
        values, _, qc = signal_only_dff(np.ones(100), t, [3.,6.], 10, 1.4, np.array([[3.],[6.]]))
        self.assertFalse(qc['usable'])
        self.assertTrue(np.isnan(values).all())
