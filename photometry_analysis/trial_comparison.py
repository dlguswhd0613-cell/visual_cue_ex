"""Fixed chronological thirds and equal-trial-weight comparisons."""
import numpy as np
import pandas as pd

STAGES = ('early', 'middle', 'late')
METRICS = {'dff_percent': 'dF/F (%)', 'f0_v': 'F0 (V)', 'signal_v': 'Signal (V)'}


def stage_labels(n):
    """Floor boundaries: 100 trials -> 33 / 33 / 34, before exclusions."""
    labels = np.empty(n, dtype=object)
    a, b = n // 3, 2 * n // 3
    labels[:a], labels[a:b], labels[b:] = STAGES
    return labels


def comparison_curves(matrix, include, labels, average):
    # One common support across all included trials, shared by all three groups.
    support = np.all(np.isfinite(matrix[include]), axis=0) if include.any() else np.zeros(matrix.shape[1], bool)
    result = {}
    for name in STAGES:
        selected = include & (labels == name)
        mean, sem, count = average(matrix, selected)
        mean[~support], sem[~support] = np.nan, np.nan
        result[name] = (mean, sem, count, int(selected.sum()))
    return result, support


def save_comparisons(out, trials, time, matrices, include, average, constant_f0=None):
    import matplotlib.pyplot as plt
    labels = trials.stage.to_numpy()
    colors = ('#18755f', '#b47720', '#8756aa')
    rows = []
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), constrained_layout=True)
    for ax, (metric, title) in zip(axes, METRICS.items()):
        curves, support = comparison_curves(matrices[metric], include, labels, average)
        for name, color in zip(STAGES, colors):
            mean, sem, count, n = curves[name]
            if metric == 'f0_v' and n and constant_f0 is not None:
                mean[np.isfinite(mean)] = constant_f0
                sem[np.isfinite(sem)] = 0.
            ax.plot(time[support], mean[support], color=color, label=f'{name} (n={n})')
            ax.fill_between(time[support], (mean-sem)[support], (mean+sem)[support], color=color, alpha=.15)
            for j in np.flatnonzero(support & np.isfinite(mean)):
                rows.append(dict(metric=metric, stage=name, time_from_trial_start_s=time[j],
                                 mean=mean[j], sem=sem[j], n_trials=int(count[j])))
        ax.set(ylabel=title, xlabel='Time from TRIAL_START (s)')
        ax.legend()
    fig.suptitle('Early / middle / late: common support, mean ± SEM')
    fig.savefig(out/'early_middle_late.png', dpi=170)
    fig.savefig(out/'early_middle_late.svg')
    plt.close(fig)
    pd.DataFrame(rows, columns=['metric','stage','time_from_trial_start_s','mean','sem','n_trials']).to_csv(
        out/'early_middle_late.csv', index=False, float_format='%.9g')
