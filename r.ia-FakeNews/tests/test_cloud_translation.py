import unittest

from fatofake.cloud_translation import GoogleCloudTranslator, TranslationError


class Response:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
    def raise_for_status(self):
        if self.error:
            raise self.error
    def json(self):
        return self.payload


class CloudTranslationTests(unittest.TestCase):
    def test_translates_batch_with_api_key_header(self):
        calls = []
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Response({"data": {"translations": [
                {"translatedText": "Objetivo em português"},
                {"translatedText": "Pergunta em português"},
            ]}})
        translator = GoogleCloudTranslator("secret", post=post)

        result = translator.translate(["Objetivo", "Pregunta"])

        self.assertEqual(result, ["Objetivo em português", "Pergunta em português"])
        self.assertEqual(calls[0][1]["headers"], {"x-goog-api-key": "secret"})
        self.assertEqual(calls[0][1]["json"]["target"], "pt")

    def test_rejects_incomplete_response(self):
        translator = GoogleCloudTranslator(
            "secret", post=lambda *_args, **_kwargs: Response({"data": {"translations": []}})
        )
        with self.assertRaises(TranslationError):
            translator.translate(["Texto"])


if __name__ == "__main__":
    unittest.main()
