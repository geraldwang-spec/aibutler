"""Transport regression tests without Flask or live API credentials."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GroqTransportTests(unittest.TestCase):
    def test_clients_send_application_agent_and_authentication(self):
        root = Path(__file__).resolve().parents[1]
        provider = load_module(root / 'personal_ai' / 'llm_provider.py')
        body = load_module(root / 'body' / 'llm_client.py')
        for name in ('personal_ai', 'body'):
            with self.subTest(client=name), patch('urllib.request.urlopen') as send:
                response = MagicMock()
                response.read.return_value = json.dumps({'ok': True}).encode()
                send.return_value.__enter__.return_value = response
                if name == 'personal_ai':
                    result = provider.GroqLLM('test-model', 'test-key')._request([])
                else:
                    result = body.BodyLlmClient(provider.GROQ_BASE_URL, 'test-model', 'test-key')._request(
                        provider.GROQ_BASE_URL + '/chat/completions', 'test-key', {'messages': []})
                request = send.call_args.args[0]
                self.assertEqual(request.get_header('User-agent'), 'AI-Butler/1.0')
                self.assertEqual(request.get_header('Accept'), 'application/json')
                self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
                self.assertEqual(result, {'ok': True})


if __name__ == '__main__':
    unittest.main()
