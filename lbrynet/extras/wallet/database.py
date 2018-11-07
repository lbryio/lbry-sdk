from torba.client.basedatabase import BaseDatabase


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

    async def get_txos(self, **constraints):
        my_account = constraints.get('my_account', constraints.get('account', None))

        txos = await super().get_txos(**constraints)

        channel_ids = set()
        for txo in txos:
            if txo.script.is_claim_name or txo.script.is_update_claim:
                if 'publisherSignature' in txo.claim_dict:
                    channel_ids.add(txo.claim_dict['publisherSignature']['certificateId'])
                if txo.claim_name.startswith('@') and my_account is not None:
                    txo.private_key = my_account.get_certificate_private_key(txo.ref)

        if channel_ids:
            channels = {
                txo.claim_id: txo for txo in
                (await self.get_claims(
                    my_account=my_account,
                    claim_id__in=channel_ids
                ))
            }
            for txo in txos:
                if txo.script.is_claim_name or txo.script.is_update_claim:
                    if 'publisherSignature' in txo.claim_dict:
                        txo.channel = channels.get(txo.claim_dict['publisherSignature']['certificateId'])

        return txos

    @staticmethod
    def constrain_claims(constraints):
        constraints['claim_type__any'] = {'is_claim': 1, 'is_update': 1}

    def get_claims(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxos(**constraints)

    def get_claim_count(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxo_count(**constraints)

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

    async def get_certificates(self, private_key_accounts, exclude_without_key=False, **constraints):
        channels = await self.get_channels(**constraints)
        certificates = []
        if private_key_accounts is not None:
            for channel in channels:
                if not channel.has_private_key:
                    private_key = None
                    for account in private_key_accounts:
                        private_key = account.get_certificate_private_key(channel.ref)
                        if private_key is not None:
                            break
                    if private_key is None and exclude_without_key:
                        continue
                    channel.private_key = private_key
                certificates.append(channel)
        return certificates
