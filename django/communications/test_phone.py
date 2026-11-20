from django.test import SimpleTestCase

from .phone import whatsapp_number


class WhatsAppNumberTests(SimpleTestCase):
    def test_brazilian_local_numbers_get_country_code_once(self):
        self.assertEqual(whatsapp_number("(81) 99999-9999"),"5581999999999")
        self.assertEqual(whatsapp_number("11 3456-7890"),"551134567890")
        self.assertEqual(whatsapp_number("+55 (81) 99999-9999"),"5581999999999")
        self.assertEqual(whatsapp_number("5581999999999"),"5581999999999")
