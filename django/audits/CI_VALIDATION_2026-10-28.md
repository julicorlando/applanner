# ApPlanner — CI validation gate (2026-10-28)

Base branch: `django-replatform`. This document records the non-production verification gate; it does not claim any test has passed.

## Required evidence before release

- [ ] Django full test suite passes against PostgreSQL.
- [ ] Migrations check and deploy security checks pass.
- [ ] Repository secret scanning and dependency audit pass.
- [ ] Tenant cross-access and booking concurrency regression tests pass.
- [ ] Mercado Pago sandbox webhook and idempotency checks pass.
- [ ] Disposable database backup restore drill passes.
- [ ] Barber/salon end-to-end smoke test passes on staging.
- [ ] Staging monitoring, rollback rehearsal, and explicit release approval are recorded.

No production deployment is authorized by this document alone. Do not add secrets, personal data, or production database dumps to CI artifacts.
