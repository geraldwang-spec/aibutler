import json
import unittest
from unittest.mock import patch
from personal_ai.llm_provider import GroqLLM,OpenAICompatibleLLM,LLMError
from personal_ai.prompt_budget import bounded_json
from personal_ai.question_validation import validate
from personal_ai.jobs import active_job


class UnlimitedAITests(unittest.TestCase):
    def test_legacy_env_does_not_restore_hard_quota_but_requests_have_efficiency_targets(self):
        with patch.dict('os.environ',{'GROQ_MAX_OUTPUT_TOKENS':'800','GROQ_MAX_INPUT_BYTES':'2000'}):
            model=GroqLLM('openai/gpt-oss-20b','unused')
        self.assertEqual(model._request_options()['max_completion_tokens'],2048)
        self.assertEqual(model.max_output_tokens,2048)
        self.assertEqual(model.max_input_bytes,16000)
    def test_large_input_and_more_than_three_images_reach_transport(self):
        messages=[dict(role='user',content=[dict(type='text',text='large input '*3000)]+
                       [dict(type='image_url',image_url={'url':'data:image/png;base64,a'}) for _ in range(4)])]
        response={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with patch.object(OpenAICompatibleLLM,'_request',return_value=response) as send,patch('personal_ai.jobs.guard'),patch('personal_ai.jobs.usage'):
            self.assertEqual(GroqLLM('test','unused')._request(messages),response)
        send.assert_called_once()
    def test_prompt_keeps_long_question_and_full_evidence_but_drops_optional_history(self):
        payload={'question':'Q'*25000,'evidence':'教材'*5000,'history':['one','two','three']}
        encoded=json.loads(bounded_json(payload))
        self.assertEqual(encoded['question'],payload['question'])
        self.assertEqual(encoded['evidence'],payload['evidence'])
        self.assertEqual(encoded['history'],[])
        self.assertEqual(payload['history'],['one','two','three'])
    def test_long_question_options_and_explanation_are_validated_without_length_cap(self):
        content='長題原文'*6000
        data,_=validate(dict(content=content,answer_key='A',q_type='單選',explanation=content),{'A':'甲'*15000,'B':'乙'*15000})
        self.assertEqual(data['content'],content)
    def test_long_provider_cooldown_is_cancellable(self):
        token=active_job.set(dict(app=None,id='test',user_id=1))
        try:
            with patch('personal_ai.jobs.read',return_value={'cancel':1}),patch('personal_ai.jobs.update'),patch('personal_ai.llm_provider.time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError,'取消'):
                    GroqLLM('test')._wait_for_rate_limit(LLMError('TPD',status_code=429,retry_after=848),1)
                sleep.assert_not_called()
        finally: active_job.reset(token)
    def test_provider_request_larger_than_quota_is_not_retried_forever(self):
        with patch('personal_ai.llm_provider.time.sleep') as sleep:
            self.assertFalse(GroqLLM('test')._wait_for_rate_limit(LLMError('Limit 8000, Used 0, Requested 9000',retry_after=60),1))
            sleep.assert_not_called()
    def test_provider_minute_and_second_cooldown_is_parsed(self):
        import io
        import urllib.error
        error=urllib.error.HTTPError('https://example.com',429,'rate',{},io.BytesIO(json.dumps({'error':{
            'code':'rate_limit_exceeded','message':'Please try again in 14m7.584s.'}}).encode()))
        with patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaises(LLMError) as caught:
                OpenAICompatibleLLM('https://example.com','test')._request([])
        self.assertAlmostEqual(caught.exception.retry_after,847.584)
    def test_cpu_wait_does_not_stop_at_sixty_poll_intervals(self):
        import queue
        from unittest.mock import MagicMock
        from personal_ai.exam_modules import cpu
        process=MagicMock()
        process.poll.return_value=None
        responses=MagicMock()
        responses.get.side_effect=[queue.Empty()]*65+[json.dumps({'ok':True,'result':['done']})]
        with patch('personal_ai.exam_modules._process',process),patch('personal_ai.exam_modules._responses',responses):
            self.assertEqual(cpu('test'),['done'])
        self.assertEqual(responses.get.call_count,66)
    def test_upload_configuration_has_no_application_caps(self):
        import tempfile
        from pathlib import Path
        from smartlife import create_app
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(dict(TESTING=True,DB_TYPE='sqlite',DATABASE=str(Path(directory)/'test.db'),SECRET_KEY='test'))
            for key in ('MAX_CONTENT_LENGTH','MAX_FORM_MEMORY_SIZE','MAX_FORM_PARTS'):
                self.assertIsNone(app.config[key])


if __name__=='__main__': unittest.main()
