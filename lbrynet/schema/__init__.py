import os

__version__ = "0.0.16"

BLOCKCHAIN_NAME_ENVVAR = "LBRYSCHEMA_BLOCKCHAIN_NAME"
if BLOCKCHAIN_NAME_ENVVAR in os.environ:
    if os.environ[BLOCKCHAIN_NAME_ENVVAR] in ['lbrycrd_main', 'lbrycrd_regtest',
                                              'lbrycrd_testnet']:
        BLOCKCHAIN_NAME = os.environ[BLOCKCHAIN_NAME_ENVVAR]
    else:
        raise OSError("invalid blockchain name: %s" % os.environ[BLOCKCHAIN_NAME_ENVVAR])
else:
    BLOCKCHAIN_NAME = "lbrycrd_main"
