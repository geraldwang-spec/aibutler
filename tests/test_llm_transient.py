import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from personal_ai.llm_provider import GroqLLM, OpenAICompatibleLLM, LLMError
from personal_ai.jobs import active_job


class TransientTests(unittest.TestCase):
    def test_cloudflare_metadata_is_read_from_top_level_body(self):
        error=urllib.error.HTTPError('https://example.com',520,'failure',{},io.BytesIO(
            json.dumps(dict(error_code=520,retry_after=60,detail='x'*1500)).encode()))
        with patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaises(LLMError) as caught:
                OpenAICompatibleLLM('https://example.com','test')._request([])
        self.assertEqual(caught.exception.retry_after,60)
        self.assertEqual(caught.exception.error_code,520)

    def test_transient_failure_retries_once_and_counts_both_attempts(self):
        answer={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with patch.object(OpenAICompatibleLLM,'_request',side_effect=[LLMError('520',status_code=520,retry_after=60),answer]) as send, \
             patch.object(GroqLLM,'_wait_for_retry',return_value=True) as wait, \
             patch('personal_ai.jobs.guard') as guard,patch('personal_ai.jobs.usage'):
            self.assertEqual(GroqLLM('test','unused')._request([]),answer)
        self.assertEqual(send.call_count,2)
        self.assertEqual(guard.call_count,2)
        wait.assert_called_once_with(60)

    def test_repeated_failure_stops_without_raw_cloudflare_json(self):
        with patch.object(OpenAICompatibleLLM,'_request',side_effect=LLMError('raw Cloudflare',status_code=520)), \
             patch.object(GroqLLM,'_wait_for_retry',return_value=True),patch('personal_ai.jobs.guard'):
            with self.assertRaisesRegex(LLMError,'Groq 服務暫時') as caught:
                GroqLLM('test','unused')._request([])
        self.assertNotIn('raw Cloudflare',str(caught.exception))

    def test_auth_failure_is_not_retried(self):
        with patch.object(OpenAICompatibleLLM,'_request',side_effect=LLMError('401',status_code=401)) as send, \
             patch.object(GroqLLM,'_wait_for_retry') as wait,patch('personal_ai.jobs.guard'):
            with self.assertRaises(LLMError): GroqLLM('test','unused')._request([])
        self.assertEqual(send.call_count,1)
        wait.assert_not_called()

    def test_wait_is_bounded_and_honors_provider_delay(self):
        with patch('personal_ai.llm_provider.time.sleep') as sleep:
            self.assertTrue(GroqLLM('test')._wait_for_retry(60))
            self.assertEqual(sleep.call_count,60)
            self.assertFalse(GroqLLM('test')._wait_for_retry(120))
            self.assertEqual(sleep.call_count,60)

    def test_job_without_total_deadline_can_retry_and_remains_cancellable(self):
        token=active_job.set(dict(app=None,id='test',user_id=1))
        try:
            with patch('personal_ai.jobs.read',return_value={'cancel':0}),patch('personal_ai.llm_provider.time.sleep') as sleep:
                self.assertTrue(GroqLLM('test')._wait_for_retry(60))
                self.assertEqual(sleep.call_count,60)
            with patch('personal_ai.jobs.read',return_value={'cancel':1}),patch('personal_ai.llm_provider.time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError,'取消'):
                    GroqLLM('test')._wait_for_retry(60)
                sleep.assert_not_called()
        finally: active_job.reset(token)
