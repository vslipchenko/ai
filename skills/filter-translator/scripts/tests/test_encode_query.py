import unittest

import encode_query as eq


class PercentEncodeTest(unittest.TestCase):
    def test_unreserved_chars_untouched(self):
        self.assertEqual(eq.percent_encode("Abc123-._~"), "Abc123-._~")

    def test_space_becomes_percent_20_not_plus(self):
        self.assertEqual(eq.percent_encode("a b"), "a%20b")

    def test_tilde_is_never_escaped(self):
        # Known Python/Node divergence point if delegated to stdlib encoders.
        self.assertEqual(eq.percent_encode("a~b"), "a~b")

    def test_reserved_ascii_punctuation_escaped_uppercase_hex(self):
        self.assertEqual(eq.percent_encode("a&b=c?d#e%f"), "a%26b%3Dc%3Fd%23e%25f")

    def test_unicode_encoded_as_utf8_bytes(self):
        self.assertEqual(eq.percent_encode("café"), "caf%C3%A9")

    def test_empty_string(self):
        self.assertEqual(eq.percent_encode(""), "")


class EncodePairsTest(unittest.TestCase):
    def test_single_pair(self):
        self.assertEqual(eq.encode_pairs([("status", "Done")]), "status=Done")

    def test_multiple_pairs_joined_with_ampersand_in_order(self):
        self.assertEqual(
            eq.encode_pairs([("a", "1"), ("b", "2 3")]), "a=1&b=2%203"
        )

    def test_pair_with_reserved_and_unicode(self):
        self.assertEqual(
            eq.encode_pairs([("$filter", "name eq 'café'")]),
            "%24filter=name%20eq%20%27caf%C3%A9%27",
        )


if __name__ == "__main__":
    unittest.main()
