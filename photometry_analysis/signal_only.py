"""Trial baselines after session-wide robust time detrending of one channel."""
import numpy as np
from scipy.ndimage import uniform_filter1d
from data_import import _bisquare_fit, PreprocessingError


def signal_only_dff(signal, session_time, starts, fs, tuning, windows):
    # Nearest sample to 50 ms (half-up), with reflection only at the session boundaries.
    width = max(1, int(np.floor(.05 * fs + .5)))
    smooth = uniform_filter1d(np.asarray(signal, float), width, mode='reflect')
    t = session_time - session_time[0]
    try:
        slope, intercept, iterations = _bisquare_fit(t, smooth, tuning)
    except PreprocessingError as error:
        return (np.full(windows.shape, np.nan), np.full(len(starts), np.nan),
                dict(f0_average_v=None, valid_baselines=0, smoothing_samples=width,
                     tuning_constant=tuning, usable=False, reason=str(error)))

    corrected = smooth - (intercept + slope * t)
    baselines = np.full(len(starts), np.nan)
    for i, start in enumerate(starts):
        lo, hi = np.searchsorted(session_time, [start - 1, start])
        if start - 1 >= session_time[0] - 1/fs and hi - lo >= int(np.floor(fs)):
            baselines[i] = corrected[lo:hi].mean()
    valid = np.isfinite(baselines)
    denominator = float(np.mean(baselines[valid])) if valid.any() else None
    norm = np.full(windows.shape, np.nan)
    usable = denominator is not None and abs(denominator) > 64*np.finfo(float).eps*np.max(np.abs(signal))
    if usable:
        # windows contains the corresponding relative sample times on the session clock.
        sampled = np.interp(windows, session_time, corrected, left=np.nan, right=np.nan)
        norm = 100 * (sampled - baselines[:, None]) / denominator
    return norm, baselines, dict(f0_average_v=denominator, valid_baselines=int(valid.sum()),
                                  smoothing_samples=width, slope_v_per_s=slope, intercept_v=intercept,
                                  iterations=iterations, tuning_constant=tuning, usable=bool(usable))


def save_signal_figure(out, time, matrix, trials, include, lick, right):
    import matplotlib.pyplot as plt
    from trial_comparison import shade_average_cue
    from matplotlib.colors import Normalize
    valid = (time >= -2) & (time <= right)
    t = time[valid]
    traces = matrix[:, valid].copy()
    traces[~include] = np.nan
    n = np.isfinite(traces).sum(axis=0)
    mean = np.divide(np.nansum(traces, axis=0), n, out=np.full(len(t), np.nan), where=n>0)
    fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 8), constrained_layout=True,
                             gridspec_kw={'height_ratios': [1, 2]})
    axes[0].plot(t, mean, color='#375ca8')
    axes[0].set_ylabel('Signal-only mean dF/F (%)')
    shade_average_cue(axes[0], trials.loc[include])
    finite = traces[np.isfinite(traces)]
    scale = np.percentile(np.abs(finite), 99) if finite.size else 1.
    scale = max(scale, np.finfo(float).eps)
    dt = (time[1]-time[0])/2
    cmap = plt.get_cmap('RdBu_r').copy()
    cmap.set_bad('#d5d5d5')
    im = axes[1].imshow(traces, origin='upper', aspect='auto', interpolation='nearest',
                        extent=[t[0]-dt,t[-1]+dt,len(trials)-.5,-.5],
                        cmap=cmap, norm=Normalize(-scale, scale))
    ticks = np.unique(np.linspace(0,len(trials)-1,min(8,len(trials)),dtype=int))
    axes[1].set(yticks=ticks, yticklabels=trials.trial_id.iloc[ticks], ylabel='Trial ID',
                xlabel='Time from TRIAL_START (s)', xlim=(-2,right))
    for ax in axes:
        ax.axvline(0,color='#555',ls=':',lw=1)
        if np.isfinite(lick):
            ax.axvline(lick,color='#8756aa',ls='--',label='Session median first lick')
    if axes[0].get_legend_handles_labels()[0]:
        axes[0].legend(fontsize=8)
    fig.colorbar(im, ax=axes[1], label='Signal-only dF/F (%)', extend='both')
    fig.savefig(out/'signal_only_heatmap.png',dpi=160)
    plt.close(fig)
