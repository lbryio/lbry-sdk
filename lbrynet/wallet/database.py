from twisted.internet import defer
from torba.basedatabase import BaseDatabase
from torba.hash import TXRefImmutable
from torba.basetransaction import TXORef
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
            is_support boolean not null default 0,
            is_buy boolean not null default 0,
            is_sell boolean not null default 0
        );
    """

    CREATE_TABLES_QUERY = (
            BaseDatabase.CREATE_TX_TABLE +
            BaseDatabase.CREATE_PUBKEY_ADDRESS_TABLE +
            CREATE_TXO_TABLE +
            BaseDatabase.CREATE_TXI_TABLE
    )

    def txo_to_row(self, tx, address, txo):
        row = super().txo_to_row(tx, address, txo)
        row.update({
            'is_claim': txo.script.is_claim_name,
            'is_update': txo.script.is_update_claim,
            'is_support': txo.script.is_support_claim,
            'is_buy': txo.script.is_buy_claim,
            'is_sell': txo.script.is_sell_claim,
        })
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_name'] = txo.claim_name
        return row

    @defer.inlineCallbacks
    def get_certificates(self, name=None, channel_id=None, private_key_accounts=None, exclude_without_key=False):
        if name is not None:
            filter_sql = 'claim_name=?'
            filter_value = name
        elif channel_id is not None:
            filter_sql = 'claim_id=?'
            filter_value = channel_id
        else:
            raise ValueError("'name' or 'claim_id' is required")

        txos = yield self.db.runQuery(
            """
            SELECT tx.txid, txo.position, txo.claim_id
            FROM txo JOIN tx ON tx.txid=txo.txid
            WHERE {} AND (is_claim OR is_update)
            GROUP BY txo.claim_id ORDER BY tx.height DESC;
            """.format(filter_sql), (filter_value,)
        )

        certificates = []
        # Lookup private keys for each certificate.
        if private_key_accounts is not None:
            for txid, nout, claim_id in txos:
                for account in private_key_accounts:
                    private_key = account.get_certificate_private_key(
                        TXORef(TXRefImmutable.from_id(txid), nout)
                    )
                    certificates.append(Certificate(txid, nout, claim_id, name, private_key))

        if exclude_without_key:
            return [c for c in certificates if c.private_key is not None]

        return certificates

    @defer.inlineCallbacks
    def get_claim(self, account, claim_id=None, txid=None, nout=None):
        if claim_id is not None:
            filter_sql = "claim_id=?"
            filter_value = (claim_id,)
        else:
            filter_sql = "txo.txid=? AND position=?"
            filter_value = (txid, nout)
        utxos = yield self.db.runQuery(
            """
            SELECT amount, script, txo.txid, position
            FROM txo JOIN tx ON tx.txid=txo.txid
            WHERE {} AND (is_claim OR is_update) AND txoid NOT IN (SELECT txoid FROM txi)
            ORDER BY tx.height DESC LIMIT 1;
            """.format(filter_sql), filter_value
        )
        output_class = account.ledger.transaction_class.output_class
        return [
            output_class(
                values[0],
                output_class.script_class(values[1]),
                TXRefImmutable.from_id(values[2]),
                position=values[3]
            ) for values in utxos
        ]

    @defer.inlineCallbacks
    def get_claims(self, account):
        utxos = yield self.db.runQuery(
            """
            SELECT amount, script, txo.txid, position
            FROM txo JOIN tx ON tx.txid=txo.txid
            WHERE (is_claim OR is_update) AND txoid NOT IN (SELECT txoid FROM txi)
            ORDER BY tx.height DESC;
            """
        )
        output_class = account.ledger.transaction_class.output_class
        return [
            output_class(
                values[0],
                output_class.script_class(values[1]),
                TXRefImmutable.from_id(values[2]),
                position=values[3]
            ) for values in utxos
        ]
