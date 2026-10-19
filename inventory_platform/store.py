"""Atomic cloud stock + append-only ledger + durable outbox. Replica-set transactions required."""
from copy import deepcopy
from uuid import uuid4
from pymongo import ReturnDocument
from .domain import adjustment, stock_state, cloud_fields, stamp, business_date, Conflict, Invalid, integer, canonical_movement_type


class Store:
    def __init__(self, db, transact=None):
        self.db=db
        self.transact=transact or self._transaction

    def _transaction(self, fn):
        with self.db.client.start_session() as session:
            return session.with_transaction(lambda s:fn({'session':s}))

    def indexes(self):
        self.db.products.create_index('last_stock_update')
        self.db.stock_movements.create_index('timestamp')
        self.db.purchase_orders.create_index('updated_at')
        self.db.business_documents.create_index('updated_at')
        self.db.stock_requests.create_index([('status',1),('created_at',-1)])
        self.db.stock_movements.create_index([('uid',1),('timestamp',-1)])
        self.db.stock_movements.create_index([('business_date',1),('movement_type',1)])
        self.db.stock_movements.create_index([('business_date',-1),('category',1),('source',1)])
        self.db.stock_movements.create_index([('user_id',1),('business_date',-1)])
        self.db.sync_events.create_index([('status',1),('created_at',1)])
        self.db.sync_events.create_index([('uid',1),('version',1)],unique=True)
        self.db.daily_demand.create_index([('uid',1),('date',1)],unique=True)
        self.db.forecasts.create_index([('uid',1),('generated_at',-1)])
        self.db.forecast_cache.create_index('uid',unique=True)
        self.db.movement_corrections.create_index([('event_id',1),('timestamp',-1)])

    def change(self, uid, data, actor, *, transaction=None, approval=None):
        event_id=data.get('event_id')
        if not isinstance(event_id,str) or len(event_id)!=36:
            raise Invalid('A unique request ID is required.')
        from uuid import UUID
        try: UUID(event_id)
        except ValueError: raise Invalid('Invalid request ID.') from None
        expected=integer(data.get('revision'),'Revision')
        def work(kw):
            existing=self.db.stock_movements.find_one({'_id':event_id},**kw)
            if existing:
                if existing['uid']!=uid or existing['user_id']!=actor['id'] or existing.get('request')!=data:
                    raise Conflict('This request ID was already used for a different change.')
                return existing
            product=self.db.products.find_one({'uid':uid},**kw)
            if not product: raise Invalid('Product not found.')
            if product.get('stock_revision',0)!=expected: raise Conflict('Stock changed. Reload and review the latest values.')
            if not product.get('access_sync_eligible'): raise Conflict('This product has not passed Access stock validation.')
            if not product.get('access_confirmed'): raise Conflict('Access baseline is not confirmed.')
            if product.get('sync_status') in ('conflict','failed'): raise Conflict('Resolve the sync issue before changing this product.')
            before,after,changes,reason,note=adjustment(product,data)
            ts=stamp(); version=expected+1
            quantity_difference=after['total']-before['total']
            movement={'_id':event_id,'event_id':event_id,'uid':uid,'product_name':product.get('name',''),
                      'category':product.get('category',''),'supplier':product.get('supplier',''),
                      'timestamp':ts,'business_date':business_date(),'user_id':actor['id'],'username':actor['username'],
                      'actor':{'id':actor['id'],'username':actor['username']},'source':'website',
                      'movement_type':canonical_movement_type(reason),'reason':reason,'changes':changes,
                      'before':before,'after':after,'unit':'units','reference':str(data.get('reference',''))[:120],
                      'note':note,'sync_status':'pending','record_version':version,
                      'quantity_difference':quantity_difference,'previous_quantity':before['total'],'new_quantity':after['total'],
                      'locations':[c.get('location','') for c in changes],'reference_id':str(data.get('reference',''))[:120],
                      'metadata':{'schema_version':2,'approval_required':approval is not None},
                      'demand_units':max(0,-quantity_difference) if reason=='issued' else 0,'request':deepcopy(data)}
            if approval: movement['approval']=deepcopy(approval)
            result=self.db.products.update_one({'_id':product['_id'],'stock_revision':expected},
                {'$set':{**cloud_fields(after),'stock_revision':version,'last_stock_update':ts,
                         'last_stock_user':actor['username'],'sync_status':'pending','last_stock_event':event_id}},**kw)
            if not result.matched_count: raise Conflict('Stock changed. Reload before saving.')
            self.db.stock_movements.insert_one(movement,**kw)
            self.db.audit_events.insert_one({'_id':str(uuid4()),'action':'stock_changed','timestamp':ts,
                'user_id':actor['id'],'username':actor['username'],'event_id':event_id,'uid':uid,
                'before':before,'after':after,'values':{'reason':reason,'reference':movement['reference']}},**kw)
            self.db.sync_events.insert_one({'_id':event_id,'uid':uid,'version':version,'before':before,'after':after,
                'status':'pending','created_at':ts,'attempts':0},**kw)
            self.db.inventory_sync_control.update_one({'_id':'forecast_job'},{'$set':{'dirty_at':ts},'$addToSet':{'dirty_uids':uid}},upsert=True,**kw)
            return movement
        return work(transaction) if transaction is not None else self.transact(work)

    def submit_request(self, uid, data, actor):
        from uuid import UUID
        try: event_id=str(UUID(data.get('event_id','')))
        except (ValueError,TypeError,AttributeError): raise Invalid('A unique request ID is required.') from None
        expected=integer(data.get('revision'),'Revision')
        def work(kw):
            existing=self.db.stock_requests.find_one({'_id':event_id},**kw)
            if existing:
                if existing['uid']!=uid or existing['requested_by']!=actor['id'] or existing['request']!=data:
                    raise Conflict('This request ID was already used.')
                return existing
            p=self.db.products.find_one({'uid':uid},**kw)
            if not p: raise Invalid('Product not found.')
            if p.get('stock_revision',0)!=expected: raise Conflict('Stock changed. Reload before submitting.')
            if not p.get('access_sync_eligible') or not p.get('access_confirmed'):
                raise Conflict('Access baseline is not confirmed.')
            if p.get('sync_status') in ('failed','conflict'): raise Conflict('Resolve the sync issue first.')
            before,after,changes,reason,note=adjustment(p,data)
            result={'_id':event_id,'uid':uid,'product_name':p.get('name',''),'stock_revision':expected,
                'before':before,'after':after,'changes':changes,'reason':reason,'note':note,
                'reference':str(data.get('reference',''))[:120],'requested_by':actor['id'],
                'requested_username':actor['username'],'created_at':stamp(),'status':'pending','revision':0,
                'request':deepcopy(data)}
            self.db.stock_requests.insert_one(result,**kw)
            return result
        return self.transact(work)

    def review_request(self, request_id, decision, revision, actor, note=''):
        from bson import ObjectId
        if decision not in ('approve','reject'): raise Invalid('Choose approve or reject.')
        if decision=='reject' and not note.strip(): raise Invalid('Provide a rejection reason.')
        def work(kw):
            ids=[actor['id']]+([ObjectId(actor['id'])] if ObjectId.is_valid(actor['id']) else [])
            # Touch the account inside the transaction so a concurrent demotion/deletion conflicts.
            allowed=self.db.users.update_one({'_id':{'$in':ids},'role':'admin','active':{'$ne':False},
                'deleted':{'$ne':True}},{'$inc':{'approval_checks':1}},**kw)
            if not allowed.matched_count: raise Invalid('An active Admin must review this request.')
            r=self.db.stock_requests.find_one({'_id':request_id},**kw)
            if not r: raise Invalid('Stock request not found.')
            if r['requested_by']==actor['id']: raise Invalid('Another Admin must review your request.')
            if r['status']!='pending' or r['revision']!=revision: raise Conflict('Request already reviewed. Refresh the list.')
            status='approved' if decision=='approve' else 'rejected'
            if decision=='approve':
                requester_ids=[r['requested_by']]+([ObjectId(r['requested_by'])] if ObjectId.is_valid(r['requested_by']) else [])
                requester=self.db.users.update_one({'_id':{'$in':requester_ids},'active':{'$ne':False},'deleted':{'$ne':True}},
                    {'$inc':{'approval_checks':1}},**kw)
                if not requester.matched_count: raise Conflict('Requester account is no longer active.')
                p=self.db.products.find_one({'uid':r['uid']},**kw)
                if not p or p.get('stock_revision',0)!=r['stock_revision'] or stock_state(p)!=r['before']:
                    status='stale'; note_text='Stock changed since submission. Submit a new request.'
                else:
                    note_text=note
                    self.change(r['uid'],r['request'],{'id':r['requested_by'],'username':r['requested_username']},
                        transaction=kw,approval={'user_id':actor['id'],'username':actor['username'],'at':stamp(),'note':note})
            else: note_text=note
            values={'status':status,'reviewed_by':actor['id'],'reviewed_username':actor['username'],
                'reviewed_at':stamp(),'review_note':note_text,'revision':revision+1}
            self.db.stock_requests.update_one({'_id':request_id},{'$set':values},**kw)
            self.db.audit_events.insert_one({'_id':str(uuid4()),'action':'stock_request_'+status,
                'timestamp':stamp(),'user_id':actor['id'],'username':actor['username'],'request_id':request_id},**kw)
            return {**r,**values}
        return self.transact(work)

    def acknowledge(self, event, method='verified_write'):
        def work(kw):
            current=self.db.sync_events.find_one({'_id':event['_id']},**kw)
            if current['status']=='synced': return
            if current['status'] not in ('pending','failed'): raise Conflict('Event is no longer available for acknowledgement.')
            self.db.sync_events.update_one({'_id':event['_id']},{'$set':{'status':'synced','synced_at':stamp(),'ack_method':method}},**kw)
            product=self.db.products.find_one({'uid':event['uid']},**kw)
            values={'access_confirmed':event['after'],'last_access_sync':stamp()}
            if product.get('stock_revision')==event['version']: values['sync_status']='synced'
            self.db.products.update_one({'_id':product['_id']},{'$set':values},**kw)
        self.transact(work)

    def observe(self, mapped):
        """Record Access observations; signed changes feed activity analytics."""
        uid=mapped['uid']; actual=stock_state(mapped)
        def work(kw):
            product=self.db.products.find_one({'uid':uid},**kw)
            if not product:
                # New products are imported only by explicitly enabled worker, never during preflight.
                self.db.products.insert_one({**mapped,'stock_revision':0,'access_confirmed':actual,'sync_status':'synced','access_sync_eligible':True,
                                             'last_access_sync':stamp()},**kw)
                return 'baseline'
            if self.db.sync_events.find_one({'uid':uid,'status':{'$ne':'synced'}},**kw): return 'pending'
            confirmed=product.get('access_confirmed')
            if confirmed is None:
                # Existing totals must agree; incomplete legacy slot mapping can be filled from Access.
                if product.get('stock')!=actual['total']: raise Conflict('Initial cloud/Access totals differ; baseline approval required.')
                self.db.products.update_one({'_id':product['_id']},{'$set':{**mapped,'stock_revision':0,'access_confirmed':actual,'access_sync_eligible':True,
                    'sync_status':'synced','last_access_sync':stamp()}},**kw)
                return 'baseline'
            if confirmed==actual:
                self.db.products.update_one({'_id':product['_id']},{'$set':{'vendor_cd':mapped.get('vendor_cd','')}},**kw)
                if not product.get('access_sync_eligible'):
                    self.db.products.update_one({'_id':product['_id']},{'$set':{'access_sync_eligible':True}},**kw)
                return 'unchanged'
            if stock_state(product)!=confirmed: raise Conflict('Cloud stock differs from confirmed Access baseline.')
            version=product.get('stock_revision',0)+1
            # Deterministic ID for retry after unknown transaction outcome.
            event_id=f'access:{uid}:{version}'
            changes=[{'slot':s,'location':actual['location_'+s.lower()],'previous':confirmed[k],
                      'change':actual[k]-confirmed[k] if actual[k] is not None and confirmed[k] is not None else None,
                      'new':actual[k],'previous_location':confirmed.get('location_'+s.lower()),
                      'new_location':actual.get('location_'+s.lower()),
                      'location_changed':confirmed.get('location_'+s.lower())!=actual.get('location_'+s.lower())}
                     for s,k in (('A','a'),('B','b')) if actual[k]!=confirmed[k] or confirmed.get('location_'+s.lower())!=actual.get('location_'+s.lower())]
            if actual['total']!=confirmed['total']:
                changes.append({'slot':'Office','location':'Office total','previous':confirmed['total'],
                                'change':actual['total']-confirmed['total'],'new':actual['total']})
            delta=actual['total']-confirmed['total']
            location_changed=any(c.get('location_changed') for c in changes)
            classification='sold' if delta<0 else ('received' if delta>0 else ('transfer' if location_changed else 'external_adjustment'))
            adjustment_reason='location_transfer' if delta==0 and location_changed else ''
            self.db.stock_movements.insert_one({'_id':event_id,'event_id':event_id,'uid':uid,'product_name':mapped['name'],
                'category':mapped['category'],'supplier':mapped['supplier'],'timestamp':stamp(),'business_date':business_date(),
                'user_id':'access-service','username':'Microsoft Access','actor':{'id':'access-service','username':'Microsoft Access'},
                'source':'access','movement_type':'STOCK_ADJUSTMENT',
                'reason':'Observed snapshot change; business reason unknown','changes':changes,'before':confirmed,'after':actual,
                'unit':'units','reference':'','note':'','sync_status':'synced','record_version':version,
                'quantity_difference':actual['total']-confirmed['total'],'previous_quantity':confirmed['total'],'new_quantity':actual['total'],
                'locations':[c.get('location','') for c in changes],'reference_id':'',
                'metadata':{'schema_version':2,'external_reason_known':False},'classification':classification,
                'classification_source':'automatic_signed_snapshot','adjustment_reason':adjustment_reason,
                'demand_units':max(0,-delta) if classification=='sold' else 0},**kw)
            self.db.inventory_sync_control.update_one({'_id':'forecast_job'},{'$set':{'dirty_at':stamp()},'$addToSet':{'dirty_uids':uid}},upsert=True,**kw)
            result=self.db.products.update_one({'_id':product['_id'],'stock_revision':version-1},{'$set':{**mapped,'access_sync_eligible':True,
                'stock_revision':version,'access_confirmed':actual,'sync_status':'synced','last_access_sync':stamp(),
                'last_stock_update':stamp(),'last_stock_user':'Microsoft Access'}},**kw)
            if not result.matched_count: raise Conflict('Concurrent website edit; retry Access observation.')
            return 'observed'
        return self.transact(work)

    def classify(self,event_id,classification,reason,remarks,actor,revision=0):
        """Append a classification correction only; never changes stock or Access outbox."""
        allowed={'sold','received','external_adjustment'}
        reasons={'human_error','stock_reconciliation','location_transfer','damaged_stock','system_correction','other',''}
        if classification not in allowed: raise Invalid('Choose Sold, Received, or External Adjustment.')
        if reason not in reasons: raise Invalid('Choose a valid adjustment reason.')
        if classification=='external_adjustment' and not reason: raise Invalid('An adjustment reason is required.')
        if not str(remarks).strip(): raise Invalid('Remarks are required for an audit correction.')
        def work(kw):
            from bson import ObjectId
            ids=[event_id,ObjectId(event_id)] if ObjectId.is_valid(event_id) else [event_id]
            row=self.db.stock_movements.find_one({'$or':[{'_id':{'$in':ids}},{'event_id':{'$in':ids}}]},**kw)
            if not row: raise Invalid('Movement not found.')
            if str(row.get('movement_type','')).upper()=='INITIAL_SNAPSHOT': raise Invalid('Initial imports cannot be reclassified.')
            current=row.get('classification_revision',0)
            if current!=revision: raise Conflict('Classification changed. Reload the record.')
            stable_id=str(row.get('event_id') or row['_id'])
            ts=stamp(); correction={'_id':str(uuid4()),'event_id':stable_id,'uid':row.get('uid'),
                'previous_classification':row.get('effective_classification') or row.get('classification'),
                'classification':classification,'adjustment_reason':reason,'remarks':str(remarks).strip()[:1000],
                'user_id':actor['id'],'username':actor['username'],'timestamp':ts,'revision':current+1}
            result=self.db.stock_movements.update_one({'_id':row['_id'],'classification_revision':{'$in':[current,None]}},
                {'$set':{'effective_classification':classification,'adjustment_reason':reason,
                    'classification_explanation':correction['remarks'],'classification_revision':current+1,
                    'classified_by':actor['id'],'classified_at':ts}},**kw)
            if not result.matched_count: raise Conflict('Classification changed. Reload the record.')
            self.db.movement_corrections.insert_one(correction,**kw)
            self.db.audit_events.insert_one({'_id':str(uuid4()),'action':'movement_classified','event_id':stable_id,
                'uid':row.get('uid'),'user_id':actor['id'],'username':actor['username'],'timestamp':ts,
                'values':{'classification':classification,'adjustment_reason':reason}},**kw)
            self.db.inventory_sync_control.update_one({'_id':'forecast_job'},{'$set':{'dirty_at':ts},
                '$addToSet':{'dirty_uids':row.get('uid')}},upsert=True,**kw)
            return correction
        return self.transact(work)

    def flag(self,event,status,detail,actual=None):
        def work(kw):
            self.db.sync_events.update_one({'_id':event['_id'],'status':{'$ne':'synced'}},{'$set':{'status':status,
                'error':detail,'observed_access':actual,'updated_at':stamp()},'$inc':{'attempts':1}},**kw)
            self.db.products.update_one({'uid':event['uid']},{'$set':{'sync_status':status}},**kw)
        self.transact(work)

    def resolve(self,event_id,decision,expected,actor,note):
        """Explicit keep-cloud approval rebases a conditional write; never an unconditional overwrite."""
        if decision!='keep_cloud': raise Invalid('Only explicit keep-cloud retry is supported; export/reconcile other cases manually.')
        if not note.strip(): raise Invalid('A resolution reason is required.')
        def work(kw):
            event=self.db.sync_events.find_one({'_id':event_id,'status':'conflict'},**kw)
            if not event or event.get('observed_access')!=expected: raise Conflict('Conflict changed. Refresh before resolving.')
            if not expected: raise Invalid('A fresh Access snapshot is required.')
            self.db.sync_events.update_one({'_id':event_id},{'$set':{'before':expected,'status':'pending','error':''},
                '$push':{'resolutions':{'by':actor['id'],'at':stamp(),'reason':note,'decision':decision,'expected':expected}}},**kw)
            self.db.products.update_one({'uid':event['uid']},{'$set':{'sync_status':'pending'}},**kw)
            self.db.audit_events.insert_one({'_id':str(uuid4()),'action':'sync_resolution','user_id':actor['id'],
                'username':actor['username'],'event_id':event_id,'timestamp':stamp(),'reason':note},**kw)
        self.transact(work)
