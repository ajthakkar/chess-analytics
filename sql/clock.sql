-- Games decided by the clock, per time control.
-- flag_balance: (games I won on time - games I lost on time) per 100 games.
SELECT
    time_class,
    COUNT(*) AS games,
    AVG(CASE WHEN result = 'win' AND termination = 'time' THEN 1 ELSE 0 END) AS won_on_time,
    AVG(CASE WHEN result = 'loss' AND termination = 'time' THEN 1 ELSE 0 END) AS lost_on_time,
    100 * (AVG(CASE WHEN result = 'win' AND termination = 'time' THEN 1 ELSE 0 END)
         - AVG(CASE WHEN result = 'loss' AND termination = 'time' THEN 1 ELSE 0 END)) AS flag_balance,
    AVG(CASE WHEN termination = 'time' THEN 1 ELSE 0 END) FILTER (WHERE result = 'loss') AS share_of_losses_on_time,
    AVG(CASE WHEN termination = 'time' THEN 1 ELSE 0 END) FILTER (WHERE result = 'win') AS share_of_wins_on_time,
    -- how much of my starting time I had left when the game ended, in games I lost
    MEDIAN(my_clock_end / base_s) FILTER (WHERE result = 'loss' AND termination <> 'time') AS median_clock_left_in_other_losses
FROM games
WHERE time_class IN ('bullet', 'blitz', 'rapid')
GROUP BY time_class
ORDER BY CASE time_class WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 ELSE 3 END
