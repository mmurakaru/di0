SELECT
  revenue_month,
  SUM(arr) AS total_arr
FROM analytics.fct_subscription_revenue
GROUP BY revenue_month
ORDER BY revenue_month
