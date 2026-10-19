"""Persistent fictional demo data shared by serverless workers."""
import re
import certifi
import mongomock
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

SEED_MARKER='fictional_demo_seed_v1'


def connect_demo(uri, name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]*demo[a-zA-Z0-9_-]*',name,re.I):
        raise RuntimeError('DEMO_MONGO_DB must contain demo (for example meadow_demo).')
    tls={'tls':True,'tlsCAFile':certifi.where()} if uri.startswith('mongodb+srv://') or 'mongodb.net' in uri else {}
    client=MongoClient(uri,serverSelectionTimeoutMS=8000,connectTimeoutMS=5000,
                       socketTimeoutMS=15000,maxPoolSize=10,**tls)
    client.admin.command('ping')
    return client


def ensure_seeded(db, seed):
    if db.platform_meta.find_one({'_id':SEED_MARKER}):
        return
    # Build the fictional fixture without touching the shared database first.
    fixture=mongomock.MongoClient()['fictional_demo_fixture']
    seed(fixture)
    def publish(session):
        if db.platform_meta.find_one({'_id':SEED_MARKER},session=session):
            return
        if db.products.find_one({},session=session) or db.users.find_one({},session=session):
            raise RuntimeError('Use a new, empty DEMO_MONGO_DB. Existing records were not overwritten.')
        db.platform_meta.insert_one({'_id':SEED_MARKER,'fictional':True},session=session)
        for name in fixture.list_collection_names():
            rows=list(fixture[name].find({}))
            if rows:
                db[name].insert_many(rows,session=session)
    try:
        with db.client.start_session() as session:
            session.with_transaction(publish)
    except DuplicateKeyError:
        # A second cold-start worker may have completed initialization first.
        if not db.platform_meta.find_one({'_id':SEED_MARKER}):
            raise
