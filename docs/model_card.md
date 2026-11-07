# StormLedger model card

> Research demonstration. Not emergency guidance. Not a forecast and not for decisions about safety, insurance, or assistance.

## What this estimates

The published number is a retrospective estimate of **owner valid registrations**
for one Florida county in one hurricane's major disaster declaration.

- Source dataset: OpenFEMA `HousingAssistanceOwners`
- Source field: `validRegistrations`
- Geography: summed from the published zip/city rows to a Census county FIPS
- Universe: Florida counties designated for Individual Assistance or the Individuals and Households program on the linked DR
- Counties with no owner-assistance rows are treated as zero inside that universe
- This is not renter assistance, not all IA applicants, and not a forecast

## How a storm is linked

A HURDAT2 storm links to a FEMA `disasterNumber` when the declaration is a DR,
the title contains `HURRICANE <NAME>`, the incident year equals the HURDAT2 season,
and the title is not a tribal declaration. If two DRs match, the one with more
IA/IH-designated Florida counties is the modeling declaration. The other disaster
stays in the declaration ledger.

## Splits

- Train: incident begin before 2018-01-01
- Calibration: incident begin from 2018-01-01 until before 2022-01-01
- Test: incident begin on or after 2022-01-01

The published model is chosen on calibration mean absolute error only.
The boosted tree is published when its calibration MAE is at most 0.9 times the linear MAE.
Otherwise the linear model is published. Test storms are scored once and are not used to choose.

Published model: **linear**.

## Test results

| Model | Test MAE (registrations) | Test median AE | Test MAE on log1p |
| --- | ---: | ---: | ---: |
| Linear baseline | 8181.8 | 1553.2 | 0.924 |
| Boosted tree | 7419.1 | 1522.4 | 0.899 |
| Published (linear) | 8181.8 | 1553.2 | |

Calibration MAE: linear 2057.4, boosted 2196.9.
Test rows: 115 counties across 5 storms (AL092022, AL092024, AL102023, AL142024, AL172022).

## Uncertainty

The 80% interval is split conformal on the calibration storms. Residuals are absolute
errors of log1p(registrations). The radius uses the finite-sample level
`ceil((n+1) * 0.80) / n` and is transformed back with expm1, so the interval is multiplicative.

- Calibration rows: 17
- Nominal coverage: 80%
- Empirical coverage on the test storms: 56.5%
- Mean interval width on the test storms: 8033 registrations

On this bundle the empirical test coverage is below the nominal 80%. The calibration
storms (Michael 2018 and Sally 2020, 17 county rows) are smaller events than Ian,
Helene, and Milton, so a radius fit on that window is too narrow. That miss is a
result, not a number that was adjusted after seeing the test storms.

Standardized linear coefficients are associations on the log1p scale after scaling.
Wind, pressure, and distance move together, so a single coefficient sign is not a
physical claim. Local explanations use ablation, not those coefficients.

## Explanation

Each county estimate stores an ablation: the change in the published prediction when
one feature is replaced by its training-set median. That is a local explanation of this
fitted model, not a causal effect of wind or distance.

Global permutation importance is computed on the calibration window, not the test storms.

## Provenance

Every estimate names the declaration natural key (`femaDeclarationString|placeCode`),
the housing natural keys (`disasterNumber|state|county|city|zipCode`), the HURDAT2 fix
keys (`storm_id|YYYYMMDD|HHMM|record_identifier`), and the Census vintage. OpenFEMA `id`
values are API-assigned and are not used as keys.

Declaration-area rows in the snapshot: 1447.
Distinct disasters (`disasterNumber`): 60.

## Leakage checks

| Check | Passed |
| --- | --- |
| time_separation | True |
| storms_do_not_cross_splits | True |
| features_exclude_target_and_identifiers | True |
| population_reference_precedes_incident | True |
| irma_uses_2010_census | True |
| ian_uses_2020_census | True |

## Limitations

- Best-track positions are a post-storm reanalysis. Replay frames are not real-time forecasts.
- Owner registrations omit renters and are not the full Individuals and Households caseload.
- Treating a missing housing row as zero is an assumption. Tribal geographies that do not join to a county FIPS are excluded and counted in the quality report.
- County interior points are geometric, not population-weighted.
- Storm-county rows are not independent, and there are few storms.
- Estimates outside IA/IH-designated counties are extrapolations.
- Do not use these numbers for emergency decisions, insurance pricing, or assistance allocation.
