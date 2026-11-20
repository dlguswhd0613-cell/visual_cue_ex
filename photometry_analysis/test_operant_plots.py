"""Regression checks for operant axes and the two average time bases."""
import unittest
import numpy as np
import pandas as pd
from align_photometry import display_average, lick_aligned_trials, session_task


class OperantPlotTests(unittest.TestCase):
    def test_explicit_pavlovian_mode_takes_precedence_over_capability(self):
        events = pd.DataFrame({
            'Arduino_ms': [0, 1, 2, 3],
            'Event': ['LICK_END_CAPS', 'TASK_OK', 'TASK_OK', 'SESSION_START'],
            'Value': ['1', '2', '1', '1'],
        })
        self.assertEqual(session_task(events), 'pavlovian')
        self.assertEqual(session_task(events.drop(index=2)), 'operant')
        self.assertEqual(session_task(events.drop(index=[1, 2])), 'operant')
        self.assertEqual(session_task(events.iloc[[-1]]), 'unknown')

    def test_real_seconds_mean_uses_available_samples_until_mean_lick(self):
        time = np.arange(9.)
        matrix = np.array([[0, 1, 2, 3, 4, np.nan, np.nan, np.nan, np.nan],
                           [0, 2, 4, 6, 8, 10, 12, 14, 16],
                           [100]*9], dtype=float)
        rows = pd.DataFrame({'end_lick_relative_s': [4., 8., 100.]})
        mean, sem, count, support, lick, limit = display_average(matrix, np.array([True, True, False]), rows, time)
        self.assertEqual(lick, 6.)
        self.assertEqual(lick, limit)
        np.testing.assert_allclose(mean[:7], [0, 1.5, 3, 4.5, 6, 10, 12])
        np.testing.assert_array_equal(count[:7], [2, 2, 2, 2, 2, 1, 1])
        self.assertTrue(np.isnan(sem[5:]).all())
        self.assertFalse(support[7:].any())
        rows.end_lick_relative_s = np.nan
        mean, _, _, support, lick, limit = display_average(matrix, np.array([True, True, False]), rows, time)
        self.assertIsNone(lick)
        self.assertEqual(limit, 4.)
        self.assertFalse(support[5:].any())

    def test_lick_warp_preserves_amplitudes_and_scales_all_event_times(self):
        time = np.arange(0, 9, .5)
        matrix = np.array([time, time * .5, time * 100])
        matrix[0, time > 4] = np.nan
        matrix[1, time > 8] = np.nan
        rows = pd.DataFrame({
            'end_lick_relative_s': [4., 8., np.nan],
            'cue_relative_s': [1., 1., 1.], 'cue_off_relative_s': [2., 2., 2.],
            'reward_relative_s': [3., 3., 3.], 'wait_lick_relative_s': [3.1, 3.1, np.nan],
            'duration_s': [4., 8., 8.],
        })
        warped, aligned_time, scaled, included = lick_aligned_trials(matrix, np.ones(3, bool), rows, time)
        np.testing.assert_array_equal(included, [True, True, False])
        self.assertEqual(aligned_time[-1], 6.)
        np.testing.assert_allclose(warped[0], warped[1])
        self.assertEqual(warped[0, -1], 4.)
        np.testing.assert_allclose(scaled.reward_relative_s[:2], [4.5, 2.25])
        np.testing.assert_allclose(scaled.end_lick_relative_s[:2], [6., 6.])
        np.testing.assert_allclose(rows.end_lick_relative_s[:2], [4., 8.])
        empty = np.zeros(3, bool)
        with self.assertRaisesRegex(ValueError, 'at least one'):
            lick_aligned_trials(matrix, empty, rows, time)
        mean, _, _, support, lick, _ = display_average(matrix, empty, rows, time)
        self.assertTrue(np.isnan(mean).all())
        self.assertFalse(support.any())
        self.assertIsNone(lick)


if __name__ == '__main__':
    unittest.main()
