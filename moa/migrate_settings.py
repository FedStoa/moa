import pickle
import sys

if __name__ == '__main__':
    import os
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from pprint import pprint as pp

    from moa.models import Bridge, TSettings

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    engine.connect()
    session = Session(engine)

    if len(sys.argv) > 1:
        bridge = session.query(Bridge).filter_by(id=sys.argv[1]).first()
        new_settings = TSettings()
        new_settings.import_settings(bridge.settings)
        session.add(new_settings)
        session.commit()

        bridge.t_settings = new_settings
        session.commit()

    else:
        bridges = session.query(Bridge).all()

        for bridge in bridges:
            print(bridge.id)
            new_settings = TSettings()
            new_settings.import_settings(bridge.settings)
            session.add(new_settings)
            session.commit()

            bridge.t_settings = new_settings
            session.commit()

    session.close()
