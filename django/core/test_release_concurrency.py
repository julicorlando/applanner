import threading
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from finance.advanced_services import consume_material, move_cash, cash_balance
from finance.models import CashMovement, MaterialConsumption
from finance import test_advanced_operations
from core import test_release_completion
from scheduling.models import Appointment, AppointmentBundle


class ParallelActions:
    def run_pair(self, action):
        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(action(index))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
        self.assertFalse(
            any(thread.is_alive() for thread in threads), "Workers did not finish"
        )
        self.assertFalse(errors, errors)
        return results


@skipUnlessDBFeature("has_select_for_update")
class LedgerConcurrencyTests(ParallelActions, TransactionTestCase):
    def setUp(self):
        test_advanced_operations.AdvancedOperationsTests.setUp(self)

    def test_two_withdrawals_cannot_exceed_cash_balance(self):
        def action(index):
            try:
                move_cash(
                    session=self.session,
                    user=self.owner,
                    kind="withdrawal",
                    amount=80,
                    reason="Cofre",
                    key=f"cash-parallel-{index}",
                )
                return "ok"
            except ValidationError:
                return "denied"

        self.assertEqual(sorted(self.run_pair(action)), ["denied", "ok"])
        self.assertEqual(CashMovement.objects.count(), 1)
        self.assertEqual(cash_balance(self.session), 20)

    def test_same_material_consumption_key_replays_under_concurrency(self):
        def action(index):
            return consume_material(
                tenant=self.tenant,
                product_id=self.product.pk,
                quantity=2,
                user=self.owner,
                key="material-parallel",
                appointment=self.appt,
            ).pk

        result = self.run_pair(action)
        self.assertEqual(result[0], result[1])
        self.assertEqual(MaterialConsumption.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)


@skipUnlessDBFeature("has_select_for_update")
class BundleConcurrencyTests(ParallelActions, TransactionTestCase):
    def setUp(self):
        test_release_completion.ReleaseCompletionTests.setUp(self)

    def test_competing_bundles_reserve_the_whole_sequence_once(self):
        payload = test_release_completion.ReleaseCompletionTests.bundle(self)

        def action(index):
            return (
                Client()
                .post(
                    reverse("public-bundle-api", args=[self.tenant.slug]),
                    payload,
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=f"bundle-parallel-{index}",
                )
                .status_code
            )

        self.assertEqual(sorted(self.run_pair(action)), [201, 409])
        self.assertEqual(AppointmentBundle.objects.count(), 1)
        self.assertEqual(Appointment.objects.count(), 2)
