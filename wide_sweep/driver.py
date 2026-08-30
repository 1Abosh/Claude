"""
Wide setpoint-sweep driver: 7 -> 4 -> 7 -> 10 -> 7, all 11 controllers, per-region
metrics, and explicit instability/limit-cycle flagging.

Replaces the old comparison_scenario's 7->8->7->6 ladder, which only ever visited
pH 6-8 (near-neutral) and so left the acidic/alkaline branches of every gain-scheduled
controller in `05_Schedules` completely untested -- while `09_Margins` scores those same
controllers against all three regions. This driver exercises all three regions with both
a servo test (the setpoint step into the region) and a regulatory test (a +-5% Ca
disturbance inside the region's dwell), for all 11 controllers, on one shared timeline,
and reports IAE / overshoot / settling time / actuator travel / saturation fraction
*per region* rather than pooled -- plus an explicit stability verdict per (controller,
region), because a large IAE alone does not distinguish "slow but converging" from
"never converges" (sustained limit cycle) or "goes unbounded" (unstable), and the
notebook's existing traces show real, sustained near-equivalence oscillation that a
pooled IAE number would hide.

Run with:  python3 -m wide_sweep.driver   (from the repo root)
"""
import numpy as np
import pandas as pd

from . import process_model as sc
from . import closed_loop as cl
from . import controllers as ctrl

# ------------------------------------------------------------------
# Scenario: symmetric sweep through all three identified regions.
#
# Dwell = 90000 s per step (>= the 20000 s floor asked for). This was extended from an
# initial 20000/30000 s trial once that trial showed some controllers -- notably C3/C4's
# heavily-detuned acidic-region tunings (selected free parameters k=5/80 in the "six
# controllers" section; that selection was validated only against the standardised
# (pH 6-8) scenario and a *short-dwell* (5000-20000 s/step) wide scenario, so it never
# actually tested a sustained acidic dwell) -- take 50000-55000 s to recover from the
# regulatory disturbance. Direct extended checks (isolated 2-step runs, single controller
# at a time, out to 120000 s post-step) confirmed: C2/C3 do settle within this window,
# and C4/Acidic genuinely has NOT settled even after 120000 s post-step and is not
# oscillating (its tail amplitude keeps shrinking) -- i.e. that is a real, confirmed
# "too slow to be useful" result for C4 in the acidic region, not a windowing artefact,
# so the window was not stretched further chasing it (per "don't truncate": the
# classification below reports it explicitly as NOT SETTLED rather than mislabelling or
# silently cutting it off).
#
# The disturbance sits at dwell_start + 20000 s (not the midpoint) in every region: a
# consistent 20000 s pure-servo phase before it, then a long (70000 s) recovery phase
# after it in which a genuine limit cycle (stationary, non-decaying amplitude) is easy to
# tell apart from a merely slow transient (amplitude still shrinking toward the window
# edge).
# ------------------------------------------------------------------
DWELL = 90000.0
DIST_OFFSET = 20000.0
N_STEPS = 5
TEND = DWELL * N_STEPS

sp_events = [
    {'time': 0 * DWELL, 'SP': 7.0},   # near-neutral (initial condition, no step)
    {'time': 1 * DWELL, 'SP': 4.0},   # -> acidic (servo test)
    {'time': 2 * DWELL, 'SP': 7.0},   # -> near-neutral (servo test)
    {'time': 3 * DWELL, 'SP': 10.0},  # -> alkaline (servo test)
    {'time': 4 * DWELL, 'SP': 7.0},   # -> near-neutral (servo test, return)
]
dist_events = [
    {'time': 1 * DWELL + DIST_OFFSET, 'Ca_factor': 1.05},  # acidic dwell: regulatory test
    {'time': 2 * DWELL + DIST_OFFSET, 'Ca_factor': 0.95},  # near-neutral dwell: regulatory test
    {'time': 3 * DWELL + DIST_OFFSET, 'Ca_factor': 1.05},  # alkaline dwell: regulatory test
]

