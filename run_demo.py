"""Fictional showcase: persistent serverless storage, or in-memory local preview."""
import os
from pathlib import Path
import secrets
import sys
from threading import RLock
from unittest.mock import patch
import mongomock

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env',override=False)
demo_uri=os.environ.get('DEMO_MONGO_URI','').strip()
demo_db=os.environ.get('DEMO_MONGO_DB','meadow_demo').strip()
demo_secret=os.environ.get('FLASK_SECRET','').strip()
serverless=os.environ.get('VERCEL')=='1'
if (serverless or demo_uri) and (not demo_uri or len(demo_secret)<32):
    raise RuntimeError('Set DEMO_MONGO_URI and a stable FLASK_SECRET of at least 32 characters in Vercel, then redeploy. See README.md.')
for key in list(os.environ):
    if key.startswith(('ACCESS_','MONGO_','SYNC_','BOOTSTRAP_','FALLBACK_')): os.environ.pop(key,None)
os.environ.update(MONGO_URI='mongodb://localhost/mizitco_demo',MONGO_DB='mizitco_demo',BOOTSTRAP_USERS='0',
    FORCE_MONGO_ONLY='1',BASE_URL='',SYNC_ENABLED='0',ACCESS_WRITEBACK_ENABLED='0',INVENTORY_PLATFORM_ENABLED='1',
    STOCK_WRITES_ENABLED='1',PLATFORM_CONFIG_WRITES='1',FLASK_SECRET=demo_secret or secrets.token_urlsafe(32))
if demo_uri:
    from demo_storage import connect_demo
    database=connect_demo(demo_uri,demo_db)
    os.environ.update(MONGO_URI=demo_uri,MONGO_DB=demo_db)
else:
    database=mongomock.MongoClient()
with patch('dotenv.load_dotenv',return_value=False),patch('pymongo.MongoClient',return_value=database):
    import application as module
from seed_data import seed
if demo_uri:
    from demo_storage import ensure_seeded
    ensure_seeded(module.db,seed)
else:
    seed(module.db)
from purchase_orders.domain import COMPANY
COMPANY.update(module.db.inventory_settings.find_one({'_id':'company'})['values'])
module.app.config.update(DEMO_MODE=True,DEMO_PERSISTENT=bool(demo_uri),TESTING=False,
    STORE_LAYOUT_FILE=str(ROOT/'store_layout.json' if (ROOT/'store_layout.json').is_file() else ROOT/'static'/'store_layout.json'))
store=module.app.extensions['inventory_platform'];lock=RLock()
def transaction(fn):
    with lock: return fn({})
if not demo_uri:
    store.transact=transaction
store.indexes()
# The demo acknowledges only its own in-memory events. No Access adapter exists here.
from inventory_platform.domain import stamp, cloud_fields
from flask import g, jsonify, request, session, abort
@module.app.after_request
def simulated_sync(response):
    if response.status_code<400 and request.method in ('POST','PUT','PATCH'):
        for event in module.db.sync_events.find({'status':'pending'}): store.acknowledge(event,'simulated_demo_only')
    return response
@module.app.post('/demo/simulate-access')
def simulate_access():
    import hmac
    if not getattr(g,'platform_user',None) or g.platform_user.get('role')!='admin': abort(403)
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('platform_csrf','')): abort(400)
    p=module.db.products.find_one({'uid':'DEMO-001'})
    state={**p['access_confirmed'],'a':max(0,(p.get('stock_a') or 0)-2),'total':max(0,p['stock']-2)}
    store.observe({**p,**cloud_fields(state)})
    return jsonify(message='Simulated Access change recorded in Stock History.')

def simulate_reconciliation():
    # The platform blueprint still enforces session and CSRF checks.
    if not getattr(g,'platform_user',None) or 'sync.manage' not in g.platform_permissions:
        abort(403)
    for event in module.db.sync_events.find({'status':'pending'}):
        store.acknowledge(event,'simulated_demo_only')
    from inventory_platform.forecasting import refresh
    refresh(module.db)
    module.db.inventory_sync_control.update_one({'_id':'worker'},
        {'$set':{'access':'Simulated demo only','heartbeat':stamp(),'last_success':stamp()}},upsert=True)
    return jsonify(message='Demo reconciliation complete. Pending demo changes confirmed and forecasts refreshed; Access is simulated.')

module.app.view_functions['platform.sync_wake']=simulate_reconciliation
@module.app.context_processor
def demo_context(): return {'demo_mode':True,'demo_persistent':bool(demo_uri)}
module.db.inventory_sync_control.update_one({'_id':'worker'},{'$set':{'access':'Simulated demo only','heartbeat':stamp(),'last_success':stamp()}},upsert=True)
if __name__=='__main__':
    print('FICTIONAL LOCAL DEMO: http://127.0.0.1:5055 — Maya / Noah: Admin; Eli: Worker. Resets on restart.')
    module.app.run(host='127.0.0.1',port=5055,debug=False,use_reloader=False)
