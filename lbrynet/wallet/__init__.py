__node_daemon__ = 'lbrycrdd'
__node_cli__ = 'lbrycrd-cli'
__node_bin__ = ''
__node_url__ = (
    'https://github.com/lbryio/lbrycrd/releases/download/v0.12.2.1/lbrycrd-linux.zip'
)
__electrumx__ = 'lbryumx.coin.LBCRegTest'

from .ledger import MainNetLedger, RegTestLedger
