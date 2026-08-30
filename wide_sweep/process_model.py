"""
Faithful re-implementation of the shared setup + all controller designs from
Lab_Scale_CSTR_Simulation_2_corrected.ipynb (uploaded, 85-cell version with the
"Reference-tuned and IMC-derived controllers" section / C1-C4/C2b/C4b).

This module reproduces, headlessly (no plotting), every number needed to run the
11 controllers: Conventional PI, IMC PI, Horn IMC-PI, IMC-scheduled PID,
Pure gain-scheduled PID, C1, C2, C3, C4, C2b, C4b.

Nothing here changes the notebook's formulas -- it is a literal transcription so the
wide-sweep driver runs the *same* designs the notebook produced (03_Tunings /
05_Schedules), not a re-derivation.
"""
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve

# ============================================================
# PROCESS CONSTANTS (lab-scale CSTR)
# ============================================================
Qa = 0.005 * 1000   # mL/s
Ca = 0.01            # mol/L
Cb = 0.01            # mol/L
Kw = 1e-14
V = 10 * 1000        # mL

# ============================================================
# CHARGE-BALANCE <-> pH CONVERSIONS
# ============================================================
def x_to_pH(x):
    H = (x + np.sqrt(x**2 + 4 * Kw)) / 2
    return -np.log10(H)

def pH_to_x(pH):
    H = 10.0 ** (-pH)
    return H - Kw / H

def residual_Qb(Qb, Qa_val, Ca_val, Cb_val, x_target):
    return (Qa_val * Ca_val - Qb * Cb_val) / (Qa_val + Qb) - x_target

def solve_Qb_for_pH(pH_target, guess, Ca_val=None):
    Ca_val = Ca if Ca_val is None else Ca_val
    x_target = pH_to_x(pH_target)
    return fsolve(residual_Qb, guess, args=(Qa, Ca_val, Cb, x_target))[0]

def default_F_max(pH_ref=9.0):
    x_ref = pH_to_x(pH_ref)
    Qb_ref = fsolve(residual_Qb, 1e-3, args=(Qa, Ca, Cb, x_ref))[0]
    return max(2 * Qb_ref, 0.1)

F_MAX = default_F_max()

# ============================================================
# STEP-TEST ROUTINE (process identification) -- no plotting
# ============================================================
def _time_to_percent_change(pc, initial_val, final_val, time_arr, val_arr, step_t):
    total_change = final_val - initial_val
    if abs(total_change) < 1e-6:
        return np.nan
    target = initial_val + pc * total_change
    post = time_arr >= step_t
    t_resp, v_resp = time_arr[post], val_arr[post]
    if len(t_resp) == 0:
        return np.nan
    cross = np.where(v_resp >= target)[0] if total_change > 0 else np.where(v_resp <= target)[0]
    if len(cross) == 0:
        return np.nan
    idx = cross[0]
    if idx == 0:
        return t_resp[idx] - step_t
    t1, v1 = t_resp[idx - 1], v_resp[idx - 1]
    t2, v2 = t_resp[idx], v_resp[idx]
    if v2 == v1:
        return t2 - step_t
    return (t1 + (target - v1) * (t2 - t1) / (v2 - v1)) - step_t


