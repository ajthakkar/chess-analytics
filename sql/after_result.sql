-- What I do right after a result: stop for the night, or queue again (and how fast).
-- A game "ends a session" when no other game starts within 30 minutes of it ending.
SELECT
    result,
    COUNT(*) AS games,
    AVG(CASE WHEN is_last_in_session THEN 1 ELSE 0 END) AS stop_rate,
    -- minutes until the next game, for games that were followed by one
    MEDIAN(next_gap) FILTER (WHERE NOT is_last_in_session) AS median_minutes_to_next
FROM (
    SELECT
        *,
        LEAD(minutes_since_prev) OVER (ORDER BY start_utc) AS next_gap
    FROM games
)
WHERE {where}
GROUP BY result
ORDER BY result
