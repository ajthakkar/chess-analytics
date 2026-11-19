-- The average of a per-game value for each group, with a 95% interval.
--
-- Usually the value is the residual: my score minus the baseline, in points per game (0 means
-- "scored exactly what I usually score in that situation"). For stop rates it's 1 if the game
-- ended a session and 0 if not.
--
-- Games in the same session aren't independent (a bad night drags down several games), so the
-- standard error is clustered by session: deviations are summed within each session first.
--
-- analyze.py fills in the per-game value, the grouping expression, and the filter.
WITH g AS (
    SELECT {key} AS grp, session_id, SUM({value}) AS s, COUNT(*) AS n
    FROM games
    WHERE {where}
    GROUP BY ALL
),
totals AS (
    SELECT grp, SUM(s) / SUM(n) AS mean, SUM(n) AS n, COUNT(*) AS clusters
    FROM g
    GROUP BY grp
)
SELECT
    t.grp,
    t.n,
    t.mean,
    sqrt(SUM(power(g.s - g.n * t.mean, 2)) * t.clusters / greatest(t.clusters - 1, 1)) / t.n AS se
FROM totals t
JOIN g USING (grp)
GROUP BY t.grp, t.n, t.mean, t.clusters
ORDER BY t.grp
