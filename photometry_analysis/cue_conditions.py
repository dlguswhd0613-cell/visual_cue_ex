"""Label cue identity from explicit records; average already processed trials."""
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

CONDITIONS = ('CS+', 'CS-', 'unknown')
COLORS = {'CS+': '#c05832', 'CS-': '#326fba', 'unknown': '#808080'}


def classify_trials(events, ids, schedule_path=None):
    labels, sources = {}, {}

    def add(trial, label, source):
        try:
            trial = int(str(trial))
        except ValueError as error:
            raise ValueError('Cue label has an invalid trial ID') from error
        if label not in CONDITIONS[:2]:
            raise ValueError(f'Trial {trial}: Cue must be CS+ or CS-')
        if trial in labels and labels[trial] != label:
            raise ValueError(f'Trial {trial}: conflicting CS+/CS- labels')
        labels[trial] = label
        sources.setdefault(trial, source)

    for _, row in events[events.Event.isin(('CS_PLUS_ON', 'CS_MINUS_ON'))].iterrows():
        add(row.Value, 'CS+' if row.Event == 'CS_PLUS_ON' else 'CS-', 'events')
    schedule_hash = None
    if schedule_path is not None and Path(schedule_path).is_file():
        schedule = pd.read_csv(schedule_path, dtype=str)
        if 'Cue' in schedule:
            if 'Trial' not in schedule or schedule.Trial.duplicated().any():
                raise ValueError('Cue schedule must have unique Trial IDs')
            for _, row in schedule.iterrows():
                if 'Rewarded' in schedule and row.Rewarded != ('1' if row.Cue == 'CS+' else '0'):
                    raise ValueError(f'Trial {row.Trial}: Cue and Rewarded disagree')
                add(row.Trial, row.Cue, 'schedule')
            schedule_hash = hashlib.sha256(Path(schedule_path).read_bytes()).hexdigest()
    # Reward omission alone is not evidence of a CS- cue, especially in old experiments.
    rows = pd.DataFrame({'trial_id': ids,
                         'cue_condition': [labels.get(int(i), 'unknown') for i in ids],
                         'cue_source': [sources.get(int(i), 'unavailable') for i in ids]})
    return rows, schedule_hash


def condition_end(trials, task, fallback):
    if task == 'operant' and trials.end_lick_relative_s.notna().any():
        return float(trials.end_lick_relative_s.median()) + 2
    return float(trials.duration_s.max()) if len(trials) else fallback


def condition_average(matrix, include, trials, time, condition, task, average):
    members = trials.cue_condition.to_numpy() == condition
    selected = include & members
    end = condition_end(trials.loc[members], task, float(time[-1]))
    mean, sem, n = average(matrix, selected)
    supported = (time >= -2) & (time <= end + 1e-9) & (n > 0)
    mean[~supported], sem[~supported] = np.nan, np.nan
    return mean, sem, n, end, selected


def save_condition_averages(out, trials, time, matrices, include, task, average):
    import matplotlib.pyplot as plt
    from trial_comparison import shade_average_cue
    records, summaries = [], []
    for condition in CONDITIONS:
        members = trials.cue_condition.to_numpy() == condition
        values = trials.loc[members & include, 'mean_dff_percent'].dropna()
        summaries.append(dict(cue_condition=condition, completed_trials=int(members.sum()),
            included_trials=int((members & include).sum()),
            mean_of_trial_means_dff_percent=values.mean(), sem_of_trial_means_dff_percent=values.sem()))
    for metric in ('dff_percent', 'signal_only_dff_percent'):
        fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
        right = 0.
        for condition in CONDITIONS:
            if not (trials.cue_condition == condition).any():
                continue
            mean, sem, n, end, selected = condition_average(matrices[metric], include, trials, time, condition, task, average)
            right = max(right, end)
            ax.plot(time, mean, color=COLORS[condition], label=f'{condition}: N={selected.sum()}')
            ax.fill_between(time, mean-sem, mean+sem, color=COLORS[condition], alpha=.18)
            for j in np.flatnonzero((time >= -2) & (time <= end + 1e-9)):
                records.append(dict(cue_condition=condition, metric=metric, time_from_trial_start_s=time[j],
                    mean=mean[j], sem=sem[j], n_trials=int(n[j]), included_trials=int(selected.sum())))
        shade_average_cue(ax, trials.loc[include])
        reward = trials.loc[include, 'reward_relative_s'].dropna()
        if len(reward):
            ax.axvline(reward.median(), ls='--', color='#ab6f27', label='Reward (rewarded trials)')
        ax.set(xlim=(-2, max(right, 1)), xlabel='Time from TRIAL_START (s)', ylabel='dF/F (%)',
               title=f'{metric}: cue-condition mean ± SEM (recorded samples at each time)')
        ax.legend()
        for suffix in ('png', 'svg'):
            fig.savefig(out / f'{metric}_by_condition.{suffix}', dpi=150)
        plt.close(fig)
    pd.DataFrame(records).to_csv(out/'condition_averages.csv', index=False, float_format='%.9g')
    pd.DataFrame(summaries).to_csv(out/'condition_summary.csv', index=False, float_format='%.9g')
