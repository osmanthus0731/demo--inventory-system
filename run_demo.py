"""Loopback-only, in-memory demonstration. No real database or Access connection."""
import os
from pathlib import Path
import secrets
import sys
from threading import RLock
from unittest.mock import patch
import mongomock

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
sys.path.insert(0,str(ROOT))
for key in list(os.environ):
    if key.startswith(('ACCESS_','MONGO_','SYNC_','BOOTSTRAP_','FALLBACK_')): os.environ.pop(key,None)
os.environ.update(MONGO_URI='mongodb://localhost/mizitco_demo',MONGO_DB='mizitco_demo',BOOTSTRAP_USERS='0',
    FORCE_MONGO_ONLY='1',BASE_URL='',SYNC_ENABLED='0',ACCESS_WRITEBACK_ENABLED='0',INVENTORY_PLATFORM_ENABLED='1',
    STOCK_WRITES_ENABLED='1',PLATFORM_CONFIG_WRITES='1',FLASK_SECRET=secrets.token_urlsafe(32))
database=mongomock.MongoClient()
with patch('dotenv.load_dotenv',return_value=False),patch('pymongo.MongoClient',return_value=database):
    import app as module
from seed_data import seed
seed(module.db)
from purchase_orders.domain import COMPANY
COMPANY.update(module.db.inventory_settings.find_one({'_id':'company'})['values'])
module.app.config.update(DEMO_MODE=True,TESTING=False,
    STORE_LAYOUT_FILE=str(ROOT/'store_layout.json' if (ROOT/'store_layout.json').is_file() else ROOT/'static'/'store_layout.json'))
store=module.app.extensions['inventory_platform'];lock=RLock()
def transaction(fn):
    with lock: return fn({})
store.transact=transaction
store.indexes()
# The demo acknowledges only its own in-memory events. No Access adapter exists here.
from inventory_platform.domain import stamp, cloud_fields
from flask import g, jsonify, request, session, abort
@module.app.after_request
def simulated_sync(response):
    if response.status_code<400 and request.method=='POST':
        for event in module.db.sync_events.find({'status':'pending'}): store.acknowledge(event,'simulated_demo_only')
    return response
@module.app.post('/demo/simulate-access')
def simulate_access():
    import hmac
    if not getattr(g,'platform_user',None) or g.platform_user.get('role')!='admin': abort(403)
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('platform_csrf','')): abort(400)
    p=module.db.products.find_one({'uid':'DEMO-001'})
    state={**p['access_confirmed'],'a':p['stock_a']-2,'total':p['stock']-2}
    store.observe({**p,**cloud_fields(state)})
    return jsonify(message='Simulated Access change recorded in Stock History.')
@module.app.context_processor
def demo_context(): return {'demo_mode':True}
module.db.inventory_sync_control.insert_one({'_id':'worker','access':'Simulated demo only','heartbeat':stamp(),'last_success':stamp()})
if __name__=='__main__':
    print('FICTIONAL LOCAL DEMO: http://127.0.0.1:5055 — Maya / Noah: Admin; Eli: Worker. Resets on restart.')
    module.app.run(host='127.0.0.1',port=5055,debug=False,use_reloader=False)
