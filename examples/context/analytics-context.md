# Analytics context (example)

Genuinely non-derivable analytical knowledge that cannot live in the schema goes
here - kept small, and example-only. Anything expressible in the schema source
(metrics, accepted values, tier buckets, filters) belongs upstream there, not in
this file (see ADR 0005).

This is a generic placeholder. Replace its contents per deployment.

## Example: a non-derivable convention

> In the example SaaS schema, a customer with `current_arr > 0` and
> `is_internal_account = FALSE` is a "paying external customer". The internal-account
> flag is in the schema; the *definition* of the segment we report on is the
> non-derivable convention recorded here.

## Example: an initiative frame

> "Quarterly revenue review" groups customers by plan tier. The tier-to-plan
> mapping is derivable from the schema and must stay there; only the fact that
> this review exists and which decision it serves is recorded here.
