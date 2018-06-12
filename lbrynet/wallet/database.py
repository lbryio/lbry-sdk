from torba.basedatabase import BaseDatabase


class WalletDatabase(BaseDatabase):

    CREATE_TABLES_QUERY = (
            BaseDatabase.CREATE_TX_TABLE +
            BaseDatabase.CREATE_PUBKEY_ADDRESS_TABLE +
            BaseDatabase.CREATE_TXO_TABLE +
            BaseDatabase.CREATE_TXI_TABLE
    )
