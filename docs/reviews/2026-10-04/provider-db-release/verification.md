# Return read connections before retrieval provider waits

Similarity, semantic search and ordinary semantic Ask requests could retain a SQL read connection while waiting for the vector provider. Under connection pressure, an authenticated paper-detail request could then time out. These routes now return that connection before the provider wait; search also returns it before draining an unfinished provider task after SQL failure or cancellation. Hydration, live generation checks, quota accounting and Ask history persistence continue through the existing database paths.

## Evidence and scope

Read-only production diagnostics found two paper-detail and three similarity HTTP 500 responses in a bounded 3 October log window. Their tracebacks contained SQLAlchemy connection-checkout timeouts, with a configured pool of five connections and ten overflow connections. The inspected deployed router and database-source bytes matched the deployed revision, and the relevant provider-wait paths were unchanged in the parent of this fix.

Those logs establish checkout exhaustion, not which requests held every connection or the cause of all historical HTTP 500 responses. Aggregate error-budget counts are time-series estimates. This change addresses the reproduced provider-wait mechanism; it does not establish recovery of the production error budget. Pool size and production checkout timeout are unchanged.

## Actual regression results

The new parameterized regression uses a real, fresh disposable PostgreSQL database and Redis service, a real SQLAlchemy pool with one connection and no overflow, registered-user authentication and a barrier around the real disposable vector adapter. While the provider worker remains blocked, another authenticated paper-detail GET must finish successfully. After releasing the worker, the original request must return its pinned generation, retain its expected quota accounting and, for Ask, persist the matching user's question and answer in that same database pool. These small pool settings apply only to this test.

- Baseline: test-only revision `94493099dec603de39b90c66fd331c247c098b88`, with all three router bytes unchanged from parent `e6d5700027b539d93feefde13e45ea9515859e07`. All three route cases failed with actual SQLAlchemy connection-checkout timeouts; there were no collection or setup errors. Its source-bound receipt is retained; a separate pre-launch clean-worktree receipt was not saved.
- Fix: clean revision `40da73da9f2f82555297edda56c48e3225334e15`. Both complete modules, `test_index_retrieval_http.py` and `test_similar_completeness.py`, passed: **28 tests, zero failures, errors or skips**. This includes all three provider-wait regression cases and neighboring retrieval/generation cases.
- The isolated runner created fresh PostgreSQL and Redis services, and its cleanup completed for both runs. For the fix run, the wrapper checked the owned subprocess group after exit: no remaining members and an absent native process group at that time; it sent no cleanup signals. The baseline did not capture a native process-group check, so its cleanup proof is limited to the runner's actual cleanup output.
- The fix run exited zero, and its source HEAD remained unchanged throughout. The two-module result is local evidence, not the complete API CI result or production-load acceptance.

Private native logs and test credentials are excluded from the repository. The fix-run JUnit SHA-256 is `f8a74ec7f7b50d02d2f9c065bceafcc53863164a093c4db417cd6c90408c8a81`; its exit/source/process receipt SHA-256 is `62213f40e64fde0d5e077677030df469e69816beea74a0536b6c143f490e56f5`.

## Publication and data boundaries

Required CI and ordinary exact-head merge remain separate gates. Signed release, the existing deployment/error-budget gate and actual public acceptance are still required before claiming this fix is live. No release exception is created by this change. The existing error-budget policy cannot be replaced by these local test results.

This change adds no scientific property, production scientific import, human approval, ML approval, physical-state association or new calculation. It changes connection lifetime only and does not resolve the remaining source/field-review requirements for the Materials upgrade.
