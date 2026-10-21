"""Dictionary-only public boundary; imports perform no I/O or cloud setup."""
from .service import AnalysisService
from .validation import validate_analysis
from .normalization import normalize_quantity, NORMALIZATION_VERSION
from .matching import make_candidate_pairs, MATCHING_VERSION
from .extraction import EXTRACTION_VERSION
from .comparison import COMPARISON_VERSION
from .budget import AttemptBudget
from .errors import AnalysisError

__all__ = ["AnalysisService", "validate_analysis", "normalize_quantity", "make_candidate_pairs",
           "EXTRACTION_VERSION", "COMPARISON_VERSION", "NORMALIZATION_VERSION", "MATCHING_VERSION",
           "AttemptBudget", "AnalysisError"]
