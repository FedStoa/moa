import pickle
import sys

if __name__ == '__main__':
    import os
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from pprint import pprint as pp

    from moa.models import Bridge

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    engine.connect()
    session = Session(engine)

    if len(sys.argv) > 1:
        bridge = session.query(Bridge).filter_by(id=sys.argv[1]).first()

        pp(bridge.settings.__dict__)
        with open(f"/tmp/moa_settings/{bridge.id}.pickle", 'wb') as fp:
            pickle.dump(bridge.settings, fp)

    else:
        bridges = session.query(Bridge).all()

        for bridge in bridges:
            print(bridge.id)
            with open(f"/tmp/moa_settings/{bridge.id}.pickle", 'wb') as fp:
                pickle.dump(bridge.settings, fp)

    session.close()