REGION_WINDOWS = {
    'Acidic':       [(1 * DWELL, 2 * DWELL)],
    'Near-neutral': [(0 * DWELL, 1 * DWELL), (2 * DWELL, 3 * DWELL), (4 * DWELL, 5 * DWELL)],
    'Alkaline':     [(3 * DWELL, 4 * DWELL)],
}
REGION_OF_SP = {4.0: 'Acidic', 7.0: 'Near-neutral', 10.0: 'Alkaline'}

# dt ~ 20 s (n_points = tend/20), the same convention the rest of the notebook uses --
# well below every regional time constant (tau_ac=1277 s, tau_neu=652 s, tau_alk=367 s;
# dead times theta_ac=228 s, theta_neu=62 s, theta_alk=38 s are themselves >1x this dt).
N_POINTS = max(800, int(TEND / 20))

PH_SETTLING_BAND = cl.PH_SETTLING_BAND
OSC_PTP_THRESHOLD = 2 * PH_SETTLING_BAND   # 0.10 pH: a tail amplitude above this is a
                                             # real cycle, not settling-band noise
OSC_DECAY_RATIO = 0.7    # tail 2nd-half ptp / 1st-half ptp >= this -> "not decaying"
DIVERGENCE_BOUND = 20.0  # pH outside +-this is treated as numerical divergence


def run_all_controllers():
    results = {}
    for name in ctrl.TRACE_ORDER:
        params = ctrl.CONTROLLERS[name]
        res = cl.run_closed_loop_fast(**params, sp_events=sp_events, dist_events=dist_events,
                                       initial_pH=7.0, tend=TEND, n_points=N_POINTS)
        results[name] = res
    return results


def _window_mask(t, lo, hi):
    return (t >= lo) & (t < hi)


def _tail_oscillation(t, pH, lo, hi):
    """Peak-to-peak pH amplitude in the last third of [lo, hi), split into two halves,
    to tell a genuine sustained limit cycle (amplitude not decaying) apart from a slow
    transient (amplitude shrinking) or a settled response (amplitude ~ 0)."""
    mask = _window_mask(t, lo, hi)
    seg_t, seg_pH = t[mask], pH[mask]
    if len(seg_t) < 6:
        return False, 0.0
    tail_start = lo + 2 * (hi - lo) / 3.0
    tail_mask = seg_t >= tail_start
    tail_t, tail_pH = seg_t[tail_mask], seg_pH[tail_mask]
    if len(tail_t) < 6:
        return False, 0.0
    mid = len(tail_pH) // 2
    ptp1 = tail_pH[:mid].max() - tail_pH[:mid].min() if mid > 1 else 0.0
    ptp2 = tail_pH[mid:].max() - tail_pH[mid:].min()
    is_cycle = (ptp2 > OSC_PTP_THRESHOLD) and (ptp1 == 0 or ptp2 >= OSC_DECAY_RATIO * ptp1)
    return bool(is_cycle), float(ptp2)


