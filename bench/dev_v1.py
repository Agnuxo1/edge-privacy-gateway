import sys, json, itertools
sys.path.insert(0, "D:/PROJECTS/105_Project-NAVAJO"); sys.path.insert(0, "bench")
from common import load, Score
from navajo_egp.detector import PIIDetector
d = PIIDetector(use_spacy=False)
s = Score(); crash=0
for r in itertools.islice(load("data/sub/nem_train_health.jsonl"), int(sys.argv[1])):
    try: pred=[(e.start, e.end) for e in d.detect(r["text"])]
    except Exception: pred=[]; crash+=1
    s.add(r["text"], r["spans"], pred)
print("crash",crash); print(json.dumps(s.result(), indent=1))
for k, v in s.label_table().items(): print(f"{k:32s} {v[0]:5d} {v[1]:.3f}")
