__node_daemon__ = 'lbrycrdd'
__node_cli__ = 'lbrycrd-cli'
__node_bin__ = ''
__node_url__ = (
    'https://github.com/lbryio/lbrycrd/releases/download/v0.12.4.0/lbrycrd-linux.zip'
)
__spvserver__ = 'lbrynet.wallet.server.coin.LBCRegTest'

from lbry.wallet.manager import LbryWalletManager
from lbry.wallet.network import Network
from lbry.wallet.ledger import MainNetLedger, RegTestLedger, TestNetLedger
