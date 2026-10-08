from django.test import SimpleTestCase

from .hostnames import normalize_public_base_url, public_allowed_host


class PublicHostTests(SimpleTestCase):
    def test_public_https_domain_can_be_added_to_allowed_hosts(self):
        self.assertEqual(public_allowed_host("https://applanner.axionwebdigital.com.br/"),"applanner.axionwebdigital.com.br")

    def test_insecure_or_malformed_urls_do_not_change_allowed_hosts(self):
        for value in ("", "http://example.test", "https://user:pass@example.test",
                      "https://example.test/path", "https://[invalid"):
            with self.subTest(url=value):
                self.assertEqual(public_allowed_host(value),"")


class PublicBaseURLTests(SimpleTestCase):
    def test_url_and_accidentally_pasted_assignment_produce_the_same_origin(self):
        for value in ('https://applanner.com.br/', ' PUBLIC_BASE_URL=https://applanner.com.br/ ',
                      'PUBLIC_BASE_URL="https://applanner.com.br/"', '"PUBLIC_BASE_URL=https://applanner.com.br/"'):
            with self.subTest(value=value):
                normalized=normalize_public_base_url(value)
                self.assertEqual(normalized,'https://applanner.com.br')
                self.assertEqual(public_allowed_host(normalized),'applanner.com.br')

    def test_empty_origin_and_unrelated_assignments_are_not_invented(self):
        self.assertEqual(normalize_public_base_url(''),'')
        value=normalize_public_base_url('OTHER_URL=https://example.test')
        self.assertEqual(public_allowed_host(value),'')
