"""Windows bridge. Access schema stays unchanged; absolute conditional writes are idempotent."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from .domain import stock_state, access_product, Conflict, Invalid, stamp

FIELDS=('Part_id','Desc','Mssid','Stock_office','Loc_film_box','StockA','Loc_wh','StockB','Cat','Supplr')


def dao_rows(path,table):
    """Yield dictionaries from a local Access table through native DAO."""
    if not str(table).replace('_','').isalnum(): raise Invalid('Invalid Access table name.')
    adapter=DaoAccessAdapter(path)
    engine=db=recordset=None
    try:
        engine,db=adapter._open()
        recordset=db.OpenRecordset(f'SELECT * FROM [{table}]',4)
        names=[recordset.Fields(i).Name for i in range(recordset.Fields.Count)]
        while not recordset.EOF:
            yield {name:recordset.Fields(name).Value for name in names}
            recordset.MoveNext()
    finally:
        if recordset is not None: recordset.Close()
        if db is not None: db.Close()


class AccessAdapter:
    def __init__(self,path,write_enabled=False,connect=None):
        if connect is None:
            import pyodbc
            connect=pyodbc.connect
        self.path=Path(path).resolve();self.write_enabled=write_enabled;self.connect=connect

    def connection(self,write=False):
        if write and not self.write_enabled: raise Invalid('Access write-back is disabled.')
        if not self.path.is_file(): raise Invalid('Access file is unavailable.')
        return self.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ='+str(self.path)+(';' if write else ';READONLY=TRUE;'),autocommit=False,timeout=10)

    @staticmethod
    def mapped(cursor,row):
        return access_product(dict(zip([c[0] for c in cursor.description],row)))

    def read(self,uid):
        cn=self.connection()
        try:
            cur=cn.cursor();cur.execute('SELECT '+','.join('['+f+']' for f in FIELDS)+' FROM [ITMMST] WHERE [Part_id]=?',uid)
            rows=cur.fetchmany(2)
            if len(rows)!=1: raise Conflict('Expected exactly one Access record for this UID.')
            return self.mapped(cur,rows[0])
        finally: cn.close()

    def scan(self):
        cn=self.connection()
        try:
            cur=cn.cursor();cur.execute('SELECT * FROM [ITMMST]')
            for row in cur:
                try: yield self.mapped(cur,row)
                except (Conflict,Invalid) as exc: yield {'uid':str(row[0]),'error':str(exc)}
        finally: cn.close()

    def compare_and_set(self,uid,before,after):
        cn=self.connection(True)
        try:
            cur=cn.cursor()
            quantity_fields=(('StockA','a'),('StockB','b'),('Stock_office','total'))
            fields=quantity_fields+(('Loc_film_box','location_a'),('Loc_wh','location_b'))
            changed=[(field,key) for field,key in fields if before[key]!=after[key]]
            if not changed: return
            values=[after[key] for _,key in changed]+[uid]
            conditions=[]
            for field,key in quantity_fields:
                conditions.append(f'[{field}] IS NULL' if before[key] is None else f'[{field}]=?')
                if before[key] is not None: values.append(before[key])
            sql=('UPDATE [ITMMST] SET '+','.join(f'[{field}]=?' for field,_ in changed)+' WHERE [Part_id]=? AND '+
                 ' AND '.join(conditions)+' '
                 'AND ([Loc_film_box]=? OR ([Loc_film_box] IS NULL AND ?=\'\')) '
                 'AND ([Loc_wh]=? OR ([Loc_wh] IS NULL AND ?=\'\'))')
            cur.execute(sql,*(values+[before['location_a'],before['location_a'],before['location_b'],before['location_b']]))
            if cur.rowcount!=1: raise Conflict('Access changed before the conditional write; no overwrite was applied.')
            cur.execute('SELECT '+','.join('['+f+']' for f in FIELDS)+' FROM [ITMMST] WHERE [Part_id]=?',uid)
            rows=cur.fetchmany(2)
            if len(rows)!=1 or stock_state(self.mapped(cur,rows[0]))!=after: raise Conflict('Access read-back did not match the intended update.')
            cn.commit()
        except Exception:
            cn.rollback();raise
        finally: cn.close()


def _dao_text(value):
    """Access SQL literal for identifiers/locations already validated by the domain layer."""
    return "'"+str(value or '').replace("'", "''")+"'"


class DaoAccessAdapter:
    """Native Windows DAO bridge for legacy Jet files that the ACE ODBC driver cannot open."""
    def __init__(self,path,write_enabled=False):
        self.path=Path(path).resolve();self.write_enabled=write_enabled

    def _open(self,write=False):
        if write and not self.write_enabled: raise Invalid('Access write-back is disabled.')
        if not self.path.is_file(): raise Invalid('Access file is unavailable.')
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        engine=Dispatch('DAO.DBEngine.120')
        return engine,engine.OpenDatabase(str(self.path),False,not write)

    @staticmethod
    def _row(recordset):
        return access_product({recordset.Fields(i).Name:recordset.Fields(i).Value for i in range(recordset.Fields.Count)})

    def read(self,uid):
        engine=db=recordset=None
        try:
            engine,db=self._open()
            sql='SELECT '+','.join('['+f+']' for f in FIELDS)+' FROM [ITMMST] WHERE [Part_id]='+_dao_text(uid)
            recordset=db.OpenRecordset(sql,4)
            if recordset.EOF: raise Conflict('Expected exactly one Access record for this UID.')
            value=self._row(recordset);recordset.MoveNext()
            if not recordset.EOF: raise Conflict('Expected exactly one Access record for this UID.')
            return value
        finally:
            if recordset is not None: recordset.Close()
            if db is not None: db.Close()

    def scan(self):
        engine=db=recordset=None
        try:
            engine,db=self._open()
            recordset=db.OpenRecordset('SELECT * FROM [ITMMST]',4)
            while not recordset.EOF:
                try: yield self._row(recordset)
                except (Conflict,Invalid) as exc: yield {'uid':str(recordset.Fields('Part_id').Value),'error':str(exc)}
                recordset.MoveNext()
        finally:
            if recordset is not None: recordset.Close()
            if db is not None: db.Close()

    def compare_and_set(self,uid,before,after):
        engine=db=None
        try:
            engine,db=self._open(True)
            quantity_fields=(('StockA','a'),('StockB','b'),('Stock_office','total'))
            fields=quantity_fields+(('Loc_film_box','location_a'),('Loc_wh','location_b'))
            changed=[(field,key) for field,key in fields if before[key]!=after[key]]
            if not changed: return
            assignments=','.join(f'[{field}]={_dao_text(after[key])}' if key.startswith('location_') else f'[{field}]={int(after[key])}' for field,key in changed)
            conditions=' AND '.join(f'[{field}] IS NULL' if before[key] is None else f'[{field}]={int(before[key])}' for field,key in quantity_fields)
            sql=(f'UPDATE [ITMMST] SET {assignments} WHERE [Part_id]={_dao_text(uid)} AND {conditions} '
                 f'AND ([Loc_film_box]={_dao_text(before["location_a"])} OR ([Loc_film_box] IS NULL AND {_dao_text(before["location_a"])}=\'\')) '
                 f'AND ([Loc_wh]={_dao_text(before["location_b"])} OR ([Loc_wh] IS NULL AND {_dao_text(before["location_b"])}=\'\'))')
            db.Execute(sql,128)
            if db.RecordsAffected!=1: raise Conflict('Access changed before the conditional write; no overwrite was applied.')
            db.Close();db=None
            if stock_state(self.read(uid))!=after: raise Conflict('Access read-back did not match the intended update.')
        finally:
            if db is not None: db.Close()

class Journal:
    def __init__(self,path):
        self.path=str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as cn:
            cn.execute('PRAGMA journal_mode=WAL')
            cn.execute('CREATE TABLE IF NOT EXISTS receipts (event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL)')

    def prepare(self,event):
        fingerprint=sha256(json.dumps({'before':event['before'],'after':event['after']},sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.path) as cn:
            prior=cn.execute('SELECT fingerprint,state FROM receipts WHERE event_id=?',(event['_id'],)).fetchone()
            if prior and prior[0]!=fingerprint:
                if prior[1]=='committed': raise Conflict('A committed local receipt differs from the reviewed event.')
                cn.execute('DELETE FROM receipts WHERE event_id=?',(event['_id'],))
            cn.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,?)',(event['_id'],fingerprint,'prepared'))

    def committed(self,event):
        with sqlite3.connect(self.path) as cn: cn.execute('UPDATE receipts SET state=? WHERE event_id=?',('committed',event['_id']))


class Worker:
    def __init__(self,store,access,journal): self.store=store;self.db=store.db;self.access=access;self.journal=journal

    def process(self,event):
        if not self.access.write_enabled: return 'disabled'
        # Earlier unresolved versions always block later versions for the same product.
        earlier=self.db.sync_events.find_one({'uid':event['uid'],'version':{'$lt':event['version']},'status':{'$ne':'synced'}})
        if earlier: return 'blocked'
        actual=None
        try:
            self.journal.prepare(event)
            actual=stock_state(self.access.read(event['uid']))
            if actual==event['after']:
                # Ambiguous previous commit: acknowledge matching absolute target without applying any delta.
                self.journal.committed(event);self.store.acknowledge(event,'reconciled_matching_values');return 'synced'
            if actual!=event['before']:
                self.store.flag(event,'conflict','Access differs from the expected confirmed snapshot.',actual);return 'conflict'
            self.access.compare_and_set(event['uid'],event['before'],event['after'])
            self.journal.committed(event)
            if stock_state(self.access.read(event['uid']))!=event['after']:
                self.store.flag(event,'conflict','Access changed after commit; reconcile manually.',stock_state(self.access.read(event['uid'])));return 'conflict'
            self.store.acknowledge(event);return 'synced'
        except Conflict as exc:
            self.store.flag(event,'conflict',str(exc),actual);return 'conflict'
        except Exception:
            # Do not log connection strings or Access data. Durable receipt permits safe retry.
            self.store.flag(event,'failed','Write/acknowledgement failed; retry will verify Access before applying anything.',actual)
            raise

    def cycle(self,scan_access=True):
        started=datetime.now(timezone.utc)
        control=self.db.inventory_sync_control
        control.update_one({'_id':'worker'},{'$set':{'heartbeat':stamp(),'access':'Connected',
            'mongo':'Connected','phase':'processing_queue','writeback_enabled':self.access.write_enabled}},upsert=True)
        for event in self.db.sync_events.find({'status':{'$in':['pending','failed']}}).sort([('created_at',1),('version',1)]).limit(100):
            if event.get('attempts',0)>=10: continue  # explicit admin retry required after repeated failures
            self.process(event)
        values={'heartbeat':stamp(),'access':'Connected','mongo':'Connected','last_success':stamp(),
                'duration_seconds':(datetime.now(timezone.utc)-started).total_seconds(),'writeback_enabled':self.access.write_enabled}
        if scan_access:
            count=0; changed=0; skipped=0; problems=[]
            # One projection query replaces thousands of unchanged per-product
            # transactions while still comparing every Access row.
            known={p['uid']:(p.get('access_confirmed'),p.get('access_sync_eligible',False))
                   for p in self.db.products.find({'uid':{'$exists':True}},{'uid':1,'access_confirmed':1,'access_sync_eligible':1})}
            control.update_one({'_id':'worker'},{'$set':{'heartbeat':stamp(),'phase':'scanning_access',
                'scan_started':stamp(),'scan_progress':0}})
            for mapped in self.access.scan():
                if mapped.get('error'): problems.append({'uid':mapped['uid'],'error':mapped['error']});continue
                try:
                    prior=known.get(mapped['uid'])
                    if prior and prior[0]==stock_state(mapped) and prior[1]:
                        self.db.products.update_one({'uid':mapped['uid']},{'$set':{'vendor_cd':mapped.get('vendor_cd','')}});skipped+=1
                    else: self.store.observe(mapped);changed+=1
                    count+=1
                except (Invalid,Conflict) as exc: problems.append({'uid':mapped['uid'],'error':str(exc)})
                if count and count % 100 == 0:
                    control.update_one({'_id':'worker'},{'$set':{'heartbeat':stamp(),'scan_progress':count}})
            values.update(observed_products=count,changed_products=changed,unchanged_products=skipped,
                          baseline_conflicts=problems[:100],baseline_conflict_count=len(problems),last_access_scan=stamp(),scan_progress=count)
        values['duration_seconds']=(datetime.now(timezone.utc)-started).total_seconds()
        values.update(phase='idle')
        control.update_one({'_id':'worker'},{'$set':values},upsert=True)


def staging_allowed(config,path):
    """Production write-back needs an explicitly supplied staging report bound to this database path."""
    if config.get('ACCESS_WRITEBACK_ENABLED')!='1': return False
    if config.get('SYNC_ENVIRONMENT')=='staging':
        source=config.get('PRODUCTION_ACCESS_PATH')
        if not source or Path(source).resolve()==Path(path).resolve():
            raise Invalid('Staging must use a separate Access copy and name the production path.')
        return True
    receipt_path=config.get('ACCESS_STAGING_RECEIPT')
    if not receipt_path: raise Invalid('Production write-back requires a successful staging receipt.')
    receipt=json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    required=('access_roundtrip','crash_recovery','conflicts','offline_reconnect','restart_recovery')
    if Path(receipt.get('production_path','')).resolve()!=Path(path).resolve() or not all(receipt.get(k) is True for k in required):
        raise Invalid('Staging receipt is incomplete or belongs to another Access database.')
    return True
