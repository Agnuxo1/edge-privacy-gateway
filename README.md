# NAVAJO Edge Privacy Gateway for JupyterHealth

Reversible, on-device de-identification of between-visit patient data (FHIR R5 + Open mHealth) before it reaches an LLM or analytics,
and re-identification of the answer for the clinician only. Pure Python, no GPU, no network, about 1 ms per note.
Built on [Project NAVAJO](https://github.com/Agnuxo1) (MIT) for the Edge Medicine Innovation Challenge (UCSF + UC Berkeley).

## Quick start

```bash
pip install pytest
python demo/run_demo.py           # synthetic JupyterHealth bundle -> safe bundle -> clinician view
python -m pytest -q demo           # round-trip and no-hard-identifier test
```

What the demo does (`demo/gateway.py`):

| Data | Treatment |
|---|---|
| Patient name, identifier | stable pseudonym (`[NAME_2]`, `[ID_1]`) kept in an ephemeral session |
| telecom, address, photo, contact | removed |
| birthDate | year only (partial generalisation; not a compliance guarantee) |
| Free text (`user_notes`, notes, messages) | NAVAJO-v2 detector, reversible placeholders (`[PHI_3]`) |
| Dates and times | shifted by a random per-session offset; intervals preserved |
| Clinical values (mmHg, mg/dL, doses) | untouched |
| Open mHealth payload in `Observation.valueAttachment` (base64 JSON) | decoded, processed, re-encoded |

Known limitation shown by the demo itself: a first name that is neither in the lexicon nor after a field label or title
(“daughter Grace”) passes through. The benchmark below quantifies this (novel-name recall) A hybrid GLiNER comparison is running; no completed hybrid improvement is claimed yet.

## Benchmark

`bench/` compares, on the same CPU budget (2 threads):

- `navajo_v1`: NAVAJO as published (regex), `navajo_v2`: clinical layer added here, plus six ablations;
- Microsoft Presidio (spaCy `en_core_web_lg`), GLiNER (`gretelai/gretel-gliner-bi-small-v1.0`, fp32 and dynamic int8);
- `nvidia/gliner-PII` only as a reference: it was trained on Nemotron-PII, so its Nemotron numbers are contaminated.

Data: NVIDIA Nemotron-PII (CC BY 4.0) health domains, test split (7,058 synthetic documents) scored once, three disjoint
partitions (mean ± sd); Gretel `pii-masking-en-v1` (Apache-2.0) health domains (403 documents) as an out-of-distribution check.
NAVAJO-v2 rules and its name lexicon were developed only on the Nemotron train split. Thresholds of Presidio and GLiNER were
picked on 300 train documents. Metrics: character recall of HIPAA Safe Harbor identifiers, precision, F2, full-entity recall,
secrets, share of clinical measurements left intact, recall on names unseen in train, latency p50/p95, peak RSS.

The offline synthetic demo and its tests run with the bundled frozen training lexicon, without the benchmark datasets. Missing lexicons now fail closed instead of silently weakening masking. The full benchmark script `bash bench/job.sh` requires the external `data/sub/{nem_train_health,nem_test_health,gretel_test_health}.jsonl` files, their annotated schema and the bundled frozen train lexicon. It creates a Linux environment, downloads comparison models and writes `results/`. The dataset extraction/dataset extraction is not yet packaged here; full end-to-end benchmark reproduction remains incomplete. Do not mistake the demo for a reproduction of the reported benchmark.

| Stage | Recorded result | Evidence scope |
|---|---|---|
| E001,NAVAJO v1 | F2 0.603,precision0.374; one detector crash |1500train documents |
| E002,clinical layer | F2 0.930 | held-out train partition |
| E003,frozen v2 | F2 **0.943**,precision0.926,clinical values retained0.974; no-lexicon F2 0.894 | Development partition; selection evidence |
| E004,plumbing smoke | v2 F2 **0.909** vs v1 **0.550** |300test documents; exploratory exposure, not untouched final test |
| E005/E006 | In progress | Server quick benchmark then full benchmark; no completed GLiNER comparison |

Full results must replace this status only after the actual outputs are checked. Test has already been inspected on300documents, so a later full test is not described as wholly unseen. These are public **synthetic** health records, not real patient validation. No clinical deployment, safety or regulatory compliance is established.

## Licence and data

MIT (original code and NAVAJO core). Datasets are not redistributed in this repository. Obtain the derived health subsets externally under their original
licences (CC BY 4.0, NVIDIA Nemotron-PII; Apache-2.0, Gretel). All records are synthetic; no real patient data is used.