def run_step_test(pH_target, step_pct, Qb0_guess, region_label="",
                   t_step=2000, t_step2=20000, tend=30000, n=600):
    Qb0 = solve_Qb_for_pH(pH_target, Qb0_guess)
    Qb_new = (1 + step_pct) * Qb0

    def dxdt(t, x):
        if t < t_step:
            Qb = 0.0
        elif t < t_step2:
            Qb = Qb0
        else:
            Qb = Qb_new
        Fout = Qa + Qb
        dx = (Qa * Ca / V) + (Qb * (-Cb) / V) - (Fout / V) * x[0]
        return [dx]

    t_eval = np.linspace(0, tend, n)
    sol = solve_ivp(dxdt, (0, tend), [Ca], t_eval=t_eval)
    pH = x_to_pH(sol.y[0])

    end_settling = t_step2 + (tend - t_step2) * 0.75
    idx_ss = sol.t >= end_settling
    pH_ss = np.mean(pH[idx_ss]) if np.any(idx_ss) else pH[-1]
    delta_Y = pH_ss - pH_target

    t63 = _time_to_percent_change(0.632, pH_target, pH_ss, sol.t, pH, t_step2)
    t28 = _time_to_percent_change(0.283, pH_target, pH_ss, sol.t, pH, t_step2)

    Kp = delta_Y / (Qb_new - Qb0)
    tau = 1.5 * (t63 - t28)
    theta = abs(t63 - tau)
    return Kp, tau, theta


Kp_ac, tau_ac, theta_ac = run_step_test(pH_target=4, step_pct=0.0125, Qb0_guess=0.05, region_label="Acidic")
Kp_neu, tau_neu, theta_neu = run_step_test(pH_target=6, step_pct=-0.0010, Qb0_guess=5.0, region_label="Near-neutral")
Kp_alk, tau_alk, theta_alk = run_step_test(pH_target=9, step_pct=0.0500, Qb0_guess=5.0, region_label="Alkaline")

Kp = (Kp_ac + Kp_neu + Kp_alk) / 3
tau = (tau_ac + tau_neu + tau_alk) / 3
theta = (theta_ac + theta_neu + theta_alk) / 3

# Conventional PI (Ziegler-Nichols open-loop, averaged model)
Kc = 0.9 * tau / (Kp * theta)
tau_i = 3.33 * theta

# ============================================================
# IMC (Rivera/Morari/Skogestad)
# ============================================================
def imc_pid_rivera(Kp_, tau_, theta_, lam):
    Kc_ = (2 * tau_ + theta_) / (Kp_ * (2 * lam + theta_))
    Ti_ = tau_ + theta_ / 2
    Td_ = tau_ * theta_ / (2 * tau_ + theta_)
    return Kc_, Ti_, Td_

LAMBDA_MULTIPLIER = 2.25
l_imc = LAMBDA_MULTIPLIER * theta
Kc_imc, Ti_imc, Td_imc = imc_pid_rivera(Kp, tau, theta, l_imc)

# ============================================================
# Frequency response / ultimate gain-period (Pade, used only for tuning rules)
# ============================================================
def calculate_bode_data(Kp_val, tau_val, theta_val, omega_values):
    mag_term1 = Kp_val / np.sqrt(1 + (tau_val * omega_values) ** 2)
    phase_term1 = -np.arctan(tau_val * omega_values)
    phase_term2 = -2 * np.arctan(theta_val * omega_values / 2)
    return mag_term1, phase_term1 + phase_term2


def find_ultimate_gain_period(Kp_val, tau_val, theta_val, omega_values):
    theta_val = max(1e-3, theta_val)
    magnitude, phase = calculate_bode_data(Kp_val, tau_val, theta_val, omega_values)
    crossings = np.where(np.diff(np.sign(phase + np.pi)))[0]
    if len(crossings) == 0:
        return np.nan, np.nan, magnitude, phase
    idx = crossings[0]
    w1, p1 = omega_values[idx], phase[idx]
    w2, p2 = omega_values[idx + 1], phase[idx + 1]
    omega_u = w1 + (w2 - w1) * (-np.pi - p1) / (p2 - p1)
    mag_u = np.interp(omega_u, omega_values, magnitude)
    Ku = 1 / mag_u
    Pu = 2 * np.pi / omega_u
    return Ku, Pu, magnitude, phase


omega = np.logspace(-3, 1, 500)
Ku, Pu, _, _ = find_ultimate_gain_period(Kp, tau, theta, omega)

regions = {'Acidic': (Kp_ac, tau_ac, theta_ac), 'Near-neutral': (Kp_neu, tau_neu, theta_neu),
           'Alkaline': (Kp_alk, tau_alk, theta_alk)}
