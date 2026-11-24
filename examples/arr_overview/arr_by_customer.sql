SELECT
    customers.customer_id,
    SUM(revenue.arr) AS total_arr
FROM analytics.dim_customers AS customers
INNER JOIN analytics.fct_subscription_revenue AS revenue
    ON customers.customer_id = revenue.customer_id
GROUP BY customers.customer_id
