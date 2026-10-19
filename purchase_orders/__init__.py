"""PO documents with optional atomic reservation of the legacy Access counter."""
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import hmac
import re
import secrets
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo
from flask import g, Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from flask import send_file
from pymongo.errors import PyMongoError
from .domain import ValidationError, snapshot, product_snapshot, purchasing_options, date_value
from .repository import Repository, Conflict
from .document import svg_pages, pdf_bytes, layout


def init_app(app, database, products, pricing):
    app.config.setdefault("PO_CURRENCIES", ("MYR", "USD", "SGD", "EUR", "GBP", "CNY", "JPY", "THB", "AUD"))
    bp = Blueprint("purchase_orders", __name__, url_prefix="/purchase-orders")
    def reserve_number():
        import os
        path=app.config.get('PO_ACCESS_DB_PATH') or os.getenv('ACCESS_DB_PATH')
        if not path:
            raise ValidationError('Legacy PO numbering requires the local Access connection.')
        from .legacy import reserve_po
        try: return reserve_po(path)
        except Exception as exc:
            current_app.logger.warning('Legacy PO reservation failed: %s',type(exc).__name__)
            raise ValidationError('Cannot reserve a legacy PO number. Check the Access connection and retry; no fallback number was issued.') from exc
    def legacy_enabled():
        import os
        return app.config.get('PO_LEGACY_NUMBERING',True) and not app.testing and not app.config.get('DEMO_MODE')
    repo = Repository(database.get_collection("purchase_orders"),lambda:reserve_number() if legacy_enabled() else None)
    app.extensions["purchase_orders"] = repo

    @app.cli.command("po-init-indexes")
    def init_indexes():
        """Create optional dashboard indexes in the PO collection only."""
        repo.collection.create_index([("date", -1), ("created_at", -1), ("_id", -1)])
        repo.collection.create_index([("created_by", 1), ("date", -1), ("created_at", -1), ("_id", -1)])
        repo.collection.create_index([("status", 1), ("date", -1), ("created_at", -1), ("_id", -1)])
        print("Purchase-order indexes are ready.")

    def scope():
        return {} if session.get("role") == "admin" else {"created_by": session["username"]}

    def permitted(name):
        if getattr(g,'platform_user',None):return name in g.platform_permissions
        if session.get('role')=='admin': return True
        from inventory_platform.accounts import find_user, permissions
        user=find_user(database,str(session.get('user_id') or ''),session.get('username'))
        return name in permissions(database,user) if user else name in {'documents.view','documents.create','documents.edit'}

    def require_permission(name):
        if not permitted(name): abort(403)

    def csrf_token():
        if "po_csrf" not in session:
            session["po_csrf"] = secrets.token_urlsafe(32)
        return session["po_csrf"]

    def today():
        return datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()

    def get_doc(number):
        doc = repo.get(number, scope())
        if not doc:
            abort(404)
        changed=False
        for receipt in doc.get('receipts',[]):
            if receipt.get('status')!='pending': continue
            ids=receipt.get('event_ids',[]);states=[e.get('status') for e in database.sync_events.find({'_id':{'$in':ids}},{'status':1})]
            if ids and len(states)==len(ids) and all(state=='synced' for state in states): receipt['status']='confirmed';changed=True
        if changed:
            received=[Decimal('0') for _ in doc['items']]
            for receipt in doc.get('receipts',[]):
                if receipt.get('status')=='confirmed':
                    for line in receipt['items']: received[line['index']]+=Decimal(line['quantity'])
            complete=all(received[i]>=Decimal(item['quantity']) for i,item in enumerate(doc['items']))
            status='received' if complete else 'partially_received';stamp=datetime.now(ZoneInfo('UTC')).isoformat()
            repo.collection.update_one({'_id':number,'revision':doc['revision']},{'$set':{'receipts':doc['receipts'],'received_quantities':[format(v,'f') for v in received],'status':status,'updated_at':stamp},'$inc':{'revision':1},'$push':{'history':{'action':status,'by':'sync-worker','at':stamp}}});doc=repo.get(number,scope())
        return doc

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("Send a JSON object.")
        return data

    def revision(data):
        value = data.get("revision")
        if type(value) is not int or value < 1:
            raise ValidationError("A valid revision is required; reload this PO.")
        return value

    def validated(data, previous=None):
        doc = snapshot(data, app.config["PO_CURRENCIES"])
        if previous:
            # Company identity is historical too, even when editing an old draft.
            doc["company"] = previous["company"]
            if legacy_enabled(): doc["legacy_number"] = previous.get("legacy_number", "")
        else:
            if legacy_enabled(): doc['legacy_number']=''
            configured=(database.inventory_settings.find_one({'_id':'company'}) or {}).get('values')
            if configured: doc['company']={**doc['company'],**{k:v for k,v in configured.items() if v}}
        try:
            layout({**doc, "number": (previous or {}).get("number", "LOCAL-PO-PENDING")})
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return doc

    @bp.before_request
    def protect():
        if "username" not in session:
            if request.path.startswith(bp.url_prefix + "/api/"):
                return jsonify(error="Please sign in again."), 401
            session["post_login_next"] = request.url
            return redirect(url_for("login", next=request.path))
        if session.get("role") not in ("admin", "worker"):
            abort(403)
        require_permission('documents.view')
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.content_length and request.content_length > 1024 * 1024:
                abort(413)
            token = request.headers.get("X-CSRF-Token", "")
            if not session.get("po_csrf") or not hmac.compare_digest(token, session["po_csrf"]):
                return jsonify(error="Security token expired. Reload this page and try again."), 400

    @bp.errorhandler(ValidationError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @bp.errorhandler(Conflict)
    def conflict(exc):
        return jsonify(error=str(exc)), 409

    @bp.errorhandler(PyMongoError)
    def unavailable(exc):
        current_app.logger.exception("Purchase-order database operation failed")
        if "/api/" in request.path:
            return jsonify(error="Purchase-order storage is unavailable. Your changes have not been confirmed; retry after checking the dashboard."), 503
        return render_template("purchase_orders/error.html"), 503

    @bp.get("/")
    def dashboard():
        return render_template("purchase_orders/dashboard.html", csrf=csrf_token())

    @bp.get("/new")
    def new():
        require_permission('documents.create')
        requested=[]
        for value in request.args.getlist("uid"):
            requested.extend(part.strip() for part in value.split(",") if part.strip())
        requested=list(dict.fromkeys(requested))[:100]
        items=[]
        if requested:
            product_map={}
            for product in products.find({"$or":[{"uid":{"$in":requested}},{"Part_id":{"$in":requested}}]}):
                for key in (product.get("uid"),product.get("Part_id")):
                    if key: product_map[str(key)]=product
            latest={row.get("uid"):row for row in database.forecast_cache.find({"uid":{"$in":requested}})}
            missing=[uid for uid in requested if uid not in latest]
            for row in database.forecasts.find({"uid":{"$in":missing}}).sort("generated_at",-1):
                latest.setdefault(row.get("uid"),row)
            for uid in requested:
                product=product_map.get(uid);forecast=latest.get(uid)
                quantity=(forecast or {}).get("replenishment",{}).get("suggested_quantity")
                if product and isinstance(quantity,(int,float)) and quantity>0:
                    item=product_snapshot(product);item["quantity"]=str(quantity);items.append(item)
        doc = {"supplier": {}, "date": today(), "currency": "MYR", "items": [], "discount_type": "amount",
               "discount_value": "0", "status": "draft"}
        doc["items"]=items
        return render_template("purchase_orders/editor.html", po=doc, csrf=csrf_token(), currencies=app.config["PO_CURRENCIES"], automatic_numbering=legacy_enabled())

    @bp.get("/<number>")
    def view(number):
        return render_template("purchase_orders/view.html", po=get_doc(number), csrf=csrf_token())

    @bp.get("/<number>/edit")
    def edit(number):
        require_permission('documents.edit')
        doc = get_doc(number)
        return render_template("purchase_orders/editor.html", po=doc, csrf=csrf_token(), currencies=app.config["PO_CURRENCIES"], automatic_numbering=legacy_enabled())

    @bp.get("/<number>/print")
    def print_order(number):
        doc = get_doc(number)
        return render_template("purchase_orders/print.html", po=doc, pages=svg_pages(doc))

    @bp.get("/<number>/pdf")
    def export_pdf(number):
        doc = get_doc(number)
        return send_file(BytesIO(pdf_bytes(doc)), mimetype="application/pdf", as_attachment=True,
                         download_name=doc["number"] + ".pdf")

    @bp.get("/api/orders")
    def list_orders():
        query = scope()
        search = request.args.get("q", "").strip()[:160]
        if search:
            rx = re.compile(re.escape(search), re.I)
            query["$or"] = [{k: rx} for k in ("number", "legacy_number", "supplier.name")]
        status = request.args.get("status", "")
        if status:
            if status not in ("draft", "finalised", "cancelled"):
                raise ValidationError("Invalid status filter.")
            query["status"] = status
        order = request.args.get("sort", "newest")
        if order not in ("oldest", "newest"):
            raise ValidationError("Invalid sort order.")
        try:
            page = max(1, min(100000, int(request.args.get("page", "1"))))
        except ValueError:
            raise ValidationError("Invalid page.") from None
        direction = 1 if order == "oldest" else -1
        fields = {k: 1 for k in ("number", "legacy_number", "supplier.name", "date", "total", "currency", "status", "revision", "created_by")}
        rows = list(repo.collection.find(query, fields).sort([("date", direction), ("created_at", direction), ("_id", direction)]).skip((page-1)*25).limit(25))
        return jsonify(orders=rows, total=repo.collection.count_documents(query), page=page)

    @bp.get("/api/orders/<number>")
    def read_order(number):
        return jsonify(get_doc(number))

    @bp.post("/api/orders")
    def create_order():
        require_permission('documents.create')
        doc = repo.create(validated(payload()), session["username"])
        database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_created','timestamp':datetime.now(ZoneInfo('UTC')).isoformat(),'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':doc['number'],'after':{'status':doc['status'],'total':doc['total']}})
        return jsonify(doc), 201

    @bp.put("/api/orders/<number>")
    def update_order(number):
        require_permission('documents.edit')
        original = get_doc(number)
        data = payload()
        updated=repo.update(number, revision(data), validated(data, original), session["username"], scope())
        database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_edited','timestamp':datetime.now(ZoneInfo('UTC')).isoformat(),'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':number,'before':{'revision':original['revision']},'after':{'revision':updated['revision'],'total':updated['total']}})
        return jsonify(updated)

    @bp.delete("/api/orders/<number>")
    def delete_order(number):
        require_permission('documents.edit')
        get_doc(number)
        repo.delete(number, revision(payload()), scope())
        database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_deleted','timestamp':datetime.now(ZoneInfo('UTC')).isoformat(),'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':number})
        return jsonify(deleted=True, number=number)

    @bp.post("/api/orders/<number>/<action>")
    def action_order(number, action):
        original = get_doc(number)
        data = payload()
        if action == "duplicate":
            require_permission('documents.create')
            duplicated=repo.duplicate(original, session["username"])
            database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_duplicated','timestamp':datetime.now(ZoneInfo('UTC')).isoformat(),'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':duplicated['number'],'source_document':number})
            return jsonify(duplicated), 201
        if action not in ("finalise", "cancel"):
            abort(404)
        if action == "finalise":
            require_permission('documents.approve')
            validated(original, original)
        else:
            require_permission('documents.edit')
        target="finalised" if action == "finalise" else "cancelled"
        updated=repo.transition(number, revision(data), target, session["username"], scope())
        database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_'+target,'timestamp':datetime.now(ZoneInfo('UTC')).isoformat(),'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':number,'before':{'status':original['status']},'after':{'status':target}})
        return jsonify(updated)

    @bp.post('/api/orders/<number>/receive')
    def receive(number):
        if not permitted('stock.receive'): abort(403)
        original=get_doc(number);body=payload();operation=str(body.get('operation_id',''))
        try: UUID(operation)
        except ValueError: raise ValidationError('A unique receipt operation ID is required.') from None
        existing=next((r for r in original.get('receipts',[]) if r.get('operation_id')==operation),None)
        if existing:return jsonify(receipt=existing,status=original['status'])
        if original['status'] not in ('finalised','partially_received'): raise Conflict('Only issued or partially received POs can receive stock.')
        confirmed=[Decimal('0') for _ in original['items']]
        for receipt in original.get('receipts',[]):
            if receipt.get('status') in ('pending','confirmed'):
                for line in receipt['items']:confirmed[line['index']]+=Decimal(line['quantity'])
        requested=body.get('items')
        if body.get('receive_all') is True:
            requested=[{'index':i,'quantity':format(Decimal(item['quantity'])-confirmed[i],'f')} for i,item in enumerate(original['items']) if Decimal(item['quantity'])>confirmed[i]]
        if not isinstance(requested,list) or not requested: raise ValidationError('Select received quantities.')
        lines=[];by_uid={}
        for line in requested:
            index=int(line.get('index',-1));qty=Decimal(str(line.get('quantity','0')))
            if index<0 or index>=len(original['items']) or qty<=0 or qty!=qty.to_integral_value(): raise ValidationError('Receipt quantities must be positive whole units.')
            remaining=Decimal(original['items'][index]['quantity'])-confirmed[index]
            if qty>remaining: raise ValidationError('Receipt exceeds the remaining ordered quantity.')
            uid=original['items'][index]['product_id'];lines.append({'index':index,'uid':uid,'quantity':format(qty,'f')});by_uid[uid]=by_uid.get(uid,0)+int(qty)
        store=app.extensions['inventory_platform'];plans=[]
        from inventory_platform.domain import stock_state
        for uid,qty in by_uid.items():
            product=products.find_one({'$or':[{'uid':uid},{'Part_id':uid}]})
            if not product: raise ValidationError('Inventory product not found: '+uid)
            state=stock_state(product);after={**state,'total':state['total']+qty}
            slot='a' if state['a'] is not None else 'b' if state['b'] is not None else None
            if not slot: raise ValidationError('No inventory location is available for '+uid)
            after[slot]+=qty;event_id=str(uuid5(UUID('16ce25aa-edb4-4b83-a3c3-88af97c33c49'),operation+':'+uid));plans.append((product,after,event_id))
        def work(kw):
            for product,after,event_id in plans: store.change(product.get('uid') or product['Part_id'],{'event_id':event_id,'revision':product.get('stock_revision',0),'mode':'set','a':after['a'],'b':after['b'],'total':after['total'],'location_a':after['location_a'],'location_b':after['location_b'],'reason':'received','reference':number,'note':'Purchase Order receipt'}, {'id':str(session.get('user_id') or session['username']),'username':session['username']},transaction=kw)
            receipt={'operation_id':operation,'status':'pending','items':lines,'event_ids':[p[2] for p in plans],'created_at':datetime.now(ZoneInfo('UTC')).isoformat(),'by':session['username']}
            result=repo.collection.update_one({'_id':number,'revision':original['revision'],'receipts.operation_id':{'$ne':operation}},{'$push':{'receipts':receipt,'history':{'action':'receipt_pending','by':session['username'],'at':receipt['created_at']}},'$inc':{'revision':1},'$set':{'updated_at':receipt['created_at']}},**kw)
            if not result.matched_count: raise Conflict('PO changed before receipt could be queued.')
            database.audit_events.insert_one({'_id':str(uuid4()),'action':'purchase_order_receipt_pending','timestamp':receipt['created_at'],'user_id':str(session.get('user_id') or session['username']),'username':session['username'],'target_document':number,'operation_id':operation,'items':lines},**kw)
        store.transact(work);return jsonify(message='Receipt queued pending Access confirmation.',status='pending'),202

    @bp.post("/api/preview")
    def preview():
        data = payload()
        original = get_doc(data["number"]) if isinstance(data.get("number"), str) else None
        doc = validated(data, original)
        doc.update(number=(original or {}).get("number", "Pending"), status=(original or {}).get("status", "draft"))
        return jsonify(pages=svg_pages(doc), subtotal=doc["subtotal"], discount=doc["discount"], total=doc["total"])

    @bp.get("/api/suppliers")
    def search_suppliers():
        rows = []
        for supplier in database.get_collection("suppliers").find({}):
            if not supplier.get("name"):
                continue
            rows.append({**{key: str(supplier.get(key) or "") for key in
                ("name", "details", "attention", "fax", "supplier_code", "currency", "terms")},
                "record_id": "suppliers:" + str(supplier["_id"])})
        return jsonify(rows=sorted(rows, key=lambda row: row["name"].casefold()))

    @bp.get("/api/products")
    def search_products():
        search = request.args.get("q", "").strip()[:120]
        fields = ("uid", "Part_id", "name", "Desc", "readable_id", "Mssid", "size", "Size", "material", "Material", "Matl")
        tokens=re.findall(r'[A-Za-z0-9]+',search)
        query={"$and":[{"$or":[{field:re.compile(re.escape(token),re.I)} for field in fields[:6]]} for token in tokens]} if tokens else {}
        docs = products.find(query, {k: 1 for k in fields}).sort('name',1).limit(20)
        return jsonify([product_snapshot(d) for d in docs])

    @bp.get("/api/prices")
    def price_options():
        uid = request.args.get("uid", "").strip()[:120]
        currency = request.args.get("currency", "MYR").upper()
        if currency not in app.config["PO_CURRENCIES"]:
            raise ValidationError("Select a supported currency.")
        on_date = date_value(request.args.get("date", today()), "Order date", True)
        product = products.find_one({"$or": [{"uid": uid}, {"Part_id": uid}]}) if uid else None
        if not product:
            return jsonify([])
        mapped = product_snapshot(product)
        candidates = list({v for v in (mapped["product_id"], mapped["mssid"],str(product.get('Part_id') or ''),str(product.get('Mssid') or '')) if v})
        part_fields=("part_id","Part_id","Part_ID","uid","UID","mssid","Mssid")
        rows = list(pricing.find({"$or": [{field:{"$in":candidates}} for field in part_fields]}).limit(500))
        # Purchase orders always use the standard 1K buying price. Selling
        # documents remain quantity-tiered through the selling-price endpoint.
        return jsonify([option for option in purchasing_options(rows, candidates, currency, on_date)
                        if option['tier']=='1K'])

    app.register_blueprint(bp)