bode_results = {name: find_ultimate_gain_period(Kp_r, tau_r, theta_r, omega)
                 for name, (Kp_r, tau_r, theta_r) in regions.items()}
Ku_ac_region, Pu_ac_region = bode_results['Acidic'][:2]
Ku_neu_region, Pu_neu_region = bode_results['Near-neutral'][:2]
Ku_alk_region, Pu_alk_region = bode_results['Alkaline'][:2]

# ============================================================
# IMC-scheduled PID (hand-tuned per-region lambda multipliers, existing hybrid)
# ============================================================
ACIDIC_LAMBDA_MULTIPLIER = 3
NEAR_NEUTRAL_LAMBDA_MULTIPLIER = 20
ALKALINE_LAMBDA_MULTIPLIER = 20

l_imc_ac = max(0.1, ACIDIC_LAMBDA_MULTIPLIER * theta_ac)
Kc_imc_ac, Ti_imc_ac, Td_imc_ac = imc_pid_rivera(Kp_ac, tau_ac, theta_ac, l_imc_ac)

l_imc_neu = max(0.1, NEAR_NEUTRAL_LAMBDA_MULTIPLIER * theta_neu)
Kc_imc_neu, Ti_imc_neu, Td_imc_neu = imc_pid_rivera(Kp_neu, tau_neu, theta_neu, l_imc_neu)

theta_alk_pos = max(1e-6, theta_alk)
l_imc_alk = max(0.1, ALKALINE_LAMBDA_MULTIPLIER * theta_alk_pos)
Kc_imc_alk, Ti_imc_alk, Td_imc_alk = imc_pid_rivera(Kp_alk, tau_alk, theta_alk_pos, l_imc_alk)

PH_7_5_KC_MULTIPLIER = 0.36


class PiecewiseLinearGainController:
    def __init__(self, breakpoints):
        self.breakpoints = sorted(breakpoints, key=lambda p: p[0])
        if len(self.breakpoints) < 2:
            raise ValueError("At least two breakpoints are required for interpolation.")

    def calculate_gain(self, current_pv):
        bp = self.breakpoints
        if current_pv <= bp[0][0]:
            return bp[0][1]
        if current_pv >= bp[-1][0]:
            return bp[-1][1]
        for (x1, y1), (x2, y2) in zip(bp[:-1], bp[1:]):
            if x1 <= current_pv <= x2:
                if x2 == x1:
                    return y1
                return y1 + (current_pv - x1) * (y2 - y1) / (x2 - x1)


kc_breakpoints_imc = [
    (0.0, Kc_imc_ac), (5.5, Kc_imc_neu), (7.5, Kc_imc_neu * PH_7_5_KC_MULTIPLIER),
    (8.5, Kc_imc_neu), (9.5, Kc_imc_alk), (14.0, Kc_imc_alk),
]
ti_breakpoints_imc = [
    (0.0, Ti_imc_ac), (5.5, Ti_imc_ac), (7.5, Ti_imc_neu),
    (8.5, Ti_imc_neu), (9.5, Ti_imc_alk), (14.0, Ti_imc_alk),
]
td_breakpoints_imc = [
    (0.0, Td_imc_ac), (5.5, Td_imc_ac), (7.5, Td_imc_neu),
    (8.5, Td_imc_neu), (9.5, Td_imc_alk), (14.0, Td_imc_alk),
]
kc_scheduler_imc = PiecewiseLinearGainController(kc_breakpoints_imc)
ti_scheduler_imc = PiecewiseLinearGainController(ti_breakpoints_imc)
td_scheduler_imc = PiecewiseLinearGainController(td_breakpoints_imc)

