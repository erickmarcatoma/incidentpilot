# Runbook: Payment Service Failure

**Category:** service_failure  
**Affected Service:** payment  
**Problem:** Payment service is failing to process charges due to invalid token or downstream dependency failure.

## Symptoms
- Checkout error rate above 20%
- Payment service returns "Invalid token" or "Connection refused"
- Traces show payment Charge span failing with error

## Diagnostic Steps
1. Check payment service metrics for error rate spike
2. Search payment service logs for "Invalid token" or "Connection refused"
3. Review traces for failed Charge spans pointing to payment service

## Remediation Steps

### Step 1: Disable failing change for payment service
**Action:** toggle_feature_flag  
**Target Service:** payment  
**Details:** Revert the most recent feature flag change in the payment service configuration.

### Step 2: Restart payment service
**Action:** restart_service  
**Target Service:** payment  
**Details:** Restart the payment service to clear any bad state, expired tokens, or connection pool issues.

## Rollback Steps
- Re-enable any disabled feature flags
- Restore previous payment service configuration

## Recovery Check
**Metric:** error_rate on service checkout  
**Threshold:** below 0.05 (5%)  
**Timeframe:** within 5 minutes of remediation

## References
- knowledge/policies/allowed-actions.yaml