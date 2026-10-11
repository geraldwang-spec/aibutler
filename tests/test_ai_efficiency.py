import json
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_ai.llm_provider import GroqLLM, OllamaLLM, OpenAICompatibleLLM, LLMError, defer_rate_limits
from personal_ai.prompt_budget import bounded_json,source_blocks
from personal_ai.import_routing import repair_local_questions
from personal_ai.question_importer import extract_by_rules
from personal_ai.question_answering import infer_missing_answers


class EfficiencyTests(unittest.TestCase):
    def test_output_grows_only_after_truncation_and_resets_for_next_request(self):
        budgets=[]
        responses=iter([
            {'choices':[{'finish_reason':'length','message':{'content':'{"partial":'}}]},
            {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]},
            {'choices':[{'message':{'content':'{"ok":true}'}}]},
        ])
        def send(model,*args,**kwargs):
            budgets.append(model._request_options()['max_completion_tokens'])
            return next(responses)
        model=GroqLLM('test','unused')
        with patch.object(OpenAICompatibleLLM,'_request',autospec=True,side_effect=send),patch('personal_ai.jobs.guard'),patch('personal_ai.jobs.usage') as usage:
            model._request([])
            model._request([])
        self.assertEqual(budgets,[2048,4096,2048])
        self.assertEqual(usage.call_count,3)

    def test_ollama_starts_with_finite_output_and_expands_when_needed(self):
        responses=[{'choices':[{'finish_reason':'length'}]},{'choices':[{'finish_reason':'stop'}]}]
        with patch.object(OllamaLLM,'_native_chat',side_effect=responses) as native:
            OllamaLLM('http://localhost','test')._request([])
        self.assertEqual([call.kwargs['num_predict'] for call in native.call_args_list],[4096,8192])

    def test_provider_cooldown_skips_same_model_but_allows_other_model_without_sleep(self):
        checkpoint={}
        def get(key,default=None): return checkpoint.get(key,default)
        def put(key,value): checkpoint[key]=value
        response={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with patch('personal_ai.import_checkpoints.get',side_effect=get),patch('personal_ai.import_checkpoints.put',side_effect=put),patch('personal_ai.jobs.guard'),patch('personal_ai.jobs.usage'),patch('personal_ai.llm_provider.time.sleep') as sleep,patch.object(OpenAICompatibleLLM,'_request',side_effect=[LLMError('TPD',status_code=429,retry_after=1056),response]) as send:
            with defer_rate_limits():
                for _ in range(2):
                    with self.assertRaises(LLMError): GroqLLM('vision','unused')._request([])
                self.assertEqual(GroqLLM('text','unused')._request([]),response)
            sleep.assert_not_called()
            self.assertEqual(send.call_count,2)

    def test_rate_limited_repair_does_not_block_good_question_answers(self):
        sections=[{'text':'1. First?\nA. one\nB. two\n2. Missing choices?\n3. Last?\nA. one\nB. two'}]
        items=extract_by_rules(sections,'測試',True)
        class Solver:
            enabled=True
            provider='test'
            model='text'
            seen=[]
            def complete_json(self,system,user):
                rows=json.loads(user.split('\n回傳 ')[0])
                self.seen.extend(row['number'] for row in rows)
                return {'answers':[dict(number=row['number'],status='answered',answer='A',explanation='來源支持',context='') for row in rows]}
        model=Solver()
        with patch('personal_ai.question_importer.extract_with_llm',side_effect=LLMError('TPD',status_code=429,retry_after=1056)):
            repaired=repair_local_questions(sections,items,'測試',{})
        with patch('personal_ai.question_answering.get_parser_llm',return_value=model):
            result=infer_missing_answers(repaired,sections,Path('source.txt'),{})
        self.assertEqual(model.seen,[1,3])
        self.assertEqual([row['_question_no'] for row in result],[1,3])
        self.assertIn('_layout_needs_review',repaired[1])

    def test_rate_limited_answer_batch_is_postponed_and_later_batch_processed(self):
        rows=[dict(_question_no=i,content='題目',q_type='單選',answer_key='',option_A='甲',option_B='乙') for i in range(1,6)]
        class Solver:
            enabled=True
            provider='test'
            model='text'
            calls=0
            def complete_json(self,system,user):
                self.calls+=1
                if self.calls==1: raise LLMError('TPM',status_code=429,retry_after=10)
                return {'answers':[dict(number=5,status='answered',answer='A',explanation='來源支持',context='')]}
        with patch('personal_ai.question_answering.get_parser_llm',return_value=Solver()),patch('personal_ai.question_answering.time.sleep') as sleep:
            result=infer_missing_answers(rows,[],Path('source.txt'),{})
        self.assertEqual([row['_question_no'] for row in result],[5])
        sleep.assert_not_called()

    def test_prompt_compaction_preserves_required_material_and_source_boundaries(self):
        payload={'question':'完整題目','evidence':'完整閱讀材料'*500,'history':['old','latest']}
        result=json.loads(bounded_json(payload,limit=100))
        self.assertEqual(result['question'],payload['question'])
        self.assertEqual(result['evidence'],payload['evidence'])
        self.assertEqual(result['history'],[])
        block='[chunk:1] title\n'+'完整文章'*500+'\n\n'
        selected=source_blocks(block+'[chunk:2] different\nother','[chunk:',target=100)
        self.assertEqual(selected,block)


if __name__=='__main__': unittest.main()
