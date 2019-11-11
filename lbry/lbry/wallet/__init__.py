__node_daemon__ = 'lbrycrdd'
__node_cli__ = 'lbrycrd-cli'
__node_bin__ = ''
__node_url__ = (
    'https://github.com/lbryio/lbrycrd/releases/download/v0.17.3.1/lbrycrd-linux-1731.zip'
)
__spvserver__ = 'lbry.wallet.server.coin.LBCRegTest'

from lbry.wallet.manager import LbryWalletManager
from lbry.wallet.network import Network
from lbry.wallet.ledger import MainNetLedger, RegTestLedger, TestNetLedger
