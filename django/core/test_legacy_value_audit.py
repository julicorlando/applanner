from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.management.commands.audit_legacy_parity import Command


class LegacyValueAuditTests(SimpleTestCase):
    def test_equal_counts_with_changed_module_price_are_rejected(self):
        connection=MagicMock()
        cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value=[{
            "slug":"agenda", "name":"Agenda", "description":"", "addon_monthly_price":20,
            "addon_sellable":1, "sort_order":0, "active":1,
        }]
        model=MagicMock()
        model.objects.values.return_value=[{
            "slug":"agenda", "name":"Agenda", "description":"", "addon_monthly_price":30,
            "addon_sellable":True, "sort_order":0, "active":True,
        }]
        columns=set(cursor.fetchall.return_value[0])
        self.assertEqual(Command()._value_differences(connection,"modules",model,columns),["agenda"])
        model.objects.values.return_value=[dict(cursor.fetchall.return_value[0],addon_sellable=True,active=True)]
        self.assertEqual(Command()._value_differences(connection,"modules",model,columns),[])

    def test_plan_module_enabled_mismatch_is_detected_with_equal_counts(self):
        connection=MagicMock()
        cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect=[
            [{"plan_id":1,"module_id":2,"enabled":1}],
            [{"id":1,"slug":"basic"}],
            [{"id":2,"slug":"agenda"}],
        ]
        model=MagicMock()
        model.objects.values.return_value=[{"plan_id":1,"module_id":2,"enabled":False}]
        plan=MagicMock()
        plan.objects.values_list.return_value=[(1,"basic")]
        module=MagicMock()
        module.objects.values_list.return_value=[(2,"agenda")]
        with patch("core.management.commands.audit_legacy_parity.apps.get_model",side_effect=[plan,module]):
            self.assertEqual(Command()._value_differences(
                connection,"plan_modules",model,{"plan_id","module_id","enabled"}
            ),["basic"])
