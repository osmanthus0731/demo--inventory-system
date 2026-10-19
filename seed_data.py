"""Deterministic fictional history; never imports or copies operational records."""
from datetime import date, timedelta
from random import Random
from inventory_platform.domain import cloud_fields, business_date
from inventory_platform.forecasting import refresh


def seed(db):
    db.inventory_settings.insert_one({'_id':'company','values':{
        'name':'Meadow Demo Co.','registration':'DEMO-ONLY',
        'address':'10 Imaginary Lane, Demo Town, Example Country',
        'telephone':'000-0000000','fax':'000-0000000','email':'hello@example.com'}})
    db.customers.insert_one({'_id':'fictional-customer','customer_code':'DEMO-C01',
        'name':'Imaginary Botanicals','details':'Fictional customer for demonstration',
        'address':'10 Example Street\nDemo Town','contact':'Alex (Demo)',
        'currency':'MYR','terms':'30 days'})
    db.suppliers.insert_one({'_id':'fictional-supplier','supplier_code':'DEMO-S01',
        'name':'Imaginary Packaging Co.','details':'20 Sample Road\nDemo Town',
        'attention':'Sam (Demo)','fax':'','currency':'MYR','terms':'30 days'})
    rng=Random(1729)
    today=date.fromisoformat(business_date()); start=today-timedelta(days=210)
    db.platform_meta.insert_many([{'_id':'users_ready','ready':True},{'_id':'collection_started','date':start.isoformat()}])
    for name,role in [('Maya','admin'),('Noah','admin'),('Eli','worker')]:
        db.users.insert_one({'_id':name,'username':name,'username_key':name.lower(),'display_name':name+' (Demo)',
            'role':role,'active':True,'account_revision':0,'created_at':start.isoformat()})
    for i in range(210): db.business_days.insert_one({'_id':(start+timedelta(days=i)).isoformat(),'complete':True,'note':'Synthetic demo day'})
    names=['Luma Airless Pump 30ml','Aster Glass Jar 50ml','Nori Mist Bottle 100ml',
           'Solstice Dropper 15ml','Cove Travel Tube 75ml','Juniper Lotion Pump 250ml']
    for index,name in enumerate(names):
        uid=f'DEMO-{index+1:03d}'; balance=2200; events=[]
        for i in range(210):
            day=(start+timedelta(days=i)).isoformat()
            demand=max(0,8+index*3+int(i/35)+rng.randint(-4,4)+(5 if i%7<5 else -4))
            if index==3 and i%5: demand=0
            for kind,amount in ([('received',1200)] if balance<150 else [])+[('issued',demand)]:
                if not amount: continue
                previous=balance;balance+=amount if kind=='received' else -amount
                event_id=f'demo:{uid}:{day}:{kind}'
                events.append({'_id':event_id,'event_id':event_id,'uid':uid,'product_name':name,'category':'Demo packaging',
                    'supplier':'Imaginary Packaging Co.','business_date':day,'timestamp':day+'T08:00:00+00:00',
                    'user_id':'Eli','username':'Eli','source':'website','movement_type':kind,'reason':kind,
                    'before':{'total':previous},'after':{'total':balance},'changes':[{'slot':'Office','location':'Office total',
                    'previous':previous,'change':balance-previous,'new':balance}],
                    'demand_units':amount if kind=='issued' else 0,'reference':f'DEMO-{i:03d}',
                    'note':'Fictional demonstration record','sync_status':'synced','approval':{'user_id':'Maya','username':'Maya'}})
        db.stock_movements.insert_many(events)
        # The current demo count is independent from either location quantity.
        total=35+index*25
        state={'a':total if index%2==0 else None,'b':None if index%2==0 else total,
               'total':total,'location_a':f'DEMO{index+1}' if index%2==0 else '',
               'location_b':'' if index%2==0 else f'DEMO{index+1}'}
        db.products.insert_one({'uid':uid,'readable_id':f'FICTIONAL-{index+1}','name':name,'category':'Demo packaging',
            'supplier':'Imaginary Packaging Co.','volume_ml':[30,50,100,15,75,250][index],**cloud_fields(state),
            'stock_revision':0,'access_confirmed':state,'access_sync_eligible':True,'sync_status':'synced'})
        for code,multiplier in [('P',1),('S',2)]:
            db.pricing.insert_one({'part_id':uid,'pricecd':code,'S12':round((1.2+index*.25)*multiplier,4),
                'S100':round((1+index*.25)*multiplier,4),
                **{tier:round((base+index*.25)*multiplier,4) for tier,base in [('S500',.95),('1K',.9),('3K',.85),('5K',.8),('10K',.75)]},
                'currency':'MYR'})
        db.inventory_settings.insert_one({'_id':'product:'+uid,'lead_time':7,'review_period':7,'minimum_order':50,
            'order_multiple':25,'confirmed_incoming':0,'committed_outgoing':0,'reorder_threshold':100})
        db.stock_movements.insert_one({'_id':'demo:count:'+uid,'event_id':'demo:count:'+uid,'uid':uid,'product_name':name,
            'business_date':today.isoformat(),'timestamp':today.isoformat()+'T00:00:00+00:00','user_id':'access-service',
            'username':'Microsoft Access (simulated)','source':'access','movement_type':'observed_correction',
            'reason':'Simulated Access count','changes':[{'slot':'Office','location':'Office total','previous':balance,'change':total-balance,'new':total}],
            'before':{'total':balance},'after':state,'demand_units':0,'reference':'DEMO-COUNT','note':'Fictional data','sync_status':'synced'})
    refresh(db)
