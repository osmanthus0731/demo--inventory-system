"""Password-free selection with stable identities, explicit roles and safe migrations."""
from datetime import datetime, timezone
from uuid import uuid4
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .domain import username, bounded_text, stamp, Conflict, Invalid, PERMISSIONS
import re
from urllib.parse import urlsplit
from werkzeug.security import generate_password_hash


def login_appearance(data):
    """Only publish validated appearance values on the account picker."""
    result={}
    for key,default in (('slide_color','#c8d7bb'),('highlight_color','#586f48')):
        value=data.get(key,default)
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
            raise ValueError('Choose a valid slide and highlight colour.')
        result[key]=value
    wallpaper=data.get('wallpaper','').strip()
    if len(wallpaper)>2048:raise ValueError('Wallpaper URL is too long.')
    if wallpaper:
        parsed=urlsplit(wallpaper)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an HTTPS image URL, or leave it empty for the meadow.')
    result['wallpaper']=wallpaper
    flower=data.get('flower_style','cosmos')
    if flower not in ('cosmos','freesia','daisy','cherry'):
        raise ValueError('Choose Cosmos, Freesia, Daisy or Cherry blossom.')
    result['flower_style']=flower
    return result


def public_appearance(user):
    try:return login_appearance(user.get('login_appearance') or {})
    except (ValueError,TypeError,AttributeError):return login_appearance({})

INITIAL_USERS=('sg','szee foon','tommy','HK','MsT','Admin')


def find_user(db, user_id=None, name=None):
    if user_id:
        ids=[user_id]
        if ObjectId.is_valid(user_id): ids.append(ObjectId(user_id))
        return db.users.find_one({'_id':{'$in':ids}})
    if not name: return None
    key=name.casefold()
    matches=[u for u in db.users.find({}) if str(u.get('username','')).casefold()==key]
    return matches[0] if len(matches)==1 else None


def public_user(u):
    return {'id':str(u['_id']),'username':u.get('username',''),'display_name':u.get('display_name') or u.get('full_name') or u.get('username',''),
            'role':u.get('role','worker'),'active':u.get('active',True),'created_at':u.get('created_at'),
            'last_login':u.get('last_login'),'revision':u.get('account_revision',0),'login_appearance':public_appearance(u),
            'profile_picture':u.get('profile_picture','') if re.fullmatch(r'data:image/jpeg;base64,[A-Za-z0-9+/=]{1,100000}',str(u.get('profile_picture',''))) else '',
            'has_custom_appearance':bool(u.get('login_appearance')),'has_pin':bool(u.get('pin_hash'))}


def migrate_users(db, apply=False, create_initial=True):
    existing=list(db.users.find({})); keys={}
    for u in existing:
        display,key=username(u.get('username',''))
        if key in keys: raise Conflict('Case-insensitive username collisions exist. Resolve them explicitly before migration.')
        keys[key]=u
    missing=[name for name in INITIAL_USERS if name.casefold() not in keys] if create_initial else []
    plan={'existing':len(existing),'create':missing,'apply':apply}
    if not apply: return plan
    # Intended for a maintenance window; web writes stay gated until this finishes.
    db.users.create_index('username_key',unique=True,partialFilterExpression={'username_key':{'$type':'string'}})
    for u in existing:
        name,key=username(u['username'])
        updates={'username_key':key,'active':u.get('active',True),'account_revision':u.get('account_revision',0)}
        if 'created_at' not in u: updates['created_at']=None  # unknown historical creation date is not invented
        db.users.update_one({'_id':u['_id']},{'$set':updates})
    for name in missing:
        db.users.insert_one({'_id':str(uuid4()),'username':name,'username_key':name.casefold(),'display_name':name,
                             'role':'admin','active':True,'created_at':stamp(),'account_revision':0})
    db.platform_meta.update_one({'_id':'users_ready'},{'$set':{'ready':True,'at':stamp()}},upsert=True)
    return plan


def permissions(db,user):
    config=db.inventory_settings.find_one({'_id':'permissions'}) or {}
    roles=config.get('roles',{'admin':list(PERMISSIONS),'worker':[]})
    result=set(roles.get(user.get('role','worker'),[])) & set(PERMISSIONS)
    # Permission documents saved before the business-document upgrade have no
    # entries for its capabilities. Preserve administrator access until the
    # expanded matrix is explicitly saved.
    if user.get('role')=='admin' and config and not config.get('document_permissions_migrated'):
        result.update({'documents.view','documents.create','documents.edit','documents.approve','dispatch.confirm','stock.receive','audit.view'})
    result.add('stock.request')
    if user.get('role')=='admin': result.add('stock.approve')
    else: result.discard('stock.approve')
    return result


