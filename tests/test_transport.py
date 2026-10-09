import ssl
import sys
import unittest
from unittest import mock

from fatofake.transport import default_ssl_context


class DefaultSslContextTests(unittest.TestCase):
    def test_falls_back_to_stdlib_when_truststore_is_missing(self) -> None:
        # None em sys.modules faz "import truststore" levantar ImportError
        with mock.patch.dict(sys.modules, {"truststore": None}):
            context = default_ssl_context()

        self.assertIsInstance(context, ssl.SSLContext)

    def test_uses_truststore_when_available(self) -> None:
        fake_truststore = mock.Mock()
        fake_truststore.SSLContext.return_value = "contexto-do-truststore"

        with mock.patch.dict(sys.modules, {"truststore": fake_truststore}):
            context = default_ssl_context()

        fake_truststore.SSLContext.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context, "contexto-do-truststore")
