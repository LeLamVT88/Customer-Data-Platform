/**
 * config/demo/README.md — Source and seed for catalog.products.json
 * ===============================================================
 * The product catalog was generated synthetically to cover 20 categories
 * with realistic product IDs (P0010001–P0200010), brand names, decimal
 * prices in USD, and placeholder image URLs via via.placeholder.com.
 *
 * Source: No REES46 parquet batch was available in the repo (the Lakehouse
 * stack must be running to read data/local-batches/rees46/).  A synthetic
 * catalog of 500 products (10 per category × 20 categories) was created
 * instead.  Product IDs use the stable P-prefix format; they do NOT overlap
 * with any IDs in the REES46 source CSV so they are distinguishable in
 * downstream Gold tables.
 *
 * If you have the Lakehouse running and a REES46 parquet batch available,
 * you can regenerate this catalog from the actual product_id values with:
 *
 *   duckdb -c "SELECT DISTINCT product_id, category_id, category_code,
 *                   brand, price FROM 'data/local-batches/rees46/<batch>/silver.parquet'
 *                   ORDER BY product_id LIMIT 2000;"
 *   # pipe output into config/demo/catalog.products.json
 *
 * Categories covered (10 products each):
 *   electronics  clothing   home        books       sports
 *   beauty      toys      grocery     automotive  pet supplies
 *   office      garden    music       health      games
 *   jewelry     supplements home app. baby        office tech
 */
