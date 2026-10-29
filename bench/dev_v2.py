import sys, json
sys.path.insert(0, "bench")
from common import load, Score, partition
from navajo_v2 import NavajoV2, build_lexicon
rows = list(load("data/sub/nem_train_health.jsonl"))
fit = [r for r in rows if partition(r["uid"]) != 2]; dev = [r for r in rows if partition(r["uid"]) == 2]
with open("data/sub/_fit.jsonl", "w", encoding="utf8") as f:
    for r in fit: f.write(json.dumps(r) + "\n")
print("lexicon", build_lexicon("data/sub/_fit.jsonl", "data/sub/_lex_fit.json"), "fit", len(fit), "dev", len(dev))
cfgs = {"v2": {}, "v2-nolex": {"lexicon_path": None}}
for name, kw in cfgs.items():
    d = NavajoV2(**{"lexicon_path": "data/sub/_lex_fit.json", **kw}); s = Score()
    for r in dev: s.add(r["text"], r["spans"], d.detect(r["text"]))
    print(name, json.dumps({k: round(v, 4) for k, v in s.result().items()}))
    if name == "v2":
        for k, v in list(s.label_table().items())[:22]: print(f"   {k:32s} {v[0]:5d} {v[1]:.3f}")
