-- A sample ad-hoc query. Every identifier here is validated against the schema
-- your profile resolves - rename a column upstream and `di0 validate`/`di0 check`
-- fails here, at build time, instead of at 2am in production.
--
-- Replace the table and columns below with your own, then run:
--   di0 validate queries/example.sql
SELECT
    customer_id,
    current_arr
FROM analytics.dim_customers
WHERE current_arr > 0
