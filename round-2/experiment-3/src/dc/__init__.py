"""Directional Consensus (DC) library: gold-free, text-blind NL->FOL faithfulness scoring by solver-verified
agreement with peer formalizations under lexical-free vocabulary alignment.

Public API (each takes formula strings or parsed ASTs, never a gold formula):
- parse_fol(s)                       -> AST | None
- align_pair(A, B, caps, use_L3)     -> config-agnostic alignment record (L1/L2/L3)
- derive(rec, use_L3, half_caps)     -> relation under one configuration
- pair_relation(A, B)                -> solver-decided entailment relation of A to B (shared vocabulary)
- fit_weights(sentences, systems)    -> one-coin Dawid-Skene system weights (label-free)
- score_group(outputs, rel, w, cfg)  -> DC for every output of one sentence
- directional_consensus(text, fol, peers, weights, cfg) -> DC for one candidate
- type_error(C, M, rec)              -> error type against the modal representative
"""
from .align import CAPS, Caps, align_pair, derive
from .consensus import DEFAULT, DCConfig, directional_consensus, score_group
from .errtype import TYPES, type_error
from .parse import canon, parse_fol
from .relation import converse, pair_relation
from .weights import fit_weights

__all__ = ["CAPS", "Caps", "align_pair", "derive", "DEFAULT", "DCConfig", "directional_consensus", "score_group",
           "TYPES", "type_error", "canon", "parse_fol", "converse", "pair_relation", "fit_weights"]
