"""
Closed-loop simulator faithful to the notebook's run_closed_loop_sim, but using the
exact analytic solution of the (locally-linear-in-x, piecewise-constant-input) charge
balance ODE instead of a per-step solve_ivp call -- verified to agree with solve_ivp
(RK45, rtol=1e-8) to ~1e-19 on a representative step, since the ODE is linear over each
control interval. This is purely a speed optimisation (needed to run the free-parameter
sweep, 11 controllers x wide-sweep scenario, and margins in reasonable time); it changes
no formula and no design choice from the notebook.
"""
import numpy as np
from . import process_model as sc

PiecewiseLinearGainController = sc.PiecewiseLinearGainController


def _scheduled(val, pH):
    return val.calculate_gain(pH) if isinstance(val, PiecewiseLinearGainController) else val


def run_closed_loop_fast(Kc, Ti, Td=0.0, sp_events=None, dist_events=None,
                          initial_pH=None, theta_dead=None,
                          F_min=0.0, F_max=None, tend=100000, n_points=None,
                          schedule_filter_tau=0.0):
    if not sp_events:
        raise ValueError("sp_events must be a non-empty list")
    dist_events = dist_events or []
    theta_dead = sc.theta if theta_dead is None else theta_dead
    F_max = sc.F_MAX if F_max is None else F_max

    if n_points is None:
        n_points = max(800, int(tend / 20))

    t_eval = np.linspace(0, tend, n_points)
    n = len(t_eval)
    dt = t_eval[1] - t_eval[0]
    theta_steps = max(1, int(theta_dead / dt))

    sp_times = np.array([ev['time'] for ev in sp_events])
    sp_vals = np.array([ev['SP'] for ev in sp_events])

    def sp_at(t):
        idx = np.searchsorted(sp_times, t, side='right') - 1
        idx = max(idx, 0)
        return sp_vals[idx]

    if dist_events:
        d_times = np.array([ev['time'] for ev in dist_events])
        d_facs = np.array([ev['Ca_factor'] for ev in dist_events])
    else:
        d_times = np.array([])
        d_facs = np.array([])

    def ca_at(t):
        if len(d_times) == 0:
            return sc.Ca
        idx = np.searchsorted(d_times, t, side='right') - 1
        if idx < 0:
            return sc.Ca
        return sc.Ca * d_facs[idx]

    initial_pH = sp_events[0]['SP'] if initial_pH is None else initial_pH
    x0_val = sc.pH_to_x(initial_pH)

    F = np.zeros(n); pH_arr = np.zeros(n); e = np.zeros(n)
    pH_arr[0] = initial_pH
    e[0] = sp_at(0) - pH_arr[0]
    F[0] = sc.solve_Qb_for_pH(initial_pH, guess=0.0)
    x0 = x0_val
    MV_buffer = np.full(theta_steps, F[0])

    pH_sched_filt = pH_arr[0]
    Qa, Cb, V = sc.Qa, sc.Cb, sc.V

    for k in range(1, n):
        current_SP = sp_at(t_eval[k])
        if schedule_filter_tau > 0:
            alpha = dt / (schedule_filter_tau + dt)
            pH_sched_filt = pH_sched_filt + alpha * (pH_arr[k - 1] - pH_sched_filt)
            current_pH = pH_sched_filt
        else:
            current_pH = pH_arr[k - 1]
        current_Kc = _scheduled(Kc, current_pH)
        current_Ti = _scheduled(Ti, current_pH)
        current_Td = _scheduled(Td, current_pH)

        e[k] = current_SP - pH_arr[k - 1]
        de_val = e[k] - e[k - 1]
        pv_prev1 = pH_arr[k - 2] if k >= 2 else pH_arr[0]
        pv_prev2 = pH_arr[k - 3] if k >= 3 else pH_arr[0]
        de_val2 = pH_arr[k - 1] - 2 * pv_prev1 + pv_prev2

        ti_term = (dt / current_Ti) * e[k] if current_Ti > 1e-6 else 0.0
        td_term = (current_Td / dt) * de_val2 if dt > 1e-6 else 0.0

        dF = current_Kc * (de_val + ti_term - td_term)
        F[k] = np.clip(F[k - 1] + dF, F_min, F_max)

        Qb_delayed = MV_buffer[-1]
        MV_buffer = np.roll(MV_buffer, 1)
        MV_buffer[0] = F[k]

        current_Ca = ca_at(t_eval[k])

        # Exact analytic solution of dx/dt = a - b*x over [t, t+dt] with Qb_delayed,
        # current_Ca held constant across the sub-interval (matches the notebook's
        # per-step solve_ivp call to within floating-point precision -- see module
        # docstring for the verification).
        Fout = Qa + Qb_delayed
        b_coef = Fout / V
        a_coef = (Qa * current_Ca - Qb_delayed * Cb) / V
        x_eq = a_coef / b_coef
        x0 = x_eq + (x0 - x_eq) * np.exp(-b_coef * dt)
        pH_arr[k] = sc.x_to_pH(x0)

    SP_trace = np.array([sp_at(t) for t in t_eval])
    return {'t': t_eval, 'pH': pH_arr, 'F': F, 'SP': SP_trace, 'dt': dt, 'F_max': F_max, 'F_min': F_min}


