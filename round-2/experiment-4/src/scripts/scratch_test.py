import sys, time, json
sys.path.insert(0, '.')
from dc import best_relation
from dc.front import canon
cases = [
 ("∀x (Dog(x) → Bark(x))", "∀x (Canine(x) → Woof(x))"),
 ("∀x (Dog(x) → Bark(x))", "∀x ((Dog(x) ∧ Brown(x)) → Bark(x))"),
 ("∀x (Dog(x) → Bark(x))", "∃x (Dog(x) ∧ Bark(x))"),
 ("Bark(rex)", "¬Bark(rex)"),
 ("∀x (BrownDog(x) → Bark(x))", "∀x ((Brown(x) ∧ Dog(x)) → Bark(x))"),
 ("∀x (A(x) → B(x))", "∀x (B(x) → A(x))"),
 ("∀x (A(x) → B(x))", "∀x∀y (R(x,y) → S(x,y))"),
 ("∀x (Student(x) ∧ Tall(x) → ∃y (Likes(x,y) ∧ Book(y)))", "∀z (Tall(z) ∧ Student(z) → ∃w (Book(w) ∧ Likes(z,w)))"),
 ("Owns(john, car1)", "OwnedBy(car1, john)"),
]
for a, b in cases:
    ca, cb = canon(a), canon(b)
    t=time.time(); r = best_relation(ca['canon'], cb['canon'])
    print(f"{a}  VS  {b}\n   -> {r['rel']} L1={r['rel_L1']} L2={r['rel_L2']} L3={r['rel_L3']} lex={r.get('rel_lex')} lvl={r['level']} defs={r.get('defs')} {time.time()-t:.3f}s")
