# Evidence and Trust Methodology

**Status:** draft for community review
**Date:** 2026-05-29

This document defines how OpenHealth reasons about uncertainty. It is the
backbone that keeps the system honest: it never diagnoses, never prescribes, and
always says how sure it is. The rules here are implemented in
[`openhealth/evidence.py`](../../openhealth/evidence.py) and
[`openhealth/reference_ranges.py`](../../openhealth/reference_ranges.py).

> OpenHealth is not a medical device and does not provide medical advice. It
> organizes your data and surfaces questions to discuss with a clinician.

## 1. The confidence scale (C1–C5)

Established evidence-grading systems (GRADE, Oxford CEBM, SORT, USPSTF) are
designed for clinical guidelines. We distill them into a five-level scale a
beginner can read at a glance. Every claim the system shows carries one label.

| Level | Label | When it applies | How it is phrased |
|-------|-------|-----------------|-------------------|
| C5 | Established | Matches a guideline / systematic review of RCTs (GRADE high; USPSTF A/B) | Stated as fact |
| C4 | Likely | Consistent RCTs or large cohorts (GRADE moderate) | Stated, "confirm with a clinician" |
| C3 | Hypothesis | Observational data + plausible mechanism (GRADE low) | Framed as a question |
| C2 | Weak signal | Little/conflicting data, or a raw personal pattern | Framed as a question |
| C1 | Speculation | Mechanism / opinion / single case only | Framed as a question |

**Hard rule:** a pattern derived purely from the user's own data is capped at
**C2** until it survives at least one repeated on/off switch against a baseline
(see §4). After that it may rise to **C3**, never higher on personal data alone.
This is what stops a beginner from mistaking a coincidence for a cause.

**Framing rule:** anything at C3 or below is rendered as an open question
("Possible pattern to check: … What else could explain it?"), not a statement.

## 2. Lab reference ranges

There is no single "correct" reference range. Ranges depend on the lab, the
assay, age, sex, and more. Therefore:

1. **The reference range printed on the user's own report always wins.** The
   built-in table is a *fallback for orientation only* and every value flagged
   from it is marked `reference_source: "fallback"`.
2. **Marker identity uses LOINC** (test identity) and **UCUM** units. Each stored
   result keeps `value`, `unit`, `value_si`, `reference_low/high`,
   `reference_source`, and a computed `flag` (low/normal/high) relative to *that
   record's* range — never a global default.
3. **Single out-of-range values are common and rarely meaningful alone.** They
   produce a C2 review prompt, not a conclusion. Trends over time matter more.

Built-in fallback markers (adult, orientation only): hemoglobin, WBC, platelets,
glucose, creatinine, sodium, potassium, total/LDL/HDL cholesterol, triglycerides,
vitamin D, B12, ferritin, TSH, HbA1c, CRP. Always defer to the lab report.

## 3. Circadian rhythm: what we can and cannot infer

The two-process model (Borbély) explains sleep via homeostatic pressure
(Process S) and a ~24 h circadian oscillator (Process C). The gold-standard
phase marker is **DLMO** (dim-light melatonin onset), which needs a saliva/plasma
assay. Kräuchi's thermoregulation models need skin-temperature sensors.

From WHOOP-style data (sleep onset/offset, HRV) we can compute behavioral
proxies only:

- **Midsleep** = (onset + offset)/2 — a stable chronotype marker.
- **Social jetlag** = midsleep difference between workdays and free days.
- A *rough* DLMO ≈ sleep onset − 2 h, explicitly an assumption, not a measurement.

**Limit, always disclosed:** WHOOP gives sleep behavior and autonomic proxies,
not melatonin phase, and it does not measure light. Any "circadian phase" claim
from WHOOP is C2–C3 at most.

## 4. Validating a personal pattern (n-of-1)

To tell a real effect from a coincidence on small personal data:

- **Baseline first.** Measure the outcome 1–2 weeks unchanged to learn your
  normal spread. An effect smaller than that spread is noise.
- **Change one thing at a time.** Two simultaneous changes can't be attributed.
- **Repeat the switch.** A pattern that returns when you toggle the intervention
  on/off/on (ABAB) is far more credible than a one-off.
- **Washout.** Wait between periods until the previous effect fades, or the
  periods leak into each other.
- **Watch for confounders.** Weekends, illness, alcohol, cycle, weather, travel,
  stress.
- **Beware reverse causation and regression to the mean.** After an unusually bad
  day things improve on their own.
- **Small n.** On 3–5 points correlation means almost nothing; you need dozens of
  observations and a clear, repeating pattern.

Until a pattern passes at least one repeated switch with a baseline, it stays at
C2 ("raw observation").

## 5. Safety: red flags and boundaries

The system **stops interpreting** and routes the user to professional care when
it detects a red flag. It never gives dosages, schedules, diagnoses, or
treatment changes.

**Symptom red flags (free-text scan):** chest pain, shortness of breath,
fainting, one-sided weakness/numbness, suicidal thoughts, blood in stool,
coughing blood, unexplained weight loss.

**Critical lab values (examples, conventional units):** glucose <50 or >300
mg/dL; potassium <2.5 or >6.0 mmol/L; hemoglobin <7 g/dL; platelets <20 ×10⁹/L;
sodium <120 or >160 mmol/L; or anything the lab itself flags "critical/panic".

**Out of scope:** pregnancy, under-18, and drug-interaction questions — the
system says so and defers to a clinician.

When any red flag fires, the system emits a `PatternAlert` with confidence 0.0,
tagged `see-clinician`, and suppresses hypothesis generation on that topic.

## Sources

- USPSTF Grade Definitions — https://www.uspreventiveservicestaskforce.org/uspstf/about-uspstf/methods-and-processes/grade-definitions
- GRADE approach — https://www.jclinepi.com/article/S0895-4356(10)00332-X/fulltext
- Oxford CEBM Levels of Evidence 2011 — https://www.cebm.ox.ac.uk/resources/levels-of-evidence/ocebm-levels-of-evidence
- SORT (AAFP) — https://www.aafp.org/pubs/afp/issues/2004/0201/p548.html
- LOINC — https://loinc.org ; UCUM — https://ucum.org
- MedlinePlus lab tests (NIH) — https://medlineplus.gov/lab-tests/
- ADA Standards of Care (HbA1c diagnosis) — https://diabetesjournals.org/care
- NGSP HbA1c conversion — http://www.ngsp.org/convert1.htm
- Borbély two-process model (2016 reappraisal) — https://pubmed.ncbi.nlm.nih.gov/26762182/
- DLMO as circadian phase marker — https://pubmed.ncbi.nlm.nih.gov/17936039/
- Kräuchi thermoregulation and sleep onset — https://pubmed.ncbi.nlm.nih.gov/10463347/
- n-of-1 trials methodology (Guyatt) — https://pubmed.ncbi.nlm.nih.gov/3411262/

> Numeric ranges above are adult orientation values and must be taken from the
> lab report in practice (`reference_low/high/source`), never treated as truth.
