"""Shared local business-document engine for QT, PI and DO."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from html import escape
from pathlib import Path
import hmac, re, secrets
import qrcode
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo
from flask import g, Blueprint, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from pymongo import ReturnDocument
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

KINDS={'quotation':{'prefix':'QT','title':'Quotation','statuses':['draft','issued','accepted','rejected','expired','cancelled'],'convert':'proforma'},
       'proforma':{'prefix':'PI','title':'Proforma Invoice','statuses':['draft','issued','confirmed','cancelled','converted'],'convert':'delivery'},
       'delivery':{'prefix':'DO','title':'Delivery Order','statuses':['draft','ready','dispatched','delivered','cancelled'],'convert':None}}

def now(): return datetime.now(ZoneInfo('UTC')).isoformat()
def clean(value,limit=600,required=False):
    if not isinstance(value,str): raise ValueError('Text value required.')
    value=value.strip()
    if len(value)>limit or required and not value: raise ValueError('Complete all required fields.')
    return value
def money(value):
    try: result=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError('Enter valid monetary values.') from None
    if not result.is_finite() or result<0: raise ValueError('Amounts cannot be negative.')
    return result
def snapshot(data,kind,company):
    payment_status=data.get('payment_status','unpaid')
    if kind=='proforma' and payment_status not in ('paid','unpaid'):
        raise ValueError('Choose Paid or Unpaid.')
    party=data.get('party') or {};rows=data.get('items')
    if not isinstance(party,dict) or not isinstance(rows,list) or not rows: raise ValueError('Party and item details are required.')
    items=[];subtotal=Decimal('0')
    for row in rows[:200]:
        qty=money(row.get('quantity'));price=money(row.get('unit_price',0));discount=money(row.get('discount',0));tax=money(row.get('tax',0))
        base=qty*price-discount
        if base<0: raise ValueError('Line discount cannot exceed its value.')
        total=(base+base*tax/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP);subtotal+=total
        items.append({'uid':clean(row.get('uid',''),120),'description':clean(row.get('description',''),600,True),'quantity':format(qty,'f'),
            'unit_price':format(price,'.4f'),'discount':format(discount,'.2f'),'tax':format(tax,'.2f'),'location':clean(row.get('location',''),100),'total':format(total,'.2f')})
    return {'kind':kind,'company':deepcopy(company),'party':{k:clean(party.get(k,''),600,k=='name') for k in ('name','details','address','contact','record_id','shipping_name','shipping_address','shipping_contact')},
        'date':clean(data.get('date',''),10,True),'valid_until':clean(data.get('valid_until',''),10),'delivery_date':clean(data.get('delivery_date',''),10),
        'reference':clean(data.get('reference',''),120),'remarks':clean(data.get('remarks',''),2000),'terms':clean(data.get('terms',''),2000),
        'prepared_by':clean(data.get('prepared_by',''),120),'received_by':clean(data.get('received_by',''),120),'signature_note':clean(data.get('signature_note',''),600),
        'currency':clean(data.get('currency','MYR'),3,True).upper(),'items':items,'subtotal':format(subtotal,'.2f'),'total':format(subtotal,'.2f'),
        **({'payment_status':payment_status} if kind=='proforma' else {})}

def proforma_pdf(doc):
    """Render the compact Meadow proforma layout used by the live preview and export."""
    output=BytesIO();company=doc.get('company',{});styles=getSampleStyleSheet()
    normal=ParagraphStyle('pi-normal',parent=styles['Normal'],fontName='Helvetica',fontSize=7.5,leading=9,textColor=colors.black)
    small=ParagraphStyle('pi-small',parent=normal,fontSize=6.5,leading=8)
    heading=ParagraphStyle('pi-heading',parent=normal,fontName='Helvetica-Bold',fontSize=15,leading=17)
    right=ParagraphStyle('pi-right',parent=normal,alignment=TA_RIGHT)
    def e(value):return escape(str(value or '')).replace('\n','<br/>')
    def p(value,style=normal):return Paragraph(str(value or ''),style)
    thin=colors.HexColor('#68707a');shade=colors.HexColor('#d9dde1')
    grid=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]
    linktree_url='https://example.com'
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4)
    qr.add_data(linktree_url);qr.make(fit=True)
    qr_image=ImageReader(qr.make_image(fill_color='black',back_color='white').convert('RGB'))
    document=SimpleDocTemplate(output,pagesize=A4,rightMargin=18,leftMargin=18,topMargin=20,bottomMargin=88,title=doc['number'])
    logo_path=Path(__file__).resolve().parents[1]/'static'/'po-logo.png'
    company_name=e(company.get('name') or 'Meadow Sdn. Bhd.')
    company_text='<b>'+company_name+'</b>'
    if company.get('registration'):company_text+=' ('+e(company['registration'])+')'
    company_text+='<br/>'+e(company.get('address'))+'<br/>Tel: '+e(company.get('telephone'))
    if company.get('fax'):company_text+=' &nbsp; Fax: '+e(company['fax'])
    if company.get('email'):company_text+='<br/>E-mail: '+e(company['email'])
    brand=Table([[Image(str(logo_path),width=94,height=48) if logo_path.exists() else p('<b>MEADOW</b>',heading),p(company_text,small)]],colWidths=[104,285],style=TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    title=p('PROFORMA INVOICE<br/><font size="8"><b>No:</b> '+e(doc['number'])+'<br/><b>Date:</b> '+e(doc['date'])+'</font>',right)
    story=[p('Proforma Invoice',heading),Spacer(1,10),Table([[brand,title]],colWidths=[389,170],style=TableStyle(grid)),Spacer(1,12)]
    party=doc['party'];bill=e(party.get('name'))
    if party.get('details'):bill+='<br/>'+e(party['details'])
    if party.get('address'):bill+='<br/>'+e(party['address'])
    if party.get('contact'):bill+='<br/><b>Attn:</b> '+e(party['contact'])
    left=Table([[p('<b>Bill To:</b>'),p(bill)]],colWidths=[54,297],style=TableStyle(grid))
    detail_rows=[['Invoice No:',doc['number']],['Date:',doc['date']],['PO No:',doc.get('reference') or ''],['Terms:',doc.get('terms') or ''],['Currency:',doc['currency']],['Reference:',doc.get('reference') or ''],['Payment:',doc.get('payment_status','unpaid').title()]]
    details=Table([[p('<b>'+e(label)+'</b>',small),p(e(value),small)] for label,value in detail_rows],colWidths=[67,141],style=TableStyle(grid))
    story.extend([Table([[left,details]],colWidths=[351,208],style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])),Spacer(1,5)])
    if party.get('shipping_address'):
        shipping='<b>Ship To:</b><br/>'+e(party.get('shipping_name') or party['name'])+'<br/>'+e(party['shipping_address'])
        if party.get('shipping_contact'):shipping+='<br/><b>Attn:</b> '+e(party['shipping_contact'])
        story.extend([p(shipping,small),Spacer(1,10)])
    rows=[[p('<b>No.</b>',small),p('<b>Description</b>',small),p('<b>Qty</b>',small),p('<b>U/Price</b>',small),p('<b>Curr.</b>',small),p('<b>Amount</b>',small)]]
    for index,item in enumerate(doc['items'],1):
        description=e(item['description'])
        if item.get('uid'):description+='<br/><font size="6.5">'+e(item['uid'])+'</font>'
        rows.append([str(index),p(description,small),item['quantity'],item['unit_price'],doc['currency'],item['total']])
    widths=[28,287,52,67,48,77]
    items=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
    items.setStyle(TableStyle(grid+[('LINEABOVE',(0,0),(-1,0),.6,thin),('LINEBELOW',(0,0),(-1,0),.6,thin),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(2,1),(-1,-1),'RIGHT'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,1),(-1,-1),7.5),('MINROWHEIGHT',(0,1),(-1,-1),22)]))
    story.extend([items,Spacer(1,7)])
    notes=e(doc.get('remarks')) or 'This is a computer generated invoice, no signature required.'
    bank=p('<b>Bank information:</b><br/>'+notes+'<br/><br/><b>E. &amp; O. E.</b>',small)
    paid=doc.get('payment_status')=='paid'
    totals=Table([[p('Paid amount',small),p(doc['currency']+' '+(doc['total'] if paid else '0.00'),right)],[p('<b>Total</b>',small),p('<b>'+doc['currency']+' '+doc['total']+'</b>',right)],[p('<b>Balance</b>',small),p('<b>'+doc['currency']+' '+('0.00' if paid else doc['total'])+'</b>',right)]],colWidths=[70,115],style=TableStyle(grid+[('LINEABOVE',(0,-1),(-1,-1),.6,thin)]))
    story.extend([Spacer(1,8),Table([[bank,totals]],colWidths=[374,185],style=TableStyle(grid+[('LINEABOVE',(0,0),(-1,0),.6,thin)])),Spacer(1,7),p('This is a computer generated invoice, no signature required.',small)])
    def footer(canvas,_):
        canvas.saveState();canvas.setFont('Helvetica',7);canvas.setFillColor(colors.HexColor('#4b5563'))
        canvas.setStrokeColor(colors.HexColor('#d9dde1'));canvas.setLineWidth(.45)
        canvas.line(18,79,A4[0]-18,79)
        canvas.drawImage(qr_image,18,22,width=54,height=54,mask='auto')
        canvas.setFont('Helvetica-Bold',8);canvas.drawString(82,57,'Connect with Meadow')
        canvas.setFont('Helvetica',8);canvas.drawString(82,43,linktree_url)
        canvas.setFont('Helvetica',6.5);canvas.drawString(82,31,'Scan the QR code or click the link to visit our pages.')
        canvas.linkURL(linktree_url,(18,22,72,76),relative=0)
        canvas.linkURL(linktree_url,(82,40,82+canvas.stringWidth(linktree_url,'Helvetica',8),52),relative=0)
        canvas.setFont('Helvetica',7)
        canvas.drawString(18,12,'Meadow - Product Packaging Solution');canvas.drawRightString(A4[0]-18,12,'Page %d' % canvas.getPageNumber());canvas.restoreState()
    document.build(story,onFirstPage=footer,onLaterPages=footer);output.seek(0);return output

def pdf(doc):
    doc={**doc,"number":doc.get("legacy_number") or doc["number"]}
    if doc['kind']=='proforma':return proforma_pdf(doc)
    output=BytesIO();kind=doc['kind'];company=doc.get('company',{});styles=getSampleStyleSheet()
    body=ParagraphStyle('body',parent=styles['Normal'],fontName='Helvetica',fontSize=9,leading=12,textColor=colors.HexColor('#1f2937'))
    small=ParagraphStyle('small',parent=body,fontSize=8,leading=10);right=ParagraphStyle('right',parent=body,alignment=TA_RIGHT)
    title=ParagraphStyle('title',parent=styles['Heading1'],fontName='Helvetica-Bold',fontSize=17,leading=20,spaceAfter=5)
    document=SimpleDocTemplate(output,pagesize=A4,rightMargin=38,leftMargin=38,topMargin=36,
        bottomMargin=175 if kind=='proforma' else 42,title=doc['number'])
    def e(value): return escape(str(value or '')).replace('\n','<br/>')
    def p(value,style=body): return Paragraph(str(value or '').replace('\n','<br/>'),style)
    def page(canvas,_):
        canvas.saveState()
        if kind=='proforma':
            canvas.setStrokeColor(colors.HexColor('#9aa3af'));canvas.setLineWidth(.5);canvas.line(38,150,A4[0]-38,150)
            canvas.setFillColor(colors.HexColor('#30343b'));canvas.setFont('Helvetica',8.5)
            canvas.drawString(38,134,'Terima Kasih, Barangan yang dijual tidak boleh dikembalikan.')
            canvas.drawString(38,120,'Pelanggan bertanggungjawab memastikan kesesuaian pembungkusan.')
            canvas.drawString(38,106,'Meadow tidak bertanggungjawab terhadap reaksi produk dan sebagainya.')
            canvas.drawString(38,84,'This is a computer generated invoice, no signature required.')
            canvas.setFont('Helvetica-Bold',9);canvas.drawString(38,68,'example.com')
            x=A4[0]-185;right=A4[0]-38;canvas.setFont('Helvetica',9)
            canvas.drawString(x,134,'Subtotal');canvas.drawRightString(right,134,doc['currency']+' '+doc['subtotal'])
            canvas.drawString(x,117,'Discount');canvas.drawRightString(right,117,doc['currency']+' 0.00')
            canvas.drawString(x,100,'Rounding Adj.');canvas.drawRightString(right,100,doc['currency']+' 0.00')
            canvas.line(x,91,right,91);canvas.setFont('Helvetica-Bold',10)
            canvas.drawString(x,73,'Total Amount:');canvas.drawRightString(right,73,doc['currency']+' '+doc['total'])
            canvas.setFont('Helvetica',8);canvas.drawRightString(right,54,'Page %d' % canvas.getPageNumber())
        else:
            canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#596273'));canvas.drawRightString(A4[0]-38,20,'Page %d' % canvas.getPageNumber())
        canvas.restoreState()
    company_lines='<b>'+e(company.get('name') or 'Meadow Sdn. Bhd.')+'</b>'
    if company.get('registration'):company_lines+=' ('+e(company['registration'])+')'
    company_lines+='<br/>'+e(company.get('address'))
    contact='Tel: '+e(company.get('telephone'))
    if company.get('fax'):contact+='   Fax: '+e(company['fax'])
    if company.get('email'):contact+='   E-mail: '+e(company['email'])
    heading='INVOICE' if kind=='proforma' else KINDS[kind]['title'].upper()
    company_block=p(company_lines+'<br/>'+contact,small)
    logo_path=Path(__file__).resolve().parents[1]/'static'/'po-logo.png'
    if kind=='quotation' and logo_path.exists():
        left=Table([[Image(str(logo_path),width=82,height=42),company_block]],colWidths=[90,250],style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    else:left=company_block
    if kind=='proforma':
        meta=p('<b>'+heading+'</b><br/><b>Invoice No:</b> '+e(doc['number'])+'<br/><b>Date:</b> '+e(doc['date'])+'<br/><b>Pay by:</b> Cash<br/><b>Currency:</b> '+e(doc['currency']),right)
    else:meta=p('<b>'+heading+'</b><br/><b>No:</b> '+e(doc['number'])+'<br/><b>Date:</b> '+e(doc['date'])+('<br/><b>Reference:</b> '+e(doc.get('reference')) if doc.get('reference') else ''),right)
    story=[Table([[left,meta]],colWidths=[340,179],style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.6,colors.HexColor('#9aa3af')),('BOTTOMPADDING',(0,0),(-1,-1),10)])),Spacer(1,12)]
    party_label='To' if kind=='delivery' else 'Bill To'
    story.extend([p('<b>'+party_label+':</b><br/>'+e(doc['party']['name'])+'<br/>'+e(doc['party'].get('details'))+'<br/>'+e(doc['party'].get('address'))+'<br/>'+e(doc['party'].get('contact'))),Spacer(1,14)])
    if doc['party'].get('shipping_address'):
        party=doc['party']
        story.extend([p('<b>Ship To:</b><br/>'+e(party.get('shipping_name') or party['name'])+'<br/>'+e(party['shipping_address'])+'<br/>'+e(party.get('shipping_contact'))),Spacer(1,12)])
    if kind=='quotation':story.extend([p('<b>Re: Quotation - '+e(doc.get('reference'))+'</b>'),p('We are pleased to quote to your organization on the following items for your perusal.<br/>Should you require further information, please do not hesitate to call upon us.'),Spacer(1,8)])
    headers=['No.','Description','Qty'] if kind=='delivery' else ['No.','Description','Qty','U/Price','Amount']
    rows=[headers]
    for index,item in enumerate(doc['items'],1):
        description=e(item['description'])
        if item.get('uid'):description+='<br/><font size="8">'+e(item['uid'])+'</font>'
        if item.get('location') and kind=='delivery':description+='<br/><font size="8">Location: '+e(item['location'])+'</font>'
        row=[str(index),p(description,small),item['quantity']]
        if kind!='delivery':row.extend([item['unit_price'],item['total']])
        rows.append(row)
    widths=[28,401,70] if kind=='delivery' else [28,271,55,75,90]
    table=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d7d9dc')),('TEXTCOLOR',(0,0),(-1,0),colors.black),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),8.5),('LEADING',(0,0),(-1,-1),11),('ALIGN',(2,1),(-1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#737b86')),('LINEBELOW',(0,-1),(-1,-1),.3,colors.HexColor('#c7ccd3')),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.extend([table,Spacer(1,12)])
    if kind not in ('delivery','proforma'):story.append(Table([['Subtotal',doc['currency']+' '+doc['subtotal']],['Total Amount',doc['currency']+' '+doc['total']]],colWidths=[420,99],style=TableStyle([('ALIGN',(0,0),(-1,-1),'RIGHT'),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),('LINEABOVE',(0,-1),(-1,-1),.8,colors.black),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])))
    story.extend([Spacer(1,16),p(e(doc.get('remarks')))])
    if kind=='quotation':
        terms=doc.get('terms') or ('Delivery: As agreed\nValidity: '+(doc.get('valid_until') or 'As stated')+'\nPayment term: As agreed')
        story.extend([Spacer(1,10),p('<b><i>Terms and conditions:</i></b><br/>'+e(terms)),Spacer(1,24),Table([[p('Thank you.<br/><br/>Best Regards,<br/><br/><br/>'+e(doc.get('prepared_by'))),p('Accepted By:<br/>(Chop &amp; Signed)<br/><br/>Name:<br/>Title:<br/>Date:')]],colWidths=[300,219])])
    elif kind=='delivery':story.extend([Spacer(1,55),Table([[p('________________________<br/>Received By'),p('E. &amp; O. E.',right),p('________________________<br/>Issued By',right)]],colWidths=[180,159,180])])
    else:story.extend([Spacer(1,10),p(e(doc.get('terms')))])
    document.build(story,onFirstPage=page,onLaterPages=page);output.seek(0);return output

def init_app(app,db,products):
    bp=Blueprint('documents',__name__,url_prefix='/documents');collection=db.business_documents
    @app.cli.command('documents-init-indexes')
    def document_indexes():
        collection.create_index([('kind',1),('updated_at',-1)])
        collection.create_index([('kind',1),('status',1),('date',-1)])
        collection.create_index([('created_by',1),('kind',1),('updated_at',-1)])
        print('Business-document indexes are ready.')
    def token():
        session.setdefault('document_csrf',secrets.token_urlsafe(32));return session['document_csrf']
    def company(): return (db.inventory_settings.find_one({'_id':'company'}) or {}).get('values',{'name':'Meadow Sdn. Bhd.','address':'','telephone':'','email':''})
    def scope(): return {} if session.get('role')=='admin' else {'created_by':session.get('username')}
    def allowed(permission):
        if getattr(g,'platform_user',None):return permission in g.platform_permissions
        if session.get('role')=='admin': return True
        from inventory_platform.accounts import find_user, permissions
        user=find_user(db,str(session.get('user_id') or ''),session.get('username'))
        return permission in permissions(db,user) if user else permission in {'documents.view','documents.create','documents.edit'}
    def require(permission):
        if not allowed(permission): abort(403)
    def audit(action,target,before=None,after=None,extra=None,transaction=None):
        event={'_id':str(uuid4()),'action':action,'timestamp':now(),'user_id':str(session.get('user_id') or session.get('username')),
               'username':session.get('username'),'target_document':target}
        if before is not None:event['before']=before
        if after is not None:event['after']=after
        if extra:event.update(extra)
        db.audit_events.insert_one(event,**(transaction or {}))
    @bp.before_request
    def protect():
        if not session.get('username'): return redirect(url_for('login',next=request.path))
        if not allowed('documents.view'): abort(403)
        if request.method!='GET' and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),token()): return jsonify(error='Security token expired.'),400
    @bp.get('/<kind>/')
    def listing(kind):
        if kind not in KINDS:abort(404)
        query={'kind':kind,**scope()};q=request.args.get('q','').strip();status=request.args.get('status','').strip()
        if q:query['$or']=[{'number':re.compile(re.escape(q),re.I)},{'legacy_number':re.compile(re.escape(q),re.I)},{'party.name':re.compile(re.escape(q),re.I)}]
        if status in KINDS[kind]['statuses']:query['status']=status
        for key,operator in (('from','$gte'),('to','$lte')):
            value=request.args.get(key,'').strip()
            if value:query.setdefault('date',{})[operator]=value
        page=max(1,int(request.args.get('page','1') or 1));total=collection.count_documents(query)
        docs=list(collection.find(query).sort('updated_at',-1).skip((page-1)*50).limit(50))
        summary={s:collection.count_documents({'kind':kind,'status':s,**scope()}) for s in KINDS[kind]['statuses']}
        return render_template('documents/list.html',kind=kind,meta=KINDS[kind],docs=docs,total=total,page=page,summary=summary)
    @bp.get('/<kind>/new')
    def new(kind):
        if kind not in KINDS:abort(404)
        require('documents.create')
        return render_template('documents/editor.html',kind=kind,meta=KINDS[kind],doc={'party':{},'items':[],'currency':'MYR','date':datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat()},csrf=token())
    @bp.get('/<kind>/<number>/edit')
    def edit(kind,number):
        require('documents.edit');doc=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not doc:abort(404)
        if doc['status']!='draft':abort(409)
        return render_template('documents/editor.html',kind=kind,meta=KINDS[kind],doc=doc,csrf=token())
    @bp.get('/<kind>/<number>')
    def view(kind,number):
        doc=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not doc:abort(404)
        if kind=='delivery' and doc.get('fulfilment',{}).get('status')=='pending':
            ids=doc['fulfilment'].get('event_ids',[]);states=[e.get('status') for e in db.sync_events.find({'_id':{'$in':ids}},{'status':1})]
            if ids and len(states)==len(ids) and all(state=='synced' for state in states):
                stamp=now();collection.update_one({'_id':number,'revision':doc['revision']},{'$set':{'status':'dispatched','fulfilment.status':'confirmed','updated_at':stamp},'$inc':{'revision':1},'$push':{'history':{'action':'dispatch_confirmed','at':stamp,'by':'sync-worker'}}});doc=collection.find_one({'_id':number})
        return render_template('documents/view.html',doc=doc,meta=KINDS[kind],csrf=token())
    @bp.post('/api/<kind>')
    def create(kind):
        if kind not in KINDS:abort(404)
        require('documents.create')
        try:data=snapshot(request.get_json() or {},kind,company())
        except ValueError as exc:return jsonify(error=str(exc)),400
        if kind=='proforma' and data['payment_status']=='paid':require('documents.approve')
        year=data['date'][:4];seq=db.document_sequences.find_one_and_update({'_id':kind+':'+year},{'$inc':{'value':1}},upsert=True,return_document=ReturnDocument.AFTER)['value'];number=f"{KINDS[kind]['prefix']}-{year}-{seq:05d}";stamp=now()
        data['prepared_by']=data.get('prepared_by') or session['username'];data.update(_id=number,number=number,status='draft',revision=1,created_by=session['username'],updated_by=session['username'],created_at=stamp,updated_at=stamp,history=[{'action':'created','at':stamp,'by':session['username']}]);collection.insert_one(data);audit(kind+'_created',number,after={'status':'draft'})
        return jsonify(number=number),201
    @bp.post('/api/<kind>/preview')
    def preview(kind):
        """Render editor data through the exact production PDF path."""
        if kind not in KINDS:abort(404)
        require('documents.create')
        body=deepcopy(request.get_json() or {});party=body.setdefault('party',{})
        party['name']=party.get('name') or 'Customer'
        body['date']=body.get('date') or datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat()
        body['currency']=body.get('currency') or 'MYR'
        rows=body.get('items') if isinstance(body.get('items'),list) else []
        if not rows:rows=[{}]
        for row in rows:
            row['description']=row.get('description') or 'Item description'
            row['quantity']=row.get('quantity') or '1';row['unit_price']=row.get('unit_price') or '0'
            row['discount']=row.get('discount') or '0';row['tax']=row.get('tax') or '0'
        body['items']=rows
        try:document=snapshot(body,kind,company())
        except ValueError as exc:return jsonify(error=str(exc)),400
        document.update(number='DRAFT',status='draft')
        return send_file(pdf(document),mimetype='application/pdf',download_name='preview.pdf')
    @bp.put('/api/<kind>/<number>')
    def update(kind,number):
        require('documents.edit');old=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not old:abort(404)
        if old['status']!='draft':return jsonify(error='Only draft documents can be edited.'),409
        body=request.get_json() or {}
        if body.get('revision')!=old.get('revision'):return jsonify(error='Document changed. Refresh before saving.'),409
        if kind=='proforma':body.setdefault('payment_status',old.get('payment_status','unpaid'))
        try:values=snapshot(body,kind,old['company'])
        except ValueError as exc:return jsonify(error=str(exc)),400
        if kind=='proforma' and values['payment_status']!=old.get('payment_status','unpaid'):require('documents.approve')
        stamp=now();values.update(updated_at=stamp,updated_by=session['username'])
        result=collection.update_one({'_id':number,'revision':old['revision'],'status':'draft','numbering_lock':{'$exists':False}},{'$set':values,'$inc':{'revision':1},'$push':{'history':{'action':'edited','at':stamp,'by':session['username']}}})
        if not result.matched_count:return jsonify(error='Document changed. Refresh before saving.'),409
        audit(kind+'_edited',number,before={'revision':old['revision']},after={'revision':old['revision']+1});return jsonify(number=number)
    @bp.post('/api/<kind>/<number>/duplicate')
    def duplicate(kind,number):
        require('documents.create')
        original=collection.find_one({'_id':number,'kind':kind,**scope()});
        if not original:abort(404)
        body={k:deepcopy(original.get(k)) for k in ('party','date','valid_until','delivery_date','reference','remarks','terms','prepared_by','received_by','signature_note','currency','items')};body['source_document']={'kind':kind,'number':number,'snapshot':deepcopy(original)}
        return create_from(kind,body)
    def create_from(kind,data):
        year=(data.get('date') or datetime.now().strftime('%Y-%m-%d'))[:4];seq=db.document_sequences.find_one_and_update({'_id':kind+':'+year},{'$inc':{'value':1}},upsert=True,return_document=ReturnDocument.AFTER)['value'];number=f"{KINDS[kind]['prefix']}-{year}-{seq:05d}";stamp=now();doc=snapshot(data,kind,company());doc['prepared_by']=doc.get('prepared_by') or session['username'];doc.update(_id=number,number=number,status='draft',revision=1,created_by=session['username'],updated_by=session['username'],created_at=stamp,updated_at=stamp,source_document=data.get('source_document'),history=[{'action':'created','at':stamp,'by':session['username']}]);collection.insert_one(doc);audit(kind+'_created',number,after={'status':'draft','source':(data.get('source_document') or {}).get('number')});return jsonify(number=number),201
    @bp.post('/api/<kind>/<number>/status')
    def transition(kind,number):
        require('documents.approve');doc=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not doc:abort(404)
        body=request.get_json() or {};target=body.get('status');revision=body.get('revision')
        flows={'quotation':{'draft':{'issued','cancelled'},'issued':{'accepted','rejected','expired','cancelled'}},'proforma':{'draft':{'issued','cancelled'},'issued':{'confirmed','cancelled'}},'delivery':{'draft':{'ready','cancelled'},'ready':{'cancelled'},'dispatched':{'delivered'}}}
        if target not in flows.get(kind,{}).get(doc['status'],set()):return jsonify(error='That status transition is not allowed.'),409
        if revision!=doc['revision']:return jsonify(error='Document changed. Refresh before continuing.'),409
        stamp=now();query={'_id':number,'revision':revision,'status':doc['status'],'numbering_lock':{'$exists':False}}
        changes={'$set':{'status':target,'updated_at':stamp,'updated_by':session['username']},'$inc':{'revision':1},'$push':{'history':{'action':'status_'+target,'at':stamp,'by':session['username']}}}
        if kind=='delivery' and target=='ready':
            from purchase_orders.legacy import numbered_transition,reserve_do,NumberingConflict
            def reserve_delivery():
                import os
                configured=app.config.get('DO_NUMBER_RESERVER')
                if configured:return configured()
                if app.testing or app.config.get('DEMO_MODE') or not app.config.get('DO_LEGACY_NUMBERING',True):return None
                path=app.config.get('DO_ACCESS_DB_PATH') or os.getenv('ACCESS_DB_PATH')
                if not path:raise ValueError('Access connection required to finalise a Delivery Order.')
                return reserve_do(path)
            try:result=numbered_transition(collection,query,changes,reserve_delivery,'delivery_order_number_claims')
            except NumberingConflict as exc:return jsonify(error=str(exc)),409
            except Exception:
                app.logger.exception('Delivery Order number reservation failed')
                return jsonify(error='Cannot reserve a legacy D.O. number. Check the Access connection and retry.'),503
        else:result=collection.update_one(query,changes)
        if not result.matched_count:return jsonify(error='Document changed. Refresh before continuing.'),409
        audit(kind+'_status',number,before={'status':doc['status']},after={'status':target});return jsonify(number=number,status=target,revision=revision+1)

    @bp.post('/api/proforma/<number>/payment')
    def payment(number):
        require('documents.approve')
        doc=collection.find_one({'_id':number,'kind':'proforma',**scope()})
        if not doc:abort(404)
        body=request.get_json() or {};target=body.get('payment_status');revision=body.get('revision')
        if target not in ('paid','unpaid'):return jsonify(error='Choose Paid or Unpaid.'),400
        if revision!=doc['revision']:return jsonify(error='Document changed. Refresh before continuing.'),409
        stamp=now();previous=doc.get('payment_status','unpaid')
        result=collection.update_one({'_id':number,'revision':revision},
            {'$set':{'payment_status':target,'payment_updated_at':stamp,'payment_updated_by':session['username'],
                     'updated_at':stamp,'updated_by':session['username']},'$inc':{'revision':1},
             '$push':{'history':{'action':'payment_'+target,'at':stamp,'by':session['username']}}})
        if not result.matched_count:return jsonify(error='Document changed. Refresh before continuing.'),409
        audit('proforma_payment',number,before={'payment_status':previous},after={'payment_status':target})
        return jsonify(number=number,payment_status=target,revision=revision+1)
    @bp.post('/api/<kind>/<number>/convert')
    def convert(kind,number):
        require('documents.create')
        target=KINDS.get(kind,{}).get('convert');original=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not target or not original:abort(404)
        required={'quotation':'accepted','proforma':'confirmed'}[kind]
        if original['status']!=required:return jsonify(error='The document must be '+required+' before conversion.'),409
        data={k:deepcopy(original.get(k)) for k in ('party','date','valid_until','delivery_date','reference','remarks','terms','prepared_by','received_by','signature_note','currency','items')};data['source_document']={'kind':kind,'number':number,'snapshot':deepcopy(original)}
        response=create_from(target,data)
        if kind=='proforma':collection.update_one({'_id':number},{'$set':{'status':'converted','updated_at':now()},'$inc':{'revision':1}})
        audit(kind+'_converted',number,extra={'target_kind':target});return response
    @bp.post('/api/delivery/<number>/dispatch')
    def dispatch(number):
        require('dispatch.confirm')
        doc=collection.find_one({'_id':number,'kind':'delivery',**scope()})
        if not doc:abort(404)
        if doc.get('fulfilment'): return jsonify(error='This Delivery Order already has a dispatch operation.'),409
        if doc.get('status')!='ready':return jsonify(error='The Delivery Order must be ready before dispatch.'),409
        store=app.extensions['inventory_platform'];plans=[]
        try:
            for index,item in enumerate(doc['items']):
                qty=Decimal(item['quantity'])
                if qty!=qty.to_integral_value() or qty<=0: raise ValueError('Dispatch quantities must be positive whole units.')
                product=products.find_one({'uid':item['uid']})
                if not product: raise ValueError('Inventory product not found: '+item['uid'])
                from inventory_platform.domain import stock_state
                state=stock_state(product);amount=int(qty);location=item.get('location','')
                slot='a' if location and location==state['location_a'] else 'b' if location and location==state['location_b'] else None
                if not slot: raise ValueError('Select a valid source location for every dispatched item.')
                if state[slot] is None or state[slot]<amount or state['total']<amount: raise ValueError('Insufficient stock for '+item['uid']+'.')
                after={**state,slot:state[slot]-amount,'total':state['total']-amount};event_id=str(uuid5(UUID('f2d70876-5b03-4c98-880f-f247b641675d'),number+':'+str(index)))
                plans.append((product,state,after,event_id))
        except Exception as exc:return jsonify(error=str(exc)),400
        def work(kw):
            for product,state,after,event_id in plans:
                store.change(product['uid'],{'event_id':event_id,'revision':product.get('stock_revision',0),'mode':'set','a':after['a'],'b':after['b'],'total':after['total'],'location_a':after['location_a'],'location_b':after['location_b'],'reason':'issued','reference':number,'note':'Delivery Order dispatch'}, {'id':str(session.get('user_id') or session['username']),'username':session['username']},transaction=kw)
            stamp=now();result=collection.update_one({'_id':number,'revision':doc['revision'],'fulfilment':{'$exists':False}},{'$set':{'fulfilment':{'status':'pending','event_ids':[p[3] for p in plans],'operation_id':number+':dispatch'},'updated_at':stamp},'$inc':{'revision':1},'$push':{'history':{'action':'dispatch_pending','at':stamp,'by':session['username']}}},**kw)
            if not result.matched_count:raise RuntimeError('Delivery Order changed before dispatch could be queued.')
            audit('delivery_dispatch_pending',number,after={'event_ids':[p[3] for p in plans]},transaction=kw)
        try:store.transact(work)
        except Exception as exc:return jsonify(error=str(exc)),409
        return jsonify(message='Dispatch queued. It remains pending until Access confirms every stock write.',event_ids=[p[3] for p in plans]),202
    @bp.get('/api/products')
    def search_products():
        search=request.args.get('q','').strip()[:120]
        if not search:return jsonify([])
        tokens=re.findall(r'[A-Za-z0-9]+',search);fields=('uid','Part_id','name','Desc','readable_id','Mssid')
        query={'$and':[{'$or':[{field:re.compile(re.escape(token),re.I)} for field in fields]} for token in tokens]} if tokens else {}
        rows=products.find(query,{field:1 for field in fields}).limit(20)
        return jsonify([{'uid':str(row.get('uid') or row.get('Part_id') or ''),'description':str(row.get('name') or row.get('Desc') or '')} for row in rows])

    @bp.get('/api/parties')
    def parties():
        """Reuse local contact masters and accessible document snapshots."""
        kind=request.args.get('kind','proforma')
        if kind not in ('delivery','proforma','quotation'):abort(404)
        rows=[];seen=set()
        def append(party,record_id,source):
            def pick(*keys):return next((str(party[k]).strip() for k in keys if party.get(k) not in (None,'')),'')
            name=pick('name','company_name','customer_name','merchant_name','Name','NAME')
            if not name:return
            address=pick('address','Address') or '\n'.join(filter(None,[pick('address1','address_1'),pick('address2','address_2'),pick('address3','address_3')]))
            row={'record_id':record_id,'name':name,'address':address,'contact':pick('contact','phone','telephone','Contact'),
                 'details':pick('details','registration','company_registration'),'source':source,
                 'customer_code':pick('customer_code'),'currency':pick('currency'),'terms':pick('terms'),
                 'shipping_name':pick('shipping_name') or name,'shipping_address':pick('shipping_address') or address,
                 'shipping_contact':pick('shipping_contact') or pick('contact','phone','telephone','Contact')}
            key=tuple(row[k].casefold() for k in ('name','address','contact','shipping_name','shipping_address','shipping_contact','customer_code'))
            if key not in seen:seen.add(key);rows.append(row)
        sources=('merchants','customers','document_parties') if kind=='delivery' else ('customers','merchants','document_parties')
        available=set(db.list_collection_names())
        for source in sources:
            if source in available:
                for row in db[source].find({}):append(row,source+':'+str(row['_id']),source)
        for doc in collection.find(scope(),{'party':1,'number':1}).sort('updated_at',-1):
            append(doc.get('party') or {},'document:'+str(doc['_id']),'Previous document')
        rows.sort(key=lambda row:row['name'].casefold())
        return jsonify(rows=rows)

    @bp.post('/api/parties')
    def save_party():
        require('documents.create')
        body=request.get_json() or {}
        try:party={k:clean(body.get(k,''),600,k=='name') for k in ('name','details','address','contact','shipping_name','shipping_address','shipping_contact')}
        except ValueError as exc:return jsonify(error=str(exc)),400
        identity={k:party[k] for k in party}
        existing=db.document_parties.find_one(identity)
        if existing:return jsonify(record_id='document_parties:'+str(existing['_id']))
        party.update(_id=str(uuid4()),created_at=now(),created_by=session['username'])
        db.document_parties.insert_one(party)
        audit('customer_saved',party['_id'],after={k:party[k] for k in ('name','address','contact')})
        return jsonify(record_id='document_parties:'+party['_id']),201
    @bp.get('/<kind>/<number>/pdf')
    def export(kind,number):
        doc=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not doc:abort(404)
        return send_file(pdf(doc),mimetype='application/pdf',as_attachment=True,download_name=number+'.pdf')
    @bp.get('/<kind>/<number>/print')
    def print_document(kind,number):
        doc=collection.find_one({'_id':number,'kind':kind,**scope()})
        if not doc:abort(404)
        return render_template('documents/print.html',doc=doc,meta=KINDS[kind])
    app.register_blueprint(bp)
