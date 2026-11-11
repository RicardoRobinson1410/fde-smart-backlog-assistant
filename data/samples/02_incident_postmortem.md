# Incident Postmortem: SEV-1 Checkout Gateway Cascading Timeout (INC-2026-884)

**Summary**: During peak flash-sale traffic (4,200 req/s), upstream Acquirer-B experienced degraded latency (p99 > 28s). Because our checkout service uses a static 30s timeout (`FIN-105`) without a circuit breaker, all worker threads blocked waiting on Acquirer-B, exhausting the connection pool and causing a 19-minute cascading outage across all payment methods.

## Actionable Engineering Requirements

1. **Adaptive Circuit Breaker & Failover Routing (New)**
   - Implement a resilience circuit breaker (e.g., trip open when failure/timeout rate > 25% over a 30s rolling window) with automatic fallback routing to Secondary Acquirer-A.
   - Expose Prometheus circuit state metrics (`closed`, `half_open`, `open`) and PagerDuty alert when open > 60s.

2. **Tighten Acquirer HTTP Timeouts & Bulkhead Isolation (Updates FIN-105)**
   - Replace the static 30-second socket timeout in `FIN-105` with a strict 4.5-second connect/read budget per attempt and isolate each acquirer in a dedicated thread/connection bulkhead (max 150 concurrent sockets).

3. **Open Ambiguities to Confirm with Architecture Team**
   - What is the maximum acceptable automatic failover fee differential when routing from Acquirer-B to Acquirer-A during a brownout?
   - Should half-open probe requests include high-value institutional wire transfers or only card authorizations under $500?
