"""
Cross-checks `09_Margins` (frequency-domain gain/phase margin verdicts, one linearised
model per region) against the new wide-sweep closed-loop data (time-domain, servo +
regulatory, all three regions) for every (controller, region) pair, and flags:
  - 'Comfortable' pairs that actually oscillate (limit cycle) or saturate in the sweep
  - 'MARGINAL' pairs that actually behave acceptably (stable, no cycling) in the sweep

Run with:  python3 -m wide_sweep.compare_to_margins   (after driver.py and margins.py)
"""
import pandas as pd

from . import margins as mg
from . import driver


def main():
    margins_df = mg.compute_margins_df()
    results = driver.run_all_controllers()
    metrics_rows = []
    for name in driver.ctrl.TRACE_ORDER:
        metrics_rows.extend(driver.compute_region_metrics(name, results[name]))
    metrics_df = pd.DataFrame(metrics_rows)

    merged = metrics_df.merge(
        margins_df[['Controller', 'Region', 'Gain margin (dB)', 'Phase margin (deg)', 'Verdict']],
        on=['Controller', 'Region'])
    merged['Oscillating_or_saturated'] = (
        merged['Stability verdict'].str.contains('LIMIT CYCLE|UNSTABLE')
        | (merged['Fraction time saturated'] > 0))

    comfortable_bad = merged[(merged['Verdict'] == 'Comfortable') & merged['Oscillating_or_saturated']]
    marginal_ok = merged[merged['Verdict'].str.contains('MARGINAL') & (merged['Stability verdict'] == 'stable')]

    merged.to_csv('wide_sweep/output/Margins_vs_WideSweep_crosscheck.csv', index=False)

    pd.set_option('display.width', 200)
    print("=== 09_Margins says 'Comfortable', wide sweep shows oscillation/saturation ===")
    print(comfortable_bad[['Controller', 'Region', 'Gain margin (dB)', 'Phase margin (deg)',
                            'Stability verdict']].to_string(index=False))
    print("\n=== 09_Margins says 'MARGINAL', wide sweep shows acceptable behaviour ===")
    if marginal_ok.empty:
        print("(none)")
    else:
        print(marginal_ok[['Controller', 'Region', 'Gain margin (dB)', 'Phase margin (deg)',
                            'Stability verdict']].to_string(index=False))
    return merged


if __name__ == '__main__':
    main()
