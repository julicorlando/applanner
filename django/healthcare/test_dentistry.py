from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from .dentistry import validate_odontogram, dental_professional_allowance


class DentalChartValidationTests(SimpleTestCase):
    def test_accepts_permanent_and_primary_fdi(self):
        result = validate_odontogram({
            "11": [{"condition": "carie", "surfaces": ["mesial", "oclusal"], "note": "Observado"}],
            "55": [{"condition": "higido", "surfaces": [], "note": ""}],
        })
        self.assertEqual(len(result), 2)

    def test_rejects_non_fdi_tooth(self):
        with self.assertRaises(ValidationError):
            validate_odontogram({"99": []})

    def test_rejects_invalid_surface(self):
        with self.assertRaises(ValidationError):
            validate_odontogram({"11": [{"condition": "carie", "surfaces": ["unknown"]}]})
