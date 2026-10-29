"""Run one detector over one dataset; write spans + per-document latency.

python run_method.py <method> <dataset.jsonl> <out.jsonl> [--limit N] [--threshold T]
Methods: navajo_v1, navajo_v2, navajo_v2_<ablation>, presidio, gliner_gretel, gliner_nvidia
Each method runs in its own process so peak RSS is attributable to it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "vendor"))


def peak_rss_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:  # Windows smoke tests
        import psutil
        return psutil.Process().memory_info().peak_wset / 2**20


THREADS = int(os.environ.get("BENCH_THREADS", "2"))
os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))

GLINER_LABELS = [
    "person", "first name", "last name", "date", "date of birth", "date time", "phone number",
    "fax number", "email", "street address", "city", "county", "postcode", "medical record number",
    "health plan beneficiary number", "account number", "certificate license number", "employee id",
    "customer id", "unique id", "biometric identifier", "social security number", "national id",
    "tax id", "credit card number", "bank routing number", "url", "ip address", "mac address",
    "user name", "license plate", "device identifier", "coordinate", "password", "pin",
]
GLINER_MODELS = {"gliner_gretel": "gretelai/gretel-gliner-bi-small-v1.0",
                 "gliner_gretel_int8": "gretelai/gretel-gliner-bi-small-v1.0",
                 "gliner_nvidia": "nvidia/gliner-PII"}


def chunks(text, size=900):
    """Split at whitespace into windows of <= size chars (GLiNER max length)."""
    i, n = 0, len(text)
    while i < n:
        j = min(n, i + size)
        if j < n:
            k = text.rfind("\n", i + size // 2, j)
            if k < 0:
                k = text.rfind(" ", i + size // 2, j)
            j = k if k > i else j
        yield i, text[i:j]
        i = j


def make(method, threshold):
    if method == "navajo_v1":
        from navajo_egp.detector import PIIDetector
        d = PIIDetector(use_spacy=False)

        def f(t):
            try:
                return [(e.start, e.end) for e in d.detect(t)], 0
            except Exception:  # v1 crashes on names split by newlines; counts as nothing masked
                return [], 1
        return f
    if method.startswith("navajo_v2"):
        from navajo_v2 import NavajoV2
        kw = {"lexicon_path": os.path.join(HERE, "..", "assets", "lexicon_train.json")}
        abl = method[len("navajo_v2"):].lstrip("_")
        if abl == "nolex":
            kw["lexicon_path"] = None
        elif abl:
            kw["use_" + abl.replace("no", "", 1)] = False
        d = NavajoV2(**kw)
        return lambda t: (d.detect(t), 0)
    if method == "presidio":
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}]}).create_engine()
        a = AnalyzerEngine(nlp_engine=nlp)
        return lambda t: ([(r.start, r.end) for r in a.analyze(text=t, language="en", score_threshold=threshold)], 0)
    if method in GLINER_MODELS:
        import torch
        torch.set_num_threads(THREADS)
        from gliner import GLiNER
        m = GLiNER.from_pretrained(GLINER_MODELS[method])
        m.eval()
        if method.endswith("_int8"):  # edge-optimised control: dynamic int8 quantisation of Linear layers
            m = torch.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8)

        def f(t):
            out = []
            with torch.inference_mode():
                for off, c in chunks(t):
                    for e in m.predict_entities(c, GLINER_LABELS, threshold=threshold):
                        out.append((off + e["start"], off + e["end"]))
            return out, 0
        return f
    raise SystemExit("unknown method " + method)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("method")
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    t0 = time.time()
    f = make(a.method, a.threshold)
    load_s = time.time() - t0
    rss_load = peak_rss_mb()
    n = crashes = 0
    with open(a.data, encoding="utf8") as fin, open(a.out, "w", encoding="utf8") as fout:
        for line in fin:
            r = json.loads(line)
            s = time.perf_counter()
            spans, crash = f(r["text"])
            ms = (time.perf_counter() - s) * 1000
            crashes += crash
            fout.write(json.dumps({"uid": r["uid"], "spans": spans, "ms": ms}) + "\n")
            n += 1
            if a.limit and n >= a.limit:
                break
    meta = dict(method=a.method, data=os.path.basename(a.data), docs=n, crashes=crashes,
                threshold=a.threshold, threads=THREADS, load_s=load_s, rss_after_load_mb=rss_load,
                peak_rss_mb=peak_rss_mb(),
                wall_s=time.time() - t0)
    with open(a.out + ".meta.json", "w") as f2:
        json.dump(meta, f2, indent=1)
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
