"""Offline regression checks; never opens a real database or Access file."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import mongomock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from demo_storage import ensure_seeded, SEED_MARKER


class Collection:
    def __init__(self, value):self.value=value
    def __getattr__(self,name):
        method=getattr(self.value,name)
        def call(*args,**kwargs):
            kwargs.pop('session',None)
            return method(*args,**kwargs)
        return call


class Session:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def with_transaction(self,fn):return fn(self)


class Client:
    def start_session(self):return Session()


class Database:
    """Session-compatible test double; not a substitute for an Atlas integration test."""
    client=Client()
    def __init__(self,value):self.value=value
    def __getitem__(self,name):return Collection(self.value[name])
    def __getattr__(self,name):return self[name]


class StorageTests(unittest.TestCase):
    def test_cold_start_keeps_existing_demo_changes(self):
        raw=mongomock.MongoClient().demo
        first=Database(raw)
        def fixture(db):db.products.insert_one({'_id':'sample','name':'Fictional'})
        ensure_seeded(first,fixture)
        raw.products.update_one({'_id':'sample'},{'$set':{'name':'Recruiter edit'}})
        ensure_seeded(Database(raw),lambda db:self.fail('Cold start reseeded demo'))
        self.assertEqual(raw.products.find_one()['name'],'Recruiter edit')
        self.assertIsNotNone(raw.platform_meta.find_one({'_id':SEED_MARKER}))

    def test_unmarked_populated_database_is_rejected(self):
        raw=mongomock.MongoClient().demo
        raw.users.insert_one({'_id':'existing'})
        with self.assertRaisesRegex(RuntimeError,'new, empty'):
            ensure_seeded(Database(raw),lambda db:None)
        self.assertEqual(raw.users.count_documents({}),1)
        self.assertIsNone(raw.platform_meta.find_one({'_id':SEED_MARKER}))

    def test_serverless_requires_persistent_configuration(self):
        env={k:v for k,v in os.environ.items() if k not in ('DEMO_MONGO_URI','DEMO_MONGO_DB','FLASK_SECRET')}
        env['VERCEL']='1'
        result=subprocess.run([sys.executable,'-c','from unittest.mock import patch\nwith patch("dotenv.load_dotenv",return_value=False):\n import run_demo'],cwd=ROOT,env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Set DEMO_MONGO_URI',result.stderr)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,{'VERCEL':'0','DEMO_MONGO_URI':''}),patch('dotenv.load_dotenv',return_value=False):
            import run_demo
        cls.demo=run_demo
        cls.app=run_demo.module.app
        cls.db=run_demo.module.db

    def setUp(self):
        self.client=self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:token=s['platform_csrf']
        self.assertEqual(self.client.post('/',data={'username':'Maya','platform_csrf':token}).status_code,302)

    def headers(self):
        self.client.get('/purchase-orders/new');self.client.get('/documents/delivery/new')
        with self.client.session_transaction() as s:
            return s,{key:{'X-CSRF-Token':s[key]} for key in ('po_csrf','document_csrf','platform_csrf')}

    def test_document_previews_exports_dispatch_and_receipt(self):
        session,headers=self.headers();doc_headers=headers['document_csrf'];po_headers=headers['po_csrf']
        body={'party':{'name':'Fictional buyer','address':'Example Street'},'date':'2026-10-19','currency':'MYR',
              'items':[{'uid':'DEMO-001','description':'Luma Airless Pump 30ml','quantity':'2','unit_price':'1.2000','discount':'0','tax':'0','location':'DEMO1'}]}
        for kind in ('quotation','proforma','delivery'):
            preview=self.client.post('/documents/api/'+kind+'/preview',json=body,headers=doc_headers)
            self.assertEqual(preview.status_code,200,preview.data[:200]);self.assertTrue(preview.data.startswith(b'%PDF'))
            created=self.client.post('/documents/api/'+kind,json=body,headers=doc_headers)
            self.assertEqual(created.status_code,201,created.data[:200])
            number=created.json['number']
            exported=self.client.get('/documents/'+kind+'/'+number+'/pdf')
            self.assertEqual(exported.status_code,200);self.assertTrue(exported.data.startswith(b'%PDF'))
            if kind=='delivery':
                ready=self.client.post('/documents/api/delivery/'+number+'/status',json={'status':'ready','revision':1},headers=doc_headers)
                self.assertEqual(ready.status_code,200,ready.data[:200])
                before=self.db.products.find_one({'uid':'DEMO-001'})['stock']
                dispatch=self.client.post('/documents/api/delivery/'+number+'/dispatch',json={},headers=doc_headers)
                self.assertEqual(dispatch.status_code,202,dispatch.data[:200])
                self.assertEqual(self.db.products.find_one({'uid':'DEMO-001'})['stock'],before-2)
                self.assertEqual(self.client.get('/documents/delivery/'+number).status_code,200)
                self.assertEqual(self.db.business_documents.find_one({'_id':number})['status'],'dispatched')
        po={'supplier':{'name':'Imaginary Packaging Co.','details':'Example Street'},'date':'2026-10-19','currency':'MYR',
            'discount_type':'amount','discount_value':'0','items':[{'product_id':'DEMO-001','description':'Luma Airless Pump 30ml','quantity':'2','unit_price':'1.2000'}]}
        created=self.client.post('/purchase-orders/api/orders',json=po,headers=po_headers)
        self.assertEqual(created.status_code,201,created.data[:200]);number=created.json['number']
        self.assertEqual(self.client.post('/purchase-orders/api/preview',json=po,headers=po_headers).status_code,200)
        exported=self.client.get('/purchase-orders/'+number+'/pdf')
        self.assertEqual(exported.status_code,200);self.assertTrue(exported.data.startswith(b'%PDF'))
        final=self.client.post('/purchase-orders/api/orders/'+number+'/finalise',json={'revision':1},headers=po_headers)
        self.assertEqual(final.status_code,200,final.data[:200])
        receive=self.client.post('/purchase-orders/api/orders/'+number+'/receive',json={'receive_all':True,'operation_id':str(uuid4())},headers=po_headers)
        self.assertEqual(receive.status_code,202,receive.data[:200])
        self.client.get('/purchase-orders/'+number)
        self.assertEqual(self.db.purchase_orders.find_one({'_id':number})['status'],'received')
        self.assertEqual(self.db.sync_events.count_documents({'status':'pending'}),0)

    def test_simulated_reconciliation_and_pricing(self):
        _,headers=self.headers()
        response=self.client.post('/platform/api/sync/wake',json={},headers=headers['platform_csrf'])
        self.assertEqual(response.status_code,200,response.data[:200])
        self.assertIn('Demo reconciliation complete',response.json['message'])
        prices=self.client.get('/purchase-orders/api/prices?uid=DEMO-001&currency=MYR&date=2026-10-19')
        self.assertEqual(prices.status_code,200);self.assertTrue(prices.json)
        self.assertTrue(all(row['tier']=='1K' for row in prices.json))


if __name__=='__main__':unittest.main(verbosity=2)
