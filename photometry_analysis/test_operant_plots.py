"""Regression checks for operant axes and the two average time bases."""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
import numpy as np
import pandas as pd
from align_photometry import average_trials, display_average, lick_aligned_trials, session_task
import matplotlib.pyplot as plt
from trial_comparison import session_windows, METRICS, comparison_curves, save_comparisons, stage_labels


class OperantPlotTests(unittest.TestCase):
    def comparison_data(self, long_trials=False):
        time = np.arange(16. if long_trials else 8.)
        durations = np.array([2.2, 12.2, 3.2, 13.2, 4.2, 14.2] if long_trials else
                             [2.2, 4.2, 3.2, 5.2, 4.2, 6.2])
        matrix = np.tile(np.arange(6.)[:, None], (1, len(time)))
        matrix[time[None, :] > durations[:, None]] = np.nan
        trials = pd.DataFrame({
            'stage': stage_labels(6), 'duration_s': durations,
            'cue_relative_s': [.5]*6, 'cue_off_relative_s': [1.]*6,
            'reward_relative_s': [1., 2., 2., np.nan, 3., 100.],
        })
        return time, matrix, trials, np.array([True]*5 + [False])

    def test_operant_stage_tails_use_available_trials_without_zero_filling(self):
        time, matrix, trials, included = self.comparison_data()
        curves, support = comparison_curves(matrix, included, trials.stage.to_numpy(),
                                             average_trials, common_support=False)
        np.testing.assert_array_equal(time[support], np.arange(6.))
        mean, sem, count, total = curves['early']
        np.testing.assert_allclose(mean[:5], [.5, .5, .5, 1., 1.])
        np.testing.assert_array_equal(count[:5], [2, 2, 2, 1, 1])
        self.assertEqual(total, 2)
        self.assertTrue(np.isnan(sem[3:]).all())
        self.assertTrue(np.isnan(mean[5:]).all())
        self.assertEqual(curves['middle'][0][5], 3.)
        self.assertTrue(np.isnan(curves['late'][0][5:]).all())
        _, common = comparison_curves(matrix, included, trials.stage.to_numpy(), average_trials)
        np.testing.assert_array_equal(time[common], [0., 1., 2.])
        empty, support = comparison_curves(matrix, np.zeros(6, bool), trials.stage.to_numpy(),
                                           average_trials, common_support=False)
        self.assertFalse(support.any())
        self.assertTrue(all(np.isnan(c[0]).all() for c in empty.values()))

    def test_saved_stage_plots_use_ten_seconds_and_mark_selected_reward_median(self):
        for long_trials in (False, True):
            time, matrix, trials, included = self.comparison_data(long_trials)
            with self.subTest(long_trials=long_trials), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                with patch('matplotlib.pyplot.close') as close:
                    save_comparisons(out, trials, time, {key: matrix for key in METRICS},
                                     included, average_trials, task='operant')
                fig = close.call_args.args[0]
                try:
                    for ax in fig.axes:
                        np.testing.assert_allclose(ax.get_xlim(), [-2., 10.])
                        reward, = [line for line in ax.lines if line.get_label() == 'Reward (median)']
                        self.assertEqual(reward.get_linestyle(), '--')
                        np.testing.assert_allclose(reward.get_xdata(), [2., 2.])
                        for line in ax.lines:
                            self.assertTrue(np.all(np.asarray(line.get_xdata()) <= 10))
                    self.assertGreater((out/'early_middle_late.png').stat().st_size, 0)
                    self.assertIn('Reward (median)', (out/'early_middle_late.svg').read_text())
                    csv = pd.read_csv(out/'early_middle_late.csv')
                    self.assertTrue(csv.time_from_trial_start_s.between(0, 10).all())
                    early = csv[(csv.metric == 'dff_percent') & (csv.stage == 'early')]
                    self.assertEqual(early.time_from_trial_start_s.max(), 10. if long_trials else 4.)
                    self.assertEqual(early.iloc[-1].n_trials, 1)
                    self.assertEqual(early.iloc[-1]['mean'], 1.)
                finally:
                    plt.close(fig)

    def test_empty_stage_selection_keeps_ten_second_axis_without_reward_marker(self):
        time, matrix, trials, _ = self.comparison_data()
        with tempfile.TemporaryDirectory() as directory:
            with patch('matplotlib.figure.Figure.savefig'), patch('matplotlib.pyplot.close') as close:
                save_comparisons(Path(directory), trials, time, {key: matrix for key in METRICS},
                                 np.zeros(len(trials), bool), average_trials, task='operant')
            fig = close.call_args.args[0]
            try:
                for ax in fig.axes:
                    np.testing.assert_allclose(ax.get_xlim(), [-2., 10.])
                    self.assertFalse(any(line.get_label() == 'Reward (median)' for line in ax.lines))
                self.assertTrue(pd.read_csv(Path(directory)/'early_middle_late.csv').empty)
            finally:
                plt.close(fig)

    def test_pretrial_and_ten_second_windows_include_iti_and_stop_at_recording_or_next_trial(self):
        session_time = np.arange(26.)
        time, query = session_windows(session_time, np.array([2., 8., 20.]), np.array([5., 18., 25.]),
                                      1, np.full(3, 10.))
        self.assertEqual(time[0], -2.)
        self.assertEqual(time[-1], 10.)
        data = 2 * query
        np.testing.assert_allclose(data[0, :8], np.arange(0,16,2))
        self.assertTrue(np.isnan(data[0, 8:]).all())
        self.assertEqual(data[1, -1], 36.)
        self.assertTrue(np.isnan(data[2, 8:]).all())
        curves, support = comparison_curves(
            data, np.ones(3, bool), np.array(['early', 'early', 'late']),
            average_trials, common_support=False)
        self.assertTrue(support.all())
        self.assertEqual(curves['early'][0][-1], 36.)
        self.assertEqual(curves['early'][2][-1], 1)
        self.assertTrue(np.isnan(curves['late'][0][-1]))

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

    def test_real_seconds_use_all_session_licks_and_extend_two_seconds(self):
        time = np.arange(9.)
        matrix = np.array([[0, 1, 2, 3, 4, np.nan, np.nan, np.nan, np.nan],
                           [0, 2, 4, 6, 8, 10, 12, 14, 16],
                           [100]*9], dtype=float)
        rows = pd.DataFrame({'end_lick_relative_s': [4., 8., 100.]})
        mean, sem, count, support, lick, limit = display_average(matrix, np.array([True, True, False]), rows, time)
        self.assertEqual(lick, 8.)
        self.assertEqual(limit, lick+2)
        np.testing.assert_allclose(mean[:7], [0, 1.5, 3, 4.5, 6, 10, 12])
        np.testing.assert_array_equal(count[:7], [2, 2, 2, 2, 2, 1, 1])
        self.assertTrue(np.isnan(sem[5:]).all())
        self.assertTrue(support[7:].all())
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
        self.assertEqual(aligned_time[-1], 8.)
        np.testing.assert_allclose(warped[0], warped[1])
        self.assertEqual(warped[0, aligned_time == 6.].item(), 4.)
        np.testing.assert_allclose(scaled.reward_relative_s[:2], [4.5, 2.25])
        np.testing.assert_allclose(scaled.end_lick_relative_s[:2], [6., 6.])
        np.testing.assert_allclose(rows.end_lick_relative_s[:2], [4., 8.])
        empty = np.zeros(3, bool)
        with self.assertRaisesRegex(ValueError, 'at least one'):
            lick_aligned_trials(matrix, empty, rows, time)
        mean, _, _, support, lick, _ = display_average(matrix, empty, rows, time)
        self.assertTrue(np.isnan(mean).all())
        self.assertFalse(support.any())
        self.assertEqual(lick, 6.)


if __name__ == '__main__':
    unittest.main()
