_wallet_manager = None


def set_wallet_manager(wallet_manager):
    global _wallet_manager
    _wallet_manager = wallet_manager


def get_wallet_manager():
    return _wallet_manager