# ============================================================
# Horn IMC-PI
# ============================================================
def imc_pid_horn(Kp_, tau_, theta_, lam):
    if not (theta_ < lam < tau_):
        raise ValueError(f"lambda={lam:.2f} outside validity range ({theta_:.2f}, {tau_:.2f})")
    beta = (lam**2 * theta_ + 2 * tau_ * (theta_ * (tau_ - lam) + lam * (2 * tau_ - lam))) \
           / (tau_ * (theta_ + 2 * tau_))
    Kc_ = (2 * tau_ + theta_) / (2 * (2 * lam + theta_ - beta) * Kp_)
    Ti_ = tau_ + theta_ / 2
    Td_ = tau_ * theta_ / (2 * tau_ + theta_)
    return Kc_, Ti_, Td_, beta

Kc_imc_horn, _, _, beta_imc_horn = imc_pid_horn(Kp, tau, theta, l_imc)
Ti_imc_horn = Ti_imc
Td_imc_horn = 0.0

# ============================================================
# Titration curve + Pure gain-scheduled PID
# ============================================================
titration_Qb = np.linspace(0, 15, 2000)
titration_x = (Qa * Ca - titration_Qb * Cb) / (Qa + titration_Qb)
titration_pH = x_to_pH(titration_x)

titration_gain = np.gradient(titration_pH, titration_Qb)
gain_floor = 0.05 * np.max(titration_gain)
titration_gain_clipped = np.clip(titration_gain, gain_floor, None)

def kp_from_titration(pH_query):
    return np.interp(pH_query, titration_pH, titration_gain_clipped)

pH_ref = 7.0
Kc_zn_ref = 0.2 * Ku_neu_region
Ti_zn_ref = 2.0 * Pu_neu_region
Td_zn_ref = 0.0

kp_ref = kp_from_titration(pH_ref)
pH_schedule_grid = np.linspace(titration_pH.min(), titration_pH.max(), 60)
kc_values_pure_raw = Kc_zn_ref * kp_ref / kp_from_titration(pH_schedule_grid)
cap_multiple = 3.0
kc_values_pure = np.clip(kc_values_pure_raw, Kc_zn_ref / cap_multiple, Kc_zn_ref * cap_multiple)
kc_scheduler_pure = PiecewiseLinearGainController(list(zip(pH_schedule_grid, kc_values_pure)))
Ti_pure = Ti_zn_ref
Td_pure = Td_zn_ref
schedule_filter_tau = 60.0

# ============================================================
# Section: analytic local process gain
# ============================================================
def dx_dQb_analytic(Qb):
    return -Qa * (Ca + Cb) / (Qa + Qb) ** 2

def dpH_dx_analytic(x):
    H = (x + np.sqrt(x ** 2 + 4 * Kw)) / 2
    dH_dx = (1 + x / np.sqrt(x ** 2 + 4 * Kw)) / 2
    return -1.0 / (H * np.log(10)) * dH_dx

def local_gain_analytic(pH_query, Qb_guess=5.0):
    Qb0 = solve_Qb_for_pH(pH_query, Qb_guess)
    x0 = (Qa * Ca - Qb0 * Cb) / (Qa + Qb0)
    return dpH_dx_analytic(x0) * dx_dQb_analytic(Qb0)

# ============================================================
# Design rules (Section 2) for C1-C4b
# ============================================================
def pi_reference(Ku_val, Pu_val, f):
    return f * Ku_val, 2.0 * Pu_val, 0.0

REFERENCE_TUNING_F_DEFAULT = 0.2
IMC_LAMBDA_K_DEFAULT = 2.25

REF_PH_5 = [4, 6, 7, 8, 9]
region_map_5ref = {
    4: ('Acidic', tau_ac, theta_ac),
    6: ('Near-neutral', tau_neu, theta_neu),
    7: ('Near-neutral', tau_neu, theta_neu),
    8: ('Near-neutral', tau_neu, theta_neu),
    9: ('Alkaline', tau_alk, theta_alk),
}

def build_C1(f):
    Kc1, Ti1, Td1 = pi_reference(Ku_neu_region, Pu_neu_region, f)
    return dict(Kc=Kc1, Ti=Ti1, Td=Td1)

