__node_daemon__ = 'lbrycrdd'
__node_cli__ = 'lbrycrd-cli'
__node_bin__ = ''
__node_url__ = (
    'https://github.com/lbryio/lbrycrd/releases/download/v0.12.4.0/lbrycrd-linux.zip'
)
__spvserver__ = 'lbrynet.extras.wallet.server.coin.LBCRegTest'

from lbrynet.extras.wallet.ledger import MainNetLedger, RegTestLedger
from lbrynet.extras.wallet.manager import LbryWalletManager
from lbrynet.extras.wallet.network import Network