def save_user(store, data, actor, user_id=None, require_pin=True):
    db=store.db
    if not db.platform_meta.find_one({'_id':'users_ready','ready':True}):
        raise Conflict('Run the reviewed user migration before managing accounts.')
    name,key=username(data.get('username',''))
    role=data.get('role','admin')
    if role not in ('admin', 'worker'):
        raise Invalid('Choose Admin or Worker.')
    active=data.get('active',True)
    if type(active) is not bool: raise Invalid('Active must be true or false.')
    display=bounded_text(data.get('display_name',name),'Display name',100,True)
    pin=str(data.get('pin') or '').strip()
    if pin and not re.fullmatch(r'\d{4,8}',pin): raise Invalid('PIN must contain 4 to 8 digits.')
    if not user_id and db.users.find_one({'username_key':key}): raise Conflict('That username already exists (case-insensitive).')
    new_id=str(uuid4())
    def work(kw):
        # Serialize last-admin changes within the transaction to avoid write skew.
        db.inventory_settings.update_one({'_id':'user_admin_lock'},{'$inc':{'revision':1}},upsert=True,**kw)
        old=None
        if user_id:
            ids=[user_id]+([ObjectId(user_id)] if ObjectId.is_valid(user_id) else [])
            old=db.users.find_one({'_id':{'$in':ids}},**kw)
            if not old or old.get('deleted'): raise Invalid('Account not found.')
            if data.get('revision')!=old.get('account_revision',0): raise Conflict('Account changed. Refresh before saving.')
            if old.get('role')=='admin' and old.get('active',True) and (role!='admin' or not active):
                if db.users.count_documents({'role':'admin','active':{'$ne':False}},**kw)<=1:
                    raise Invalid('Keep at least one active administrator.')
        values={'username':name,'username_key':key,'display_name':display,'role':role,'active':active,
                'updated_at':stamp(),'account_revision':(old or {}).get('account_revision',-1)+1}
        if pin: values['pin_hash']=generate_password_hash(pin)
        if require_pin and not old and not pin: raise Invalid('Set a 4 to 8 digit PIN for the new account.')
        if old:
            aliases=list(dict.fromkeys(old.get('username_aliases',[])+[old['username']]))
            values['username_aliases']=aliases
            db.users.update_one({'_id':old['_id']},{'$set':values},**kw)
            result={**old,**values}
        else:
            result={'_id':new_id,'created_at':stamp(),**values}
            db.users.insert_one(result,**kw)
        db.audit_events.insert_one({'_id':str(uuid4()),'action':'user_updated' if old else 'user_created',
            'timestamp':stamp(),'user_id':actor['id'],'username':actor['username'],'target_user_id':str(result['_id']),
            'before':public_user(old) if old else None,'after':public_user(result)},**kw)
        return public_user(result)
    try: return store.transact(work)
    except DuplicateKeyError: raise Conflict('That username already exists (case-insensitive).') from None


def delete_user(store, user_id, revision, actor):
    """Revoke access while retaining stable identities in the audit ledger."""
    if user_id==actor['id']: raise Invalid('You cannot delete your own account.')
    def work(kw):
        db=store.db
        db.inventory_settings.update_one({'_id':'user_admin_lock'},{'$inc':{'revision':1}},upsert=True,**kw)
        ids=[user_id]+([ObjectId(user_id)] if ObjectId.is_valid(user_id) else [])
        old=db.users.find_one({'_id':{'$in':ids}},**kw)
        if not old or old.get('deleted'): raise Invalid('Account not found.')
        if revision!=old.get('account_revision',0): raise Conflict('Account changed. Refresh before deleting.')
        if old.get('role')=='admin' and old.get('active',True):
            if db.users.count_documents({'role':'admin','active':{'$ne':False},'deleted':{'$ne':True}},**kw)<=1:
                raise Invalid('Keep at least one active administrator.')
        ts=stamp()
        db.users.update_one({'_id':old['_id']},{'$set':{'active':False,'deleted':True,'deleted_at':ts,
            'deleted_by':actor['id']},'$inc':{'account_revision':1}},**kw)
        db.stock_requests.update_many({'requested_by':user_id,'status':'pending'},
            {'$set':{'status':'cancelled','review_note':'Requester account deleted.','reviewed_at':ts},'$inc':{'revision':1}},**kw)
        db.audit_events.insert_one({'_id':str(uuid4()),'action':'user_deleted','timestamp':ts,
            'user_id':actor['id'],'username':actor['username'],'target_user_id':user_id,'before':public_user(old)},**kw)
        return {'message':'Account deleted. Historical records are preserved.'}
    return store.transact(work)
