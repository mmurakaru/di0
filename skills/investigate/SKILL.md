---
name: investigate
description: Decompose an analytics question into a sequence of validated queries - funnels, journeys, cohorts, ratio checks. Use when a question needs several steps, not one query.
---

# investigate

A method, not a query. Break a question into steps, and run each through
`resolve-schema` -> `compose-and-validate` -> `execute-and-author`.

## Method

1. State the question and the decision it informs.
2. Decompose into measurable sub-questions (population, event, segment, time grain).
3. For each sub-question: resolve the references, compose, validate, execute.
4. Reconcile findings; note what each step assumes and what would falsify it.

## Rule

This skill is warehouse-blind. It carries no schema knowledge and no table names;
every reference is resolved at the moment it is needed.