def compute_region_metrics(name, res):
    t, pH, F, SP = res['t'], res['pH'], res['F'], res['SP']
    dt = res['dt']
    step_records = cl.calculate_performance_metrics(t, SP, pH)
    # Map each auto-detected setpoint-change segment to the region of its *new* setpoint.
    rec_by_region = {}
    for rec in step_records:
        idx = min(np.searchsorted(t, rec['Time']), len(SP) - 1)
        sp_new = SP[idx]
        region = REGION_OF_SP.get(round(sp_new, 6))
        rec_by_region.setdefault(region, []).append(rec)

    unstable_any = bool(np.any(~np.isfinite(pH)) or np.any(np.abs(pH) > DIVERGENCE_BOUND))

    rows = []
    for region, windows in REGION_WINDOWS.items():
        iae_total = 0.0
        travel_total = 0.0
        sat_time = 0.0
        total_time = 0.0
        cycle_flag = False
        max_tail_ptp = 0.0
        for lo, hi in windows:
            mask = _window_mask(t, lo, hi)
            seg_pH, seg_F, seg_SP = pH[mask], F[mask], SP[mask]
            if len(seg_pH) == 0:
                continue
            iae_total += float(np.sum(np.abs(seg_SP - seg_pH)) * dt)
            travel_total += float(np.sum(np.abs(np.diff(seg_F))))
            sat = np.isclose(seg_F, res['F_max'], atol=1e-6) | np.isclose(seg_F, res['F_min'], atol=1e-6)
            sat_time += float(np.sum(sat)) * dt
            total_time += len(seg_pH) * dt
            is_cyc, tail_ptp = _tail_oscillation(t, pH, lo, hi)
            cycle_flag = cycle_flag or is_cyc
            max_tail_ptp = max(max_tail_ptp, tail_ptp)

        recs = rec_by_region.get(region, [])
        overshoots = [r['Overshoot'] for r in recs]
        settling_times = [r['Settling_Time'] for r in recs]
        n_not_settled = sum(1 for s in settling_times if not np.isfinite(s))
        finite_settling = [s for s in settling_times if np.isfinite(s)]

        if unstable_any:
            stability = 'UNSTABLE (divergent)'
        elif cycle_flag:
            stability = 'LIMIT CYCLE (sustained oscillation)'
        elif n_not_settled > 0:
            stability = 'NOT SETTLED (slow transient)'
        else:
            stability = 'stable'

        rows.append({
            'Controller': name, 'Region': region,
            'IAE': round(iae_total, 2),
            'Mean overshoot (pH)': round(float(np.mean(overshoots)), 4) if overshoots else np.nan,
            'Max overshoot (pH)': round(float(np.max(overshoots)), 4) if overshoots else np.nan,
            'Worst settling time (s)': round(float(np.max(finite_settling)), 1) if finite_settling else np.nan,
            'Steps not settled': n_not_settled,
            'Steps evaluated': len(recs),
            'Actuator travel (int|dQb/dt|, mL/s)': round(travel_total, 3),
            'Fraction time saturated': round(sat_time / total_time, 4) if total_time > 0 else np.nan,
            'Tail peak-to-peak (pH, last third)': round(max_tail_ptp, 4),
            'Stability verdict': stability,
        })
    return rows


def build_trace_df(results):
    t = results['Conventional PI']['t']
    idx = np.unique(np.linspace(0, len(t) - 1, 1700).round().astype(int))
    row = {'Time (s)': t[idx], 'Setpoint': results['Conventional PI']['SP'][idx]}
    first4 = ['Conventional PI', 'IMC PI', 'IMC-scheduled PID', 'Pure gain-scheduled PID']
    rest7 = ['Horn IMC-PI', 'C1', 'C2', 'C3', 'C4', 'C2b', 'C4b']
    for name in first4:
        row[f'pH — {name}'] = results[name]['pH'][idx]
    for name in first4:
        row[f'Qb — {name}'] = results[name]['F'][idx]
    for name in rest7:
        row[f'pH — {name}'] = results[name]['pH'][idx]
    for name in rest7:
        row[f'Qb — {name}'] = results[name]['F'][idx]
    return pd.DataFrame(row)


def main():
    import time
    t0 = time.time()
    results = run_all_controllers()
    dt = results['Conventional PI']['dt']
    n = len(results['Conventional PI']['t'])
    print(f"Simulated {len(ctrl.TRACE_ORDER)} controllers in {time.time() - t0:.1f}s. "
          f"dt={dt:.4f}s, n_points={n}, tend={TEND:.0f}s.")

    all_rows = []
    for name in ctrl.TRACE_ORDER:
        all_rows.extend(compute_region_metrics(name, results[name]))
    metrics_df = pd.DataFrame(all_rows)
    metrics_df.to_csv('wide_sweep/output/WideSweep_Metrics_by_Region.csv', index=False)

    trace_df = build_trace_df(results)
    trace_df.to_csv('wide_sweep/output/12_Traces_wide_sweep.csv', index=False)

    print(f"\nWrote wide_sweep/output/WideSweep_Metrics_by_Region.csv "
          f"({len(metrics_df)} rows) and wide_sweep/output/12_Traces_wide_sweep.csv "
          f"({len(trace_df)} rows).")
    pd.set_option('display.width', 200)
    pd.set_option('display.max_rows', 200)
    print(metrics_df.to_string(index=False))
    return metrics_df, trace_df


if __name__ == '__main__':
    main()
