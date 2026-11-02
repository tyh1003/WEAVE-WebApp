"""Offline SDK exceptions and responses only; never instantiate a live client."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

BACKEND=Path(__file__).resolve().parents[1]/'backend'
sys.path.insert(0,str(BACKEND))
from google.genai import errors, types
from retrieve_diagnostics import sanitize


class RetrieveDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        spec=importlib.util.spec_from_file_location('retrieve_diagnostics_test',BACKEND/'Retrieve.py')
        self.r=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{'WEAVE_WORK_DIR':str(self.root),'GEMINI_API_KEY':'mock-private-key'}),patch('dotenv.load_dotenv'):
            spec.loader.exec_module(self.r)
        self.contents=[types.Part.from_bytes(data=b'private-image-bytes',mime_type='image/png'),'private transcript text']
        self.response=SimpleNamespace(text=json.dumps({'Rc':' claim ','Rv':'visual','K_int':'internal','K_ext':'external'}),candidates=[])
    def error(self,code):
        return errors.ClientError(code,{'error':{'code':code,'status':'INVALID_ARGUMENT' if code==400 else 'UNAVAILABLE',
            'message':'Invalid configuration; api_key=mock-private-key Bearer private-token private transcript text',
            'details':[{'@type':'type.googleapis.com/google.rpc.BadRequest','fieldViolations':[{'field':'tools','description':'Invalid tool setting'}],
                       'headers':{'Authorization':'private-header'},'contents':'private transcript text','api_key':'private-nested-key'}]}})
    def run_calls(self,side_effect):
        generate=Mock(side_effect=side_effect);client=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        output=io.StringIO()
        with patch.object(self.r.genai,'Client',return_value=client),patch.object(self.r.time,'sleep') as sleep,patch.object(self.r,'save_model_response') as save,contextlib.redirect_stdout(output):
            result=self.r.generate_with_retry(self.contents,'fixture')
        return result,generate,sleep,save,output.getvalue()
    def test_400_structured_sanitized_diagnostics_and_no_retry(self):
        (result,error),generate,sleep,save,log=self.run_calls([self.error(400)])
        self.assertIsNone(result);self.assertIsInstance(error,str);self.assertEqual(error.http_code,400)
        generate.assert_called_once();sleep.assert_not_called();save.assert_not_called()
        paths=list(self.r.OUTPUT_DIR.glob('retrieve_error_*.json'));self.assertEqual(len(paths),1)
        d=json.loads(paths[0].read_text(encoding='utf-8'))
        self.assertEqual(d['exception_class'],'google.genai.errors.ClientError');self.assertEqual(d['http_code'],400)
        self.assertEqual(d['structured_error']['error']['details'][0]['fieldViolations'][0]['field'],'tools')
        self.assertTrue(d['traceback']);self.assertTrue(any(f['function']=='generate_with_client' for f in d['traceback']))
        self.assertEqual(d['request']['model'],self.r.MODEL_NAME);self.assertEqual(d['request']['tools'],[{'google_search':{}}])
        serialized=json.dumps(d)+log+error
        for secret in ['mock-private-key','private-token','private-header','private-nested-key','private transcript text','private-image-bytes']:
            self.assertNotIn(secret,serialized)
        self.assertNotIn('headers',d['structured_error']['error']['details'][0])
        self.assertEqual(d['request']['images'],[{'mime_type':'image/png','bytes':19}])
    def test_transient_retry_then_success_preserves_request_and_output(self):
        (result,raw),generate,sleep,save,_=self.run_calls([self.error(429),self.response])
        self.assertEqual(generate.call_count,2);sleep.assert_called_once();save.assert_called_once()
        self.assertEqual({k:result[k] for k in ('Rc','Rv','K_int','K_ext')},{'Rc':'claim','Rv':'visual','K_int':'internal','K_ext':'external'})
        self.assertEqual(raw,self.response.text)
        self.assertEqual(generate.call_args.kwargs['contents'],self.contents)
        config=generate.call_args.kwargs['config']
        self.assertEqual(config.system_instruction,self.r.SYSTEM_PROMPT);self.assertEqual(config.temperature,0.0)
        self.assertIsNotNone(config.tools[0].google_search)
    def test_transient_retries_bounded_and_diagnostics_append(self):
        (result,_),generate,sleep,_,_=self.run_calls([self.error(503)]*3)
        self.assertIsNone(result);self.assertEqual(generate.call_count,3);self.assertEqual(sleep.call_count,2)
        self.assertEqual(len(list(self.r.OUTPUT_DIR.glob('retrieve_error_*.json'))),3)
    def test_success_does_not_create_error_files(self):
        (result,_),generate,sleep,save,_=self.run_calls([self.response])
        self.assertIsNotNone(result);generate.assert_called_once();sleep.assert_not_called();save.assert_called_once()
        self.assertEqual(list(self.r.OUTPUT_DIR.glob('retrieve_error_*.json')),[])
    def test_url_encoded_credentials_and_headers_redacted(self):
        text=sanitize('https://user:pass@example.com?key=secret Authorization: "Bearer hidden" access_token=hidden2 a%2Bb',['a+b'])
        for value in ['user:pass','secret','hidden','hidden2','a%2Bb']:self.assertNotIn(value,text)
    def test_diagnostic_disk_failure_does_not_replace_original_error(self):
        with patch('retrieve_diagnostics.json.dump',side_effect=OSError('fixture disk failure')):
            (_,error),generate,sleep,_,_=self.run_calls([self.error(400)])
        self.assertEqual(error.http_code,400);generate.assert_called_once();sleep.assert_not_called()
