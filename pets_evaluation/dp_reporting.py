"""
Differential privacy reporting.

Applies differential privacy mechanisms to aggregate compliance statistics
so that individual website contributions are protected. This module
demonstrates the privacy–utility tradeoff using the Laplace mechanism
and randomized response at multiple epsilon values.

Mechanisms used:
- Laplace mechanism: Adds calibrated Laplace noise to numeric aggregates
  (mean scores, tracker counts, violation rates).
- Randomized response: Applies local DP to binary per-site attributes
  (e.g., "has dark patterns?", "has pre-consent trackers?").

The module generates reports at multiple epsilon values (e.g., 0.1, 0.5,
1.0, 2.0, 5.0) to illustrate the privacy–utility tradeoff.
"""

from __future__ import annotations


def apply_laplace_mechanism(
    value: float, sensitivity: float, epsilon: float
) -> float:
    """Add Laplace noise to a single numeric value.

    Draws noise from Lap(sensitivity / epsilon) and adds it to the value.

    Args:
        value: The true aggregate value.
        sensitivity: The sensitivity of the query (max change from one record).
        epsilon: The privacy budget parameter.

    Returns:
        The noisy value.
    """
    raise NotImplementedError("Implemented in Phase 4")


def apply_randomized_response(value: bool, epsilon: float) -> bool:
    """Apply randomized response to a single binary value.

    With probability p = e^epsilon / (1 + e^epsilon), reports the true
    value; otherwise reports the flipped value.

    Args:
        value: The true binary value.
        epsilon: The privacy budget parameter.

    Returns:
        The (possibly flipped) binary value.
    """
    raise NotImplementedError("Implemented in Phase 4")


def generate_dp_report(
    metrics_path: str, epsilons: list[float], output_path: str
) -> None:
    """Generate differentially private versions of aggregate metrics.

    Reads true aggregate metrics, applies Laplace mechanism and randomized
    response at each epsilon level, and writes a report comparing noisy
    vs. true values.

    Args:
        metrics_path: Path to the true aggregate metrics JSON.
        epsilons: List of epsilon values to evaluate (e.g., [0.1, 0.5, 1.0, 2.0, 5.0]).
        output_path: Path to write the DP report JSON.
    """
    raise NotImplementedError("Implemented in Phase 4")
