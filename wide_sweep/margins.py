"""
Stability margins (gain/phase margin, exact dead time) for all 11 controllers against
all 3 regions -- extends the notebook's "Stability margins" section (which already
computes this for all 11 once Horn + C1-C4b exist) into a standalone module, and adds
the verdict classification used by the existing `09_Margins` sheet:
    GM < 6 dB or PM < 30 deg   -> MARGINAL
    GM >= 10 dB and PM >= 45   -> Comfortable
    otherwise                 -> Acceptable
"""
import numpy as np
import pandas as pd

from . import process_model as sc
from . import controllers as ctrl

omega_margins = np.logspace(-7, 3, 8000)
region_pH = {'Acidic': 4, 'Near-neutral': 6, 'Alkaline': 9}


def pid_freq_response(Kc, Ti, Td, omega_values):
    imag_part = Td * omega_values - 1.0 / (Ti * omega_values)
    magnitude = Kc * np.sqrt(1 + imag_part ** 2)
    phase = np.arctan(imag_part)
    return magnitude, phase


def _eval_param(val, pH):
    return val.calculate_gain(pH) if isinstance(val, sc.PiecewiseLinearGainController) else val


def calculate_bode_data_exact(Kp_val, tau_val, theta_val, omega_values):
    """G(s) = Kp / (tau*s + 1) * exp(-j*theta*omega) -- exact dead time, no Pade
    approximation (unlike the tuning-rule Bode function in process_model.py)."""
    mag_term1 = Kp_val / np.sqrt(1 + (tau_val * omega_values) ** 2)
    phase_term1 = -np.arctan(tau_val * omega_values)
    phase_term2 = -theta_val * omega_values
    return mag_term1, phase_term1 + phase_term2


def find_margins(Kc, Ti, Td, Kp_val, tau_val, theta_val, omega_values):
    mag_G, phase_G = calculate_bode_data_exact(Kp_val, tau_val, max(1e-3, theta_val), omega_values)
    mag_C, phase_C = pid_freq_response(Kc, Ti, max(Td, 0.0), omega_values)
    mag_L = mag_G * mag_C
    phase_L = phase_G + phase_C
    mag_L_dB = 20 * np.log10(mag_L)

    gc_cross = np.where(np.diff(np.sign(mag_L_dB)))[0]
    if len(gc_cross) == 0:
        PM = np.nan
    else:
        idx = gc_cross[0]
        w1, m1 = omega_values[idx], mag_L_dB[idx]
        w2, m2 = omega_values[idx + 1], mag_L_dB[idx + 1]
        w_gc = w1 + (w2 - w1) * (0 - m1) / (m2 - m1)
        phase_at_gc = np.interp(w_gc, omega_values, phase_L)
        PM = 180 + phase_at_gc * 180 / np.pi

    pc_cross = np.where(np.diff(np.sign(phase_L + np.pi)))[0]
    if len(pc_cross) == 0:
        GM_dB = np.inf if phase_L.min() > -np.pi else np.nan
    else:
        idx = pc_cross[0]
        w1, p1 = omega_values[idx], phase_L[idx]
        w2, p2 = omega_values[idx + 1], phase_L[idx + 1]
        w_pc = w1 + (w2 - w1) * (-np.pi - p1) / (p2 - p1)
        mag_at_pc = np.interp(w_pc, omega_values, mag_L)
        GM_dB = -20 * np.log10(mag_at_pc)

    return GM_dB, PM


def verdict(gm_db, pm_deg):
    if np.isnan(gm_db) or np.isnan(pm_deg):
        return 'UNDEFINED'
    if gm_db < 6 or pm_deg < 30:
        return 'MARGINAL — below 6 dB / 30 deg'
    if gm_db >= 10 and pm_deg >= 45:
        return 'Comfortable'
    return 'Acceptable'


def compute_margins_df():
    rows = []
    for cname in ctrl.TRACE_ORDER:
        params = ctrl.CONTROLLERS[cname]
        Kc_c, Ti_c, Td_c = params['Kc'], params['Ti'], params['Td']
        for rname, (Kp_r, tau_r, theta_r) in sc.regions.items():
            ph_r = region_pH[rname]
            Kc_eval = _eval_param(Kc_c, ph_r)
            Ti_eval = _eval_param(Ti_c, ph_r)
            Td_eval = _eval_param(Td_c, ph_r)
            GM_dB, PM = find_margins(Kc_eval, Ti_eval, Td_eval, Kp_r, tau_r, theta_r, omega_margins)
            rows.append({
                'Controller': cname, 'Region': rname,
                'Kc (evaluated)': Kc_eval, 'Ti (s)': Ti_eval, 'Td (s)': Td_eval,
                'Gain margin (dB)': GM_dB, 'Phase margin (deg)': PM,
                'Verdict': verdict(GM_dB, PM),
            })
    return pd.DataFrame(rows).round(3)


if __name__ == '__main__':
    df = compute_margins_df()
    pd.set_option('display.width', 160)
    pd.set_option('display.max_rows', 200)
    print(df.to_string(index=False))
    df.to_csv('wide_sweep/output/09_Margins_all_controllers.csv', index=False)
