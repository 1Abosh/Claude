# Reference-tuned and IMC-derived controllers -- summary

## Free-parameter selection
Selected on this notebook's own sweep grids (F_GRID / K_GRID above), by minimising mean
IAE over the standardised+wide scenarios subject to zero non-settled steps on the
standardised scenario (falling back to minimising the mean when nothing on the grid
was feasible):

- C1: f = 0.1
- C2: f = 0.02
- C2b: f = 0.1
- C3: k = 5
- C4: k = 80
- C4b: k = 8

## Scenario results vs. this section's own design brief targets
(Reported as run, not tuned to match -- see Section 5/7 above for the full table.)

                                     Controller  IAE std  IAE wide  IAE regulatory Not settled (std)  p-p pH (t>150000s)
C1 -- Conventional PI (reference tuning, fixed)  16766.2    4189.6         41999.4               1/3                0.00
                     C2 -- GS-PI (3 references)  43108.6   15634.6         65736.0               3/3                3.16
           C3 -- IMC PI (fixed, averaged model)  20154.8    5156.2         51814.8               1/3                0.00
                    C4 -- GS-IMC (3 references)  30773.2    3810.6         44692.1               1/3                1.01
    C2b -- GS-PI (5 references, analytic gains)   5236.2    1114.6          6920.5               0/3                0.00
   C4b -- GS-IMC (5 references, analytic gains)   8134.2    1231.8          8136.2               0/3                0.00

## Loop-gain flatness
                                      Controller  Loop-gain max/min (pH 5-9)  Mean IAE (standardised)
    C4b -- GS-IMC (5 references, analytic gains)                         5.0                   8134.2
     C2b -- GS-PI (5 references, analytic gains)                         5.0                   5236.2
     Existing: IMC-scheduled PID (report GS-IMC)                         8.5                  11819.0
Existing: Pure gain-scheduled PID (report GS-PI)                        24.3                  21345.2
            C3 -- IMC PI (fixed, averaged model)                        50.1                  20154.8
 C1 -- Conventional PI (reference tuning, fixed)                        50.1                  16766.2
               Existing: Conventional PI (fixed)                        50.1                      NaN
                     C4 -- GS-IMC (3 references)                        72.2                  30773.2
                      C2 -- GS-PI (3 references)                        72.2                  43108.6

Correlation (flatness ratio vs. mean IAE): 0.881. Not monotonic across the whole set -- see the table above for where it breaks.

## Reference tuning vs. IMC, once the schedule shape is corrected
Fixed: reference C1 = 16766  vs.  IMC C3 = 20155  -> reference ahead
3-ref: reference C2 = 43109  vs.  IMC C4 = 30773  -> IMC ahead
5-ref: reference C2b = 5236  vs.  IMC C4b = 8134  -> reference ahead

No consistent winner across all three schedule densities: which basis wins flips between the fixed, 3-reference and 5-reference comparisons. Schedule density (how many points the gain schedule is built from, and whether those points use the correct local gain) affects mean IAE far more than the choice between reference tuning and IMC does -- the 5-reference designs (C2b/C4b) beat every 3-reference and fixed design regardless of which rule built them.

## C2b vs. C4b: margins
      Region  Gain margin (dB)  Phase margin (deg)
      Acidic            13.374              71.582
Near-neutral            26.110              68.570
    Alkaline            34.964              79.733
      Region  Gain margin (dB)  Phase margin (deg)
      Acidic            18.595              84.738
Near-neutral            31.311              88.791
    Alkaline            40.167              89.564

Mean GM gap between C2b and C4b: 5.21 dB; mean PM gap: 14.40 deg.
For comparison, each controller's own margin already varies by 21.59 dB (C2b) / 21.57 dB (C4b) across its three regions.
The C2b/C4b margin gap is smaller than the region-to-region spread either controller already has on its own -- the defensible claim is that the two are **comparable** in robustness, not that one beats the other.
