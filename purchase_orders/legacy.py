"""Reserve document references in the legacy counters used by Access."""
from inventory_platform.sync import DaoAccessAdapter
from inventory_platform.domain import integer


def reserve_counter(path, field):
    if field not in ("nextpo", "nextdo"): raise ValueError("Unsupported legacy counter.")
    adapter=DaoAccessAdapter(path,write_enabled=True)
    engine=db=recordset=None
    active=False
    try:
        engine,db=adapter._open(True)
        workspace=engine.Workspaces(0)
        workspace.BeginTrans();active=True
        recordset=db.OpenRecordset(f'SELECT [ID],[{field}] FROM [DOSETUP]',4)
        if recordset.EOF: raise ValueError('DOSETUP has no document counter.')
        row_id=integer(recordset.Fields('ID').Value,'DOSETUP ID')
        value=integer(recordset.Fields(field).Value,field,1,1_999_999_999)
        recordset.MoveNext()
        if not recordset.EOF: raise ValueError('DOSETUP has multiple counters; select the correct setup row before issuing POs.')
        recordset.Close();recordset=None
        db.Execute(f'UPDATE [DOSETUP] SET [{field}]={value+1} WHERE [ID]={row_id} AND [{field}]={value}',128)
        if db.RecordsAffected!=1: raise ValueError('The legacy counter changed concurrently. Retry finalisation.')
        workspace.CommitTrans(1);active=False
        return str(value)
    finally:
        if active: workspace.Rollback()
        if recordset is not None: recordset.Close()
        if db is not None: db.Close()


def reserve_po(path):
    return reserve_counter(path,'nextpo')


def reserve_do(path):
    return reserve_counter(path,'nextdo')


class NumberingConflict(ValueError): pass


def numbered_transition(collection,query,update,reserve,claims_name):
    """Serialize finalisation before touching Access; drafts never call the counter."""
    from uuid import uuid4
    from pymongo import ReturnDocument
    from pymongo.errors import DuplicateKeyError
    lock=str(uuid4())
    locked=collection.find_one_and_update({**query,'numbering_lock':{'$exists':False}}, {'$set':{'numbering_lock':lock}},return_document=ReturnDocument.AFTER)
    if not locked: raise NumberingConflict('Document changed or is being finalised. Refresh before continuing.')
    locked_query={'_id':locked['_id'],'numbering_lock':lock}
    try:
        if not locked.get('legacy_number'):
            reserved=reserve()
            if reserved is not None:
                if collection.find_one({'legacy_number':reserved}):raise NumberingConflict('This legacy number was already issued. Check the Access counter.')
                try:collection.database.get_collection(claims_name).insert_one({'_id':reserved,'document':locked['_id']})
                except DuplicateKeyError:raise NumberingConflict('This legacy number was already issued. Check the Access counter.') from None
                # Retain a committed reservation if a later write must be retried.
                collection.update_one(locked_query,{'$set':{'legacy_number':reserved}})
        return collection.update_one(locked_query,update)
    finally:
        collection.update_one(locked_query,{'$unset':{'numbering_lock':''}})
