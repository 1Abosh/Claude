"""
Assembles the final 11-controller dict: Conventional PI, IMC PI, IMC-scheduled PID,
Pure gain-scheduled PID, Horn IMC-PI, C1, C2, C3, C4, C2b, C4b -- i.e. every controller
in `03_Tunings`/the notebook's controller comparison, not just the four the old
comparison scenario exercised.

C1-C4b's one free parameter (f or k) is selected by the notebook's own Section 4 rule
(minimise mean IAE over the standardised+wide scenarios, subject to zero non-settled
steps on the standardised scenario) -- reproduced here verbatim so this module uses the
*designed* tunings, not a re-derivation of them.
"""
import pandas as pd

from . import process_model as sc
from . import closed_loop as cl

# ------------------------------------------------------------------
# Free-parameter sweep for C1-C4b (notebook Section 4)
# ------------------------------------------------------------------
_standardised_scenario = dict(
    sp_events=[
        {'time': 0,      'SP': 7.0},
        {'time': 60000,  'SP': 8.0},
        {'time': 80000,  'SP': 7.0},
        {'time': 100000, 'SP': 6.0},
    ],
    dist_events=[
        {'time': 20000,  'Ca_factor': 1.05},
        {'time': 65000,  'Ca_factor': 0.95},
        {'time': 120000, 'Ca_factor': 1.05},
    ],
    initial_pH=7.0, tend=170000,
)

_wide_scenario = dict(
    sp_events=[
        {'time': 0,      'SP': 4},
        {'time': 5000,   'SP': 5},
        {'time': 30000,  'SP': 6},
        {'time': 60000,  'SP': 7},
        {'time': 80000,  'SP': 8},
        {'time': 100000, 'SP': 9},
        {'time': 120000, 'SP': 10},
    ],
    initial_pH=4, tend=150000,
)

_F_GRID = [0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
_K_GRID = [1, 2.25, 5, 8, 10, 20, 40, 80, 160]


def _evaluate_candidate(builder, value):
    params = builder(value)
    res_std = cl.run_closed_loop_fast(**params, **_standardised_scenario)
    res_wide = cl.run_closed_loop_fast(**params, **_wide_scenario)
    iae_std = cl.mean_step_iae(res_std)
    iae_wide = cl.mean_step_iae(res_wide)
    return dict(mean_iae=(iae_std + iae_wide) / 2, not_settled=cl.steps_not_settled(res_std))


def _select_free_parameter(controller_id):
    param_name, builder = sc.CONTROLLER_BUILDERS[controller_id]
    grid = _F_GRID if param_name == 'f' else _K_GRID
    rows = []
    for value in grid:
        ev = _evaluate_candidate(builder, value)
        rows.append(dict(Controller=controller_id, **{param_name: value}, **ev))
    sweep_df = pd.DataFrame(rows)
    feasible = sweep_df[sweep_df['not_settled'] == 0]
    pool = feasible if len(feasible) > 0 else sweep_df
    best_row = pool.loc[pool['mean_iae'].idxmin()]
    return best_row[param_name]


SELECTED_PARAMS = {cid: _select_free_parameter(cid) for cid in sc.CONTROLLER_BUILDERS}

_final_params_C1 = sc.build_C1(SELECTED_PARAMS['C1'])
_final_params_C2 = sc.build_C2(SELECTED_PARAMS['C2'])
_final_params_C3 = sc.build_C3(SELECTED_PARAMS['C3'])
_final_params_C4 = sc.build_C4(SELECTED_PARAMS['C4'])
_final_params_C2b = sc.build_C2b(SELECTED_PARAMS['C2b'])
_final_params_C4b = sc.build_C4b(SELECTED_PARAMS['C4b'])

# Applied uniformly to every scheduled controller in this rewrite (task spec: "Schedule
# lookup uses a filtered pH, tau_f = 60 s"). Note this widens the original notebook's
# IMC-scheduled PID call, which used raw (unfiltered) pH for its own schedule lookup --
# every other scheduled controller here (Pure GS-PID, C2, C4, C2b, C4b) already used this
# filter, so this makes IMC-scheduled PID consistent with the rest rather than an outlier.
SCHEDULE_FILTER_TAU = 60.0

# First 4 (existing 12_Traces column order), then Horn + the six new controllers, in the
# exact order specified for the new trace CSV.
CONTROLLERS = {
    'Conventional PI': dict(Kc=sc.Kc, Ti=sc.tau_i, Td=0.0),
    'IMC PI': dict(Kc=sc.Kc_imc, Ti=sc.Ti_imc, Td=0.0),
    'IMC-scheduled PID': dict(Kc=sc.kc_scheduler_imc, Ti=sc.ti_scheduler_imc,
                               Td=sc.td_scheduler_imc, schedule_filter_tau=SCHEDULE_FILTER_TAU),
    'Pure gain-scheduled PID': dict(Kc=sc.kc_scheduler_pure, Ti=sc.Ti_pure, Td=sc.Td_pure,
                                     schedule_filter_tau=SCHEDULE_FILTER_TAU),
    'Horn IMC-PI': dict(Kc=sc.Kc_imc_horn, Ti=sc.Ti_imc_horn, Td=sc.Td_imc_horn),
    'C1': _final_params_C1,
    'C2': _final_params_C2,
    'C3': _final_params_C3,
    'C4': _final_params_C4,
    'C2b': _final_params_C2b,
    'C4b': _final_params_C4b,
}

TRACE_ORDER = ['Conventional PI', 'IMC PI', 'IMC-scheduled PID', 'Pure gain-scheduled PID',
               'Horn IMC-PI', 'C1', 'C2', 'C3', 'C4', 'C2b', 'C4b']


def _desc(v):
    if isinstance(v, sc.PiecewiseLinearGainController):
        return 'scheduled'
    return f"{v:.5f}"


if __name__ == '__main__':
    for name in TRACE_ORDER:
        p = CONTROLLERS[name]
        print(f"{name:26s} Kc={_desc(p['Kc']):>10s}  Ti={_desc(p['Ti']):>10s}  "
              f"Td={_desc(p['Td']):>10s}  filt={p.get('schedule_filter_tau', 0.0)}")