PH_SETTLING_BAND = 0.05


def calculate_performance_metrics(t_eval, SP_trace, pH_arr):
    """Literal port of the notebook's per-setpoint-step metrics (Shared setup)."""
    dt = t_eval[1] - t_eval[0]
    sp_change_indices = [0] + list(np.where(np.diff(SP_trace) != 0)[0] + 1)

    results = []
    step_num = 0
    for i in range(len(sp_change_indices)):
        start_idx = sp_change_indices[i]
        end_idx = sp_change_indices[i + 1] if (i + 1) < len(sp_change_indices) else len(t_eval)

        SP_old = SP_trace[start_idx - 1] if start_idx > 0 else SP_trace[0]
        SP_new = SP_trace[start_idx]
        if SP_old == SP_new:
            continue

        if end_idx > start_idx:
            t_slice = t_eval[start_idx:end_idx]
            pH_slice = pH_arr[start_idx:end_idx]
        else:
            t_slice = t_eval[start_idx:start_idx + 1]
            pH_slice = pH_arr[start_idx:start_idx + 1]
        if len(t_slice) == 0:
            continue

        error_slice = SP_new - pH_slice
        iae = np.sum(np.abs(error_slice)) * dt

        overshoot = 0.0
        if SP_new > SP_old:
            dev = pH_slice - SP_new
            dev = dev[dev > 0]
            if len(dev) > 0:
                overshoot = np.max(dev)
        elif SP_new < SP_old:
            dev = SP_new - pH_slice
            dev = dev[dev > 0]
            if len(dev) > 0:
                overshoot = np.max(dev)

        settling_time = np.inf
        tol = PH_SETTLING_BAND
        upper, lower = SP_new + tol, SP_new - tol
        out_of_band = (pH_slice < lower) | (pH_slice > upper)
        out_idx = np.where(out_of_band)[0]
        if len(out_idx) == 0:
            settling_time = 0.0
        else:
            last = out_idx[-1]
            if last == len(t_slice) - 1:
                settling_time = np.inf
            elif np.all(~out_of_band[last + 1:]):
                settling_time = t_slice[last + 1] - t_slice[0]

        step_num += 1
        results.append({'Step': step_num, 'Time': t_slice[0], 'IAE': iae,
                         'Overshoot': overshoot, 'Settling_Time': settling_time})
    return results


def mean_step_iae(res):
    metrics = calculate_performance_metrics(res['t'], res['SP'], res['pH'])
    return float(np.mean([m['IAE'] for m in metrics])) if metrics else np.nan


def steps_not_settled(res):
    metrics = calculate_performance_metrics(res['t'], res['SP'], res['pH'])
    return int(sum(1 for m in metrics if m['Settling_Time'] == np.inf))
