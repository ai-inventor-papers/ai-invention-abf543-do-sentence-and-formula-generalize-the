import json
def read_jsonl(path):
    out=[]
    for l in open(path, encoding="utf-8"):
        l=l.strip()
        if l: out.append(json.loads(l))
    return out
