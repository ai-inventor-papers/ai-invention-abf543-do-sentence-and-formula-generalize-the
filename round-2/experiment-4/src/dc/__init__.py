"""Directional Consensus (DC): gold-free NL->FOL faithfulness from lexical-free logical agreement with peer
formalisations. Public API: align_pair, pair_relation, best_relation, directional_consensus."""
from .align import align_pair  # noqa: F401
from .pairs import best_relation, best_relation_ast  # noqa: F401
from .relation import pair_relation  # noqa: F401
