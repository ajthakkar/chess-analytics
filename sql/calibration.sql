-- Do the predictions describe my games?
-- Bucket games by the rating gap (opponent minus me) and compare the plain Elo prediction,
-- the fitted baseline, and what actually happened.
SELECT
    CAST(round(rating_gap / 50) * 50 AS INTEGER) AS gap,
    COUNT(*) AS games,
    AVG(expected_elo) AS expected_elo,
    AVG(expected) AS baseline,
    AVG(score) AS actual
FROM games
WHERE abs(rating_gap) <= 300
GROUP BY 1
HAVING COUNT(*) >= 30
ORDER BY 1
