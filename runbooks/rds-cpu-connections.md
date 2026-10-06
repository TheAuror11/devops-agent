# RDS CPU and connection exhaustion

## Signals

- `CPUUtilization` > 80% for 10+ minutes
- `DatabaseConnections` approaching `max_connections`
- Application `too many connections` / checkout timeouts talking to RDS

## Hypotheses

1. Missing index after a new query shipped
2. Connection leak in the app pool
3. Noisy neighbor on shared instance (check `ReadIOPS` / `WriteIOPS`)
4. Failover in progress (`ReplicaLag`, events)

Do not reboot RDS as a first step. Capture Performance Insights *before* bouncing.
