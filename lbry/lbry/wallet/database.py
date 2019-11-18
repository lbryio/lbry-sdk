from typing import List

from torba.client.basedatabase import BaseDatabase

from lbry.wallet.transaction import Output
from lbry.wallet.constants import TXO_TYPES, CLAIM_TYPES


class WalletDatabase(BaseDatabase):

    SCHEMA_VERSION = f"{BaseDatabase.SCHEMA_VERSION}+1"

    CREATE_TX_TABLE = """
        create table if not exists tx (
            txid text primary key,
            raw blob not null,
            height integer not null,
            position integer not null,
            is_verified boolean not null default 0,
            purchased_claim_id text
        );
        create index if not exists tx_purchased_claim_id_idx on tx (purchased_claim_id);
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txid text references tx,
            txoid text primary key,
            address text references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0,

            txo_type integer not null default 0,
            claim_id text,
            claim_name text
        );
        create index if not exists txo_txid_idx on txo (txid);
        create index if not exists txo_address_idx on txo (address);
        create index if not exists txo_claim_id_idx on txo (claim_id);
        create index if not exists txo_txo_type_idx on txo (txo_type);
    """

    CREATE_TABLES_QUERY = (
        BaseDatabase.PRAGMAS +
        BaseDatabase.CREATE_ACCOUNT_TABLE +
        BaseDatabase.CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_TX_TABLE +
        CREATE_TXO_TABLE +
        BaseDatabase.CREATE_TXI_TABLE
    )

    def tx_to_row(self, tx):
        row = super().tx_to_row(tx)
        txos = tx.outputs
        if len(txos) >= 2 and txos[1].can_decode_purchase_data:
            txos[0].purchase = txos[1]
            row['purchased_claim_id'] = txos[1].purchase_data.claim_id
        return row

    def txo_to_row(self, tx, address, txo):
        row = super().txo_to_row(tx, address, txo)
        if txo.is_claim:
            if txo.can_decode_claim:
                row['txo_type'] = TXO_TYPES.get(txo.claim.claim_type, TXO_TYPES['stream'])
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_name'] = txo.claim_name
        return row

    async def get_transactions(self, **constraints):
        txs = await super().get_transactions(**constraints)
        for tx in txs:
            txos = tx.outputs
            if len(txos) >= 2 and txos[1].can_decode_purchase_data:
                txos[0].purchase = txos[1]
        return txs

    @staticmethod
    def constrain_purchases(constraints):
        accounts = constraints.pop('accounts', None)
        assert accounts, "'accounts' argument required to find purchases"
        if not {'purchased_claim_id', 'purchased_claim_id__in'}.intersection(constraints):
            constraints['purchased_claim_id__is_not_null'] = True
        constraints.update({
            f'$account{i}': a.public_key.address for i, a in enumerate(accounts)
        })
        account_values = ', '.join([f':$account{i}' for i in range(len(accounts))])
        constraints['txid__in'] = f"""
            SELECT txid FROM txi JOIN account_address USING (address)
            WHERE account_address.account IN ({account_values})
        """

    async def get_purchases(self, **constraints):
        self.constrain_purchases(constraints)
        return [tx.outputs[0] for tx in await self.get_transactions(**constraints)]

    def get_purchase_count(self, **constraints):
        self.constrain_purchases(constraints)
        return self.get_transaction_count(**constraints)

    async def get_txos(self, wallet=None, no_tx=False, **constraints) -> List[Output]:
        txos = await super().get_txos(wallet=wallet, no_tx=no_tx, **constraints)

        channel_ids = set()
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                if txo.claim.is_signed:
                    channel_ids.add(txo.claim.signing_channel_id)
                if txo.claim.is_channel and wallet:
                    for account in wallet.accounts:
                        private_key = account.get_channel_private_key(
                            txo.claim.channel.public_key_bytes
                        )
                        if private_key:
                            txo.private_key = private_key
                            break

        if channel_ids:
            channels = {
                txo.claim_id: txo for txo in
                (await self.get_claims(
                    wallet=wallet,
                    claim_id__in=channel_ids
                ))
            }
            for txo in txos:
                if txo.is_claim and txo.can_decode_claim:
                    txo.channel = channels.get(txo.claim.signing_channel_id, None)

        return txos

    @staticmethod
    def constrain_claims(constraints):
        claim_type = constraints.pop('claim_type', None)
        if claim_type is not None:
            constraints['txo_type'] = TXO_TYPES[claim_type]
        else:
            constraints['txo_type__in'] = CLAIM_TYPES

    async def get_claims(self, **constraints) -> List[Output]:
        self.constrain_claims(constraints)
        return await self.get_utxos(**constraints)

    def get_claim_count(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_streams(constraints):
        constraints['txo_type'] = TXO_TYPES['stream']

    def get_streams(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claims(**constraints)

    def get_stream_count(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_channels(constraints):
        constraints['txo_type'] = TXO_TYPES['channel']

    def get_channels(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claims(**constraints)

    def get_channel_count(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_supports(constraints):
        constraints['txo_type'] = TXO_TYPES['support']

    def get_supports(self, **constraints):
        self.constrain_supports(constraints)
        return self.get_utxos(**constraints)

    def get_support_count(self, **constraints):
        self.constrain_supports(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_collections(constraints):
        constraints['txo_type'] = TXO_TYPES['collection']

    def get_collections(self, **constraints):
        self.constrain_collections(constraints)
        return self.get_utxos(**constraints)

    def get_collection_count(self, **constraints):
        self.constrain_collections(constraints)
        return self.get_utxo_count(**constraints)

    async def release_all_outputs(self, account):
        await self.db.execute_fetchall(
            "UPDATE txo SET is_reserved = 0 WHERE"
            "  is_reserved = 1 AND txo.address IN ("
            "    SELECT address from account_address WHERE account = ?"
            "  )", (account.public_key.address, )
        )

    def get_supports_summary(self, account_id):
        return self.db.execute_fetchall(f"""
            select txo.amount, exists(select * from txi where txi.txoid=txo.txoid) as spent,
                (txo.txid in
                (select txi.txid from txi join account_address a on txi.address = a.address
                    where a.account = ?)) as from_me,
                (txo.address in (select address from account_address where account=?)) as to_me,
                tx.height
            from txo join tx using (txid) where txo_type={TXO_TYPES['support']}
        """, (account_id, account_id))
