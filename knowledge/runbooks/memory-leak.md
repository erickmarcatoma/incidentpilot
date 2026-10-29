# Runbook: Memory Leak

**Category:** resource_exhaustion  
**Affected Service:** recommendation  
**Problem:** Recommendation service memory is growing unboundedly, causing increasing latency and eventual failure.

## Symptoms
- Frontend p95 latency above 1s
- Memory usage in recommendation service monotonically increasing
- No corresponding increase in load or traffic

## Diagnostic Steps
1. Check recommendation service memory metric (memory_mb) - it should be rising above baseline
2. Search recommendation service logs for OOM warnings or GC pressure
3. Review traces for recommendation spans showing increasing duration

## Remediation Steps

### Step 1: Restart the recommendation service
**Action:** restart_service  
**Target Service:** recommendation  
**Details:** Restart the recommendation service to clear accumulated memory. This provides temporary relief while the root cause (e.g., cache not being properly evicted) is investigated.

### Step 2: Disable cache warming
**Action:** toggle_feature_flag  
**Target Service:** recommendation  
**Details:** Disable the cache warming feature that is causing unbounded memory growth. This stops the cache from continuing to grow.

## Rollback Steps
- Re-enable cache warming feature flag
- Restore any disabled caching configurations

## Recovery Check
**Metric:** recommendation memory_mb on service recommendation  
**Threshold:** return to baseline within 10 minutes  
**Timeframe:** within 10 minutes of remediation

## References
- knowledge/policies/allowed-actions.yaml