import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import training_catalog as catalog
import psg_agent

class ProgramPanel(unittest.TestCase):
    def snapshot(self):
        return {'students':[
            {'fio_nom':'Тестов Иван Иванович','program':'Высота'},
            {'fio_nom':'Примеров Петр Петрович','program':'Квалификационное Высота.'},
            {'fio_nom':'Образцов Алексей Иванович','program':'ПП'}], 'source':'Синтетическая заявка', 'title':'Заявка', 'ai_errors':[], 'recognition_issues':[], 'ai_candidates':[], 'engines':['test']}
    def run_application(self,temp,snapshot,**overrides):
        return psg_agent.process_application(recognized_input=snapshot,output_file=str(Path(temp)/'result.docx'),manual_overrides={'study_dates':'28.09.2026','date_role':'start',**overrides})
    def test_catalog_ordinals_and_hours(self):
        for q in ['Безопасные методы и приемы выполнения работ в электроустановках','Безопасные методы и приемы выполнения земляных работ']:
            result=catalog.resolve(q)
            self.assertTrue(result['is_canonical']);self.assertEqual(result['hours'],8)
        self.assertNotEqual(catalog.resolve('Высота 1 группа')['id'],catalog.resolve('Высота 2 группа')['id'])
    def test_height_suggestions_only_relevant_and_offered(self):
        for q in ['Высота','Квалификационное Высота.']:
            result=catalog.resolve(q)
            self.assertFalse(result['is_canonical'])
            self.assertTrue(result['candidates'])
            self.assertTrue(all('высот' in p['name'].lower() and p['status']=='offered' for p in result['candidates']))
            self.assertEqual({h for p in result['candidates'] for h in p['hours']},{8,24})
    def test_scoped_replacement_preserves_other_rows_and_source(self):
        source=self.snapshot();original=copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as temp, patch('doc_reader.parse_incoming_application',side_effect=AssertionError('must not OCR again')):
            result=self.run_application(temp,source,program_replacements={'Высота':catalog.resolve('Высота 2 группа')['id']})
        self.assertEqual(source,original)
        groups=result['grouped_data']
        self.assertIn('Квалификационное Высота.',groups)
        self.assertEqual(len(groups[catalog.resolve('Высота 2 группа')['name']]['students']),1)
        row=groups[catalog.resolve('Высота 2 группа')['name']]['students'][0]
        self.assertEqual(row['study_dates'],'28.09.2026 - 30.09.2026')
        self.assertEqual(row['recognition']['program_input'],'Высота')
        self.assertEqual(len(result['program_questions']),2)
        self.assertTrue(any(p['hours']==16 for p in groups.values()))
    def test_replacement_can_be_changed_from_original(self):
        with tempfile.TemporaryDirectory() as temp:
            first=self.run_application(temp,self.snapshot(),program_replacements={'Высота':catalog.resolve('Высота 1 группа')['id']})
            second=self.run_application(temp,first['_recognized_input'],program_replacements={'Высота':catalog.resolve('Высота 3 группа')['id']})
        self.assertNotIn(catalog.resolve('Высота 1 группа')['name'],second['grouped_data'])
        self.assertIn(catalog.resolve('Высота 3 группа')['name'],second['grouped_data'])
    def test_no_false_missing_dates_violation(self):
        with tempfile.TemporaryDirectory() as temp:result=self.run_application(temp,self.snapshot())
        self.assertFalse(any('Сроки обучения не указаны' in x['message'] for x in result['audit']['rule_violations']))
        self.assertTrue(result['program_questions'])
    def test_api_snapshot_recalculation_and_validation(self):
        from fastapi.testclient import TestClient
        import web_app
        client=TestClient(web_app.app)
        with tempfile.TemporaryDirectory() as temp, patch('psg_agent.doc_reader.parse_raw_text_application',return_value={'students':self.snapshot()['students'],'title':'Заявка'}), patch('web_app.BASE_DIR',temp):
            Path(temp,'output_1c').mkdir()
            # Always use a temporary destination for initial text processing too.
            original=psg_agent.process_application
            def process(**kwargs):
                kwargs['output_file']=str(Path(temp)/'output_1c'/'test.docx')
                return original(**kwargs)
            with patch('web_app.psg_agent.process_application',side_effect=process):
                first=client.post('/api/process',data={'raw_text':'test','study_dates':'28.09.2026','date_role':'start'}).json()
                self.assertNotIn('_recognized_input',first)
                token=first['recognition_token']
                import json
                with patch('doc_reader.parse_raw_text_application',side_effect=AssertionError('repeated recognition')):
                    second=client.post('/api/process',data={'recognition_token':token,'study_dates':'28.09.2026','date_role':'start','program_replacements':json.dumps({'Высота':catalog.resolve('Высота 1 группа')['id']})})
                self.assertEqual(second.status_code,200)
                self.assertEqual(second.json()['unique_students'],3)
                self.assertEqual(client.post('/api/process',data={'program_replacements':'{"x":"not-real"}'}).status_code,422)
                self.assertEqual(client.post('/api/process',data={'recognition_token':'expired'}).status_code,410)

    def test_selection_from_full_catalog_remains_visible(self):
        selected=catalog.resolve('ПП')
        with tempfile.TemporaryDirectory() as temp:
            result=self.run_application(temp,self.snapshot(),program_replacements={'Высота':selected['id']})
        question=next(q for q in result['program_questions'] if q['name']=='Высота')
        self.assertTrue(any(c['id']==selected['id'] and c['hours']==[16,8] for c in question['candidates']))
