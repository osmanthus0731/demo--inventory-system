"""Existing-app extension. No migration, stock mutation or service startup at import time."""
from collections import defaultdict
from datetime import date, timedelta
from functools import wraps
from io import StringIO
import csv
import hmac
import json
import os
import re
import secrets
import time
from uuid import uuid4
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, session, url_for, Response
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash
from .accounts import find_user, public_user, public_appearance, permissions, migrate_users, save_user, delete_user
from .domain import Invalid, Conflict, PERMISSIONS, bounded_text, integer, stamp, business_date, stock_state, numeric, movement_change, movement_delta, movement_class, movement_view, analytics_range
from .store import Store
from .forecasting import dates, policy, forecast, replenishment, aggregate


def init_app(app,db):
    app.config.setdefault('INVENTORY_PLATFORM_ENABLED',os.getenv('INVENTORY_PLATFORM_ENABLED','1')=='1')
    app.config.setdefault('STOCK_WRITES_ENABLED',os.getenv('STOCK_WRITES_ENABLED','1' if os.getenv('VERCEL')=='1' else '0')=='1')
    app.config.setdefault('PLATFORM_CONFIG_WRITES',os.getenv('PLATFORM_CONFIG_WRITES','1' if os.getenv('VERCEL')=='1' else '0')=='1')
    store=Store(db); app.extensions['inventory_platform']=store
    bp=Blueprint('platform',__name__,url_prefix='/platform')

    def csrf():
        if not session.get('platform_csrf'): session['platform_csrf']=secrets.token_urlsafe(32)
        return session['platform_csrf']

    def actor():
        user=getattr(g,'platform_user',None)
        if not user: abort(401)
        return public_user(user)

    def require(permission=None, config_write=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*a,**kw):
                actor()
                if permission and permission not in g.platform_permissions: abort(403)
                if permission in ('users.manage','stock.approve') and g.platform_user.get('role')!='admin': abort(403)
                if config_write and not app.config['PLATFORM_CONFIG_WRITES']:
                    return jsonify(error='Administrative writes are disabled until the deployment checklist is approved.'),409
                return fn(*a,**kw)
            return wrapped
        return decorate

    def data():
        value=request.get_json(silent=True)
        if not isinstance(value,dict): raise Invalid('Send a JSON object.')
        return value

    def json_doc(doc):
        if doc is None: return None
        out=dict(doc)
        if '_id' in out: out['_id']=str(out['_id'])
        out.pop('request',None)
        return out

    @app.before_request
    def identify():
        g.platform_user=None; g.platform_permissions=set()
        if not app.config['INVENTORY_PLATFORM_ENABLED'] or request.path.startswith('/static/'): return
        if 'username' in session:
            try: user=find_user(db,session.get('user_id'),session.get('username'))
            except PyMongoError:
                if '/api/' in request.path:return jsonify(error='Database temporarily unavailable. Please try again shortly.'),503
                return render_template('platform/unavailable.html'),503
            if not user or user.get('active') is False or user.get('deleted'):
                session.clear()
                if '/api/' in request.path: return jsonify(error='Account unavailable. Select an active user.'),401
                return redirect(url_for('login'))
            session.update(username=user['username'],role=user.get('role','worker'),user_id=str(user['_id']))
            g.platform_user=user; g.platform_permissions=permissions(db,user)
        # Legacy profile changes now use the same CSRF boundary as new features.
        if request.endpoint=='logout' and request.method=='POST':
            if not hmac.compare_digest(request.form.get('platform_csrf','').encode(),csrf().encode()): abort(400)
        if request.endpoint=='profile' and request.method=='POST':
            if not hmac.compare_digest(request.form.get('platform_csrf','').encode(),csrf().encode()): abort(400)
            if request.form.get('action')=='change_password':
                return jsonify(error='Password changes are disabled because this installation uses password-free account selection.'),400

    @app.context_processor
    def context():
        return {'platform_enabled':app.config['INVENTORY_PLATFORM_ENABLED'],
                'sidebar_appearance':public_appearance(getattr(g,'platform_user',None) or {}),
                'platform_permissions':getattr(g,'platform_permissions',set()),
                'platform_csrf':csrf() if app.config['INVENTORY_PLATFORM_ENABLED'] else '',
                'stock_writes_enabled':app.config['STOCK_WRITES_ENABLED']}

    @bp.before_request
    def secure():
        if not app.config['INVENTORY_PLATFORM_ENABLED']: abort(404)
        if not getattr(g,'platform_user',None):
            if '/api/' in request.path: return jsonify(error='Please select an active user.'),401
            return redirect(url_for('login'))
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.content_length and request.content_length>131072: abort(413)
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token','').encode(),csrf().encode()): abort(400)

    @bp.errorhandler(Invalid)
    def invalid(exc): return jsonify(error=str(exc)),400
    @bp.errorhandler(Conflict)
    def conflict(exc): return jsonify(error=str(exc)),409
    @bp.errorhandler(PyMongoError)
    def database_error(exc):
        app.logger.exception('Inventory platform database operation failed')
        return jsonify(error='Database unavailable. Retry with the same request ID; check history before resubmitting.'),503
    @bp.errorhandler(NotImplementedError)
    def transactions_required(exc): return jsonify(error='MongoDB replica-set transactions are required. No fallback writes are allowed.'),503

    def render_account_login(error=None,status=200):
        try:
            accounts=[public_user(u) for u in db.users.find({'active':{'$ne':False},'deleted':{'$ne':True}})]
            accounts.sort(key=lambda u:u['username'].casefold())
        except PyMongoError: return render_template('platform/unavailable.html'),503
        return render_template('platform/login.html',accounts=accounts,error=error,token=csrf()),status

    @app.get('/auth/login-token')
    def login_token():
        if not app.config['INVENTORY_PLATFORM_ENABLED']: abort(404)
        return jsonify(token=csrf())

    def account_login():
        if request.method=='GET' and getattr(g,'platform_user',None):
            return redirect(url_for('admin_dashboard' if session['role']=='admin' else 'index'))
        error=None
        if request.method=='POST':
            if not hmac.compare_digest(request.form.get('platform_csrf','').encode(),csrf().encode()):
                return render_account_login('Your sign-in session changed or expired. Select your account and try again.',400)
            user=find_user(db,name=request.form.get('username','').strip())
            supplied_pin=(request.form.get('pin') or '').strip()
            valid_pin=app.config.get('DEMO_MODE') is True
            if not valid_pin and user and re.fullmatch(r'\d{4,8}',supplied_pin):
                if user.get('pin_hash'):
                    try: valid_pin=check_password_hash(user['pin_hash'],supplied_pin)
                    except (ValueError,TypeError): valid_pin=False
                else:
                    bootstrap=os.getenv('LOGIN_BOOTSTRAP_PIN','').strip()
                    valid_pin=bool(bootstrap and secrets.compare_digest(bootstrap,supplied_pin))
                    if valid_pin: db.users.update_one({'_id':user['_id']},{'$set':{'pin_hash':generate_password_hash(supplied_pin)}})
            if user and valid_pin and user.get('active',True) and not user.get('deleted'):
                next_url=request.args.get('next') or session.get('post_login_next','')
                session.clear(); session.update(username=user['username'],role=user.get('role','worker'),user_id=str(user['_id']))
                db.users.update_one({'_id':user['_id']},{'$set':{'last_login':stamp()}})
                db.audit_events.insert_one({'_id':str(uuid4()),'action':'login','user_id':str(user['_id']),
                    'username':user['username'],'timestamp':stamp()})
                if next_url.startswith('/') and not next_url.startswith('//') and '\\' not in next_url:
                    return redirect(next_url)
                return redirect(url_for('admin_dashboard' if session['role']=='admin' else 'index'))
            error='Incorrect PIN, or this account is unavailable. Contact an administrator if you need a PIN reset.'
        return render_account_login(error)

    original_login=app.view_functions['login']; original_create=app.view_functions['create_user']
    app.view_functions['login']=lambda: account_login() if app.config['INVENTORY_PLATFORM_ENABLED'] else original_login()
    app.view_functions['create_user']=lambda: redirect(url_for('platform.page',section='users')) if app.config['INVENTORY_PLATFORM_ENABLED'] else original_create()

    @bp.get('/<section>')
    @require()
    def page(section):
        if section not in ('users','history','analytics','forecasting','sync','settings','approvals','audit'): abort(404)
        required={'users':'users.manage','sync':'sync.manage','audit':'audit.view'}.get(section)
        if required and required not in g.platform_permissions: abort(403)
        titles={'users':'Users','history':'Stock History','analytics':'Inventory Analytics','forecasting':'Stock Forecasting','sync':'Inventory Sync','settings':'Settings','audit':'Audit Logs'}
        titles['approvals']='Stock Requests'
        return render_template('platform/page.html',section=section,title=titles[section],today=business_date())

    @bp.get('/api/users')
    @require('users.manage')
    def user_list(): return jsonify([public_user(u) for u in db.users.find({'deleted':{'$ne':True}}).sort('username',1)])

    @bp.delete('/api/users/<user_id>')
    @require('users.manage',True)
    def user_delete(user_id): return jsonify(delete_user(store,user_id,data().get('revision'),actor()))

    @bp.route('/api/users',methods=['POST'])
    @bp.route('/api/users/<user_id>',methods=['PUT'])
    @require('users.manage',True)
    def user_save(user_id=None): return jsonify(save_user(store,data(),actor(),user_id,require_pin=app.config.get('DEMO_MODE') is not True))

    @bp.get('/api/users/<user_id>/activity')
    @require('users.manage')
    def user_activity(user_id):
        events=[json_doc(v) for v in db.audit_events.find({'$or':[{'user_id':user_id},{'target_user_id':user_id}]}).sort('timestamp',-1).limit(100)]
        events += [{**json_doc(v),'action':'stock_'+v.get('movement_type','movement')} for v in db.stock_movements.find({'user_id':user_id}).sort('timestamp',-1).limit(100)]
        return jsonify(sorted(events,key=lambda v:v.get('timestamp',''),reverse=True)[:100])

    @bp.get('/api/stock/<path:uid>')
    @require()
    def stock_get(uid):
        p=db.products.find_one({'uid':uid})
        if not p: abort(404)
        error=None
        try: state=stock_state(p)
        except (Invalid,Conflict) as exc: state=None; error=str(exc)
        recent=list(db.stock_movements.find({'uid':uid}).sort('timestamp',-1).limit(10))
        linked=None
        if state is None and p.get('readable_id'):
            candidates=list(db.products.find({'uid':{'$ne':uid},'readable_id':p['readable_id'],
                                             'access_sync_eligible':True},{'uid':1}).limit(2))
            if len(candidates)==1:
                linked=url_for('item_detail',uid=candidates[0]['uid'])
        return jsonify(uid=uid,name=p.get('name',''),mssid=p.get('readable_id',''),state=state,error=error,
            linked_product_url=linked,
            revision=p.get('stock_revision',0),last_updated=p.get('last_stock_update'),last_updated_by=p.get('last_stock_user'),
            sync_status=p.get('sync_status','uninitialised'),writable=state is not None and app.config['STOCK_WRITES_ENABLED'] and 'stock.request' in g.platform_permissions and bool(p.get('access_sync_eligible')) and bool(p.get('access_confirmed')),
            recent=[json_doc(m) for m in recent])

    @bp.post('/api/stock/<path:uid>')
    @require('stock.request')
    def stock_update(uid):
        if not app.config['STOCK_WRITES_ENABLED']: return jsonify(error='Stock editing is disabled during staging. Live quantities have not changed.'),409
        body=data(); bounded_text(body.get('reference',''),'Reference',120)
        return jsonify(approval_required=True,request=json_doc(store.submit_request(uid,body,actor()))),202

    @bp.get('/api/stock-requests')
    @require('stock.request')
    def stock_requests():
        query={} if 'stock.approve' in g.platform_permissions else {'requested_by':actor()['id']}
        status=request.args.get('status','pending')
        if status: query['status']=bounded_text(status,'Status',30)
        page=integer(request.args.get('page',1),'Page',1,100000)
        return jsonify(rows=[json_doc(r) for r in db.stock_requests.find(query).sort('created_at',-1).skip((page-1)*50).limit(50)],
            total=db.stock_requests.count_documents(query),page=page,user_id=actor()['id'],can_approve='stock.approve' in g.platform_permissions)

    @bp.post('/api/stock-requests/<request_id>/review')
    @require('stock.approve')
    def stock_review(request_id):
        if not app.config['STOCK_WRITES_ENABLED']: raise Conflict('Stock writes are disabled.')
        body=data()
        return jsonify(request=json_doc(store.review_request(request_id,body.get('decision'),
            integer(body.get('revision'),'Revision'),actor(),bounded_text(body.get('note',''),'Review note',1000))))

    def history_query(default_today=False):
        q={}
        for param,field in (('uid','uid'),('user','user_id'),('location','changes.location'),('source','source'),('category','category')):
            value=request.args.get(param,'').strip()
            if not value: continue
            if param=='uid':
                tokens=re.findall(r'[A-Za-z0-9]+',value[:120]);term=re.compile('.*'.join(re.escape(token) for token in tokens) if tokens else re.escape(value[:120]),re.I)
                product_ids=[p.get('uid') for p in db.products.find(
                    {'$or':[{'uid':term},{'name':term},{'readable_id':term}]},{'uid':1}).limit(50) if p.get('uid')]
                q['$or']=[{'uid':term},{'uid':{'$in':product_ids}},{'product_name':term}]
            else: q[field]=value[:120]
        start=request.args.get('start',''); end=request.args.get('end','')
        if default_today and not start and not end:
            start=end=business_date()
        if start or end:
            list(dates(start or '2020-01-01',end or business_date()))
            if end and end>business_date(): raise Invalid('Future stock-history dates are unavailable.')
            q['business_date']={'$gte':start or '2020-01-01','$lte':end or business_date()}
        ref=request.args.get('reference','').strip()
        if ref: q['reference']=re.compile(re.escape(ref[:120]),re.I)
        return q

    def movement_status(rows):
        states={d['_id']:d['status'] for d in db.sync_events.find({'_id':{'$in':[r['_id'] for r in rows]}})}
        return [{**json_doc(movement_view(r)),'sync_status':states.get(r['_id'],r.get('sync_status'))} for r in rows]

    def movement_ids(event_id):
        from bson import ObjectId
        return [event_id,ObjectId(event_id)] if ObjectId.is_valid(event_id) else [event_id]

    @bp.get('/api/history')
    @require()
    def history():
        q=history_query(True); page=integer(request.args.get('page',1),'Page',1,100000)
        selected=request.args.get('type','').strip()
        aliases={'issued':'sale','sold':'sale','received':'received','correction':'adjustment','other':'adjustment'}
        if selected:
            wanted=aliases.get(selected,selected)
            candidates=list(db.stock_movements.find(q).sort([('timestamp',-1),('_id',-1)]))
            candidates=[row for row in candidates if movement_class(row)==wanted]
            total=len(candidates);rows=candidates[(page-1)*50:page*50]
        else:
            total=db.stock_movements.count_documents(q)
            rows=list(db.stock_movements.find(q).sort([('timestamp',-1),('_id',-1)]).skip((page-1)*50).limit(50))
        return jsonify(rows=movement_status(rows),total=total,page=page)

    @bp.get('/api/history/detail')
    @bp.get('/api/history/<path:event_id>')
    @require()
    def history_detail(event_id=None):
        event_id=event_id or request.args.get('id','')
        ids=movement_ids(event_id)
        row=db.stock_movements.find_one({'$or':[{'_id':{'$in':ids}},{'event_id':{'$in':ids}}]})
        if not row: abort(404)
        stable_id=str(row.get('event_id') or row['_id'])
        corrections=[json_doc(v) for v in db.movement_corrections.find({'event_id':{'$in':movement_ids(stable_id)}}).sort('timestamp',1)]
        return jsonify(movement=json_doc(movement_view(row)),corrections=corrections)

    @bp.post('/api/history/classification')
    @bp.post('/api/history/<path:event_id>/classification')
    @require('stock.approve')
    def history_classify(event_id=None):
        event_id=event_id or request.args.get('id','')
        body=data(); correction=store.classify(event_id,body.get('classification',''),body.get('adjustment_reason',''),
            bounded_text(body.get('remarks',''),'Remarks',1000,True),actor(),integer(body.get('revision',0),'Revision',0))
        return jsonify(message='Classification updated. Inventory quantities and Access were not changed.',correction=json_doc(correction))

    @bp.get('/api/history/dates')
    @require()
    def history_dates():
        month=request.args.get('month',business_date()[:7])
        try:
            start=date.fromisoformat(month+'-01')
        except ValueError:
            raise Invalid('Month must use YYYY-MM.') from None
        end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        if end>date.fromisoformat(business_date()): end=date.fromisoformat(business_date())
        q=history_query()
        q['business_date']={'$gte':start.isoformat(),'$lte':end.isoformat()}
        rows=db.stock_movements.aggregate([
            {'$match':q},{'$group':{'_id':'$business_date','count':{'$sum':1}}},{'$sort':{'_id':1}}
        ])
        return jsonify(days=[{'date':row['_id'],'count':row['count']} for row in rows])

    @bp.get('/api/history.csv')
    @require()
    def history_csv():
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        def stream():
            output=StringIO(); writer=csv.writer(output)
            header=['Event ID','Product UID','Product name','Business date','UTC timestamp','User ID','Username','Source','Classification','Location','Previous','Change','New','Explanation','Adjustment reason','Reference','Remarks','Sync status']
            writer.writerow(header); yield '\ufeff'+output.getvalue(); output.seek(0);output.truncate(0)
            cursor=db.stock_movements.find(history_query()).sort('timestamp',-1)
            for raw in cursor:
                m=movement_view(raw)
                state=db.sync_events.find_one({'_id':m['_id']},{'status':1}) or m
                changes=m.get('changes') or [{'location':'','previous':(m.get('before') or {}).get('total'),
                    'change':m.get('quantity_difference'),'new':(m.get('after') or {}).get('total')}]
                for c in changes:
                    values=[m['_id'],m.get('uid',''),m.get('product_name',''),m.get('business_date',''),m.get('timestamp',''),m.get('user_id',''),m.get('username',''),m.get('source',''),m['classification'],c.get('location',''),c.get('previous',''),c.get('change',''),c.get('new',''),m['explanation'],m.get('adjustment_reason',''),m.get('reference',''),m.get('classification_explanation') or m.get('note',''),state.get('status',m.get('sync_status',''))]
                    writer.writerow([safe(v) for v in values]); yield output.getvalue(); output.seek(0);output.truncate(0)
        from flask import stream_with_context
        return Response(stream_with_context(stream()),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=stock-history.csv'})

    @bp.get('/api/analytics')
    @require()
    def analytics():
        period=request.args.get('period','custom' if request.args.get('start') else '30')
        start,end,previous_start,previous_end=analytics_range(period,request.args.get('start',''),request.args.get('end',''),business_date())
        day_list=list(dates(start,end)); daily={d:{'date':d,'issued':0,'received':0} for d in day_list}
        stats=defaultdict(lambda:{'issued':0,'received':0,'adjustments':0,'frequency':0,'last_movement':None})
        categories=defaultdict(int); weekly=defaultdict(int); monthly=defaultdict(int); movement_types=defaultdict(int)
        first_movement={};daily_changes=defaultdict(float);review_uids=set()
        totals={'confirmed_sold':0,'received':0,'adjustments':0,'movements':0}
        for m in db.stock_movements.find({'business_date':{'$gte':start,'$lte':end}}):
            uid=m.get('uid');
            if not uid: continue
            s=stats[uid]; s['frequency']+=1; s['last_movement']=max(s['last_movement'] or '',m.get('timestamp',''))
            first_movement[uid]=min(first_movement.get(uid,m['business_date']),m['business_date'])
            change=movement_change(m); kind=movement_class(m); totals['movements']+=1;movement_types[kind]+=1
            if movement_view(m)['review_flags']: review_uids.add(uid)
            daily_changes[m['business_date']]+=change
            if kind=='sale' and change<0:
                amount=-change; s['issued']+=amount; daily[m['business_date']]['issued']+=amount
                totals['confirmed_sold']+=amount
                categories[m.get('category') or 'Uncategorized']+=amount
                d=date.fromisoformat(m['business_date']); weekly[(d-timedelta(days=d.weekday())).isoformat()]+=amount
                monthly[m['business_date'][:7]]+=amount
            elif kind=='received' and change>0:
                amount=change
                s['received']+=amount;daily[m['business_date']]['received']+=amount
                totals['received']+=amount
            elif change and kind in ('adjustment','correction','other'):
                s['adjustments']+=abs(change);totals['adjustments']+=abs(change)
        previous={'confirmed_sold':0,'received':0,'adjustments':0,'movements':0}
        for m in db.stock_movements.find({'business_date':{'$gte':previous_start,'$lte':previous_end}}):
            change=movement_change(m);kind=movement_class(m);previous['movements']+=1
            if kind=='sale' and change<0: previous['confirmed_sold']+=-change
            elif kind=='received' and change>0: previous['received']+=change
            elif change and kind in ('adjustment','correction','other'): previous['adjustments']+=abs(change)
        coverage={d['_id']:d.get('complete',False) for d in db.business_days.find({'_id':{'$gte':start,'$lte':end}})}
        closed=sum(coverage.get(d,False) for d in day_list)
        settings_by_uid={str(setting['_id'])[8:]:setting for setting in db.inventory_settings.find({'_id':re.compile('^product:')})}
        rows=[]
        product_fields={'uid':1,'Part_id':1,'name':1,'Desc':1,'category':1,'Category':1,'Catergory':1,'Cat':1,'stock':1,'Stock_office':1}
        for p in db.products.find({},product_fields):
            uid=str(p.get('uid') or p.get('Part_id') or '');
            if not uid: continue
            s=stats[uid]; settings=settings_by_uid.get(uid,{})
            # Show useful day-one analytics as soon as movement exists. The
            # denominator begins at this product's first activity in the range,
            # rather than requiring every business day to be manually closed.
            first=first_movement.get(uid)
            active_days=(date.fromisoformat(end)-date.fromisoformat(first)).days+1 if first else 0
            avg=s['issued']/active_days if active_days else 0
            stock=numeric(p.get('stock') if p.get('stock') is not None else p.get('Stock_office')); threshold=numeric(settings.get('reorder_threshold'))
            rows.append({'uid':uid,'name':p.get('name') or p.get('Desc') or uid,'category':p.get('category') or p.get('Category') or p.get('Catergory') or p.get('Cat') or 'Uncategorized','stock':stock,**s,'average_daily_demand':avg,
                         'coverage_days':stock/avg if avg else None,'reorder_threshold':threshold,
                         'suggested_quantity':max(0,threshold-stock) if threshold else None})
        rows.sort(key=lambda r:r['issued'],reverse=True)
        # Product master category is authoritative; legacy movement rows often
        # contain a UID or blank value in their category snapshot.
        if totals['confirmed_sold']:
            categories=defaultdict(int)
            for row in rows:
                if row['issued']: categories[row['category'] or 'Uncategorized']+=row['issued']
        current_stock=sum(max(0,r['stock']) for r in rows)
        stock_status={'Healthy stock':sum(r['stock']>0 and r['reorder_threshold']>0 and r['stock']>r['reorder_threshold'] for r in rows),
            'Low stock':sum(r['reorder_threshold']>0 and 0<r['stock']<=r['reorder_threshold'] for r in rows),
            'Out of stock':sum(r['stock']==0 for r in rows),'Negative stock':sum(r['stock']<0 for r in rows),
            'No threshold':sum(r['stock']>0 and not r['reorder_threshold'] for r in rows)}
        review_uids.update(r['uid'] for r in rows if r['stock']<0)
        inventory_categories=defaultdict(float)
        for row in rows: inventory_categories[row['category']]+=max(0,row['stock'])
        cards={'Active products':len(rows),'Confirmed units sold':totals['confirmed_sold'],'Stock received':totals['received'],'Adjustments':totals['adjustments'],
            'Low stock products':stock_status['Low stock'],'Out of stock products':stock_status['Out of stock']+stock_status['Negative stock'],
            'Products requiring review':len(review_uids),'Current inventory quantity':current_stock}
        comparisons={key:(None if previous[key]==0 else round((totals[key]-previous[key])*100/previous[key],1)) for key in totals}
        top_sold=[{'uid':r['uid'],'name':r['name'],'units':r['issued']} for r in rows if r['issued']][:10]
        top_received=sorted(({'uid':r['uid'],'name':r['name'],'units':r['received']} for r in rows if r['received']),key=lambda x:x['units'],reverse=True)[:10]
        # The detailed table is movement-focused. Do not send/render all 3,000+
        # products when only a handful changed in the selected period.
        display_rows=[row for row in rows if row['frequency']]
        if not display_rows: display_rows=sorted(rows,key=lambda row:row['stock'],reverse=True)[:100]
        stock_trend=[];level=current_stock
        for day in reversed(day_list): stock_trend.append({'date':day,'quantity':level});level-=daily_changes[day]
        stock_trend.reverse()
        replenishment=sorted((r for r in rows if r['stock']<=0 or (r['reorder_threshold']>0 and r['stock']<=r['reorder_threshold'])),key=lambda r:(r['stock']>0,r['coverage_days'] if r['coverage_days'] is not None else 10**9))[:20]
        return jsonify(period={'start':start,'end':end,'previous_start':previous_start,'previous_end':previous_end},cards=cards,comparisons=comparisons,
            rows=display_rows,daily=list(daily.values()),weekly=dict(weekly),monthly=dict(monthly),categories=dict(categories),inventory_categories=dict(inventory_categories),movement_types=dict(movement_types),
            stock_status=stock_status,replenishment=replenishment,top_sold=top_sold,top_received=top_received,fast_moving=top_sold,slow_moving=[{'uid':r['uid'],'name':r['name'],'category':r['category'],'stock':r['stock'],'last_movement':r['last_movement']} for r in rows if not r['issued'] and r['stock']>0][:10],stock_trend=stock_trend,
            coverage={'closed_days':closed,'days':len(day_list)},note=('No stock movements exist in this period yet; current inventory and category stock are shown below.' if not totals['movements'] else 'Confirmed and automatically classified Sold movements count as demand. Adjustments, transfers, duplicates, and opening balances are excluded.'))

    @bp.get('/api/forecasting')
    @require()
    def forecasting():
        query=request.args.get('q','').strip();tokens=re.findall(r'[A-Za-z0-9]+',query);term=re.compile('.*'.join(re.escape(token) for token in tokens) if tokens else re.escape(query),re.I);match={'$or':[{'uid':term},{'name':term},{'readable_id':term}]} if query else {}
        category=request.args.get('category','').strip()
        if category: match['category']=re.compile(re.escape(category),re.I)
        products=list(db.products.find(match,{'uid':1,'name':1,'stock':1,'category':1}).limit(100));uids=[p.get('uid') for p in products if p.get('uid')]
        end=request.args.get('end') or business_date(); start=request.args.get('start') or (date.fromisoformat(end)-timedelta(days=89)).isoformat()
        list(dates(start,end))
        movement_rows=list(db.stock_movements.find({'uid':{'$in':uids},'business_date':{'$gte':start,'$lte':end}}))
        by_uid=defaultdict(list)
        for movement in movement_rows: by_uid[movement.get('uid')].append(movement)
        cached={row['uid']:row for row in db.forecast_cache.find({'uid':{'$in':uids}})}
        missing=[uid for uid in uids if uid not in cached]
        for row in db.forecasts.find({'uid':{'$in':missing}}).sort('generated_at',-1):
            cached.setdefault(row['uid'],row)
        rows=[]
        for p in products:
            uid=p.get('uid','');result=cached.get(uid)
            relevant=by_uid.get(uid,[])
            if relevant:
                first=max(start,min(m.get('business_date',start) for m in relevant))
                coverage={day:True for day in dates(first,end)}
                analysis=forecast(aggregate(relevant,coverage,first,end,uid))
                usable=analysis.get('days_recorded',0)
                if usable<14: analysis['status']='Collecting Data'
                elif usable<30: analysis['status']='Preliminary forecast'
                elif usable<90: analysis['status']='Improved trends'
                else: analysis['status']='Longer-term analysis'
                plan=replenishment(numeric(p.get('stock')),analysis,db.inventory_settings.find_one({'_id':'product:'+uid}) or {})
                result={'analysis':analysis,'replenishment':plan,'generated_at':stamp(),'data_cutoff':end}
            if result:
                rows.append({'uid':uid,'name':p.get('name',''),'stock':p.get('stock'),
                    'analysis':json_doc(result.get('analysis',{})),'replenishment':json_doc(result.get('replenishment',{})),
                    'generated_at':result.get('generated_at'),'data_cutoff':result.get('data_cutoff'),
                    'history':[json_doc(r) for r in db.daily_demand.find({'uid':uid}).sort('date',-1).limit(60)][::-1]})
            else:
                rows.append({'uid':uid,'name':p.get('name',''),'stock':p.get('stock'),'analysis':{
                    'stage':0,'status':'Forecast queued','days_recorded':0,'valid_demand_events':0,'coverage':0,'models':[]},
                    'replenishment':{'status':'No cached forecast yet.'},'history':[],'generated_at':None,'data_cutoff':None})
        return jsonify(rows=rows,job=json_doc(db.inventory_sync_control.find_one({'_id':'forecast_job'})),period={'start':start,'end':end},
            note='Forecasts use classified Sold movements only; receipts, baselines, transfers, duplicates, and external adjustments are excluded.')

    @bp.get('/api/sync')
    @require('sync.manage')
    def sync_info():
        return jsonify(heartbeat=json_doc(db.inventory_sync_control.find_one({'_id':'worker'})),mongo='Connected',
            pending=db.sync_events.count_documents({'status':'pending'}),failed=db.sync_events.count_documents({'status':'failed'}),
            conflicts=db.sync_events.count_documents({'status':'conflict'}),
            events=[json_doc(e) for e in db.sync_events.find({'status':{'$ne':'synced'}}).sort('created_at',1).limit(100)])

    @bp.get('/api/events')
    @require()
    def events():
        """Authenticated SSE hints; clients re-fetch authoritative API data."""
        from flask import stream_with_context
        def latest(collection, sort_field):
            row=collection.find_one({},{sort_field:1,'_id':0},sort=[(sort_field,-1)])
            return str((row or {}).get(sort_field,'') or '')
        def state():
            heartbeat=db.inventory_sync_control.find_one({'_id':'worker'}) or {}
            return {
                'inventory':latest(db.products,'last_stock_update'),
                'history':latest(db.stock_movements,'timestamp'),
                'sync':str(heartbeat.get('heartbeat',''))+':'+str(db.sync_events.count_documents({'status':{'$ne':'synced'}})),
                'presence':latest(db.presence,'last_seen_at'),
                'documents':max(latest(db.purchase_orders,'updated_at'),latest(db.business_documents,'updated_at')),
            }
        if request.args.get('poll')=='1':
            try:previous=json.loads(request.args.get('since','{}'))
            except (ValueError,TypeError):return jsonify(error='Invalid update cursor.'),400
            if not isinstance(previous,dict):return jsonify(error='Invalid update cursor.'),400
            current=state();changed=[key for key in current if previous and current[key]!=previous.get(key)]
            if 'inventory' in changed or 'history' in changed:changed.extend(['analytics','alerts'])
            return jsonify(state=current,channels=sorted(set(changed)))
        def stream():
            previous=state();yield 'event: ready\ndata: '+json.dumps({'at':stamp()})+'\n\n'
            heartbeat_at=time.monotonic()
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                time.sleep(5);current=state();changed=[key for key in current if current[key]!=previous[key]]
                if changed:
                    if 'inventory' in changed or 'history' in changed: changed.extend(['analytics','alerts'])
                    yield 'event: update\ndata: '+json.dumps({'channels':sorted(set(changed)),'at':stamp()})+'\n\n'
                    previous=current;heartbeat_at=time.monotonic()
                elif time.monotonic()-heartbeat_at>=15:
                    yield ': keepalive\n\n';heartbeat_at=time.monotonic()
        return Response(stream_with_context(stream()),mimetype='text/event-stream',headers={
            'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no','Connection':'keep-alive'})

    @bp.post('/api/sync/wake')
    @require('sync.manage',True)
    def sync_wake():
        db.inventory_sync_control.update_one({'_id':'wake'},{'$set':{'requested_at':stamp(),'by':actor()['id']}},upsert=True)
        return jsonify(message='Sync requested. The Windows worker must be online; queued changes remain durable while it is off.')

    @bp.post('/api/sync/<event_id>/resolve')
    @require('sync.manage',True)
    def sync_resolve(event_id):
        body=data(); store.resolve(event_id,body.get('decision'),body.get('expected'),actor(),bounded_text(body.get('note',''),'Reason',1000,True))
        return jsonify(message='Conflict queued for a conditional retry against the reviewed Access values.')

    @bp.get('/api/settings')
    @require('settings.manage')
    def settings_get():
        return jsonify(permissions=(db.inventory_settings.find_one({'_id':'permissions'}) or {}).get('roles',{'admin':list(PERMISSIONS),'worker':[]}),
            company=(db.inventory_settings.find_one({'_id':'company'}) or {}).get('values',{}),
            stock_writes=app.config['STOCK_WRITES_ENABLED'],config_writes=app.config['PLATFORM_CONFIG_WRITES'],
            policies=[json_doc(v) for v in db.inventory_settings.find({'_id':re.compile('^product:')})],
            calendar=[json_doc(v) for v in db.calendar_events.find({}).sort('start',-1).limit(100)])

    @bp.get('/api/audit')
    @require('audit.view')
    def audit_list():
        page=integer(request.args.get('page',1),'Page',1,100000);query={}
        if request.args.get('action','').strip(): query['action']=re.compile(re.escape(request.args['action'].strip()[:120]),re.I)
        if request.args.get('user','').strip(): query['username']=re.compile(re.escape(request.args['user'].strip()[:120]),re.I)
        return jsonify(rows=[json_doc(v) for v in db.audit_events.find(query).sort('timestamp',-1).skip((page-1)*50).limit(50)],total=db.audit_events.count_documents(query),page=page)

    @bp.post('/api/settings/<kind>')
    @require('settings.manage',True)
    def settings_save(kind):
        body=data(); who=actor()
        if kind=='product':
            uid=bounded_text(body.get('uid',''),'Product UID',120,True)
            if not db.products.find_one({'uid':uid}): raise Invalid('Unknown product UID.')
            collection=db.inventory_settings; key='product:'+uid; values=policy(body)
        elif kind=='permissions':
            roles=body.get('roles')
            if not isinstance(roles,dict) or set(roles)!={'admin','worker'}: raise Invalid('Provide Admin and Worker permissions.')
            if any(not isinstance(v,list) or any(p not in PERMISSIONS for p in v) for v in roles.values()): raise Invalid('Invalid permissions.')
            if not {'users.manage','settings.manage'}.issubset(roles['admin']): raise Invalid('Keep Admin user/settings management permissions.')
            collection=db.inventory_settings;key='permissions';values={'roles':roles,'document_permissions_migrated':True}
        elif kind=='calendar':
            start=body.get('start','');end=body.get('end','');list(dates(start,end))
            collection=db.calendar_events;key=str(uuid4());values={'start':start,'end':end,'name':bounded_text(body.get('name',''),'Event name',160,True),'note':bounded_text(body.get('note',''),'Note',1000),'supplier':bounded_text(body.get('supplier',''),'Supplier',160)}
        elif kind=='coverage':
            day=body.get('date','');list(dates(day,day))
            if day>=business_date(): raise Invalid('Only completed Malaysia business days may be closed.')
            if body.get('complete') is not True: raise Invalid('Confirm that all demand and stockouts were recorded for the day.')
            collection=db.business_days;key=day;values={'complete':True,'by':who['id'],'at':stamp(),'note':bounded_text(body.get('note',''),'Evidence/note',1000,True)}
        elif kind=='company':
            collection=db.inventory_settings;key='company';values={'values':{field:bounded_text(body.get(field,''),field.replace('_',' ').title(),600,field=='name') for field in ('name','registration','address','telephone','fax','email')}}
        elif kind=='override':
            collection=db.forecast_overrides;key=str(uuid4());values={'uid':bounded_text(body.get('uid',''),'UID',120,True),'quantity':integer(body.get('quantity'),'Quantity'),'reason':bounded_text(body.get('reason',''),'Reason',1000,True),'user_id':who['id'],'at':stamp()}
        else: abort(404)
        def write(kw):
            collection.update_one({'_id':key},{'$set':values},upsert=True,**kw)
            db.audit_events.insert_one({'_id':str(uuid4()),'action':'settings_'+kind,'timestamp':stamp(),'user_id':who['id'],'username':who['username'],'values':values},**kw)
        store.transact(write)
        return jsonify(message='Saved.')

    @app.cli.command('inventory-init')
    def initialise():
        """Explicit migration; use tools/platform_admin.py for a dry-run plan first."""
        print(migrate_users(db,True));store.indexes()
        db.platform_meta.update_one({'_id':'collection_started'},{'$setOnInsert':{'date':business_date(),'at':stamp()}},upsert=True)

    app.register_blueprint(bp)
