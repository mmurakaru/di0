SELECT c.customer_id, SUM(r.arr) AS total_arr
FROM analytics.dim_customers c
JOIN analytics.fct_subscription_revenue r ON r.customer_id = c.customer_id
GROUP BY c.customer_id
