"""Offline transport contract checks; no real credentials or evidence modified."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.llm import client

POLICY = {'sentences': [{'clause_id': '1.1', 'text': 'Information.', 'kind': 'info'}], 'rules': []}


def completion(value, finish='stop'):
    return io.BytesIO(json.dumps({'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(value)}}]}).encode())


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'RECEIPT_LLM_PROVIDER': 'gemini', 'RECEIPT_LLM_API_KEY': 'test-only-token',
                                          'RECEIPT_LLM_MODEL': 'test-model', 'RECEIPT_LLM_ENDPOINT': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_money_schema_matches_runtime_string_requirement(self):
        schema = client.ReceiptFields.model_json_schema()
        assert {'type': 'number'} not in schema['properties']['total']['anyOf']
        self.assertEqual(client._validate({'total': '2521.61'}, client.ReceiptFields), {'total': '2521.61'})
        with self.assertRaises(client.LLMError):
            client._validate({'total': 2521.61}, client.ReceiptFields)

    def test_policy_translation_and_independent_calls(self):
        with patch.object(client, 'urlopen', side_effect=[completion(POLICY), completion(POLICY)]) as transport:
            for _ in range(2):
                self.assertEqual(client.compile_policy_text('source', .4, 12), POLICY)
        self.assertEqual(transport.call_count, 2)
        request = transport.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, client.GEMINI_ENDPOINT)
        self.assertEqual(body['temperature'], .4)
        self.assertEqual(body['model'], 'test-model')
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertIn('source', body['messages'][1]['content'])
        self.assertLessEqual(transport.call_args.kwargs['timeout'], 12)

    def test_receipt_cache_isolates_model_ocr_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(client, 'urlopen', side_effect=lambda *a, **k: completion({'total': '12.00', 'city': None})) as transport:
            for _ in range(2):
                self.assertEqual(client.extract_receipt_fields('text', 'sha', Path(tmp)), {'total': '12.00'})
            self.assertEqual(transport.call_count, 1)
            with patch.dict(os.environ, {'RECEIPT_LLM_MODEL': 'other-test-model'}):
                client.extract_receipt_fields('text', 'sha', Path(tmp))
            client.extract_receipt_fields('new OCR', 'sha', Path(tmp))
            with patch.object(client, 'SCHEMA_VERSION', 'new-version'):
                client.extract_receipt_fields('text', 'sha', Path(tmp))
            self.assertEqual(transport.call_count, 4)

    def test_invalid_outputs_fail(self):
        for result in [{}, {'sentences': [], 'rules': []}, {**POLICY, 'rules': [{'rule_type': 'INVENTED'}]}]:
            with self.subTest(result=result), patch.object(client, 'urlopen', return_value=completion(result)):
                with self.assertRaises(client.LLMError):
                    client.compile_policy_text('source')
        with patch.object(client, 'urlopen', return_value=completion(POLICY, 'length')):
            with self.assertRaises(client.LLMError):
                client.compile_policy_text('source')
        for raw in [{'total': 12.50}, {'guest_count': -1}, {'password': 'not-a-field'}]:
            with self.assertRaises(client.LLMError):
                client._validate(raw, client.ReceiptFields)

    def test_auth_error_sanitized_no_retry(self):
        error = HTTPError('https://example.invalid?secret=test-only-token', 401, 'test-only-token', {}, None)
        with patch.object(client, 'urlopen', side_effect=error) as transport:
            with self.assertRaises(client.LLMError) as caught:
                client.compile_policy_text('source')
        self.assertNotIn('test-only-token', str(caught.exception))
        self.assertEqual(transport.call_count, 1)

    def test_retry_transient_bounded(self):
        def rate_limit():
            return HTTPError('https://example.invalid', 429, 'limited', {}, None)
        with patch.object(client, 'urlopen', side_effect=[rate_limit(), completion(POLICY)]) as transport, patch.object(client.time, 'sleep'):
            self.assertEqual(client.compile_policy_text('source'), POLICY)
            self.assertEqual(transport.call_count, 2)
        with patch.object(client, 'urlopen', side_effect=lambda *a, **k: (_ for _ in ()).throw(rate_limit())) as transport, patch.object(client.time, 'sleep'):
            with self.assertRaisesRegex(client.LLMError, 'rate limited'):
                client.compile_policy_text('source')
            self.assertEqual(transport.call_count, 3)

    def test_custom_contract_and_unconfigured_fallback(self):
        with patch.dict(os.environ, {'RECEIPT_LLM_PROVIDER': 'custom', 'RECEIPT_LLM_ENDPOINT': 'http://localhost:9999/json', 'RECEIPT_LLM_API_KEY': ''}):
            with patch.object(client, 'urlopen', return_value=io.BytesIO(json.dumps(POLICY).encode())) as transport:
                self.assertEqual(client.compile_policy_text('source'), POLICY)
                self.assertIn('policy_text', json.loads(transport.call_args.args[0].data))
                self.assertNotIn('Authorization', transport.call_args.args[0].headers)
            with patch.dict(os.environ, {'RECEIPT_LLM_ENDPOINT': ''}):
                self.assertEqual(client.extract_receipt_fields('', 'sha', Path('/unused')), {})
                with self.assertRaises(client.LLMError):
                    client.compile_policy_text('source')

    def test_models_and_required_config(self):
        with patch.object(client, 'urlopen', return_value=io.BytesIO(b'{"data":[{"id":"models/test-model"}]}')):
            self.assertEqual(client.list_gemini_models(), ['test-model'])
        for key in ['RECEIPT_LLM_API_KEY', 'RECEIPT_LLM_MODEL']:
            with patch.dict(os.environ, {key: ''}), self.assertRaises(client.LLMError):
                client.compile_policy_text('source')

    def test_malformed_json_and_timeout(self):
        with patch.object(client, 'urlopen', return_value=io.BytesIO(b'not JSON')):
            with self.assertRaisesRegex(client.LLMError, 'malformed JSON'):
                client.compile_policy_text('source')
        with patch.object(client, 'urlopen', side_effect=TimeoutError()), patch.object(client.time, 'sleep'):
            with self.assertRaisesRegex(client.LLMError, 'timed out'):
                client.compile_policy_text('source')
