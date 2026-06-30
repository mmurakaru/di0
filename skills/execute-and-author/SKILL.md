---
name: execute-and-author
description: Run a validated query to return rows, or author a dashboard from validated queries. Use after compose-and-validate to produce results or deliverables.
---

# execute-and-author

Maps to the ExecutionPort. Execute returns rows and works on any execution
adapter; authoring deliverables is optional and only available on adapters that
support it.

## How

```bash
di0 query "<sql>"               # validate then execute, printing rows
di0 author deliverables/<spec>.yml   # build a dashboard from a versioned spec
```

Execution is gated on validation - an invalid query never reaches the warehouse.
If the configured execution adapter cannot author, `di0 author` refuses rather
than pretending.

## Rule

The execution target and whether it can author are profile settings. This skill
names no specific warehouse or BI tool.
