import pickle
import sys

if __name__ == '__main__':
    import os
    import importlib
    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import Session
    from pprint import pprint as pp

    from moa.models import Bridge

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    engine.connect()
    session = Session(engine)

    if len(sys.argv) > 1:

        bridge = session.query(Bridge).filter_by(id=sys.argv[1]).with_entities(Bridge.id).first()

        with open(f"/tmp/moa_settings/{bridge.id}.pickle", 'rb') as fp:
            print(bridge.id)
            s = pickle.load(fp)
            pp(s.__dict__)

            session.query(Bridge).update({Bridge.settings: s})
            session.commit()

    else:
        bridges = session.query(Bridge).with_entities(Bridge.id).order_by(Bridge.id.asc()).all()

        for b in bridges:
            bridge = session.query(Bridge).filter_by(id=b.id).with_entities(Bridge.id).first()

            try:
                with open(f"/tmp/moa_settings/{bridge.id}.pickle", 'rb') as fp:
                    # print(bridge.id)
                    s = pickle.load(fp)
                    session.query(Bridge).filter_by(id=bridge.id).update({Bridge.settings: s})
                    session.commit()
            except FileNotFoundError:
                print(f"No settings found for {bridge.id}")
    session.close()
