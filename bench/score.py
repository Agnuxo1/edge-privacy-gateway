"""Score prediction files: 3 disjoint partitions (uid hash), mean ± sd, latency, RSS.

python score.py tune <data.jsonl> <pred1.jsonl> ...        -> prints best file by char_f2
python score.py report <outdir>                              -> results.json + results.md
Hybrids are unions of span sets, latency = sum of the parts.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PHI, Score, load, partition  # noqa: E402

KEYS = ["char_recall", "char_precision", "char_f2", "entity_recall_full", "secret_recall", "clinical_preserved"]
HYBRIDS = {"hybrid_v2+gliner_gretel": ["navajo_v2", "gliner_gretel"],
           "hybrid_v2+presidio": ["navajo_v2", "presidio"],
           "hybrid_v2+gliner_gretel_int8": ["navajo_v2", "gliner_gretel_int8"],
           "hybrid_v2+gliner_nvidia": ["navajo_v2", "gliner_nvidia"]}


def read_preds(path):
    return {r["uid"]: r for r in load(path)}


def evaluate(rows, preds_list, k=3, lexicon=None):
    parts = [Score() for _ in range(k)]
    total = Score()
    novel = [0, 0]
    ms = []
    for r in rows:
        if not all(r["uid"] in p for p in preds_list):
            continue
        spans = [tuple(s) for p in preds_list for s in p[r["uid"]]["spans"]]
        ms.append(sum(p[r["uid"]]["ms"] for p in preds_list))
        parts[partition(r["uid"], k)].add(r["text"], r["spans"], spans)
        total.add(r["text"], r["spans"], spans)
        if lexicon is not None:
            for g in r["spans"]:
                if g["label"] in ("first_name", "last_name") and r["text"][g["start"]:g["end"]] not in lexicon:
                    novel[0] += 1
                    novel[1] += any(s <= g["start"] and e >= g["end"] for s, e in spans)
    res = {"docs": total.c["docs"], "phi_entities": total.c["ent"]}
    for key in KEYS:
        vals = [p.result()[key] for p in parts]
        res[key] = {"mean": st.mean(vals), "sd": st.stdev(vals), "all": total.result()[key]}
    ms.sort()
    if ms:
        res["latency_ms_p50"] = ms[len(ms) // 2]
        res["latency_ms_p95"] = ms[int(len(ms) * 0.95)]
    if lexicon is not None:
        res["novel_name_recall"] = novel[1] / max(1, novel[0])
        res["novel_names"] = novel[0]
    res["per_label"] = total.label_table()
    return res


def report(outdir):
    datasets = {"nem": "data/sub/nem_test_health.jsonl", "gretel": "data/sub/gretel_test_health.jsonl"}
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    lex = set(json.load(open(os.path.join(root, "data/sub/lexicon_train.json"), encoding="utf8")))
    out = {}
    for ds, path in datasets.items():
        rows = list(load(os.path.join(root, path)))
        preds = {}
        for f in sorted(glob.glob(os.path.join(outdir, f"{ds}__*.jsonl"))):
            m = os.path.basename(f)[len(ds) + 2:-6]
            preds[m] = read_preds(f)
        for h, parts in HYBRIDS.items():
            if all(p in preds for p in parts):
                preds[h] = None
        for m in preds:
            plist = [preds[p] for p in HYBRIDS[m]] if m in HYBRIDS else [preds[m]]
            res = evaluate(rows, plist, lexicon=lex)
            metas = []
            for p in (HYBRIDS.get(m) or [m]):
                mp = os.path.join(outdir, f"{ds}__{p}.jsonl.meta.json")
                if os.path.exists(mp):
                    metas.append(json.load(open(mp)))
            res["peak_rss_mb"] = max((x["peak_rss_mb"] for x in metas), default=None)
            res["crashes"] = sum(x.get("crashes", 0) for x in metas)
            res["threshold"] = [x.get("threshold") for x in metas]
            out[f"{ds}/{m}"] = res
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    lines = ["| dataset/method | docs | char recall | char precision | char F2 | entity recall (full) | "
             "secrets | clinical kept | novel names | p50 ms | p95 ms | peak RSS MB | crashes |", "|" + "---|" * 13]
    for k, r in out.items():
        fmt = lambda key: f"{r[key]['mean']:.3f} ± {r[key]['sd']:.3f}"
        lines.append(f"| {k} | {r['docs']} | {fmt('char_recall')} | {fmt('char_precision')} | {fmt('char_f2')} | "
                     f"{fmt('entity_recall_full')} | {fmt('secret_recall')} | {fmt('clinical_preserved')} | "
                     f"{r.get('novel_name_recall', 0):.3f} | {r.get('latency_ms_p50', 0):.1f} | "
                     f"{r.get('latency_ms_p95', 0):.1f} | {r['peak_rss_mb'] or 0:.0f} | {r['crashes']} |")
    with open(os.path.join(outdir, "results.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def tune(data, files):
    rows = list(load(data))
    best = None
    for f in files:
        r = evaluate(rows, [read_preds(f)])
        v = r["char_f2"]["all"]
        print(f, round(v, 4), round(r["char_recall"]["all"], 4), round(r["char_precision"]["all"], 4))
        if best is None or v > best[1]:
            best = (f, v)
    print("BEST", best[0])


if __name__ == "__main__":
    if sys.argv[1] == "tune":
        tune(sys.argv[2], sys.argv[3:])
    else:
        report(sys.argv[2])
