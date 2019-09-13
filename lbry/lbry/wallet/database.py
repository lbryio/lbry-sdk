from typing import List

from torba.client.basedatabase import BaseDatabase

from lbry.wallet.transaction import Output
from lbry.wallet.constants import TXO_TYPES


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

            txo_type integer not null default 0,
            claim_id text,
            claim_name text
        );
        create index if not exists txo_claim_id_idx on txo (claim_id);
        create index if not exists txo_txo_type_idx on txo (txo_type);
    """

    CREATE_TABLES_QUERY = (
            BaseDatabase.CREATE_TX_TABLE +
            BaseDatabase.CREATE_PUBKEY_ADDRESS_TABLE +
            BaseDatabase.CREATE_PUBKEY_ADDRESS_INDEX +
            CREATE_TXO_TABLE +
            BaseDatabase.CREATE_TXO_INDEX +
            BaseDatabase.CREATE_TXI_TABLE +
            BaseDatabase.CREATE_TXI_INDEX
    )

    def txo_to_row(self, tx, address, txo):
        row = super().txo_to_row(tx, address, txo)
        if txo.is_claim:
            if txo.can_decode_claim:
                row['txo_type'] = TXO_TYPES.get(txo.claim.claim_type, TXO_TYPES['stream'])
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_name'] = txo.claim_name
        return row

    async def get_txos(self, **constraints) -> List[Output]:
        my_accounts = constraints.get('my_accounts', constraints.get('accounts', []))

        txos = await super().get_txos(**constraints)

        channel_ids = set()
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                if txo.claim.is_signed:
                    channel_ids.add(txo.claim.signing_channel_id)
                if txo.claim.is_channel and my_accounts:
                    for account in my_accounts:
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
                    my_accounts=my_accounts,
                    claim_id__in=channel_ids
                ))
            }
            for txo in txos:
                if txo.is_claim and txo.can_decode_claim:
                    txo.channel = channels.get(txo.claim.signing_channel_id, None)

        return txos

    @staticmethod
    def constrain_claims(constraints):
        constraints['txo_type__in'] = [
            TXO_TYPES['stream'], TXO_TYPES['channel']
        ]

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

    async def release_all_outputs(self, account):
        await self.db.execute(
            "UPDATE txo SET is_reserved = 0 WHERE"
            "  is_reserved = 1 AND txo.address IN ("
            "    SELECT address from pubkey_address WHERE account = ?"
            "  )", [account.public_key.address]
        )

    def get_supports_summary(self, account_id):
        return self.db.execute_fetchall(f"""
            select txo.amount, exists(select * from txi where txi.txoid=txo.txoid) as spent,
                (txo.txid in
                (select txi.txid from txi join pubkey_address a on txi.address = a.address
                    where a.account = ?)) as from_me,
                (txo.address in (select address from pubkey_address where account=?)) as to_me,
                tx.height
            from txo join tx using (txid) where txo_type={TXO_TYPES['support']}
        """, (account_id, account_id))
