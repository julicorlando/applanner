from django import forms
from django.test import SimpleTestCase
from core.portal import PhysiotherapyRecordForm


class BodyFindingsValidationTests(SimpleTestCase):
    def validate(self,findings):
        form=PhysiotherapyRecordForm()
        form.cleaned_data={"body_findings":findings}
        return form.clean_body_findings()

    def test_accepts_laterality_pain_and_notes(self):
        result=self.validate({"knee_left":{"pain":7,"condition":"edema","note":"Sessão inicial"}})
        self.assertEqual(result["knee_left"]["pain"],7)

    def test_rejects_invalid_region_condition_pain_and_note(self):
        for findings in ([1],{"unknown":{}},{"knee_left":{"pain":11,"condition":"pain"}},
                {"knee_left":{"pain":True,"condition":"pain"}},
                {"knee_left":{"pain":4,"condition":"invalid"}},
                {"knee_left":{"pain":4,"condition":"pain","note":"x"*2001}}):
            with self.subTest(findings=findings),self.assertRaises(forms.ValidationError):
                self.validate(findings)

    def test_registration_is_required(self):
        self.assertTrue(PhysiotherapyRecordForm().fields["registration"].required)