def build_C2(f):
    Kc_ac, Ti_ac, _ = pi_reference(Ku_ac_region, Pu_ac_region, f)
    Kc_neu, Ti_neu, _ = pi_reference(Ku_neu_region, Pu_neu_region, f)
    Kc_alk, Ti_alk, _ = pi_reference(Ku_alk_region, Pu_alk_region, f)
    kc_sched = PiecewiseLinearGainController([(4, Kc_ac), (6, Kc_neu), (9, Kc_alk)])
    ti_sched = PiecewiseLinearGainController([(4, Ti_ac), (6, Ti_neu), (9, Ti_alk)])
    return dict(Kc=kc_sched, Ti=ti_sched, Td=0.0, schedule_filter_tau=schedule_filter_tau)

def build_C3(k):
    Kc3, Ti3, _ = imc_pid_rivera(Kp, tau, theta, k * theta)
    return dict(Kc=Kc3, Ti=Ti3, Td=0.0)

def build_C4(k):
    Kc_ac, Ti_ac, Td_ac = imc_pid_rivera(Kp_ac, tau_ac, theta_ac, k * theta_ac)
    Kc_neu, Ti_neu, Td_neu = imc_pid_rivera(Kp_neu, tau_neu, theta_neu, k * theta_neu)
    Kc_alk, Ti_alk, Td_alk = imc_pid_rivera(Kp_alk, tau_alk, theta_alk, k * theta_alk)
    kc_sched = PiecewiseLinearGainController([(4, Kc_ac), (6, Kc_neu), (9, Kc_alk)])
    ti_sched = PiecewiseLinearGainController([(4, Ti_ac), (6, Ti_neu), (9, Ti_alk)])
    td_sched = PiecewiseLinearGainController([(4, Td_ac), (6, Td_neu), (9, Td_alk)])
    return dict(Kc=kc_sched, Ti=ti_sched, Td=td_sched, schedule_filter_tau=schedule_filter_tau)

def build_C2b(f):
    kc_pts, ti_pts = [], []
    for ph in REF_PH_5:
        _, tau_r, theta_r = region_map_5ref[ph]
        Kp_r = local_gain_analytic(ph)
        Ku_r, Pu_r, _, _ = find_ultimate_gain_period(Kp_r, tau_r, theta_r, omega)
        Kc_r, Ti_r, _ = pi_reference(Ku_r, Pu_r, f)
        kc_pts.append((ph, Kc_r)); ti_pts.append((ph, Ti_r))
    kc_sched = PiecewiseLinearGainController(kc_pts)
    ti_sched = PiecewiseLinearGainController(ti_pts)
    return dict(Kc=kc_sched, Ti=ti_sched, Td=0.0, schedule_filter_tau=schedule_filter_tau)

def build_C4b(k):
    kc_pts, ti_pts, td_pts = [], [], []
    for ph in REF_PH_5:
        _, tau_r, theta_r = region_map_5ref[ph]
        Kp_r = local_gain_analytic(ph)
        Kc_r, Ti_r, Td_r = imc_pid_rivera(Kp_r, tau_r, theta_r, k * theta_r)
        kc_pts.append((ph, Kc_r)); ti_pts.append((ph, Ti_r)); td_pts.append((ph, Td_r))
    kc_sched = PiecewiseLinearGainController(kc_pts)
    ti_sched = PiecewiseLinearGainController(ti_pts)
    td_sched = PiecewiseLinearGainController(td_pts)
    return dict(Kc=kc_sched, Ti=ti_sched, Td=td_sched, schedule_filter_tau=schedule_filter_tau)

CONTROLLER_BUILDERS = {
    'C1': ('f', build_C1), 'C2': ('f', build_C2), 'C2b': ('f', build_C2b),
    'C3': ('k', build_C3), 'C4': ('k', build_C4), 'C4b': ('k', build_C4b),
}
