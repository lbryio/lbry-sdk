from torba.basedatabase import BaseDatabase


class WalletDatabase(BaseDatabase):

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txoid integer primary key,
            txhash blob references tx,
            address blob references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0,
            
            claim_name text,
            is_claim boolean not null default 0,
            is_update boolean not null default 0,
            is_support boolean not null default 0
        );
    """

    CREATE_TABLES_QUERY = (
            BaseDatabase.CREATE_TX_TABLE +
            BaseDatabase.CREATE_PUBKEY_ADDRESS_TABLE +
            CREATE_TXO_TABLE +
            BaseDatabase.CREATE_TXI_TABLE
    )

    def txo_to_row(self, tx, address, txo):
        row = super(WalletDatabase, self).txo_to_row(tx, address, txo)
        row.update({
            'is_claim': txo.script.is_claim_name,
            'is_update': txo.script.is_update_claim,
            'is_support': txo.script.is_support_claim,
        })
        if txo.script.is_claim_involved:
            row['claim_name'] = txo.script.values['claim_name']
        return row
