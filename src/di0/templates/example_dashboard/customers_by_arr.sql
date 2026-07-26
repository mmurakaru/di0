-- Backs the sample dashboard card. Replace with your own query; it is validated
-- against the resolved schema before the dashboard is authored.
SELECT
    customer_id,
    current_arr
FROM analytics.dim_customers
ORDER BY current_arr DESC
