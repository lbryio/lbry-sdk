from typing import List

from torba.client.basedatabase import BaseDatabase

from lbry.wallet.transaction import Output


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
        create index if not exists txo_claim_id_idx on txo (claim_id);
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
        constraints['claim_type__any'] = {'is_claim': 1, 'is_update': 1}

    async def get_claims(self, **constraints) -> List[Output]:
        self.constrain_claims(constraints)
        return await self.get_utxos(**constraints)

    def get_claim_count(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_streams(constraints):
        if 'claim_name' not in constraints or 'claim_id' not in constraints:
            constraints['claim_name__not_like'] = '@%'

    def get_streams(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claims(**constraints)

    def get_stream_count(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_channels(constraints):
        if 'claim_name' not in constraints or 'claim_id' not in constraints:
            constraints['claim_name__like'] = '@%'

    def get_channels(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claims(**constraints)

    def get_channel_count(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_supports(constraints):
        constraints['is_support'] = 1

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
        return self.db.execute_fetchall("""
            select txo.amount, exists(select * from txi where txi.txoid=txo.txoid) as spent,
                (txo.txid in
                (select txi.txid from txi join pubkey_address a on txi.address = a.address
                    where a.account = ?)) as from_me,
                (txo.address in (select address from pubkey_address where account=?)) as to_me,
                tx.height
            from txo join tx using (txid) where is_support=1
        """, (account_id, account_id))
