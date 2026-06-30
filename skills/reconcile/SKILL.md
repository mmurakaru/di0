---
name: reconcile
description: Cross-check a number across sources - source of truth, warehouse, and the surface that displays it - to find where they diverge. Use when a metric is disputed or suspect.
---

# reconcile

A method for cross-source agreement. The same quantity computed from different
sources should match; where it does not, the divergence is the finding.

## Method

1. Define the quantity and the grain precisely (one number, one time window).
2. Compute it from each source via `compose-and-validate` -> `execute-and-author`.
3. Compare; localize the first step where the numbers diverge.
4. Report the divergence and the likely boundary (extraction, transformation, or display).

## Rule

Warehouse-blind. Sources and their schemas come from profiles; this skill names
none of them.
