"""Analysis: run metrics, distributions and comparisons, computed in DuckDB."""

from .compare import compare_runs
from .stats import chi2_sf_df5, exact_throw_distribution, nice_width, run_analysis, wilson

__all__ = ["chi2_sf_df5", "compare_runs", "exact_throw_distribution", "nice_width", "run_analysis", "wilson"]
