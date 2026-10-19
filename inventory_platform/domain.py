"""Stock invariants shared by the website and Windows worker."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

# Legacy values remain accepted so older pending requests can still be reviewed;
# the UI intentionally offers only the four current choices.
REASONS = {'received':'Stock received', 'issued':'Stock sold', 'correction':'Correction', 'other':'Other',
           'damaged':'Damaged stock', 'transfer':'Stock transfer', 'return':'Customer return'}
MOVEMENT_TYPES = ('SALE','STOCK_RECEIVED','STOCK_ADJUSTMENT','STOCK_TRANSFER',
                  'STOCK_RETURN','STOCK_CORRECTION','INITIAL_SNAPSHOT')
REASON_MOVEMENT_TYPES = {'issued':'SALE','received':'STOCK_RECEIVED','transfer':'STOCK_TRANSFER',
                         'return':'STOCK_RETURN','correction':'STOCK_CORRECTION',
                         'other':'STOCK_ADJUSTMENT','damaged':'STOCK_ADJUSTMENT'}
PERMISSIONS = ('stock.edit','stock.request','stock.approve','users.manage','sync.manage','settings.manage','forecast.manage','documents.view','documents.create','documents.edit','documents.approve','dispatch.confirm','stock.receive','audit.view')


class Invalid(ValueError): pass
class Conflict(ValueError): pass


def numeric(value, default=0):
    """Coerce legacy Mongo/Access quantities without breaking analytics."""
    if value is None or value == '': return default
    if hasattr(value,'to_decimal'): value=value.to_decimal()
    try:
        result=float(value)
        return int(result) if result.is_integer() else result
    except (TypeError,ValueError,ArithmeticError):
        return default


def movement_change(movement):
    """Return signed office-stock movement, including legacy records."""
    before=(movement.get('before') or {}).get('total')
    after=(movement.get('after') or {}).get('total')
    if before not in (None,'') and after not in (None,''):
        return numeric(after)-numeric(before)
    office=next((c for c in movement.get('changes',[]) if c.get('slot')=='Office' or c.get('location')=='Office total'),None)
    if office: return numeric(office.get('change'))
    return -numeric(movement.get('demand_units')) if str(movement.get('movement_type')).upper() in ('ISSUED','SALE') else 0


def movement_delta(movement):
    """Signed movement, or None when the historical evidence is incomplete."""
    before=(movement.get('before') or {}).get('total')
    after=(movement.get('after') or {}).get('total')
    if before not in (None,'') and after not in (None,''):
        return numeric(after)-numeric(before)
    previous=movement.get('previous_quantity'); current=movement.get('new_quantity')
    if previous not in (None,'') and current not in (None,''):
        return numeric(current)-numeric(previous)
    office=next((c for c in movement.get('changes',[]) if c.get('slot')=='Office' or c.get('location')=='Office total'),None)
    if office and office.get('change') not in (None,''): return numeric(office['change'])
    if str(movement.get('movement_type')).upper() in ('ISSUED','SALE') and movement.get('demand_units') not in (None,''):
        return -numeric(movement['demand_units'])
    return None


def movement_class(movement):
    """Canonical class. Manual corrections win; observed signed stock changes are inferred."""
    if movement.get('duplicate_of') or movement.get('is_duplicate'): return 'duplicate'
    explicit=str(movement.get('effective_classification') or movement.get('classification') or '').lower()
    if explicit in ('sold','sale'): return 'sale'
    if explicit in ('received','receipt'): return 'received'
    if explicit in ('external_adjustment','adjustment','correction'): return 'adjustment'
    if explicit in ('transfer','initial_snapshot','return'): return explicit
    kind=str(movement.get('movement_type') or movement.get('reason') or '').strip().upper()
    change=movement_delta(movement)
    if kind in ('SALE','ISSUED'): return 'sale'
    if kind in ('STOCK_RECEIVED','RECEIVED'): return 'received'
    if kind in ('STOCK_TRANSFER','TRANSFER'): return 'transfer'
    if kind in ('STOCK_RETURN','RETURN'): return 'return'
    if kind in ('INITIAL_SNAPSHOT',): return 'initial_snapshot'
    if kind in ('STOCK_CORRECTION','CORRECTION'): return 'adjustment'
    if kind=='OBSERVED_CORRECTION' or (kind=='STOCK_ADJUSTMENT' and movement.get('source')=='access'):
        before=movement.get('before') or {};after=movement.get('after') or {}
        location_changed=any(before.get(key)!=after.get(key) for key in ('location_a','location_b'))
        return 'sale' if change is not None and change<0 else ('received' if change is not None and change>0 else ('transfer' if location_changed else 'adjustment'))
    if kind in ('STOCK_ADJUSTMENT','OTHER','DAMAGED'): return 'adjustment'
    return 'adjustment' if change else 'other'


def movement_view(movement):
    """Human-readable facts and review flags without inventing missing quantities."""
    row=dict(movement); delta=movement_delta(row); kind=movement_class(row)
    before=(row.get('before') or {}).get('total'); after=(row.get('after') or {}).get('total')
    flags=[]
    if before in (None,'') or after in (None,''): flags.append('incomplete_history')
    if after not in (None,'') and numeric(after)<0: flags.append('negative_balance')
    if row.get('duplicate_of'): flags.append('possible_duplicate')
    if kind=='initial_snapshot': explanation='Initial import establishes a baseline and is not a sale or receipt.'
    elif delta is None: explanation='Previous snapshot unavailable; the movement amount cannot be confirmed.'
    elif kind=='transfer': explanation='Location changed without changing total inventory.'
    elif row.get('effective_classification'): explanation=row.get('classification_explanation') or 'Classification was reviewed manually; inventory quantity was not changed.'
    elif row.get('source')=='access':
        before_state=row.get('before') or {};after_state=row.get('after') or {}
        moved=any(before_state.get(key)!=after_state.get(key) for key in ('location_a','location_b'))
        explanation=('Access snapshot decreased; automatically classified as Sold.' if delta<0 else 'Access snapshot increased; automatically classified as Received.' if delta>0 else 'Access location changed without changing total inventory.' if moved else 'No net quantity or location change is visible in this legacy sync record; review and classify it if the business reason is known.')
        if delta==0 and not moved: flags.append('incomplete_history')
    else: explanation=row.get('note') or row.get('reason') or 'The quantity change is confirmed; its business cause was not supplied.'
    row.update(classification=kind,quantity_difference=delta,explanation=explanation,review_flags=flags,
               eligible_for_edit=kind!='initial_snapshot')
    return row


def canonical_movement_type(reason):
    if reason in MOVEMENT_TYPES: return reason
    try: return REASON_MOVEMENT_TYPES[reason]
    except KeyError: raise Invalid('Unsupported stock movement reason.') from None


def analytics_range(period, start='', end='', today=None):
    """Resolve named Malaysia business periods and their equivalent predecessor."""
    current=today or date.fromisoformat(business_date())
    if isinstance(current,str): current=date.fromisoformat(current)
    if period=='custom':
        try: first,last=date.fromisoformat(start),date.fromisoformat(end)
        except ValueError: raise Invalid('Custom dates must use YYYY-MM-DD.') from None
    elif period=='today': first=last=current
    elif period=='yesterday': first=last=current-timedelta(days=1)
    elif period in ('7','14','30','90','180','365'):
        last=current; first=last-timedelta(days=int(period)-1)
    elif period=='this_week': first=current-timedelta(days=current.weekday());last=current
    elif period=='this_month': first=current.replace(day=1);last=current
    elif period=='last_month':
        last=current.replace(day=1)-timedelta(days=1);first=last.replace(day=1)
    else: raise Invalid('Select a valid analytics period.')
    if last>current: raise Invalid('Future analytics dates are unavailable.')
    if first>last or (last-first).days>730: raise Invalid('Select a valid range of at most 731 days.')
    length=(last-first).days+1; previous_end=first-timedelta(days=1);previous_start=previous_end-timedelta(days=length-1)
    return first.isoformat(),last.isoformat(),previous_start.isoformat(),previous_end.isoformat()


def now(): return datetime.now(timezone.utc)
def stamp(): return now().isoformat()
def business_date(value=None): return (value or now()).astimezone(ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat()


def bounded_text(value, label, limit=200, required=False):
    if not isinstance(value,str) or len(value.strip()) > limit or (required and not value.strip()):
        raise Invalid(f'{label}: enter {"nonempty " if required else ""}text, at most {limit} characters.')
    if any(ord(c)<32 and c not in '\n\t' for c in value): raise Invalid(f'{label}: invalid characters.')
    return value.strip()


def integer(value, label, minimum=0, maximum=2_000_000_000):
    if isinstance(value,bool) or not re.fullmatch(r'-?\d{1,12}',str(value)):
        raise Invalid(f'{label} must be a whole number.')
    result=int(value)
    if not minimum<=result<=maximum: raise Invalid(f'{label} must be between {minimum} and {maximum}.')
    return result


def username(value):
    value=bounded_text(value,'Username',60,True)
    if any(c in value for c in '\n\t'): raise Invalid('Username must be on one line.')
    return value, value.casefold()


def stock_state(product):
    required=('stock_a','stock_b','stock','location_a','location_b')
    if any(k not in product for k in required):
        raise Conflict('This record has not been matched to Access yet. Its stock is read-only.')
    a=location_quantity(product['stock_a'],product['location_a'],'StockA')
    b=location_quantity(product['stock_b'],product['location_b'],'StockB')
    total=integer(product['stock'],'Stock_office',-2_000_000_000)
    return {'a':a,'b':b,'total':total,'location_a':str(product['location_a'] or ''),'location_b':str(product['location_b'] or '')}


def location_quantity(value, location, label):
    # A blank unused slot is absent, not zero. Preserve it on the round trip.
    if value is None and not str(location or '').strip(): return None
    return integer(value,label,-2_000_000_000)


def cloud_fields(state):
    return {'stock_a':state['a'],'stock_b':state['b'],'stock':state['total'],
            'location_a':state['location_a'],'location_b':state['location_b'],
            'locations':[{'slot':slot,'area':state['location_'+slot.lower()],'quantity':state[slot.lower()]}
                         for slot in ('A','B') if state['location_'+slot.lower()].strip()]}


def adjustment(product, data):
    before=stock_state(product)
    reason=data.get('reason')
    if reason not in REASONS: raise Invalid('Select a stock movement reason.')
    note=bounded_text(data.get('note',''),'Note',1000,reason=='other')
    mode=data.get('mode','set')
    if mode not in ('set','adjust'): raise Invalid('Select new quantities or adjustments.')
    locations={}
    for key in ('a','b'):
        old=before['location_'+key]
        proposed=bounded_text(data.get('location_'+key,old),'Location '+key.upper(),10)
        if old and proposed!=old: raise Invalid('Existing location names cannot be changed during a stock update.')
        locations[key]=proposed
    def entered(key):
        if before[key] is None:
            if not locations[key]:
                if data.get(key) not in (None,''): raise Invalid('Enter a location name before its quantity.')
                return None
            return integer(data.get(key),'Stock'+key.upper(),-2_000_000_000)
        value=integer(data.get(key,before[key] if mode=='set' else 0),'Stock'+key.upper(),-2_000_000_000)
        return integer(value+(before[key] if mode=='adjust' else 0),'New Stock'+key.upper(),-2_000_000_000)
    a=entered('a'); b=entered('b')
    total=integer(data.get('total',0 if mode=='adjust' else before['total']),'Stock_office',-2_000_000_000)
    if mode=='adjust': total+=before['total']
    total=integer(total,'New Stock_office',-2_000_000_000)
    after={**before,'a':a,'b':b,'total':total,'location_a':locations['a'],'location_b':locations['b']}
    deltas=[0 if a==before['a'] else a-(before['a'] or 0),0 if b==before['b'] else b-(before['b'] or 0),total-before['total']]
    location_changed=any(before['location_'+key]!=after['location_'+key] for key in ('a','b'))
    if deltas==[0,0,0] and not location_changed: raise Invalid('No stock quantities changed.')
    if reason=='transfer' and (deltas[0]+deltas[1]!=0 or not deltas[0] or not deltas[1] or deltas[2]!=0):
        raise Invalid('A transfer must move the same quantity between A and B without changing Stock_office.')
    if reason=='received' and any(d<0 for d in deltas): raise Invalid('Stock received cannot reduce stock.')
    if reason=='issued' and any(d>0 for d in deltas): raise Invalid('Stock sold cannot increase stock.')
    changes=[{'slot':slot,'location':after['location_'+slot.lower()], 'previous':before[key],
              'change':after[key]-(before[key] or 0), 'new':after[key],
              'location_added':not before['location_'+slot.lower()] and bool(after['location_'+slot.lower()])}
             for slot,key in (('A','a'),('B','b'))
             if before[key]!=after[key] or before['location_'+slot.lower()]!=after['location_'+slot.lower()]]
    if any(not c['location'] for c in changes): raise Invalid('A changed stock slot must have a confirmed location.')
    if before['total']!=after['total']:
        changes.append({'slot':'Office','location':'Office total','previous':before['total'],
                        'change':after['total']-before['total'],'new':after['total']})
    return before,after,changes,reason,note


def access_product(row):
    """Keep unused slots blank and office stock independent of location quantities."""
    r={str(k).strip().casefold():v for k,v in row.items()}
    def required(k):
        if k not in r or r[k] is None: raise Invalid(f'Access is missing {k}.')
        return r[k]
    for key in ('stocka','stockb'):
        if key not in r: raise Invalid(f'Access is missing {key}.')
    a=location_quantity(r['stocka'],r.get('loc_film_box'),'StockA')
    b=location_quantity(r['stockb'],r.get('loc_wh'),'StockB')
    total=integer(required('stock_office'),'Stock_office',-2_000_000_000)
    state={'a':a,'b':b,'total':total,'location_a':str(r.get('loc_film_box') or ''), 'location_b':str(r.get('loc_wh') or '')}
    return {'uid':str(required('part_id')).strip(),'name':str(r.get('desc') or ''),'readable_id':str(r.get('mssid') or ''),
            'category':str(r.get('cat') or 'Uncategorized'),'supplier':str(r.get('supplr') or ''),'vendor_cd':str(r.get('vendor-cd') or r.get('vendor_cd') or ''), **cloud_fields(state)}
