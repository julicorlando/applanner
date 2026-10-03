from django.test import SimpleTestCase

from .hostnames import public_allowed_host


class PublicHostTests(SimpleTestCase):
    def test_public_https_domain_can_be_added_to_allowed_hosts(self):
        self.assertEqual(public_allowed_host("https://applanner.axionwebdigital.com.br/"),"applanner.axionwebdigital.com.br")

    def test_insecure_or_malformed_urls_do_not_change_allowed_hosts(self):
        for value in ("", "http://example.test", "https://user:pass@example.test",
                      "https://example.test/path", "https://[invalid"):
            with self.subTest(url=value):
                self.assertEqual(public_allowed_host(value),"")
