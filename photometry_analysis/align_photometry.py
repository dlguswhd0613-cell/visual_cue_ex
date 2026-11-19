"""TTL alignment, session crop, trial averages, and an offline review report.

Uses the supplied GPLv3 pyPhotometry preprocessing formulas on the cropped session.
All dF/F values are percent (the supplied preprocess_data already multiplies by 100).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'photometry-mpl'))
os.environ.setdefault('XDG_CACHE_HOME', str(Path(tempfile.gettempdir()) / 'photometry-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data_import import import_ppd, preprocess_data
from trial_comparison import stage_labels, save_comparisons

TRIGGERS = ('CUE_TRIGGER_ON', 'REWARD_TRIGGER_ON')


def parse_exclusions(value):
    excluded = set()
    for item in value.replace('–', '-').replace(' ', '').split(','):
        if not item:
            continue
        bounds = item.split('-')
        if len(bounds) == 1:
            excluded.add(int(item))
        elif len(bounds) == 2:
            first, last = map(int, bounds)
            if first > last:
                raise ValueError(f'Invalid trial range: {item}')
            excluded.update(range(first, last + 1))
        else:
            raise ValueError(f'Invalid trial selection: {item}')
    return excluded


def load_exclusions(args):
    if not getattr(args, 'selection_json', None):
        return parse_exclusions(args.exclude_trials)
    selection = json.loads(Path(args.selection_json).read_text(encoding='utf-8'))
    for key, path in [('ppd_sha256', args.ppd), ('events_sha256', args.events)]:
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if selection.get(key) != actual:
            raise ValueError('The saved trial selection belongs to different input files. '
                             'Choose exclusions for this session with --exclude-trials.')
    ids = selection['exclude_trials']
    if not isinstance(ids, list) or any(type(v) is not int or v < 1 for v in ids):
        raise ValueError('exclude_trials must contain positive integer trial IDs.')
    return set(ids)


def fit_sync(events, pulse_times_s, fs, manual_pairs=None):
    anchors = events.loc[events.Event.isin(TRIGGERS) & (events.Source == 'arduino')].copy()
    if manual_pairs is None:
        if len(anchors) != len(pulse_times_s):
            raise ValueError(f'TTL counts differ: CSV={len(anchors)}, PPD={len(pulse_times_s)}. '
                             'Do not pair by index. Supply verified --sync-pairs CSV '
                             '(arduino_ms,ppd_time_s) or inspect the recordings first.')
        pairs = pd.DataFrame({'arduino_ms': anchors.Arduino_ms.to_numpy(float),
                              'ppd_time_s': pulse_times_s,
                              'event': anchors.Event.to_numpy(), 'trial': anchors.Value.to_numpy()})
    else:
        pairs = pd.read_csv(manual_pairs)
    x = pairs.arduino_ms.to_numpy(float) / 1000
    y = pairs.ppd_time_s.to_numpy(float)
    if len(x) < 3 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError('At least three finite, verified TTL pairs are required.')
    if np.any(np.diff(x) <= 0) or np.any(np.diff(y) <= 0):
        raise ValueError('TTL pairs must be strictly ordered in both clocks; unwrap Arduino rollover first.')
    a = float(np.dot(x - x.mean(), y - y.mean()) / np.dot(x - x.mean(), x - x.mean()))
    b = float(y.mean() - a * x.mean())
    residual = y - (a * x + b)
    if abs(a - 1) > .01 or np.max(np.abs(residual)) > 2 / fs:
        raise ValueError('TTL pairs do not support a reliable affine alignment. Inspect pulse matching; '
                         'no aligned output has been written.')
    pairs['predicted_ppd_time_s'] = a * x + b
    pairs['residual_ms'] = residual * 1000
    return a, b, pairs


def assign_trials(times, starts, ends, ids):
    index = np.searchsorted(starts, times, side='right') - 1
    safe = np.clip(index, 0, len(starts) - 1)
    inside = np.isfinite(times) & (index >= 0) & (times <= ends[safe] + 1e-9)
    return np.where(inside, ids[safe], 0)


def average_trials(matrix, include):
    values = matrix[include]
    n = np.isfinite(values).sum(axis=0)
    mean = np.divide(np.nansum(values, axis=0), n, out=np.full(matrix.shape[1], np.nan), where=n > 0)
    ss = np.nansum((values - mean) ** 2, axis=0)
    sem = np.sqrt(np.divide(ss, n * (n - 1), out=np.full_like(mean, np.nan), where=n > 1))
    return mean, sem, n


def json_safe(value):
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(f'{value:.8g}') if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def make_plots(out, session, licks, trials, relative_time, matrix, include, pairs):
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(4, 1, figsize=(15, 9), sharex=True, constrained_layout=True)
    for ax, key, label, color in zip(axes[:3], ('signal_v', 'control_v', 'dff_percent'),
                                    ('Signal (V)', 'Control (V)', 'dF/F (%)'), ('#137d68', '#ab6f27', '#375ca8')):
        ax.plot(session.time_session_s, session[key], lw=.45, color=color)
        ax.set_ylabel(label)
    axes[3].vlines(licks.time_session_s, 0, 1, color='#302a47', lw=.8)
    axes[3].set(ylim=(-.1, 1.1), yticks=[], ylabel='Lick', xlabel='Time since SESSION_START (s)')
    axes[3].set_xlim(0, trials.end_session_s.max())
    if session.time_session_s.iloc[0] > 0:
        for ax in axes:
            ax.axvspan(0, session.time_session_s.iloc[0], color='#d1d5db', alpha=.6)
    fig.suptitle('TTL-aligned signal, control, processed dF/F, and licking')
    fig.savefig(out / 'aligned_session.png', dpi=170)
    plt.close(fig)

    mean, sem, n = average_trials(matrix, include)
    common = (n == include.sum()) & (n > 0)
    mean[~common] = np.nan
    sem[~common] = np.nan
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True, constrained_layout=True,
                             gridspec_kw={'height_ratios': [2, 1, 1.5]})
    axes[0].fill_between(relative_time, mean-sem, mean+sem, color='#537fb9', alpha=.25, label='Mean ± SEM')
    axes[0].plot(relative_time, mean, color='#24529c', lw=2, label=f'Mean ({include.sum()} trials)')
    for key, label, color in [('cue_relative_s', 'Cue ACK (median)', '#137d68'),
                              ('reward_relative_s', 'Reward (median)', '#ab6f27')]:
        if trials.loc[include, key].notna().any():
            axes[0].axvline(trials.loc[include, key].median(), color=color, ls='--', label=label)
    axes[0].set_ylabel('dF/F (%)')
    axes[0].legend(fontsize=8)
    axes[1].plot(relative_time[common], n[common], color='#24529c')
    axes[1].set_ylabel('Contributing trials')
    for row in trials.loc[include].itertuples():
        lt = licks.loc[licks.trial_id == row.trial_id, 'time_session_s'].to_numpy() - row.start_session_s
        axes[2].scatter(lt, np.full(len(lt), row.trial_id), marker='|', s=14, color='#302a47')
    axes[2].set(xlabel='Time from TRIAL_START (s; photometry clock)', ylabel='Lick / trial ID',
                xlim=(0, relative_time[np.flatnonzero(common)[-1]] if common.any() else relative_time[-1]))
    fig.suptitle('Trial-aligned dF/F average and lick raster; no time warping')
    fig.savefig(out / 'dff_average.png', dpi=180)
    fig.savefig(out / 'dff_average.svg')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 3.5), constrained_layout=True)
    ax.scatter(pairs.ppd_time_s, pairs.residual_ms, s=10, color='#137d68')
    ax.axhline(0, color='gray', lw=.7)
    ax.set(xlabel='PPD time (s)', ylabel='TTL residual (ms)', title='Alignment quality: matched digital rising edges')
    fig.savefig(out / 'ttl_alignment_qc.png', dpi=170)
    plt.close(fig)


def run(args):
    out = Path(args.out)
    events = pd.read_csv(args.events, dtype={'Value': str})
    events['Arduino_ms'] = pd.to_numeric(events.Arduino_ms, errors='coerce')
    board = events[(events.Source == 'arduino') & events.Arduino_ms.notna()]
    if np.any(np.diff(board.Arduino_ms) < 0):
        raise ValueError('Arduino clock reset or rollover: split/unwrap the session before alignment.')
    session_starts = board[board.Event == 'SESSION_START']
    if len(session_starts) != 1:
        raise ValueError('Exactly one SESSION_START is required.')
    data = import_ppd(args.ppd, low_pass=None, high_pass=None)
    fs = float(data['sampling_rate'])
    ppd_time = data['time'] / 1000
    a, b, pairs = fit_sync(events, data[f'pulse_times_{args.digital}'] / 1000, fs, args.sync_pairs)
    map_time = lambda ms: a * np.asarray(ms, dtype=float) / 1000 + b
    origin = float(map_time(session_starts.Arduino_ms.iloc[0]))
    trial_starts = board[board.Event == 'TRIAL_START'].copy()
    trial_ends = board[board.Event == 'TRIAL_END'].copy()
    trial_starts['trial_id'] = trial_starts.Value.astype(int)
    trial_ends['trial_id'] = trial_ends.Value.astype(int)
    if trial_starts.trial_id.duplicated().any() or trial_ends.trial_id.duplicated().any():
        raise ValueError('Duplicate trial boundaries.')
    trial_rows = trial_starts.merge(trial_ends[['trial_id', 'Arduino_ms']], on='trial_id', suffixes=('_start', '_end'))
    trial_rows = trial_rows.sort_values('Arduino_ms_start')
    if not len(trial_rows):
        raise ValueError('No completed trials.')
    ids = trial_rows.trial_id.to_numpy(int)
    starts = map_time(trial_rows.Arduino_ms_start)
    ends = map_time(trial_rows.Arduino_ms_end)
    if np.any(ends <= starts) or np.any(starts[1:] < ends[:-1]):
        raise ValueError('Invalid or overlapping trial windows.')
    excluded = load_exclusions(args)
    if excluded - set(ids):
        raise ValueError(f'Unknown completed trial IDs in exclusions: {sorted(excluded-set(ids))}')
    # Define the analysis window before any filtering or fitted correction.
    mask = (ppd_time >= origin) & (ppd_time <= ends[-1])
    if not mask.any():
        raise ValueError('PPD and completed behavior session do not overlap.')
    cropped = dict(data)
    for key, value in data.items():
        if isinstance(value, np.ndarray) and value.shape == ppd_time.shape:
            cropped[key] = value[mask]
    try:
        components = preprocess_data(cropped, signal=args.signal, control=args.control,
                                     low_pass=args.low_pass, normalisation=None, plot=False,
                                     return_components=True)
    except (ValueError, RuntimeError) as error:
        raise ValueError(f'Session-only preprocessing failed (available duration {mask.sum()/fs:.3f}s): {error}') from error
    processed = np.full(ppd_time.shape, np.nan)
    f0 = np.full(ppd_time.shape, np.nan)
    # One denominator for every sample/trial, including all ITIs in the cropped session.
    session_f0 = float(np.mean(components['signal_expfit']))
    if not np.isfinite(session_f0) or session_f0 <= 0:
        raise ValueError('The session-wide mean exponential fit must be finite and positive.')
    processed[mask] = 100 * components['signal_mc'] / session_f0
    f0[mask] = session_f0
    if not np.all(np.isfinite(processed[mask])) or not np.all(np.isfinite(f0[mask])) or np.any(f0[mask] <= 0):
        raise ValueError('Session preprocessing must return finite dF/F and positive F0 per sample.')
    selected_time = ppd_time[mask]
    all_trial_ids = assign_trials(ppd_time, starts, ends, ids)
    events['time_ppd_s'] = map_time(events.Arduino_ms)
    events['time_session_s'] = events.time_ppd_s - origin
    events['time_source'] = np.where(events.Arduino_ms.notna(), 'arduino_TTL_affine', 'not_mapped_host_clock')
    events['trial_id'] = assign_trials(events.time_ppd_s.to_numpy(), starts, ends, ids)
    within_session = events.time_ppd_s.between(origin, ends[-1])
    licks = events[(events.Event == 'LICK') & within_session].copy()
    licks['ppd_recorded'] = licks.time_ppd_s.between(ppd_time[0], ppd_time[-1])
    lick_count = np.zeros(len(ppd_time), dtype=int)
    bins = np.rint(licks.loc[licks.ppd_recorded, 'time_ppd_s'].to_numpy() * fs).astype(int)
    np.add.at(lick_count, bins.clip(np.flatnonzero(mask)[0], np.flatnonzero(mask)[-1]), 1)
    session = pd.DataFrame({'ppd_sample_index': np.flatnonzero(mask), 'time_ppd_s': selected_time,
                            'time_session_s': selected_time-origin,
                            'signal_v': data[args.signal][mask], 'control_v': data[args.control][mask],
                            'dff_percent': processed[mask], 'f0_v': f0[mask],
                            'bleaching_fit_v': components['signal_expfit'], 'lick_count': lick_count[mask],
                            'digital_1': data['digital_1'][mask], 'digital_2': data['digital_2'][mask],
                            'trial_id': all_trial_ids[mask]})
    relative_time = np.arange(int(np.floor((ends-starts).max()*fs)) + 1) / fs
    matrices = {key: np.full((len(ids), len(relative_time)), np.nan) for key in ('signal_v','control_v','dff_percent','f0_v')}
    signals = {'signal_v': data[args.signal], 'control_v': data[args.control], 'dff_percent': processed, 'f0_v': f0}
    summary_rows, lick_relative = [], []
    for i, (trial_id, start, end) in enumerate(zip(ids, starts, ends)):
        query = start + relative_time
        valid = (query <= end + 1e-9) & (query >= selected_time[0]) & (query <= selected_time[-1])
        for key, signal in signals.items():
            matrices[key][i, valid] = np.interp(query[valid], selected_time, signal[mask])
        native = (all_trial_ids == trial_id) & mask
        full = start >= ppd_time[0] and end <= ppd_time[-1]
        row = {'trial_id': int(trial_id), 'start_ppd_s': start, 'end_ppd_s': end,
               'start_session_s': start-origin, 'end_session_s': end-origin, 'duration_s': end-start,
               'photometry_complete': bool(full), 'included': bool(full and trial_id not in excluded),
               'exclusion_reason': 'user' if trial_id in excluded else ('' if full else 'incomplete_photometry'),
               'native_sample_count': int(native.sum()),
               'mean_dff_percent': float(np.mean(processed[native])) if native.any() else np.nan,
               'mean_f0_v': session_f0 if native.any() else np.nan,
               'mean_signal_v': float(np.mean(data[args.signal][native])) if native.any() else np.nan,
               'lick_count': int((licks.trial_id == trial_id).sum())}
        for event, column in [('CUE_ON','cue_relative_s'), ('CUE_OFF','cue_off_relative_s'), ('REWARD_ON','reward_relative_s')]:
            ev = events[(events.Event == event) & (events.Value == str(trial_id))]
            row[column] = float(ev.time_ppd_s.iloc[0]-start) if len(ev) else np.nan
        summary_rows.append(row)
        lick_relative.append((licks.loc[licks.trial_id == trial_id, 'time_ppd_s']-start).tolist())
    trials = pd.DataFrame(summary_rows)
    trials['stage'] = stage_labels(len(trials))
    include = trials.included.to_numpy(bool)
    mean, sem, count = average_trials(matrices['dff_percent'], include)
    average = pd.DataFrame({'time_from_trial_start_s': relative_time, 'mean_dff_percent': mean,
                            'sem_dff_percent': sem, 'n_trials': count})
    common = (count == include.sum()) & (count > 0)
    qc = {'ppd_file': Path(args.ppd).name, 'ppd_subject_ID': str(data['subject_ID']),
          'ppd_sha256': hashlib.sha256(Path(args.ppd).read_bytes()).hexdigest(),
          'events_sha256': hashlib.sha256(Path(args.events).read_bytes()).hexdigest(),
          'sampling_rate_hz': fs, 'digital_channel': args.digital, 'matched_ttl_count': len(pairs),
          'mapping': 'ppd_time_s = slope * (Arduino_ms / 1000) + intercept_s',
          'slope': a, 'intercept_s': b, 'relative_clock_drift_ppm': (a-1)*1e6,
          'ttl_rms_error_ms': float(np.sqrt(np.mean(pairs.residual_ms**2))),
          'ttl_max_abs_error_ms': float(np.abs(pairs.residual_ms).max()),
          'session_start_ppd_s': origin, 'last_trial_end_ppd_s': float(ends[-1]),
          'session_duration_s': float(ends[-1]-origin),
          'missing_start_photometry_s': float(max(0, ppd_time[0]-origin)),
          'complete_behavior_trials': len(trials), 'included_trials': int(include.sum()),
          'excluded_trials': trials.loc[~include, 'trial_id'].tolist(),
          'incomplete_behavior_trials': sorted(set(trial_starts.trial_id)-set(ids)),
          'lick_events_in_session': len(licks), 'lick_events_in_trials': int((licks.trial_id > 0).sum()),
          'signal_channel': args.signal, 'control_channel': args.control, 'low_pass_hz': args.low_pass,
          'preprocessing': 'Supplied preprocess_data: lowpass -> double-exponential bleaching correction '
                           '-> control linear regression -> 100 * corrected_signal / mean(session_signal_expfit).',
          'normalisation': 'dF/F percent with one constant session denominator; no extra per-trial baseline subtraction',
          'session_f0_v': session_f0,
          'denominator_scope': 'Mean exponential fit over all recorded samples in the cropped session, including ITIs; fixed before trial exclusions and group selection.',
          'fit_scope': 'SESSION_START through last completed TRIAL_END, cropped BEFORE filtering and all fits; trial exclusions affect averages only.',
          'preprocessing_window_ppd_s': [float(selected_time[0]), float(selected_time[-1])],
          'stage_definition': 'Chronological completed trials before exclusions: floor(N/3), floor(2N/3); 100 -> 33/33/34.',
          'host_events': 'Rows without Arduino_ms are left unmapped; CUE_ON is an Arduino screen-ACK marker, not photons.',
          'trial_alignment': 'TRIAL_START; fixed seconds on PPD clock; no duration stretching; NaN after each TRIAL_END. '
                             'Primary average uses common support of all included trials; available-support CSV is separate.',
          'mean_of_trial_means_percent': float(trials.loc[include, 'mean_dff_percent'].mean()) if include.any() else None,
          'clipping_samples': {k: int(v.sum()) for k,v in data.items() if k.endswith('_clipping')}}
    out.mkdir(parents=True, exist_ok=True)
    session.to_csv(out/'processed_data.csv', index=False, float_format='%.9g')
    session[session.trial_id > 0].to_csv(out/'trials_only.csv', index=False, float_format='%.9g')
    events.to_csv(out/'events_aligned.csv', index=False, float_format='%.9g')
    events[within_session].to_csv(out/'events_session.csv', index=False, float_format='%.9g')
    licks.to_csv(out/'lick_events.csv', index=False, float_format='%.9g')
    pairs.to_csv(out/'ttl_matches.csv', index=False, float_format='%.12g')
    trials.to_csv(out/'trial_summary.csv', index=False, float_format='%.9g')
    average[common].to_csv(out/'dff_average.csv', index=False, float_format='%.9g')
    average.to_csv(out/'dff_average_available_support.csv', index=False, float_format='%.9g')
    pd.DataFrame(matrices['dff_percent'].T, index=relative_time,
                 columns=[f'trial_{i}' for i in ids]).rename_axis('time_from_trial_start_s').to_csv(
                     out/'trial_dff_matrix.csv', float_format='%.9g')
    np.savez_compressed(out/'processed_data.npz', **{k:session[k].to_numpy() for k in session})
    np.savez_compressed(out/'trial_data.npz', trial_ids=ids, time_from_trial_start_s=relative_time, **matrices)
    (out/'alignment_qc.json').write_text(json.dumps(qc, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    selection = {key: qc[key] for key in ('ppd_file','ppd_sha256','events_sha256')}
    selection['exclude_trials'] = trials.loc[~include, 'trial_id'].tolist()
    (out/'trial_selection.json').write_text(json.dumps(selection, indent=2), encoding='utf-8')
    make_plots(out, session, licks, trials, relative_time, matrices['dff_percent'], include, pairs)
    save_comparisons(out, trials, relative_time, matrices, include, average_trials)
    # The review overview is reduced for rendering only. CSV/NPZ and trial data retain full resolution.
    step = max(1, len(session)//16000)
    display = session.iloc[::step]
    payload = {'qc': qc, 'overview': {k: display[k].to_numpy() for k in ('time_session_s','signal_v','control_v','dff_percent','f0_v')},
               'overview_step': step, 'licks': licks.time_session_s.to_numpy(), 'trials': trials.to_dict('records'),
               'relative_time': relative_time, 'matrices': matrices, 'trial_licks': lick_relative,
               'session_means': {'start_s': float(session.time_session_s.iloc[0]), 'fs': fs,
                   'prefix': {key: np.r_[0., np.cumsum(session[key].to_numpy())].tolist() for key in ('signal_v','dff_percent','f0_v')}}}
    template = Path(__file__).with_name('review_template.html').read_text(encoding='utf-8')
    template = template.replace('__COMPARISON_SCRIPT__', Path(__file__).with_name('trial_comparison.js').read_text(encoding='utf-8'))
    safe_payload = json_safe(payload)
    safe_payload['qc']['session_f0_v'] = session_f0
    safe_payload['session_means'] = payload['session_means']  # Preserve precision for differences of cumulative sums.
    blob = json.dumps(safe_payload, ensure_ascii=False, separators=(',',':'), allow_nan=False).replace('</', '<\\/')
    (out/'review.html').write_text(template.replace('__ANALYSIS_DATA__', blob), encoding='utf-8')
    print(json.dumps(qc, indent=2, ensure_ascii=False))
    return qc


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ppd', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--out', default='results')
    parser.add_argument('--digital', type=int, choices=(1,2), default=1)
    parser.add_argument('--signal', default='analog_2')
    parser.add_argument('--control', default='analog_1')
    parser.add_argument('--low-pass', type=float, default=20)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--exclude-trials', default='', help='Example: 3,7,12-15')
    group.add_argument('--selection-json', help='Saved trial_selection.json for these exact input files')
    parser.add_argument('--sync-pairs', help='Verified pairs CSV, required if automatic pulse counts differ')
    run(parser.parse_args())
