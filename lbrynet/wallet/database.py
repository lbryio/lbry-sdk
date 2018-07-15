import sqlite3
from binascii import hexlify
from twisted.internet import defer
from torba.basedatabase import BaseDatabase
from .certificate import Certificate


class WalletDatabase(BaseDatabase):

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txid text references tx,
            txoid text primary key,
            address text references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0,

            claim_id text,
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
        if txo.script.is_update_claim or txo.script.is_support_claim:
            row['claim_id'] = hexlify(txo.script.values['claim_id'][::-1])
        elif txo.script.is_claim_name:
            row['claim_id'] = hexlify(tx.get_claim_id(txo.position)[::-1])
        return row

    @defer.inlineCallbacks
    def get_certificates(self, name, private_key_accounts=None, exclude_without_key=False):
        txos = yield self.db.runQuery(
            """
            SELECT tx.hash, txo.position, txo.claim_id
            FROM txo JOIN tx ON tx.txhash=txo.txhash
            WHERE claim_name=:claim AND (is_claim=1 OR is_update=1)
            ORDER BY tx.height DESC
            GROUP BY txo.claim_id
            """, {'name': name}
        )

        certificates = [
            Certificate(
                values[0],
                values[1],
                values[2],
                name,
                None
            ) for values in txos
        ]

        # Lookup private keys for each certificate.
        if private_key_accounts is not None:
            for cert in certificates:
                for account in private_key_accounts:
                    private_key = account.get_certificate_private_key(
                        cert.txhash, cert.nout
                    )
                    if private_key is not None:
                        cert.private_key = private_key
                        break

        if exclude_without_key:
            defer.returnValue([
                c for c in certificates if c.private_key is not None
            ])

        defer.returnValue(certificates)
