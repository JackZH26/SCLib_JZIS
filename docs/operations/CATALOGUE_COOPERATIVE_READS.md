# Cooperative catalogue computation

An actual owned restore of the production corpus measured a23.57-second cold
Timeline response and13.50seconds of event-loop delay. The same bytes were
served from its fenced warm cache in0.009seconds. The long synchronous source
assessment and point-construction loops could starve unrelated API/health reads.

The visibility adapter and Materials/Timeline scan loops now yield to the event
loop after each32materials. They preserve every material, record, ancestry
limit, source lifecycle decision, anomaly filter, result order and final
catalogue/source epoch fence. There is no cross-request policy memo, evidence
substitution or early cut-off. Cancellation can interrupt an unfinished CPU
scan; no partial result is returned or published to the response cache.
Timeline also fetches ORM rows in128-row pages and yields between32-point
digest batches. Synchronous internal callers drive the same response builder
to completion; HTTP callers drive it cooperatively. The full point set still
determines the digest before any response is published.

The isolated actual-corpus comparison checks response body SHA256, full count
and Timeline coverage/data version against the original cold and warm outputs.
Its heartbeat measures responsiveness separately from total computation time.
Cooperative scheduling does not promise a faster cold scientific computation;
normal warm reads keep the existing revision-fenced cache behavior.
