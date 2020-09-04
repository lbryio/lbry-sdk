# pylint: skip-file
# DO NOT EDIT: GENERATED FILE
interface = {
    "groups": {
        "account": "Create, modify and inspect wallet accounts.",
        "address": "List, generate and verify addresses. Golomb-Rice coding filters for addresses.",
        "blob": "Blob management.",
        "channel": "Create, update, abandon and list your channel claims.",
        "claim": "List and search all types of claims.",
        "collection": "Create, update, list, resolve, and abandon collections.",
        "comment": "View, create and abandon comments.",
        "file": "File management.",
        "peer": "DHT / Blob Exchange peer commands.",
        "preference": "Preferences management.",
        "purchase": "List and make purchases of claims.",
        "settings": "Settings management.",
        "stream": "Create, update, abandon, list and inspect your stream claims.",
        "support": "Create, list and abandon all types of supports.",
        "sync": "Wallet synchronization.",
        "tracemalloc": "Controls and queries tracemalloc memory tracing tools for troubleshooting.",
        "transaction": "Transaction management.",
        "txo": "List and sum transaction outputs.",
        "utxo": "Unspent transaction management.",
        "wallet": "Create, modify and inspect wallets."
    },
    "commands": {
        "account_add": {
            "name": "add",
            "desc": {
                "text": [
                    "Add a previously created account from a seed, private key or public key (read-only).",
                    "Specify --single_key for single address or vanity address accounts."
                ],
                "usage": [
                    "    account add (<account_name> | --account_name=<account_name>)",
                    "         (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)",
                    "         [--single_key] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_name",
                    "desc": [
                        "name of the account being add"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "add account to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "single_key",
                    "desc": [
                        "create single key account, default is multi-key"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "seed",
                    "desc": [
                        "seed to generate account from"
                    ],
                    "type": "str"
                },
                {
                    "name": "private_key",
                    "desc": [
                        "private key of account"
                    ],
                    "type": "str"
                },
                {
                    "name": "public_key",
                    "desc": [
                        "public key of account"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "added account"
                ],
                "type": "Account",
                "json": {
                    "id": "account_id",
                    "is_default": "this account is used by default",
                    "ledger": "name of crypto currency and network",
                    "name": "optional account name",
                    "seed": "human friendly words from which account can be recreated",
                    "encrypted": "if account is encrypted",
                    "private_key": "extended private key",
                    "public_key": "extended public key",
                    "address_generator": "settings for generating addresses",
                    "modified_on": "date of last modification to account settings"
                }
            },
            "group": "account",
            "cli": "account add",
            "help": "Add a previously created account from a seed, private key or public key (read-only).\nSpecify --single_key for single address or vanity address accounts.\n\nUsage:\n    account add (<account_name> | --account_name=<account_name>)\n         (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)\n         [--single_key] [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_name=<account_name>  : (str) name of the account being add\n    --wallet_id=<wallet_id>        : (str) add account to specific wallet\n    --single_key                   : (bool) create single key account, default is multi-\n                                      key\n    --seed=<seed>                  : (str) seed to generate account from\n    --private_key=<private_key>    : (str) private key of account\n    --public_key=<public_key>      : (str) public key of account\n\nReturns:\n    (Account) added account\n    {\n        \"id\": \"account_id\",\n        \"is_default\": \"this account is used by default\",\n        \"ledger\": \"name of crypto currency and network\",\n        \"name\": \"optional account name\",\n        \"seed\": \"human friendly words from which account can be recreated\",\n        \"encrypted\": \"if account is encrypted\",\n        \"private_key\": \"extended private key\",\n        \"public_key\": \"extended public key\",\n        \"address_generator\": \"settings for generating addresses\",\n        \"modified_on\": \"date of last modification to account settings\"\n    }"
        },
        "account_balance": {
            "name": "balance",
            "desc": {
                "text": [
                    "Return the balance of an account"
                ],
                "usage": [
                    "    account balance [<account_id>] [--wallet_id=<wallet_id>] [--confirmations=<confirmations>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "balance for specific account, default otherwise"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "confirmations",
                    "desc": [
                        "required confirmations of transactions included"
                    ],
                    "default": 0,
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [],
                "type": "dict"
            },
            "group": "account",
            "cli": "account balance",
            "help": "Return the balance of an account\n\nUsage:\n    account balance [<account_id>] [--wallet_id=<wallet_id>] [--confirmations=<confirmations>]\n\nOptions:\n    --account_id=<account_id>        : (str) balance for specific account, default\n                                        otherwise\n    --wallet_id=<wallet_id>          : (str) restrict operation to specific wallet\n    --confirmations=<confirmations>  : (int) required confirmations of transactions\n                                        included [default: 0]\n\nReturns:\n    (dict) "
        },
        "account_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create a new account. Specify --single_key if you want to use",
                    "the same address for all transactions (not recommended)."
                ],
                "usage": [
                    "    account create (<account_name> | --account_name=<account_name>)",
                    "                   [--language=<language>]",
                    "                   [--single_key] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_name",
                    "desc": [
                        "name of the account being created"
                    ],
                    "type": "str"
                },
                {
                    "name": "language",
                    "desc": [
                        "language to use for seed phrase words,",
                        "available languages: en, fr, it, ja, es, zh"
                    ],
                    "default": "'en'",
                    "type": "str"
                },
                {
                    "name": "single_key",
                    "desc": [
                        "create single key account, default is multi-key"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "create account in specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "created account"
                ],
                "type": "Account",
                "json": {
                    "id": "account_id",
                    "is_default": "this account is used by default",
                    "ledger": "name of crypto currency and network",
                    "name": "optional account name",
                    "seed": "human friendly words from which account can be recreated",
                    "encrypted": "if account is encrypted",
                    "private_key": "extended private key",
                    "public_key": "extended public key",
                    "address_generator": "settings for generating addresses",
                    "modified_on": "date of last modification to account settings"
                }
            },
            "group": "account",
            "cli": "account create",
            "help": "Create a new account. Specify --single_key if you want to use\nthe same address for all transactions (not recommended).\n\nUsage:\n    account create (<account_name> | --account_name=<account_name>)\n                   [--language=<language>]\n                   [--single_key] [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_name=<account_name>  : (str) name of the account being created\n    --language=<language>          : (str) language to use for seed phrase words,\n                                      available languages: en, fr, it, ja, es, zh [default:\n                                      'en']\n    --single_key                   : (bool) create single key account, default is multi-\n                                      key\n    --wallet_id=<wallet_id>        : (str) create account in specific wallet\n\nReturns:\n    (Account) created account\n    {\n        \"id\": \"account_id\",\n        \"is_default\": \"this account is used by default\",\n        \"ledger\": \"name of crypto currency and network\",\n        \"name\": \"optional account name\",\n        \"seed\": \"human friendly words from which account can be recreated\",\n        \"encrypted\": \"if account is encrypted\",\n        \"private_key\": \"extended private key\",\n        \"public_key\": \"extended public key\",\n        \"address_generator\": \"settings for generating addresses\",\n        \"modified_on\": \"date of last modification to account settings\"\n    }"
        },
        "account_fund": {
            "name": "fund",
            "desc": {
                "text": [
                    "Transfer some amount (or --everything) to an account from another",
                    "account (can be the same account). Amounts are interpreted as LBC.",
                    "You can also spread the transfer across a number of --outputs (cannot",
                    "be used together with --everything)."
                ],
                "usage": [
                    "    account fund [<to_account> | --to_account=<to_account>]",
                    "        [<from_account> | --from_account=<from_account>]",
                    "        (<amount> | --amount=<amount> | --everything)",
                    "        [<outputs> | --outputs=<outputs>] [--wallet_id=<wallet_id>]",
                    "        [--broadcast]"
                ]
            },
            "arguments": [
                {
                    "name": "to_account",
                    "desc": [
                        "send to this account"
                    ],
                    "type": "str"
                },
                {
                    "name": "from_account",
                    "desc": [
                        "spend from this account"
                    ],
                    "type": "str"
                },
                {
                    "name": "amount",
                    "desc": [
                        "the amount of LBC to transfer"
                    ],
                    "default": "'0.0'",
                    "type": "str"
                },
                {
                    "name": "everything",
                    "desc": [
                        "transfer everything (excluding claims)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "outputs",
                    "desc": [
                        "split payment across many outputs"
                    ],
                    "default": 1,
                    "type": "int"
                },
                {
                    "name": "broadcast",
                    "desc": [
                        "broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "group": "account",
            "cli": "account fund",
            "help": "Transfer some amount (or --everything) to an account from another\naccount (can be the same account). Amounts are interpreted as LBC.\nYou can also spread the transfer across a number of --outputs (cannot\nbe used together with --everything).\n\nUsage:\n    account fund [<to_account> | --to_account=<to_account>]\n        [<from_account> | --from_account=<from_account>]\n        (<amount> | --amount=<amount> | --everything)\n        [<outputs> | --outputs=<outputs>] [--wallet_id=<wallet_id>]\n        [--broadcast]\n\nOptions:\n    --to_account=<to_account>      : (str) send to this account\n    --from_account=<from_account>  : (str) spend from this account\n    --amount=<amount>              : (str) the amount of LBC to transfer [default: '0.0']\n    --everything                   : (bool) transfer everything (excluding claims)\n    --outputs=<outputs>            : (int) split payment across many outputs [default: 1]\n    --broadcast                    : (bool) broadcast the transaction\n    --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet\n\nReturns:\n    (Transaction) \n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "account_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List details of all of the accounts or a specific account."
                ],
                "usage": [
                    "    account list [<account_id>] [--wallet_id=<wallet_id>]",
                    "                 [--confirmations=<confirmations>] [--include_seed]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "show specific wallet only"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "confirmations",
                    "desc": [
                        "required confirmations for account balance"
                    ],
                    "default": 0,
                    "type": "int"
                },
                {
                    "name": "include_seed",
                    "desc": [
                        "include the seed phrase of the accounts"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "paginated accounts"
                ],
                "type": "Paginated[Account]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "id": "account_id",
                            "is_default": "this account is used by default",
                            "ledger": "name of crypto currency and network",
                            "name": "optional account name",
                            "seed": "human friendly words from which account can be recreated",
                            "encrypted": "if account is encrypted",
                            "private_key": "extended private key",
                            "public_key": "extended public key",
                            "address_generator": "settings for generating addresses",
                            "modified_on": "date of last modification to account settings"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "account",
            "cli": "account list",
            "help": "List details of all of the accounts or a specific account.\n\nUsage:\n    account list [<account_id>] [--wallet_id=<wallet_id>]\n                 [--confirmations=<confirmations>] [--include_seed]\n                 [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --account_id=<account_id>        : (str) show specific wallet only\n    --wallet_id=<wallet_id>          : (str) restrict operation to specific wallet\n    --confirmations=<confirmations>  : (int) required confirmations for account balance\n                                        [default: 0]\n    --include_seed                   : (bool) include the seed phrase of the accounts\n    --page=<page>                    : (int) page to return for paginating\n    --page_size=<page_size>          : (int) number of items on page for pagination\n    --include_total                  : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Account]) paginated accounts\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"id\": \"account_id\",\n                \"is_default\": \"this account is used by default\",\n                \"ledger\": \"name of crypto currency and network\",\n                \"name\": \"optional account name\",\n                \"seed\": \"human friendly words from which account can be recreated\",\n                \"encrypted\": \"if account is encrypted\",\n                \"private_key\": \"extended private key\",\n                \"public_key\": \"extended public key\",\n                \"address_generator\": \"settings for generating addresses\",\n                \"modified_on\": \"date of last modification to account settings\"\n            }\n        ]\n    }"
        },
        "account_max_address_gap": {
            "name": "max_address_gap",
            "desc": {
                "text": [
                    "Finds ranges of consecutive addresses that are unused and returns the length",
                    "of the longest such range: for change and receiving address chains. This is",
                    "useful to figure out ideal values to set for 'receiving_gap' and 'change_gap'",
                    "account settings."
                ],
                "usage": [
                    "    account max_address_gap (<account_id> | --account_id=<account_id>)",
                    "                            [--wallet_id=<wallet_id>]"
                ],
                "returns": [
                    "    {",
                    "        'max_change_gap': (int),",
                    "        'max_receiving_gap': (int),",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "account for which to get max gaps"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "maximum gap for change and receiving addresses"
                ],
                "type": "dict"
            },
            "group": "account",
            "cli": "account max_address_gap",
            "help": "Finds ranges of consecutive addresses that are unused and returns the length\nof the longest such range: for change and receiving address chains. This is\nuseful to figure out ideal values to set for 'receiving_gap' and 'change_gap'\naccount settings.\n\nUsage:\n    account max_address_gap (<account_id> | --account_id=<account_id>)\n                            [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_id=<account_id>  : (str) account for which to get max gaps\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) maximum gap for change and receiving addresses\n    {\n        'max_change_gap': (int),\n        'max_receiving_gap': (int),\n    }"
        },
        "account_remove": {
            "name": "remove",
            "desc": {
                "text": [
                    "Remove an existing account."
                ],
                "usage": [
                    "    account remove (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "id of account to remove"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "remove account from specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "removed account"
                ],
                "type": "Account",
                "json": {
                    "id": "account_id",
                    "is_default": "this account is used by default",
                    "ledger": "name of crypto currency and network",
                    "name": "optional account name",
                    "seed": "human friendly words from which account can be recreated",
                    "encrypted": "if account is encrypted",
                    "private_key": "extended private key",
                    "public_key": "extended public key",
                    "address_generator": "settings for generating addresses",
                    "modified_on": "date of last modification to account settings"
                }
            },
            "group": "account",
            "cli": "account remove",
            "help": "Remove an existing account.\n\nUsage:\n    account remove (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_id=<account_id>  : (str) id of account to remove\n    --wallet_id=<wallet_id>    : (str) remove account from specific wallet\n\nReturns:\n    (Account) removed account\n    {\n        \"id\": \"account_id\",\n        \"is_default\": \"this account is used by default\",\n        \"ledger\": \"name of crypto currency and network\",\n        \"name\": \"optional account name\",\n        \"seed\": \"human friendly words from which account can be recreated\",\n        \"encrypted\": \"if account is encrypted\",\n        \"private_key\": \"extended private key\",\n        \"public_key\": \"extended public key\",\n        \"address_generator\": \"settings for generating addresses\",\n        \"modified_on\": \"date of last modification to account settings\"\n    }"
        },
        "account_set": {
            "name": "set",
            "desc": {
                "text": [
                    "Change various settings on an account."
                ],
                "usage": [
                    "    account set (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]",
                    "        [--default] [--new_name=<new_name>]",
                    "        [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]",
                    "        [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "id of account to modify"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "default",
                    "desc": [
                        "make this account the default"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "new_name",
                    "desc": [
                        "new name for the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_gap",
                    "desc": [
                        "set the gap for change addresses"
                    ],
                    "type": "int"
                },
                {
                    "name": "change_max_uses",
                    "desc": [
                        "set the maximum number of times to"
                    ],
                    "type": "int"
                },
                {
                    "name": "receiving_gap",
                    "desc": [
                        "set the gap for receiving addresses use a change address"
                    ],
                    "type": "int"
                },
                {
                    "name": "receiving_max_uses",
                    "desc": [
                        "set the maximum number of times to use a receiving address"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "modified account"
                ],
                "type": "Account",
                "json": {
                    "id": "account_id",
                    "is_default": "this account is used by default",
                    "ledger": "name of crypto currency and network",
                    "name": "optional account name",
                    "seed": "human friendly words from which account can be recreated",
                    "encrypted": "if account is encrypted",
                    "private_key": "extended private key",
                    "public_key": "extended public key",
                    "address_generator": "settings for generating addresses",
                    "modified_on": "date of last modification to account settings"
                }
            },
            "group": "account",
            "cli": "account set",
            "help": "Change various settings on an account.\n\nUsage:\n    account set (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]\n        [--default] [--new_name=<new_name>]\n        [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]\n        [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]\n\nOptions:\n    --account_id=<account_id>                  : (str) id of account to modify\n    --wallet_id=<wallet_id>                    : (str) restrict operation to specific\n                                                  wallet\n    --default                                  : (bool) make this account the default\n    --new_name=<new_name>                      : (str) new name for the account\n    --change_gap=<change_gap>                  : (int) set the gap for change addresses\n    --change_max_uses=<change_max_uses>        : (int) set the maximum number of times to\n    --receiving_gap=<receiving_gap>            : (int) set the gap for receiving addresses\n                                                  use a change address\n    --receiving_max_uses=<receiving_max_uses>  : (int) set the maximum number of times to\n                                                  use a receiving address\n\nReturns:\n    (Account) modified account\n    {\n        \"id\": \"account_id\",\n        \"is_default\": \"this account is used by default\",\n        \"ledger\": \"name of crypto currency and network\",\n        \"name\": \"optional account name\",\n        \"seed\": \"human friendly words from which account can be recreated\",\n        \"encrypted\": \"if account is encrypted\",\n        \"private_key\": \"extended private key\",\n        \"public_key\": \"extended public key\",\n        \"address_generator\": \"settings for generating addresses\",\n        \"modified_on\": \"date of last modification to account settings\"\n    }"
        },
        "address_block_filters": {
            "name": "block_filters",
            "desc": {},
            "arguments": [],
            "returns": {
                "desc": [],
                "type": None
            },
            "group": "address",
            "cli": "address block_filters",
            "help": "\nUsage:\n    address block_filters\n"
        },
        "address_is_mine": {
            "name": "is_mine",
            "desc": {
                "text": [
                    "Checks if an address is associated with the current wallet."
                ],
                "usage": [
                    "    address is_mine (<address> | --address=<address>)",
                    "                    [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "address",
                    "desc": [
                        "address to check"
                    ],
                    "type": "str"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id of the account to use"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "if address is associated with current wallet"
                ],
                "type": "bool"
            },
            "group": "address",
            "cli": "address is_mine",
            "help": "Checks if an address is associated with the current wallet.\n\nUsage:\n    address is_mine (<address> | --address=<address>)\n                    [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n\nOptions:\n    --address=<address>        : (str) address to check\n    --account_id=<account_id>  : (str) id of the account to use\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n\nReturns:\n    (bool) if address is associated with current wallet"
        },
        "address_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List account addresses or details of single address."
                ],
                "usage": [
                    "    address list [--address=<address>] [--account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "address",
                    "desc": [
                        "just show details for single address"
                    ],
                    "type": "str"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id of the account to use"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Address]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "address": "(str)"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "address",
            "cli": "address list",
            "help": "List account addresses or details of single address.\n\nUsage:\n    address list [--address=<address>] [--account_id=<account_id>] [--wallet_id=<wallet_id>]\n                 [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --address=<address>        : (str) just show details for single address\n    --account_id=<account_id>  : (str) id of the account to use\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n    --page=<page>              : (int) page to return for paginating\n    --page_size=<page_size>    : (int) number of items on page for pagination\n    --include_total            : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Address]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"address\": \"(str)\"\n            }\n        ]\n    }"
        },
        "address_transaction_filters": {
            "name": "transaction_filters",
            "desc": {},
            "arguments": [
                {
                    "name": "block_hash",
                    "desc": [],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [],
                "type": None
            },
            "group": "address",
            "cli": "address transaction_filters",
            "help": "\nUsage:\n    address transaction_filters\n\nOptions:\n    --block_hash=<block_hash>  : (str)\n"
        },
        "address_unused": {
            "name": "unused",
            "desc": {
                "text": [
                    "Return an address containing no balance, will create",
                    "a new address if there is none."
                ],
                "usage": [
                    "    address_unused [--account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "id of the account to use"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "unused address"
                ],
                "type": "str"
            },
            "group": "address",
            "cli": "address unused",
            "help": "Return an address containing no balance, will create\na new address if there is none.\n\nUsage:\n    address_unused [--account_id=<account_id>] [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_id=<account_id>  : (str) id of the account to use\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n\nReturns:\n    (str) unused address"
        },
        "blob_announce": {
            "name": "announce",
            "desc": {
                "text": [
                    "Announce blobs to the DHT"
                ],
                "usage": [
                    "    blob announce (<blob_hash> | --blob_hash=<blob_hash>",
                    "                  | --stream_hash=<stream_hash> | --sd_hash=<sd_hash>)"
                ]
            },
            "arguments": [
                {
                    "name": "blob_hash",
                    "desc": [
                        "announce a blob, specified by blob_hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "announce all blobs associated with stream_hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "announce all blobs associated with sd_hash and the sd_hash itself"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "true if successful"
                ],
                "type": "bool"
            },
            "group": "blob",
            "cli": "blob announce",
            "help": "Announce blobs to the DHT\n\nUsage:\n    blob announce (<blob_hash> | --blob_hash=<blob_hash>\n                  | --stream_hash=<stream_hash> | --sd_hash=<sd_hash>)\n\nOptions:\n    --blob_hash=<blob_hash>      : (str) announce a blob, specified by blob_hash\n    --stream_hash=<stream_hash>  : (str) announce all blobs associated with stream_hash\n    --sd_hash=<sd_hash>          : (str) announce all blobs associated with sd_hash and\n                                    the sd_hash itself\n\nReturns:\n    (bool) true if successful"
        },
        "blob_delete": {
            "name": "delete",
            "desc": {
                "text": [
                    "Delete a blob"
                ],
                "usage": [
                    "    blob_delete (<blob_hash> | --blob_hash=<blob_hash>)"
                ]
            },
            "arguments": [
                {
                    "name": "blob_hash",
                    "desc": [
                        "blob hash of the blob to delete"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "Success/fail message"
                ],
                "type": "str"
            },
            "group": "blob",
            "cli": "blob delete",
            "help": "Delete a blob\n\nUsage:\n    blob_delete (<blob_hash> | --blob_hash=<blob_hash>)\n\nOptions:\n    --blob_hash=<blob_hash>  : (str) blob hash of the blob to delete\n\nReturns:\n    (str) Success/fail message"
        },
        "blob_get": {
            "name": "get",
            "desc": {
                "text": [
                    "Download and return a blob"
                ],
                "usage": [
                    "    blob get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>] [--read]"
                ]
            },
            "arguments": [
                {
                    "name": "blob_hash",
                    "desc": [
                        "blob hash of the blob to get"
                    ],
                    "type": "str"
                },
                {
                    "name": "timeout",
                    "desc": [
                        "timeout in number of seconds"
                    ],
                    "type": "int"
                },
                {
                    "name": "read",
                    "desc": [],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "Success/Fail message or (dict) decoded data"
                ],
                "type": "str"
            },
            "group": "blob",
            "cli": "blob get",
            "help": "Download and return a blob\n\nUsage:\n    blob get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>] [--read]\n\nOptions:\n    --blob_hash=<blob_hash>  : (str) blob hash of the blob to get\n    --timeout=<timeout>      : (int) timeout in number of seconds\n    --read                   : (bool)\n\nReturns:\n    (str) Success/Fail message or (dict) decoded data"
        },
        "blob_list": {
            "name": "list",
            "desc": {
                "text": [
                    "Returns blob hashes. If not given filters, returns all blobs known by the blob manager"
                ],
                "usage": [
                    "    blob list [--needed] [--finished] [<uri> | --uri=<uri>]",
                    "              [<stream_hash> | --stream_hash=<stream_hash>]",
                    "              [<sd_hash> | --sd_hash=<sd_hash>]",
                    "              [--page=<page>] [--page_size=<page_size>]"
                ]
            },
            "arguments": [
                {
                    "name": "uri",
                    "desc": [
                        "filter blobs by stream in a uri"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter blobs by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter blobs by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "needed",
                    "desc": [
                        "only return needed blobs"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "finished",
                    "desc": [
                        "only return finished blobs"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return during paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page during pagination"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "List of blob hashes"
                ],
                "type": "list"
            },
            "group": "blob",
            "cli": "blob list",
            "help": "Returns blob hashes. If not given filters, returns all blobs known by the blob manager\n\nUsage:\n    blob list [--needed] [--finished] [<uri> | --uri=<uri>]\n              [<stream_hash> | --stream_hash=<stream_hash>]\n              [<sd_hash> | --sd_hash=<sd_hash>]\n              [--page=<page>] [--page_size=<page_size>]\n\nOptions:\n    --uri=<uri>                  : (str) filter blobs by stream in a uri\n    --stream_hash=<stream_hash>  : (str) filter blobs by stream hash\n    --sd_hash=<sd_hash>          : (str) filter blobs by sd hash\n    --needed                     : (bool) only return needed blobs\n    --finished                   : (bool) only return finished blobs\n    --page=<page>                : (int) page to return during paginating\n    --page_size=<page_size>      : (int) number of items on page during pagination\n\nReturns:\n    (list) List of blob hashes"
        },
        "channel_abandon": {
            "name": "abandon",
            "desc": {
                "text": [
                    "Abandon one of my channel claims."
                ],
                "usage": [
                    "    channel abandon"
                ],
                "kwargs": 20
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction abandoning the channel"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "channel",
            "cli": "channel abandon",
            "help": "Abandon one of my channel claims.\n\nUsage:\n    channel abandon\n                    [--claim_id=<claim_id>] [--txid=<txid>] [--nout=<nout>]\n                    [--account_id=<account_id>] [--change_account_id=<change_account_id>]\n                    [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the claim to abandon\n    --txid=<txid>                            : (str) txid of the claim to abandon\n    --nout=<nout>                            : (int) nout of the claim to abandon\n                                                [default: 0]\n    --account_id=<account_id>                : (str) restrict operation to specific\n                                                account, otherwise all accounts in wallet\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction abandoning the channel\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "channel_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create a new channel by generating a channel private key and establishing an '@' prefixed claim."
                ],
                "usage": [
                    "    channel create (<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]"
                ],
                "kwargs": 19
            },
            "arguments": [
                {
                    "name": "name",
                    "desc": [
                        "name of the channel prefixed with '@'"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "allow_duplicate_name",
                    "desc": [
                        "create new channel even if one already exists with given name"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "email",
                    "desc": [
                        "email of channel owner"
                    ],
                    "type": "str"
                },
                {
                    "name": "website_url",
                    "desc": [
                        "website url"
                    ],
                    "type": "str"
                },
                {
                    "name": "cover_url",
                    "desc": [
                        "url to cover image"
                    ],
                    "type": "str"
                },
                {
                    "name": "featured",
                    "desc": [
                        "claim_id(s) of featured content in channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "new channel transaction"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "email",
                    "desc": [
                        "email of channel owner"
                    ],
                    "type": "str"
                },
                {
                    "name": "website_url",
                    "desc": [
                        "website url"
                    ],
                    "type": "str"
                },
                {
                    "name": "cover_url",
                    "desc": [
                        "url to cover image"
                    ],
                    "type": "str"
                },
                {
                    "name": "featured",
                    "desc": [
                        "claim_id(s) of featured content in channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "channel",
            "cli": "channel create",
            "help": "Create a new channel by generating a channel private key and establishing an '@' prefixed claim.\n\nUsage:\n    channel create (<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]\n                   [--email=<email>] [--website_url=<website_url>]\n                   [--cover_url=<cover_url>] [--featured=<featured>...] [--title=<title>]\n                   [--description=<description>] [--thumbnail_url=<thumbnail_url>]\n                   [--tag=<tag>...] [--language=<language>...] [--location=<location>...]\n                   [--account_id=<account_id>] [--claim_address=<claim_address>]\n                   [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n                   [--change_account_id=<change_account_id>]\n                   [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --name=<name>                            : (str) name of the channel prefixed with '@'\n    --bid=<bid>                              : (str) amount to back the channel\n    --allow_duplicate_name                   : (bool) create new channel even if one\n                                                already exists with given name\n    --wallet_id=<wallet_id>                  : (str) restrict operation to specific wallet\n    --email=<email>                          : (str) email of channel owner\n    --website_url=<website_url>              : (str) website url\n    --cover_url=<cover_url>                  : (str) url to cover image\n    --featured=<featured>                    : (str, list) claim_id(s) of featured content\n                                                in channel\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) new channel transaction\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "channel_export": {
            "name": "export",
            "desc": {
                "text": [
                    "Export channel private key."
                ],
                "usage": [
                    "    channel export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)",
                    "                   [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of channel to export"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of channel to export"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "serialized channel private key"
                ],
                "type": "str"
            },
            "group": "channel",
            "cli": "channel export",
            "help": "Export channel private key.\n\nUsage:\n    channel export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)\n                   [--wallet_id=<wallet_id>]\n\nOptions:\n    --channel_id=<channel_id>      : (str) claim id of channel to export\n    --channel_name=<channel_name>  : (str) name of channel to export\n    --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet\n\nReturns:\n    (str) serialized channel private key"
        },
        "channel_import": {
            "name": "import",
            "desc": {
                "text": [
                    "Import serialized channel private key (to allow signing new streams to the channel)"
                ],
                "usage": [
                    "    channel import (<channel_data> | --channel_data=<channel_data>) [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "channel_data",
                    "desc": [
                        "serialized channel, as exported by channel export"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "import into specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "result message"
                ],
                "type": "str"
            },
            "group": "channel",
            "cli": "channel import",
            "help": "Import serialized channel private key (to allow signing new streams to the channel)\n\nUsage:\n    channel import (<channel_data> | --channel_data=<channel_data>) [--wallet_id=<wallet_id>]\n\nOptions:\n    --channel_data=<channel_data>  : (str) serialized channel, as exported by channel\n                                      export\n    --wallet_id=<wallet_id>        : (str) import into specific wallet\n\nReturns:\n    (str) result message"
        },
        "channel_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my channel claims."
                ],
                "usage": [
                    "    channel list [--account_id=<account_id>] [--wallet_id=<wallet_id>] [--is_spent] [--resolve]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "shows previous channel updates and abandons"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "resolve",
                    "desc": [
                        "resolves each channel to provide additional metadata"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "channel",
            "cli": "channel list",
            "help": "List my channel claims.\n\nUsage:\n    channel list [--account_id=<account_id>] [--wallet_id=<wallet_id>] [--is_spent] [--resolve]\n                 [--name=<name>...] [--claim_id=<claim_id>...] [--text=<text>]\n                 [--txid=<txid>] [--nout=<nout>] [--height=<height>]\n                 [--timestamp=<timestamp>] [--creation_height=<creation_height>]\n                 [--creation_timestamp=<creation_timestamp>] [--amount=<amount>]\n                 [--any_tag=<any_tag>...] [--all_tag=<all_tag>...]\n                 [--not_tag=<not_tag>...] [--any_language=<any_language>...]\n                 [--all_language=<all_language>...] [--not_language=<not_language>...]\n                 [--any_location=<any_location>...] [--all_location=<all_location>...]\n                 [--not_location=<not_location>...] [--release_time=<release_time>]\n                 [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --account_id=<account_id>                  : (str) restrict operation to specific\n                                                  account\n    --wallet_id=<wallet_id>                    : (str) restrict operation to specific\n                                                  wallet\n    --is_spent                                 : (bool) shows previous channel updates and\n                                                  abandons\n    --resolve                                  : (bool) resolves each channel to provide\n                                                  additional metadata\n    --name=<name>                              : (str, list) claim name (normalized)\n    --claim_id=<claim_id>                      : (str, list) full or partial claim id\n    --text=<text>                              : (str) full text search\n    --txid=<txid>                              : (str) transaction id\n    --nout=<nout>                              : (int) position in the transaction\n    --height=<height>                          : (int) last updated block height (supports\n                                                  equality constraints)\n    --timestamp=<timestamp>                    : (int) last updated timestamp (supports\n                                                  equality constraints)\n    --creation_height=<creation_height>        : (int) created at block height (supports\n                                                  equality constraints)\n    --creation_timestamp=<creation_timestamp>  : (int) created at timestamp (supports\n                                                  equality constraints)\n    --amount=<amount>                          : (str) claim amount (supports equality\n                                                  constraints)\n    --any_tag=<any_tag>                        : (str, list) containing any of the tags\n    --all_tag=<all_tag>                        : (str, list) containing every tag\n    --not_tag=<not_tag>                        : (str, list) not containing any of these\n                                                  tags\n    --any_language=<any_language>              : (str, list) containing any of the\n                                                  languages\n    --all_language=<all_language>              : (str, list) containing every language\n    --not_language=<not_language>              : (str, list) not containing any of these\n                                                  languages\n    --any_location=<any_location>              : (str, list) containing any of the\n                                                  locations\n    --all_location=<all_location>              : (str, list) containing every location\n    --not_location=<not_location>              : (str, list) not containing any of these\n                                                  locations\n    --release_time=<release_time>              : (int) limit to claims self-described as\n                                                  having been released to the public on or\n                                                  after this UTC timestamp, when claim does\n                                                  not provide a release time the publish\n                                                  time is used instead (supports equality\n                                                  constraints)\n    --page=<page>                              : (int) page to return for paginating\n    --page_size=<page_size>                    : (int) number of items on page for\n                                                  pagination\n    --include_total                            : (bool) calculate total number of items\n                                                  and pages\n\nReturns:\n    (Paginated[Output]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "channel_update": {
            "name": "update",
            "desc": {
                "text": [
                    "Update an existing channel claim."
                ],
                "usage": [
                    "    channel update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]",
                    "                   [--new_signing_key] [--clear_featured]"
                ],
                "kwargs": 19
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the channel to update"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "update amount backing the channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "new_signing_key",
                    "desc": [
                        "generate a new signing key, will invalidate all previous publishes"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_featured",
                    "desc": [
                        "clear existing featured content (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "email",
                    "desc": [
                        "email of channel owner"
                    ],
                    "type": "str"
                },
                {
                    "name": "website_url",
                    "desc": [
                        "website url"
                    ],
                    "type": "str"
                },
                {
                    "name": "cover_url",
                    "desc": [
                        "url to cover image"
                    ],
                    "type": "str"
                },
                {
                    "name": "featured",
                    "desc": [
                        "claim_id(s) of featured content in channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction updating the channel"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "new_signing_key",
                    "desc": [
                        "generate a new signing key, will invalidate all previous publishes"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_featured",
                    "desc": [
                        "clear existing featured content (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "email",
                    "desc": [
                        "email of channel owner"
                    ],
                    "type": "str"
                },
                {
                    "name": "website_url",
                    "desc": [
                        "website url"
                    ],
                    "type": "str"
                },
                {
                    "name": "cover_url",
                    "desc": [
                        "url to cover image"
                    ],
                    "type": "str"
                },
                {
                    "name": "featured",
                    "desc": [
                        "claim_id(s) of featured content in channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "channel",
            "cli": "channel update",
            "help": "Update an existing channel claim.\n\nUsage:\n    channel update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]\n                   [--new_signing_key] [--clear_featured]\n                   [--new_signing_key] [--clear_featured] [--email=<email>]\n                   [--website_url=<website_url>] [--cover_url=<cover_url>]\n                   [--featured=<featured>...] [--title=<title>]\n                   [--description=<description>] [--thumbnail_url=<thumbnail_url>]\n                   [--tag=<tag>...] [--language=<language>...] [--location=<location>...]\n                   [--account_id=<account_id>] [--claim_address=<claim_address>]\n                   [--channel_id=<channel_id>] [--channel_name=<channel_name>] [--replace]\n                   [--clear_tags] [--clear_languages] [--clear_locations]\n                   [--change_account_id=<change_account_id>]\n                   [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the channel to update\n    --bid=<bid>                              : (str) update amount backing the channel\n    --new_signing_key                        : (bool) generate a new signing key, will\n                                                invalidate all previous publishes\n    --clear_featured                         : (bool) clear existing featured content\n                                                (prior to adding new ones)\n    --email=<email>                          : (str) email of channel owner\n    --website_url=<website_url>              : (str) website url\n    --cover_url=<cover_url>                  : (str) url to cover image\n    --featured=<featured>                    : (str, list) claim_id(s) of featured content\n                                                in channel\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --replace                                : (bool) instead of modifying specific values\n                                                on the claim, this will clear all existing\n                                                values and only save passed in values,\n                                                useful for form submissions where all\n                                                values are always set\n    --clear_tags                             : (bool) clear existing tags (prior to adding\n                                                new ones)\n    --clear_languages                        : (bool) clear existing languages (prior to\n                                                adding new ones)\n    --clear_locations                        : (bool) clear existing locations (prior to\n                                                adding new ones)\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction updating the channel\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "claim_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my stream and channel claims."
                ],
                "usage": [
                    "    claim list [--account_id=<account_id>] [--wallet_id=<wallet_id>]",
                    "               [--is_spent] [--resolve] [--include_received_tips]"
                ],
                "kwargs": 15
            },
            "arguments": [
                {
                    "name": "claim_type",
                    "desc": [
                        "claim type: channel, stream, repost, collection"
                    ],
                    "type": "str"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "shows previous claim updates and abandons"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "resolve",
                    "desc": [
                        "resolves each claim to provide additional metadata"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_received_tips",
                    "desc": [
                        "calculate the amount of tips recieved for claim outputs"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "stream_type",
                    "desc": [
                        "filter by 'video', 'image', 'document', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "media_type",
                    "desc": [
                        "filter by 'video/mp4', 'image/png', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency# LBC, BTC, USD"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "duration",
                    "desc": [
                        "duration of video or audio in seconds (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel",
                    "desc": [
                        "signed by this channel (argument is",
                        "a URL which automatically gets resolved),",
                        "see --channel_id if you need to filter by",
                        "multiple channels at the same time,",
                        "includes results with invalid signatures,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "signed by any of these channels including invalid signatures,",
                        "implies --has_channel_signature,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_channel_id",
                    "desc": [
                        "exclude everything signed by any of these channels"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "has_channel_signature",
                    "desc": [
                        "results with a channel signature (valid or invalid)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "valid_channel_signature",
                    "desc": [
                        "results with a valid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with valid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "invalid_channel_signature",
                    "desc": [
                        "results with invalid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with invalid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "streams and channels in wallet"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "stream_type",
                    "desc": [
                        "filter by 'video', 'image', 'document', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "media_type",
                    "desc": [
                        "filter by 'video/mp4', 'image/png', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency# LBC, BTC, USD"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "duration",
                    "desc": [
                        "duration of video or audio in seconds (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel",
                    "desc": [
                        "signed by this channel (argument is",
                        "a URL which automatically gets resolved),",
                        "see --channel_id if you need to filter by",
                        "multiple channels at the same time,",
                        "includes results with invalid signatures,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "signed by any of these channels including invalid signatures,",
                        "implies --has_channel_signature,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_channel_id",
                    "desc": [
                        "exclude everything signed by any of these channels"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "has_channel_signature",
                    "desc": [
                        "results with a channel signature (valid or invalid)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "valid_channel_signature",
                    "desc": [
                        "results with a valid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with valid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "invalid_channel_signature",
                    "desc": [
                        "results with invalid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with invalid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "claim",
            "cli": "claim list",
            "help": "List my stream and channel claims.\n\nUsage:\n    claim list [--account_id=<account_id>] [--wallet_id=<wallet_id>]\n               [--is_spent] [--resolve] [--include_received_tips]\n               [--name=<name>...] [--claim_id=<claim_id>...] [--text=<text>]\n               [--txid=<txid>] [--nout=<nout>] [--height=<height>]\n               [--timestamp=<timestamp>] [--creation_height=<creation_height>]\n               [--creation_timestamp=<creation_timestamp>] [--amount=<amount>]\n               [--any_tag=<any_tag>...] [--all_tag=<all_tag>...] [--not_tag=<not_tag>...]\n               [--any_language=<any_language>...] [--all_language=<all_language>...]\n               [--not_language=<not_language>...] [--any_location=<any_location>...]\n               [--all_location=<all_location>...] [--not_location=<not_location>...]\n               [--release_time=<release_time>] [--stream_type=<stream_type>...]\n               [--media_type=<media_type>...] [--fee_currency=<fee_currency>]\n               [--fee_amount=<fee_amount>] [--duration=<duration>] [--channel=<channel>]\n               [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]\n               [--has_channel_signature] [--valid_channel_signature]\n               [--invalid_channel_signature] [--page=<page>] [--page_size=<page_size>]\n               [--include_total]\n\nOptions:\n    --claim_type=<claim_type>                  : (str) claim type: channel, stream,\n                                                  repost, collection\n    --account_id=<account_id>                  : (str) restrict operation to specific\n                                                  account, otherwise all accounts in wallet\n    --wallet_id=<wallet_id>                    : (str) restrict operation to specific\n                                                  wallet\n    --is_spent                                 : (bool) shows previous claim updates and\n                                                  abandons\n    --resolve                                  : (bool) resolves each claim to provide\n                                                  additional metadata\n    --include_received_tips                    : (bool) calculate the amount of tips\n                                                  recieved for claim outputs\n    --name=<name>                              : (str, list) claim name (normalized)\n    --claim_id=<claim_id>                      : (str, list) full or partial claim id\n    --text=<text>                              : (str) full text search\n    --txid=<txid>                              : (str) transaction id\n    --nout=<nout>                              : (int) position in the transaction\n    --height=<height>                          : (int) last updated block height (supports\n                                                  equality constraints)\n    --timestamp=<timestamp>                    : (int) last updated timestamp (supports\n                                                  equality constraints)\n    --creation_height=<creation_height>        : (int) created at block height (supports\n                                                  equality constraints)\n    --creation_timestamp=<creation_timestamp>  : (int) created at timestamp (supports\n                                                  equality constraints)\n    --amount=<amount>                          : (str) claim amount (supports equality\n                                                  constraints)\n    --any_tag=<any_tag>                        : (str, list) containing any of the tags\n    --all_tag=<all_tag>                        : (str, list) containing every tag\n    --not_tag=<not_tag>                        : (str, list) not containing any of these\n                                                  tags\n    --any_language=<any_language>              : (str, list) containing any of the\n                                                  languages\n    --all_language=<all_language>              : (str, list) containing every language\n    --not_language=<not_language>              : (str, list) not containing any of these\n                                                  languages\n    --any_location=<any_location>              : (str, list) containing any of the\n                                                  locations\n    --all_location=<all_location>              : (str, list) containing every location\n    --not_location=<not_location>              : (str, list) not containing any of these\n                                                  locations\n    --release_time=<release_time>              : (int) limit to claims self-described as\n                                                  having been released to the public on or\n                                                  after this UTC timestamp, when claim does\n                                                  not provide a release time the publish\n                                                  time is used instead (supports equality\n                                                  constraints)\n    --stream_type=<stream_type>                : (str, list) filter by 'video', 'image',\n                                                  'document', etc\n    --media_type=<media_type>                  : (str, list) filter by 'video/mp4',\n                                                  'image/png', etc\n    --fee_currency=<fee_currency>              : (str) specify fee currency# LBC, BTC, USD\n    --fee_amount=<fee_amount>                  : (str) content download fee (supports\n                                                  equality constraints)\n    --duration=<duration>                      : (int) duration of video or audio in\n                                                  seconds (supports equality constraints)\n    --channel=<channel>                        : (str) signed by this channel (argument is\n                                                  a URL which automatically gets resolved),\n                                                  see --channel_id if you need to filter by\n                                                  multiple channels at the same time,\n                                                  includes results with invalid signatures,\n                                                  use in conjunction with \"--\n                                                  valid_channel_signature\"\n    --channel_id=<channel_id>                  : (str, list) signed by any of these\n                                                  channels including invalid signatures,\n                                                  implies --has_channel_signature, use in\n                                                  conjunction with \"--\n                                                  valid_channel_signature\"\n    --not_channel_id=<not_channel_id>          : (str, list) exclude everything signed by\n                                                  any of these channels\n    --has_channel_signature                    : (bool) results with a channel signature\n                                                  (valid or invalid)\n    --valid_channel_signature                  : (bool) results with a valid channel\n                                                  signature or no signature, use in\n                                                  conjunction with --has_channel_signature\n                                                  to only get results with valid signatures\n    --invalid_channel_signature                : (bool) results with invalid channel\n                                                  signature or no signature, use in\n                                                  conjunction with --has_channel_signature\n                                                  to only get results with invalid\n                                                  signatures\n    --page=<page>                              : (int) page to return for paginating\n    --page_size=<page_size>                    : (int) number of items on page for\n                                                  pagination\n    --include_total                            : (bool) calculate total number of items\n                                                  and pages\n\nReturns:\n    (Paginated[Output]) streams and channels in wallet\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "claim_search": {
            "name": "search",
            "desc": {
                "text": [
                    "Search for stream and channel claims on the blockchain.",
                    "Arguments marked with \"supports equality constraints\" allow prepending the",
                    "value with an equality constraint such as '>', '>=', '<' and '<='",
                    "eg. --height=\">400000\" would limit results to only claims above 400k block height."
                ],
                "usage": [
                    "    claim search",
                    "                 [--is_controlling] [--public_key_id=<public_key_id>]",
                    "                 [--creation_height=<creation_height>]",
                    "                 [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]",
                    "                 [--effective_amount=<effective_amount>]",
                    "                 [--support_amount=<support_amount>] [--trending_group=<trending_group>]",
                    "                 [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]",
                    "                 [--trending_global=<trending_global]",
                    "                 [--reposted_claim_id=<reposted_claim_id>] [--reposted=<reposted>]",
                    "                 [--claim_type=<claim_type>] [--order_by=<order_by>...]",
                    "                 [--wallet_id=<wallet_id>] [--include_purchase_receipt] [--include_is_my_output]",
                    "                 [--protobuf]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet to check for claim purchase reciepts"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_type",
                    "desc": [
                        "claim type: channel, stream, repost, collection"
                    ],
                    "type": "str"
                },
                {
                    "name": "include_purchase_receipt",
                    "desc": [
                        "lookup and include a receipt if this wallet has purchased the claim"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_is_my_output",
                    "desc": [
                        "lookup and include a boolean indicating if claim being resolved is yours"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_controlling",
                    "desc": [
                        "winning claims of their respective name"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "activation_height",
                    "desc": [
                        "height at which claim starts competing for name",
                        "(supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "expiration_height",
                    "desc": [
                        "height at which claim will expire (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "support_amount",
                    "desc": [
                        "limit by supports and tips received (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "effective_amount",
                    "desc": [
                        "limit by total value (initial claim value plus all tips and supports",
                        "received), this amount is blank until claim has reached activation",
                        "height (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "trending_group",
                    "desc": [
                        "group numbers 1 through 4 representing the trending groups of the",
                        "content: 4 means content is trending globally and independently,",
                        "3 means content is not trending globally but is trending",
                        "independently (locally), 2 means it is trending globally but not",
                        "independently and 1 means it's not trending globally or locally (supports",
                        "equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "trending_mixed",
                    "desc": [
                        "trending amount taken from the global or local value depending on the",
                        "trending group: 4 - global value, 3 - local value, 2 - global value,",
                        "1 - local value (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "trending_local",
                    "desc": [
                        "trending value calculated relative only to the individual contents past",
                        "history (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "trending_global",
                    "desc": [
                        "trending value calculated relative to all trending content globally",
                        "(supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "public_key_id",
                    "desc": [
                        "only return channels having this public key id, this is the same key",
                        "as used in the wallet file to map channel certificate private keys:",
                        "{'public_key_id': 'private key'}"
                    ],
                    "type": "str"
                },
                {
                    "name": "reposted_claim_id",
                    "desc": [
                        "all reposts of the specified original claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "reposted",
                    "desc": [
                        "claims reposted this many times (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "order_by",
                    "desc": [
                        "field to order by, default is descending order, to do an ascending order",
                        "prepend ^ to the field name, eg. '^amount' available fields: 'name',",
                        "'height', 'release_time', 'publish_time', 'amount', 'effective_amount',",
                        "'support_amount', 'trending_group', 'trending_mixed', 'trending_local',",
                        "'trending_global', 'activation_height'"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "protobuf",
                    "desc": [
                        "protobuf encoded result"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "stream_type",
                    "desc": [
                        "filter by 'video', 'image', 'document', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "media_type",
                    "desc": [
                        "filter by 'video/mp4', 'image/png', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency# LBC, BTC, USD"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "duration",
                    "desc": [
                        "duration of video or audio in seconds (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel",
                    "desc": [
                        "signed by this channel (argument is",
                        "a URL which automatically gets resolved),",
                        "see --channel_id if you need to filter by",
                        "multiple channels at the same time,",
                        "includes results with invalid signatures,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "signed by any of these channels including invalid signatures,",
                        "implies --has_channel_signature,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_channel_id",
                    "desc": [
                        "exclude everything signed by any of these channels"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "has_channel_signature",
                    "desc": [
                        "results with a channel signature (valid or invalid)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "valid_channel_signature",
                    "desc": [
                        "results with a valid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with valid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "invalid_channel_signature",
                    "desc": [
                        "results with invalid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with invalid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "search results"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "stream_type",
                    "desc": [
                        "filter by 'video', 'image', 'document', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "media_type",
                    "desc": [
                        "filter by 'video/mp4', 'image/png', etc"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency# LBC, BTC, USD"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "duration",
                    "desc": [
                        "duration of video or audio in seconds (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel",
                    "desc": [
                        "signed by this channel (argument is",
                        "a URL which automatically gets resolved),",
                        "see --channel_id if you need to filter by",
                        "multiple channels at the same time,",
                        "includes results with invalid signatures,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "signed by any of these channels including invalid signatures,",
                        "implies --has_channel_signature,",
                        "use in conjunction with \"--valid_channel_signature\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_channel_id",
                    "desc": [
                        "exclude everything signed by any of these channels"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "has_channel_signature",
                    "desc": [
                        "results with a channel signature (valid or invalid)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "valid_channel_signature",
                    "desc": [
                        "results with a valid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with valid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "invalid_channel_signature",
                    "desc": [
                        "results with invalid channel signature or no signature,",
                        "use in conjunction with --has_channel_signature to",
                        "only get results with invalid signatures"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "claim",
            "cli": "claim search",
            "help": "Search for stream and channel claims on the blockchain.\nArguments marked with \"supports equality constraints\" allow prepending the\nvalue with an equality constraint such as '>', '>=', '<' and '<='\neg. --height=\">400000\" would limit results to only claims above 400k block height.\n\nUsage:\n    claim search\n                 [--is_controlling] [--public_key_id=<public_key_id>]\n                 [--creation_height=<creation_height>]\n                 [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]\n                 [--effective_amount=<effective_amount>]\n                 [--support_amount=<support_amount>] [--trending_group=<trending_group>]\n                 [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]\n                 [--trending_global=<trending_global]\n                 [--reposted_claim_id=<reposted_claim_id>] [--reposted=<reposted>]\n                 [--claim_type=<claim_type>] [--order_by=<order_by>...]\n                 [--wallet_id=<wallet_id>] [--include_purchase_receipt] [--include_is_my_output]\n                 [--protobuf]\n                 [--name=<name>...] [--claim_id=<claim_id>...] [--text=<text>]\n                 [--txid=<txid>] [--nout=<nout>] [--height=<height>]\n                 [--timestamp=<timestamp>] [--creation_height=<creation_height>]\n                 [--creation_timestamp=<creation_timestamp>] [--amount=<amount>]\n                 [--any_tag=<any_tag>...] [--all_tag=<all_tag>...]\n                 [--not_tag=<not_tag>...] [--any_language=<any_language>...]\n                 [--all_language=<all_language>...] [--not_language=<not_language>...]\n                 [--any_location=<any_location>...] [--all_location=<all_location>...]\n                 [--not_location=<not_location>...] [--release_time=<release_time>]\n                 [--stream_type=<stream_type>...] [--media_type=<media_type>...]\n                 [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]\n                 [--duration=<duration>] [--channel=<channel>]\n                 [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]\n                 [--has_channel_signature] [--valid_channel_signature]\n                 [--invalid_channel_signature] [--page=<page>] [--page_size=<page_size>]\n                 [--include_total]\n\nOptions:\n    --wallet_id=<wallet_id>                    : (str) wallet to check for claim purchase\n                                                  reciepts\n    --claim_type=<claim_type>                  : (str) claim type: channel, stream,\n                                                  repost, collection\n    --include_purchase_receipt                 : (bool) lookup and include a receipt if\n                                                  this wallet has purchased the claim\n    --include_is_my_output                     : (bool) lookup and include a boolean\n                                                  indicating if claim being resolved is\n                                                  yours\n    --is_controlling                           : (bool) winning claims of their respective\n                                                  name\n    --activation_height=<activation_height>    : (int) height at which claim starts\n                                                  competing for name (supports equality\n                                                  constraints)\n    --expiration_height=<expiration_height>    : (int) height at which claim will expire\n                                                  (supports equality constraints)\n    --support_amount=<support_amount>          : (str) limit by supports and tips received\n                                                  (supports equality constraints)\n    --effective_amount=<effective_amount>      : (str) limit by total value (initial claim\n                                                  value plus all tips and supports\n                                                  received), this amount is blank until\n                                                  claim has reached activation height\n                                                  (supports equality constraints)\n    --trending_group=<trending_group>          : (int) group numbers 1 through 4\n                                                  representing the trending groups of the\n                                                  content: 4 means content is trending\n                                                  globally and independently, 3 means\n                                                  content is not trending globally but is\n                                                  trending independently (locally), 2 means\n                                                  it is trending globally but not\n                                                  independently and 1 means it's not\n                                                  trending globally or locally (supports\n                                                  equality constraints)\n    --trending_mixed=<trending_mixed>          : (int) trending amount taken from the\n                                                  global or local value depending on the\n                                                  trending group: 4 - global value, 3 -\n                                                  local value, 2 - global value, 1 - local\n                                                  value (supports equality constraints)\n    --trending_local=<trending_local>          : (int) trending value calculated relative\n                                                  only to the individual contents past\n                                                  history (supports equality constraints)\n    --trending_global=<trending_global>        : (int) trending value calculated relative\n                                                  to all trending content globally\n                                                  (supports equality constraints)\n    --public_key_id=<public_key_id>            : (str) only return channels having this\n                                                  public key id, this is the same key as\n                                                  used in the wallet file to map channel\n                                                  certificate private keys:\n                                                  {'public_key_id': 'private key'}\n    --reposted_claim_id=<reposted_claim_id>    : (str) all reposts of the specified\n                                                  original claim id\n    --reposted=<reposted>                      : (int) claims reposted this many times\n                                                  (supports equality constraints)\n    --order_by=<order_by>                      : (str, list) field to order by, default is\n                                                  descending order, to do an ascending\n                                                  order prepend ^ to the field name, eg.\n                                                  '^amount' available fields: 'name',\n                                                  'height', 'release_time', 'publish_time',\n                                                  'amount', 'effective_amount',\n                                                  'support_amount', 'trending_group',\n                                                  'trending_mixed', 'trending_local',\n                                                  'trending_global', 'activation_height'\n    --protobuf                                 : (bool) protobuf encoded result\n    --name=<name>                              : (str, list) claim name (normalized)\n    --claim_id=<claim_id>                      : (str, list) full or partial claim id\n    --text=<text>                              : (str) full text search\n    --txid=<txid>                              : (str) transaction id\n    --nout=<nout>                              : (int) position in the transaction\n    --height=<height>                          : (int) last updated block height (supports\n                                                  equality constraints)\n    --timestamp=<timestamp>                    : (int) last updated timestamp (supports\n                                                  equality constraints)\n    --creation_height=<creation_height>        : (int) created at block height (supports\n                                                  equality constraints)\n    --creation_timestamp=<creation_timestamp>  : (int) created at timestamp (supports\n                                                  equality constraints)\n    --amount=<amount>                          : (str) claim amount (supports equality\n                                                  constraints)\n    --any_tag=<any_tag>                        : (str, list) containing any of the tags\n    --all_tag=<all_tag>                        : (str, list) containing every tag\n    --not_tag=<not_tag>                        : (str, list) not containing any of these\n                                                  tags\n    --any_language=<any_language>              : (str, list) containing any of the\n                                                  languages\n    --all_language=<all_language>              : (str, list) containing every language\n    --not_language=<not_language>              : (str, list) not containing any of these\n                                                  languages\n    --any_location=<any_location>              : (str, list) containing any of the\n                                                  locations\n    --all_location=<all_location>              : (str, list) containing every location\n    --not_location=<not_location>              : (str, list) not containing any of these\n                                                  locations\n    --release_time=<release_time>              : (int) limit to claims self-described as\n                                                  having been released to the public on or\n                                                  after this UTC timestamp, when claim does\n                                                  not provide a release time the publish\n                                                  time is used instead (supports equality\n                                                  constraints)\n    --stream_type=<stream_type>                : (str, list) filter by 'video', 'image',\n                                                  'document', etc\n    --media_type=<media_type>                  : (str, list) filter by 'video/mp4',\n                                                  'image/png', etc\n    --fee_currency=<fee_currency>              : (str) specify fee currency# LBC, BTC, USD\n    --fee_amount=<fee_amount>                  : (str) content download fee (supports\n                                                  equality constraints)\n    --duration=<duration>                      : (int) duration of video or audio in\n                                                  seconds (supports equality constraints)\n    --channel=<channel>                        : (str) signed by this channel (argument is\n                                                  a URL which automatically gets resolved),\n                                                  see --channel_id if you need to filter by\n                                                  multiple channels at the same time,\n                                                  includes results with invalid signatures,\n                                                  use in conjunction with \"--\n                                                  valid_channel_signature\"\n    --channel_id=<channel_id>                  : (str, list) signed by any of these\n                                                  channels including invalid signatures,\n                                                  implies --has_channel_signature, use in\n                                                  conjunction with \"--\n                                                  valid_channel_signature\"\n    --not_channel_id=<not_channel_id>          : (str, list) exclude everything signed by\n                                                  any of these channels\n    --has_channel_signature                    : (bool) results with a channel signature\n                                                  (valid or invalid)\n    --valid_channel_signature                  : (bool) results with a valid channel\n                                                  signature or no signature, use in\n                                                  conjunction with --has_channel_signature\n                                                  to only get results with valid signatures\n    --invalid_channel_signature                : (bool) results with invalid channel\n                                                  signature or no signature, use in\n                                                  conjunction with --has_channel_signature\n                                                  to only get results with invalid\n                                                  signatures\n    --page=<page>                              : (int) page to return for paginating\n    --page_size=<page_size>                    : (int) number of items on page for\n                                                  pagination\n    --include_total                            : (bool) calculate total number of items\n                                                  and pages\n\nReturns:\n    (Paginated[Output]) search results\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "collection_abandon": {
            "name": "abandon",
            "desc": {
                "text": [
                    "Abandon one of my collection claims."
                ],
                "usage": [
                    "    collection abandon"
                ],
                "kwargs": 23
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction abandoning the collection"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "collection",
            "cli": "collection abandon",
            "help": "Abandon one of my collection claims.\n\nUsage:\n    collection abandon\n                       [--claim_id=<claim_id>] [--txid=<txid>] [--nout=<nout>]\n                       [--account_id=<account_id>]\n                       [--change_account_id=<change_account_id>]\n                       [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the claim to abandon\n    --txid=<txid>                            : (str) txid of the claim to abandon\n    --nout=<nout>                            : (int) nout of the claim to abandon\n                                                [default: 0]\n    --account_id=<account_id>                : (str) restrict operation to specific\n                                                account, otherwise all accounts in wallet\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction abandoning the collection\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "collection_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create a new collection."
                ],
                "usage": [
                    "    collection create (<name> | --name=<name>) (<bid> | --bid=<bid>)",
                    "                      (<claims>... | --claims=<claims>...) [--allow_duplicate_name]"
                ],
                "kwargs": 22
            },
            "arguments": [
                {
                    "name": "name",
                    "desc": [
                        "name for the stream (can only consist of a-z A-Z 0-9 and -(dash))"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the content"
                    ],
                    "type": "str"
                },
                {
                    "name": "claims",
                    "desc": [
                        "claim ids to be included in the collection"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "allow_duplicate_name",
                    "desc": [
                        "create new collection even if one already exists with given name"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "collection",
            "cli": "collection create",
            "help": "Create a new collection.\n\nUsage:\n    collection create (<name> | --name=<name>) (<bid> | --bid=<bid>)\n                      (<claims>... | --claims=<claims>...) [--allow_duplicate_name]\n                      [--title=<title>] [--description=<description>]\n                      [--thumbnail_url=<thumbnail_url>] [--tag=<tag>...]\n                      [--language=<language>...] [--location=<location>...]\n                      [--account_id=<account_id>] [--claim_address=<claim_address>]\n                      [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n                      [--change_account_id=<change_account_id>]\n                      [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --name=<name>                            : (str) name for the stream (can only consist\n                                                of a-z A-Z 0-9 and -(dash))\n    --bid=<bid>                              : (str) amount to back the content\n    --claims=<claims>                        : (str, list) claim ids to be included in the\n                                                collection\n    --allow_duplicate_name                   : (bool) create new collection even if one\n                                                already exists with given name\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) \n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "collection_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my collection claims."
                ],
                "usage": [
                    "    collection list [--resolve_claims=<resolve_claims>]",
                    "                    [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 20
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "resolve_claims",
                    "desc": [
                        "resolve this number of items in the collection"
                    ],
                    "default": 0,
                    "type": "int"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "collection",
            "cli": "collection list",
            "help": "List my collection claims.\n\nUsage:\n    collection list [--resolve_claims=<resolve_claims>]\n                    [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n                    [--name=<name>...] [--claim_id=<claim_id>...] [--text=<text>]\n                    [--txid=<txid>] [--nout=<nout>] [--height=<height>]\n                    [--timestamp=<timestamp>] [--creation_height=<creation_height>]\n                    [--creation_timestamp=<creation_timestamp>] [--amount=<amount>]\n                    [--any_tag=<any_tag>...] [--all_tag=<all_tag>...]\n                    [--not_tag=<not_tag>...] [--any_language=<any_language>...]\n                    [--all_language=<all_language>...] [--not_language=<not_language>...]\n                    [--any_location=<any_location>...] [--all_location=<all_location>...]\n                    [--not_location=<not_location>...] [--release_time=<release_time>]\n                    [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --account_id=<account_id>                  : (str) restrict operation to specific\n                                                  account\n    --wallet_id=<wallet_id>                    : (str) restrict operation to specific\n                                                  wallet\n    --resolve_claims=<resolve_claims>          : (int) resolve this number of items in the\n                                                  collection [default: 0]\n    --name=<name>                              : (str, list) claim name (normalized)\n    --claim_id=<claim_id>                      : (str, list) full or partial claim id\n    --text=<text>                              : (str) full text search\n    --txid=<txid>                              : (str) transaction id\n    --nout=<nout>                              : (int) position in the transaction\n    --height=<height>                          : (int) last updated block height (supports\n                                                  equality constraints)\n    --timestamp=<timestamp>                    : (int) last updated timestamp (supports\n                                                  equality constraints)\n    --creation_height=<creation_height>        : (int) created at block height (supports\n                                                  equality constraints)\n    --creation_timestamp=<creation_timestamp>  : (int) created at timestamp (supports\n                                                  equality constraints)\n    --amount=<amount>                          : (str) claim amount (supports equality\n                                                  constraints)\n    --any_tag=<any_tag>                        : (str, list) containing any of the tags\n    --all_tag=<all_tag>                        : (str, list) containing every tag\n    --not_tag=<not_tag>                        : (str, list) not containing any of these\n                                                  tags\n    --any_language=<any_language>              : (str, list) containing any of the\n                                                  languages\n    --all_language=<all_language>              : (str, list) containing every language\n    --not_language=<not_language>              : (str, list) not containing any of these\n                                                  languages\n    --any_location=<any_location>              : (str, list) containing any of the\n                                                  locations\n    --all_location=<all_location>              : (str, list) containing every location\n    --not_location=<not_location>              : (str, list) not containing any of these\n                                                  locations\n    --release_time=<release_time>              : (int) limit to claims self-described as\n                                                  having been released to the public on or\n                                                  after this UTC timestamp, when claim does\n                                                  not provide a release time the publish\n                                                  time is used instead (supports equality\n                                                  constraints)\n    --page=<page>                              : (int) page to return for paginating\n    --page_size=<page_size>                    : (int) number of items on page for\n                                                  pagination\n    --include_total                            : (bool) calculate total number of items\n                                                  and pages\n\nReturns:\n    (Paginated[Output]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "collection_resolve": {
            "name": "resolve",
            "desc": {
                "text": [
                    "Resolve claims in the collection."
                ],
                "usage": [
                    "    collection resolve (--claim_id=<claim_id> | --url=<url>) [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 23
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id of the collection"
                    ],
                    "type": "str"
                },
                {
                    "name": "url",
                    "desc": [
                        "url of the collection"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "resolved items in the collection"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "collection",
            "cli": "collection resolve",
            "help": "Resolve claims in the collection.\n\nUsage:\n    collection resolve (--claim_id=<claim_id> | --url=<url>) [--wallet_id=<wallet_id>]\n                       [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --claim_id=<claim_id>    : (str) claim id of the collection\n    --url=<url>              : (str) url of the collection\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n    --page=<page>            : (int) page to return for paginating\n    --page_size=<page_size>  : (int) number of items on page for pagination\n    --include_total          : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) resolved items in the collection\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "collection_update": {
            "name": "update",
            "desc": {
                "text": [
                    "Update an existing collection claim."
                ],
                "usage": [
                    "    collection update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]",
                    "                      [--claims=<claims>...] [--clear_claims]"
                ],
                "kwargs": 22
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the collection to update"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the collection"
                    ],
                    "type": "str"
                },
                {
                    "name": "claims",
                    "desc": [
                        "claim ids to be included in the collection"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "clear_claims",
                    "desc": [
                        "clear existing claims (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "updated collection transaction"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "collection",
            "cli": "collection update",
            "help": "Update an existing collection claim.\n\nUsage:\n    collection update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]\n                      [--claims=<claims>...] [--clear_claims]\n                      [--title=<title>] [--description=<description>]\n                      [--thumbnail_url=<thumbnail_url>] [--tag=<tag>...]\n                      [--language=<language>...] [--location=<location>...]\n                      [--account_id=<account_id>] [--claim_address=<claim_address>]\n                      [--replace] [--clear_tags] [--clear_languages] [--clear_locations]\n                      [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n                      [--change_account_id=<change_account_id>]\n                      [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the collection to update\n    --bid=<bid>                              : (str) amount to back the collection\n    --claims=<claims>                        : (str, list) claim ids to be included in the\n                                                collection\n    --clear_claims                           : (bool) clear existing claims (prior to\n                                                adding new ones)\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --replace                                : (bool) instead of modifying specific values\n                                                on the claim, this will clear all existing\n                                                values and only save passed in values,\n                                                useful for form submissions where all\n                                                values are always set\n    --clear_tags                             : (bool) clear existing tags (prior to adding\n                                                new ones)\n    --clear_languages                        : (bool) clear existing languages (prior to\n                                                adding new ones)\n    --clear_locations                        : (bool) clear existing locations (prior to\n                                                adding new ones)\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) updated collection transaction\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "comment_abandon": {
            "name": "abandon",
            "desc": {
                "text": [
                    "Abandon a comment published under your channel identity."
                ],
                "usage": [
                    "    comment abandon  (<comment_id> | --comment_id=<comment_id>) [--wallet_id=<wallet_id>]"
                ],
                "returns": [
                    "    {",
                    "        <comment_id> (str): {",
                    "            \"abandoned\": (bool)",
                    "        }",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "comment_id",
                    "desc": [
                        "The ID of the comment to be abandoned."
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "Object with the `comment_id` passed in as the key, and a flag indicating if it was abandoned"
                ],
                "type": "dict"
            },
            "group": "comment",
            "cli": "comment abandon",
            "help": "Abandon a comment published under your channel identity.\n\nUsage:\n    comment abandon  (<comment_id> | --comment_id=<comment_id>) [--wallet_id=<wallet_id>]\n\nOptions:\n    --comment_id=<comment_id>  : (str) The ID of the comment to be abandoned.\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) Object with the `comment_id` passed in as the key, and a flag indicating if it was abandoned\n    {\n        <comment_id> (str): {\n            \"abandoned\": (bool)\n        }\n    }"
        },
        "comment_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create and associate a comment with a claim using your channel identity."
                ],
                "usage": [
                    "    comment create  (<comment> | --comment=<comment>)",
                    "                    (<claim_id> | --claim_id=<claim_id> | --parent_id=<parent_id>)",
                    "                    [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 20,
                "returns": [
                    "    {",
                    "        \"comment\":      (str) The actual string as inputted by the user,",
                    "        \"comment_id\":   (str) The Comment's unique identifier,",
                    "        \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',",
                    "        \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,",
                    "        \"signature\":    (str) The signature of the comment,",
                    "        \"signing_ts\":   (str) The timestamp used to sign the comment,",
                    "        \"channel_url\":  (str) Channel's URI in the ClaimTrie,",
                    "        \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,",
                    "        \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "comment",
                    "desc": [
                        "Comment to be made, should be at most 2000 characters."
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "The ID of the claim to comment on"
                    ],
                    "type": "str"
                },
                {
                    "name": "parent_id",
                    "desc": [
                        "The ID of a comment to make a response to"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "Comment object if successfully made, (None) otherwise"
                ],
                "type": "dict"
            },
            "kwargs": [
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                }
            ],
            "group": "comment",
            "cli": "comment create",
            "help": "Create and associate a comment with a claim using your channel identity.\n\nUsage:\n    comment create  (<comment> | --comment=<comment>)\n                    (<claim_id> | --claim_id=<claim_id> | --parent_id=<parent_id>)\n                    [--wallet_id=<wallet_id>]\n                    [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n\nOptions:\n    --comment=<comment>            : (str) Comment to be made, should be at most 2000\n                                      characters.\n    --claim_id=<claim_id>          : (str) The ID of the claim to comment on\n    --parent_id=<parent_id>        : (str) The ID of a comment to make a response to\n    --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet\n    --channel_id=<channel_id>      : (str) claim id of the publishing channel\n    --channel_name=<channel_name>  : (str) name of publishing channel\n\nReturns:\n    (dict) Comment object if successfully made, (None) otherwise\n    {\n        \"comment\":      (str) The actual string as inputted by the user,\n        \"comment_id\":   (str) The Comment's unique identifier,\n        \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',\n        \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,\n        \"signature\":    (str) The signature of the comment,\n        \"signing_ts\":   (str) The timestamp used to sign the comment,\n        \"channel_url\":  (str) Channel's URI in the ClaimTrie,\n        \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,\n        \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.\n    }"
        },
        "comment_hide": {
            "name": "hide",
            "desc": {
                "text": [
                    "Hide a comment published to a claim you control."
                ],
                "usage": [
                    "    comment hide  <comment_ids>... [--wallet_id=<wallet_id>]"
                ],
                "returns": [
                    "    '<comment_id>': {",
                    "        \"hidden\": (bool)  flag indicating if comment_id was hidden",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "comment_ids",
                    "desc": [
                        "one or more comment_id to hide."
                    ],
                    "type": "str, list"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "keyed by comment_id, containing success info"
                ],
                "type": "dict"
            },
            "group": "comment",
            "cli": "comment hide",
            "help": "Hide a comment published to a claim you control.\n\nUsage:\n    comment hide  <comment_ids>... [--wallet_id=<wallet_id>]\n\nOptions:\n    --comment_ids=<comment_ids>  : (str, list) one or more comment_id to hide.\n    --wallet_id=<wallet_id>      : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) keyed by comment_id, containing success info\n    '<comment_id>': {\n        \"hidden\": (bool)  flag indicating if comment_id was hidden\n    }"
        },
        "comment_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List comments associated with a claim."
                ],
                "usage": [
                    "    comment list (<claim_id> | --claim_id=<claim_id>)",
                    "                 [(--page=<page> --page_size=<page_size>)]",
                    "                 [--parent_id=<parent_id>] [--include_replies]",
                    "                 [--is_channel_signature_valid]",
                    "                 [--visible | --hidden]"
                ],
                "returns": [
                    "    {",
                    "        \"page\": \"Page number of the current items.\",",
                    "        \"page_size\": \"Number of items to show on a page.\",",
                    "        \"total_pages\": \"Total number of pages.\",",
                    "        \"total_items\": \"Total number of items.\",",
                    "        \"items\": \"A List of dict objects representing comments.\"",
                    "        [",
                    "            {",
                    "                \"comment\":      (str) The actual string as inputted by the user,",
                    "                \"comment_id\":   (str) The Comment's unique identifier,",
                    "                \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',",
                    "                \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,",
                    "                \"signature\":    (str) The signature of the comment,",
                    "                \"channel_url\":  (str) Channel's URI in the ClaimTrie,",
                    "                \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,",
                    "                \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.",
                    "            },",
                    "            ...",
                    "        ]",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "The claim on which the comment will be made on"
                    ],
                    "type": "str"
                },
                {
                    "name": "parent_id",
                    "desc": [
                        "CommentId of a specific thread you'd like to see"
                    ],
                    "type": "str"
                },
                {
                    "name": "include_replies",
                    "desc": [
                        "Whether or not you want to include replies in list"
                    ],
                    "default": True,
                    "type": "bool"
                },
                {
                    "name": "is_channel_signature_valid",
                    "desc": [
                        "Only include comments with valid signatures.",
                        "[Warning: Paginated total size will not change, even if list reduces]"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "hidden",
                    "desc": [
                        "Select only Hidden Comments"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "visible",
                    "desc": [
                        "Select only Visible Comments"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [],
                    "default": 1,
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [],
                    "default": 50,
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "Containing the list, and information about the paginated content"
                ],
                "type": "dict"
            },
            "group": "comment",
            "cli": "comment list",
            "help": "List comments associated with a claim.\n\nUsage:\n    comment list (<claim_id> | --claim_id=<claim_id>)\n                 [(--page=<page> --page_size=<page_size>)]\n                 [--parent_id=<parent_id>] [--include_replies]\n                 [--is_channel_signature_valid]\n                 [--visible | --hidden]\n\nOptions:\n    --claim_id=<claim_id>         : (str) The claim on which the comment will be made on\n    --parent_id=<parent_id>       : (str) CommentId of a specific thread you'd like to see\n    --include_replies             : (bool) Whether or not you want to include replies in\n                                     list\n    --is_channel_signature_valid  : (bool) Only include comments with valid signatures.\n                                     [Warning: Paginated total size will not change, even\n                                     if list reduces]\n    --hidden                      : (bool) Select only Hidden Comments\n    --visible                     : (bool) Select only Visible Comments\n    --page=<page>                 : (int)  [default: 1]\n    --page_size=<page_size>       : (int)  [default: 50]\n\nReturns:\n    (dict) Containing the list, and information about the paginated content\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": \"A List of dict objects representing comments.\"\n        [\n            {\n                \"comment\":      (str) The actual string as inputted by the user,\n                \"comment_id\":   (str) The Comment's unique identifier,\n                \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',\n                \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,\n                \"signature\":    (str) The signature of the comment,\n                \"channel_url\":  (str) Channel's URI in the ClaimTrie,\n                \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,\n                \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.\n            },\n            ...\n        ]\n    }"
        },
        "comment_update": {
            "name": "update",
            "desc": {
                "text": [
                    "Edit a comment published as one of your channels."
                ],
                "usage": [
                    "    comment update (<comment> | --comment=<comment>)",
                    "                 (<comment_id> | --comment_id=<comment_id>)",
                    "                 [--wallet_id=<wallet_id>]"
                ],
                "returns": [
                    "    {",
                    "        \"comment\":      (str) The actual string as inputted by the user,",
                    "        \"comment_id\":   (str) The Comment's unique identifier,",
                    "        \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',",
                    "        \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,",
                    "        \"signature\":    (str) The signature of the comment,",
                    "        \"signing_ts\":   (str) Timestamp used to sign the most recent signature,",
                    "        \"channel_url\":  (str) Channel's URI in the ClaimTrie,",
                    "        \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,",
                    "        \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "comment",
                    "desc": [
                        "New comment replacing the old one"
                    ],
                    "type": "str"
                },
                {
                    "name": "comment_id",
                    "desc": [
                        "Hash identifying the comment to edit"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "Comment object if edit was successful, (None) otherwise"
                ],
                "type": "dict"
            },
            "group": "comment",
            "cli": "comment update",
            "help": "Edit a comment published as one of your channels.\n\nUsage:\n    comment update (<comment> | --comment=<comment>)\n                 (<comment_id> | --comment_id=<comment_id>)\n                 [--wallet_id=<wallet_id>]\n\nOptions:\n    --comment=<comment>        : (str) New comment replacing the old one\n    --comment_id=<comment_id>  : (str) Hash identifying the comment to edit\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) Comment object if edit was successful, (None) otherwise\n    {\n        \"comment\":      (str) The actual string as inputted by the user,\n        \"comment_id\":   (str) The Comment's unique identifier,\n        \"channel_name\": (str) Name of the channel this was posted under, prepended with a '@',\n        \"channel_id\":   (str) The Channel Claim ID that this comment was posted under,\n        \"signature\":    (str) The signature of the comment,\n        \"signing_ts\":   (str) Timestamp used to sign the most recent signature,\n        \"channel_url\":  (str) Channel's URI in the ClaimTrie,\n        \"parent_id\":    (str) Comment this is replying to, (None) if this is the root,\n        \"timestamp\":    (int) The time at which comment was entered into the server at, in nanoseconds.\n    }"
        },
        "ffmpeg_find": {
            "name": "ffmpeg_find",
            "desc": {
                "text": [
                    "Get ffmpeg installation information"
                ],
                "returns": [
                    "    {",
                    "        'available': (bool) found ffmpeg,",
                    "        'which': (str) path to ffmpeg,",
                    "        'analyze_audio_volume': (bool) should ffmpeg analyze audio",
                    "    }"
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "ffmpeg information"
                ],
                "type": "dict"
            },
            "cli": "ffmpeg_find",
            "help": "Get ffmpeg installation information\n\nUsage:\n    ffmpeg_find\n\nReturns:\n    (dict) ffmpeg information\n    {\n        'available': (bool) found ffmpeg,\n        'which': (str) path to ffmpeg,\n        'analyze_audio_volume': (bool) should ffmpeg analyze audio\n    }"
        },
        "file_delete": {
            "name": "delete",
            "desc": {
                "text": [
                    "Delete a LBRY file"
                ],
                "usage": [
                    "    file delete [--delete_from_download_dir] [--delete_all]"
                ],
                "kwargs": 16
            },
            "arguments": [
                {
                    "name": "delete_from_download_dir",
                    "desc": [
                        "delete file from download directory, instead of just deleting blobs"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "delete_all",
                    "desc": [
                        "if there are multiple matching files, allow the deletion of multiple files.",
                        "otherwise do not delete anything."
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "true if deletion was successful"
                ],
                "type": "bool"
            },
            "kwargs": [
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "group": "file",
            "cli": "file delete",
            "help": "Delete a LBRY file\n\nUsage:\n    file delete [--delete_from_download_dir] [--delete_all]\n                [--sd_hash=<sd_hash>] [--file_name=<file_name>]\n                [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--added_on=<added_on>]\n                [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>]\n                [--nout=<nout>] [--channel_claim_id=<channel_claim_id>]\n                [--channel_name=<channel_name>] [--claim_name=<claim_name>]\n                [--blobs_in_stream=<blobs_in_stream>]\n                [--blobs_remaining=<blobs_remaining>]\n\nOptions:\n    --delete_from_download_dir             : (bool) delete file from download directory,\n                                              instead of just deleting blobs\n    --delete_all                           : (bool) if there are multiple matching files,\n                                              allow the deletion of multiple files.\n                                              otherwise do not delete anything.\n    --sd_hash=<sd_hash>                    : (str) filter by sd hash\n    --file_name=<file_name>                : (str) filter by file name\n    --stream_hash=<stream_hash>            : (str) filter by stream hash\n    --rowid=<rowid>                        : (int) filter by row id\n    --added_on=<added_on>                  : (int) filter by time of insertion\n    --claim_id=<claim_id>                  : (str) filter by claim id\n    --outpoint=<outpoint>                  : (str) filter by claim outpoint\n    --txid=<txid>                          : (str) filter by claim txid\n    --nout=<nout>                          : (int) filter by claim nout\n    --channel_claim_id=<channel_claim_id>  : (str) filter by channel claim id\n    --channel_name=<channel_name>          : (str) filter by channel name\n    --claim_name=<claim_name>              : (str) filter by claim name\n    --blobs_in_stream=<blobs_in_stream>    : (int) filter by blobs in stream\n    --blobs_remaining=<blobs_remaining>    : (int) filter by number of remaining blobs to\n                                              download\n\nReturns:\n    (bool) true if deletion was successful"
        },
        "file_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List files limited by optional filters"
                ],
                "usage": [
                    "    file list [--wallet_id=<wallet_id>]",
                    "              [--sort=<sort_by>] [--reverse] [--comparison=<comparison>]"
                ],
                "kwargs": 14
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "add purchase receipts from this wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "sort",
                    "desc": [
                        "field to sort by"
                    ],
                    "type": "str"
                },
                {
                    "name": "reverse",
                    "desc": [
                        "reverse sort order"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "comparison",
                    "desc": [
                        "logical comparison, (eq|ne|g|ge|l|le)"
                    ],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[ManagedStream]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "streaming_url": "(str) url to stream the file using range requests",
                            "completed": "(bool) true if download is completed",
                            "file_name": "(str) name of file",
                            "download_directory": "(str) download directory",
                            "points_paid": "(float) credit paid to download file",
                            "stopped": "(bool) true if download is stopped",
                            "stream_hash": "(str) stream hash of file",
                            "stream_name": "(str) stream name",
                            "suggested_file_name": "(str) suggested file name",
                            "sd_hash": "(str) sd hash of file",
                            "download_path": "(str) download path of file",
                            "mime_type": "(str) mime type of file",
                            "key": "(str) key attached to file",
                            "total_bytes_lower_bound": "(int) lower bound file size in bytes",
                            "total_bytes": "(int) file upper bound size in bytes",
                            "written_bytes": "(int) written size in bytes",
                            "blobs_completed": "(int) number of fully downloaded blobs",
                            "blobs_in_stream": "(int) total blobs on stream",
                            "blobs_remaining": "(int) total blobs remaining to download",
                            "status": "(str) downloader status",
                            "claim_id": "(str) None if claim is not found else the claim id",
                            "txid": "(str) None if claim is not found else the transaction id",
                            "nout": "(int) None if claim is not found else the transaction output index",
                            "outpoint": "(str) None if claim is not found else the tx and output",
                            "metadata": "(dict) None if claim is not found else the claim metadata",
                            "channel_claim_id": "(str) None if claim is not found or not signed",
                            "channel_name": "(str) None if claim is not found or not signed",
                            "claim_name": "(str) None if claim is not found else the claim name"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "file",
            "cli": "file list",
            "help": "List files limited by optional filters\n\nUsage:\n    file list [--wallet_id=<wallet_id>]\n              [--sort=<sort_by>] [--reverse] [--comparison=<comparison>]\n              [--sd_hash=<sd_hash>] [--file_name=<file_name>]\n              [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--added_on=<added_on>]\n              [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>]\n              [--nout=<nout>] [--channel_claim_id=<channel_claim_id>]\n              [--channel_name=<channel_name>] [--claim_name=<claim_name>]\n              [--blobs_in_stream=<blobs_in_stream>] [--blobs_remaining=<blobs_remaining>]\n              [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --wallet_id=<wallet_id>                : (str) add purchase receipts from this wallet\n    --sort=<sort>                          : (str) field to sort by\n    --reverse                              : (bool) reverse sort order\n    --comparison=<comparison>              : (str) logical comparison, (eq|ne|g|ge|l|le)\n    --sd_hash=<sd_hash>                    : (str) filter by sd hash\n    --file_name=<file_name>                : (str) filter by file name\n    --stream_hash=<stream_hash>            : (str) filter by stream hash\n    --rowid=<rowid>                        : (int) filter by row id\n    --added_on=<added_on>                  : (int) filter by time of insertion\n    --claim_id=<claim_id>                  : (str) filter by claim id\n    --outpoint=<outpoint>                  : (str) filter by claim outpoint\n    --txid=<txid>                          : (str) filter by claim txid\n    --nout=<nout>                          : (int) filter by claim nout\n    --channel_claim_id=<channel_claim_id>  : (str) filter by channel claim id\n    --channel_name=<channel_name>          : (str) filter by channel name\n    --claim_name=<claim_name>              : (str) filter by claim name\n    --blobs_in_stream=<blobs_in_stream>    : (int) filter by blobs in stream\n    --blobs_remaining=<blobs_remaining>    : (int) filter by number of remaining blobs to\n                                              download\n    --page=<page>                          : (int) page to return for paginating\n    --page_size=<page_size>                : (int) number of items on page for pagination\n    --include_total                        : (bool) calculate total number of items and\n                                              pages\n\nReturns:\n    (Paginated[ManagedStream]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"streaming_url\": \"(str) url to stream the file using range requests\",\n                \"completed\": \"(bool) true if download is completed\",\n                \"file_name\": \"(str) name of file\",\n                \"download_directory\": \"(str) download directory\",\n                \"points_paid\": \"(float) credit paid to download file\",\n                \"stopped\": \"(bool) true if download is stopped\",\n                \"stream_hash\": \"(str) stream hash of file\",\n                \"stream_name\": \"(str) stream name\",\n                \"suggested_file_name\": \"(str) suggested file name\",\n                \"sd_hash\": \"(str) sd hash of file\",\n                \"download_path\": \"(str) download path of file\",\n                \"mime_type\": \"(str) mime type of file\",\n                \"key\": \"(str) key attached to file\",\n                \"total_bytes_lower_bound\": \"(int) lower bound file size in bytes\",\n                \"total_bytes\": \"(int) file upper bound size in bytes\",\n                \"written_bytes\": \"(int) written size in bytes\",\n                \"blobs_completed\": \"(int) number of fully downloaded blobs\",\n                \"blobs_in_stream\": \"(int) total blobs on stream\",\n                \"blobs_remaining\": \"(int) total blobs remaining to download\",\n                \"status\": \"(str) downloader status\",\n                \"claim_id\": \"(str) None if claim is not found else the claim id\",\n                \"txid\": \"(str) None if claim is not found else the transaction id\",\n                \"nout\": \"(int) None if claim is not found else the transaction output index\",\n                \"outpoint\": \"(str) None if claim is not found else the tx and output\",\n                \"metadata\": \"(dict) None if claim is not found else the claim metadata\",\n                \"channel_claim_id\": \"(str) None if claim is not found or not signed\",\n                \"channel_name\": \"(str) None if claim is not found or not signed\",\n                \"claim_name\": \"(str) None if claim is not found else the claim name\"\n            }\n        ]\n    }"
        },
        "file_reflect": {
            "name": "reflect",
            "desc": {
                "text": [
                    "Reflect all the blobs in a file matching the filter criteria"
                ],
                "usage": [
                    "    file reflect [--reflector=<reflector>]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "reflector",
                    "desc": [
                        "reflector server, ip address or url, by default choose a server from the config"
                    ],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "list of blobs reflected"
                ],
                "type": "list"
            },
            "kwargs": [
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "group": "file",
            "cli": "file reflect",
            "help": "Reflect all the blobs in a file matching the filter criteria\n\nUsage:\n    file reflect [--reflector=<reflector>]\n                 [--sd_hash=<sd_hash>] [--file_name=<file_name>]\n                 [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--added_on=<added_on>]\n                 [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>]\n                 [--nout=<nout>] [--channel_claim_id=<channel_claim_id>]\n                 [--channel_name=<channel_name>] [--claim_name=<claim_name>]\n                 [--blobs_in_stream=<blobs_in_stream>]\n                 [--blobs_remaining=<blobs_remaining>]\n\nOptions:\n    --reflector=<reflector>                : (str) reflector server, ip address or url, by\n                                              default choose a server from the config\n    --sd_hash=<sd_hash>                    : (str) filter by sd hash\n    --file_name=<file_name>                : (str) filter by file name\n    --stream_hash=<stream_hash>            : (str) filter by stream hash\n    --rowid=<rowid>                        : (int) filter by row id\n    --added_on=<added_on>                  : (int) filter by time of insertion\n    --claim_id=<claim_id>                  : (str) filter by claim id\n    --outpoint=<outpoint>                  : (str) filter by claim outpoint\n    --txid=<txid>                          : (str) filter by claim txid\n    --nout=<nout>                          : (int) filter by claim nout\n    --channel_claim_id=<channel_claim_id>  : (str) filter by channel claim id\n    --channel_name=<channel_name>          : (str) filter by channel name\n    --claim_name=<claim_name>              : (str) filter by claim name\n    --blobs_in_stream=<blobs_in_stream>    : (int) filter by blobs in stream\n    --blobs_remaining=<blobs_remaining>    : (int) filter by number of remaining blobs to\n                                              download\n\nReturns:\n    (list) list of blobs reflected"
        },
        "file_save": {
            "name": "save",
            "desc": {
                "text": [
                    "Start saving a file to disk."
                ],
                "usage": [
                    "    file save [--download_directory=<download_directory>]"
                ],
                "kwargs": 14
            },
            "arguments": [
                {
                    "name": "download_directory",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "file being saved to disk"
                ],
                "type": "ManagedStream",
                "json": {
                    "streaming_url": "(str) url to stream the file using range requests",
                    "completed": "(bool) true if download is completed",
                    "file_name": "(str) name of file",
                    "download_directory": "(str) download directory",
                    "points_paid": "(float) credit paid to download file",
                    "stopped": "(bool) true if download is stopped",
                    "stream_hash": "(str) stream hash of file",
                    "stream_name": "(str) stream name",
                    "suggested_file_name": "(str) suggested file name",
                    "sd_hash": "(str) sd hash of file",
                    "download_path": "(str) download path of file",
                    "mime_type": "(str) mime type of file",
                    "key": "(str) key attached to file",
                    "total_bytes_lower_bound": "(int) lower bound file size in bytes",
                    "total_bytes": "(int) file upper bound size in bytes",
                    "written_bytes": "(int) written size in bytes",
                    "blobs_completed": "(int) number of fully downloaded blobs",
                    "blobs_in_stream": "(int) total blobs on stream",
                    "blobs_remaining": "(int) total blobs remaining to download",
                    "status": "(str) downloader status",
                    "claim_id": "(str) None if claim is not found else the claim id",
                    "txid": "(str) None if claim is not found else the transaction id",
                    "nout": "(int) None if claim is not found else the transaction output index",
                    "outpoint": "(str) None if claim is not found else the tx and output",
                    "metadata": "(dict) None if claim is not found else the claim metadata",
                    "channel_claim_id": "(str) None if claim is not found or not signed",
                    "channel_name": "(str) None if claim is not found or not signed",
                    "claim_name": "(str) None if claim is not found else the claim name"
                }
            },
            "kwargs": [
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "group": "file",
            "cli": "file save",
            "help": "Start saving a file to disk.\n\nUsage:\n    file save [--download_directory=<download_directory>]\n              [--sd_hash=<sd_hash>] [--file_name=<file_name>]\n              [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--added_on=<added_on>]\n              [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>]\n              [--nout=<nout>] [--channel_claim_id=<channel_claim_id>]\n              [--channel_name=<channel_name>] [--claim_name=<claim_name>]\n              [--blobs_in_stream=<blobs_in_stream>] [--blobs_remaining=<blobs_remaining>]\n\nOptions:\n    --download_directory=<download_directory>  : (str)\n    --sd_hash=<sd_hash>                        : (str) filter by sd hash\n    --file_name=<file_name>                    : (str) filter by file name\n    --stream_hash=<stream_hash>                : (str) filter by stream hash\n    --rowid=<rowid>                            : (int) filter by row id\n    --added_on=<added_on>                      : (int) filter by time of insertion\n    --claim_id=<claim_id>                      : (str) filter by claim id\n    --outpoint=<outpoint>                      : (str) filter by claim outpoint\n    --txid=<txid>                              : (str) filter by claim txid\n    --nout=<nout>                              : (int) filter by claim nout\n    --channel_claim_id=<channel_claim_id>      : (str) filter by channel claim id\n    --channel_name=<channel_name>              : (str) filter by channel name\n    --claim_name=<claim_name>                  : (str) filter by claim name\n    --blobs_in_stream=<blobs_in_stream>        : (int) filter by blobs in stream\n    --blobs_remaining=<blobs_remaining>        : (int) filter by number of remaining blobs\n                                                  to download\n\nReturns:\n    (ManagedStream) file being saved to disk\n    {\n        \"streaming_url\": \"(str) url to stream the file using range requests\",\n        \"completed\": \"(bool) true if download is completed\",\n        \"file_name\": \"(str) name of file\",\n        \"download_directory\": \"(str) download directory\",\n        \"points_paid\": \"(float) credit paid to download file\",\n        \"stopped\": \"(bool) true if download is stopped\",\n        \"stream_hash\": \"(str) stream hash of file\",\n        \"stream_name\": \"(str) stream name\",\n        \"suggested_file_name\": \"(str) suggested file name\",\n        \"sd_hash\": \"(str) sd hash of file\",\n        \"download_path\": \"(str) download path of file\",\n        \"mime_type\": \"(str) mime type of file\",\n        \"key\": \"(str) key attached to file\",\n        \"total_bytes_lower_bound\": \"(int) lower bound file size in bytes\",\n        \"total_bytes\": \"(int) file upper bound size in bytes\",\n        \"written_bytes\": \"(int) written size in bytes\",\n        \"blobs_completed\": \"(int) number of fully downloaded blobs\",\n        \"blobs_in_stream\": \"(int) total blobs on stream\",\n        \"blobs_remaining\": \"(int) total blobs remaining to download\",\n        \"status\": \"(str) downloader status\",\n        \"claim_id\": \"(str) None if claim is not found else the claim id\",\n        \"txid\": \"(str) None if claim is not found else the transaction id\",\n        \"nout\": \"(int) None if claim is not found else the transaction output index\",\n        \"outpoint\": \"(str) None if claim is not found else the tx and output\",\n        \"metadata\": \"(dict) None if claim is not found else the claim metadata\",\n        \"channel_claim_id\": \"(str) None if claim is not found or not signed\",\n        \"channel_name\": \"(str) None if claim is not found or not signed\",\n        \"claim_name\": \"(str) None if claim is not found else the claim name\"\n    }"
        },
        "file_set_status": {
            "name": "set_status",
            "desc": {
                "text": [
                    "Start or stop downloading a file"
                ],
                "usage": [
                    "    file set_status (<status> | --status=<status>)"
                ],
                "kwargs": 20
            },
            "arguments": [
                {
                    "name": "status",
                    "desc": [
                        "one of \"start\" or \"stop\""
                    ],
                    "type": "str"
                },
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "confirmation message"
                ],
                "type": "str"
            },
            "kwargs": [
                {
                    "name": "sd_hash",
                    "desc": [
                        "filter by sd hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "filter by file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "stream_hash",
                    "desc": [
                        "filter by stream hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "rowid",
                    "desc": [
                        "filter by row id"
                    ],
                    "type": "int"
                },
                {
                    "name": "added_on",
                    "desc": [
                        "filter by time of insertion"
                    ],
                    "type": "int"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "filter by claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "outpoint",
                    "desc": [
                        "filter by claim outpoint"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "filter by claim txid"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "filter by claim nout"
                    ],
                    "type": "int"
                },
                {
                    "name": "channel_claim_id",
                    "desc": [
                        "filter by channel claim id"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "filter by channel name"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_name",
                    "desc": [
                        "filter by claim name"
                    ],
                    "type": "str"
                },
                {
                    "name": "blobs_in_stream",
                    "desc": [
                        "filter by blobs in stream"
                    ],
                    "type": "int"
                },
                {
                    "name": "blobs_remaining",
                    "desc": [
                        "filter by number of remaining blobs to download"
                    ],
                    "type": "int"
                }
            ],
            "group": "file",
            "cli": "file set_status",
            "help": "Start or stop downloading a file\n\nUsage:\n    file set_status (<status> | --status=<status>)\n                    [--sd_hash=<sd_hash>] [--file_name=<file_name>]\n                    [--stream_hash=<stream_hash>] [--rowid=<rowid>]\n                    [--added_on=<added_on>] [--claim_id=<claim_id>]\n                    [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]\n                    [--channel_claim_id=<channel_claim_id>]\n                    [--channel_name=<channel_name>] [--claim_name=<claim_name>]\n                    [--blobs_in_stream=<blobs_in_stream>]\n                    [--blobs_remaining=<blobs_remaining>]\n\nOptions:\n    --status=<status>                      : (str) one of \"start\" or \"stop\"\n    --sd_hash=<sd_hash>                    : (str) filter by sd hash\n    --file_name=<file_name>                : (str) filter by file name\n    --stream_hash=<stream_hash>            : (str) filter by stream hash\n    --rowid=<rowid>                        : (int) filter by row id\n    --added_on=<added_on>                  : (int) filter by time of insertion\n    --claim_id=<claim_id>                  : (str) filter by claim id\n    --outpoint=<outpoint>                  : (str) filter by claim outpoint\n    --txid=<txid>                          : (str) filter by claim txid\n    --nout=<nout>                          : (int) filter by claim nout\n    --channel_claim_id=<channel_claim_id>  : (str) filter by channel claim id\n    --channel_name=<channel_name>          : (str) filter by channel name\n    --claim_name=<claim_name>              : (str) filter by claim name\n    --blobs_in_stream=<blobs_in_stream>    : (int) filter by blobs in stream\n    --blobs_remaining=<blobs_remaining>    : (int) filter by number of remaining blobs to\n                                              download\n\nReturns:\n    (str) confirmation message"
        },
        "get": {
            "name": "get",
            "desc": {
                "text": [
                    "Download stream from a LBRY name."
                ],
                "usage": [
                    "    get <uri> [<file_name> | --file_name=<file_name>]",
                    "     [<download_directory> | --download_directory=<download_directory>]",
                    "     [<timeout> | --timeout=<timeout>]",
                    "     [--save_file=<save_file>] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "uri",
                    "desc": [
                        "uri of the content to download"
                    ],
                    "type": "str"
                },
                {
                    "name": "file_name",
                    "desc": [
                        "specified name for the downloaded file, overrides the stream file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "download_directory",
                    "desc": [
                        "full path to the directory to download into"
                    ],
                    "type": "str"
                },
                {
                    "name": "timeout",
                    "desc": [
                        "download timeout in number of seconds"
                    ],
                    "type": "int"
                },
                {
                    "name": "save_file",
                    "desc": [
                        "save the file to the downloads directory"
                    ],
                    "type": "bool"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet to check for claim purchase reciepts"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [],
                "type": "ManagedStream",
                "json": {
                    "streaming_url": "(str) url to stream the file using range requests",
                    "completed": "(bool) true if download is completed",
                    "file_name": "(str) name of file",
                    "download_directory": "(str) download directory",
                    "points_paid": "(float) credit paid to download file",
                    "stopped": "(bool) true if download is stopped",
                    "stream_hash": "(str) stream hash of file",
                    "stream_name": "(str) stream name",
                    "suggested_file_name": "(str) suggested file name",
                    "sd_hash": "(str) sd hash of file",
                    "download_path": "(str) download path of file",
                    "mime_type": "(str) mime type of file",
                    "key": "(str) key attached to file",
                    "total_bytes_lower_bound": "(int) lower bound file size in bytes",
                    "total_bytes": "(int) file upper bound size in bytes",
                    "written_bytes": "(int) written size in bytes",
                    "blobs_completed": "(int) number of fully downloaded blobs",
                    "blobs_in_stream": "(int) total blobs on stream",
                    "blobs_remaining": "(int) total blobs remaining to download",
                    "status": "(str) downloader status",
                    "claim_id": "(str) None if claim is not found else the claim id",
                    "txid": "(str) None if claim is not found else the transaction id",
                    "nout": "(int) None if claim is not found else the transaction output index",
                    "outpoint": "(str) None if claim is not found else the tx and output",
                    "metadata": "(dict) None if claim is not found else the claim metadata",
                    "channel_claim_id": "(str) None if claim is not found or not signed",
                    "channel_name": "(str) None if claim is not found or not signed",
                    "claim_name": "(str) None if claim is not found else the claim name"
                }
            },
            "cli": "get",
            "help": "Download stream from a LBRY name.\n\nUsage:\n    get <uri> [<file_name> | --file_name=<file_name>]\n     [<download_directory> | --download_directory=<download_directory>]\n     [<timeout> | --timeout=<timeout>]\n     [--save_file=<save_file>] [--wallet_id=<wallet_id>]\n\nOptions:\n    --uri=<uri>                                : (str) uri of the content to download\n    --file_name=<file_name>                    : (str) specified name for the downloaded\n                                                  file, overrides the stream file name\n    --download_directory=<download_directory>  : (str) full path to the directory to\n                                                  download into\n    --timeout=<timeout>                        : (int) download timeout in number of\n                                                  seconds\n    --save_file                                : (bool) save the file to the downloads\n                                                  directory\n    --wallet_id=<wallet_id>                    : (str) wallet to check for claim purchase\n                                                  reciepts\n\nReturns:\n    (ManagedStream) \n    {\n        \"streaming_url\": \"(str) url to stream the file using range requests\",\n        \"completed\": \"(bool) true if download is completed\",\n        \"file_name\": \"(str) name of file\",\n        \"download_directory\": \"(str) download directory\",\n        \"points_paid\": \"(float) credit paid to download file\",\n        \"stopped\": \"(bool) true if download is stopped\",\n        \"stream_hash\": \"(str) stream hash of file\",\n        \"stream_name\": \"(str) stream name\",\n        \"suggested_file_name\": \"(str) suggested file name\",\n        \"sd_hash\": \"(str) sd hash of file\",\n        \"download_path\": \"(str) download path of file\",\n        \"mime_type\": \"(str) mime type of file\",\n        \"key\": \"(str) key attached to file\",\n        \"total_bytes_lower_bound\": \"(int) lower bound file size in bytes\",\n        \"total_bytes\": \"(int) file upper bound size in bytes\",\n        \"written_bytes\": \"(int) written size in bytes\",\n        \"blobs_completed\": \"(int) number of fully downloaded blobs\",\n        \"blobs_in_stream\": \"(int) total blobs on stream\",\n        \"blobs_remaining\": \"(int) total blobs remaining to download\",\n        \"status\": \"(str) downloader status\",\n        \"claim_id\": \"(str) None if claim is not found else the claim id\",\n        \"txid\": \"(str) None if claim is not found else the transaction id\",\n        \"nout\": \"(int) None if claim is not found else the transaction output index\",\n        \"outpoint\": \"(str) None if claim is not found else the tx and output\",\n        \"metadata\": \"(dict) None if claim is not found else the claim metadata\",\n        \"channel_claim_id\": \"(str) None if claim is not found or not signed\",\n        \"channel_name\": \"(str) None if claim is not found or not signed\",\n        \"claim_name\": \"(str) None if claim is not found else the claim name\"\n    }"
        },
        "peer_list": {
            "name": "list",
            "desc": {
                "text": [
                    "Get peers for blob hash"
                ],
                "usage": [
                    "    peer list (<blob_hash> | --blob_hash=<blob_hash>)",
                    "        [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]",
                    "        [--page=<page>] [--page_size=<page_size>]"
                ],
                "returns": [
                    "    {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>, 'node_id': <peer node id>}"
                ]
            },
            "arguments": [
                {
                    "name": "blob_hash",
                    "desc": [
                        "find available peers for this blob hash"
                    ],
                    "type": "str"
                },
                {
                    "name": "search_bottom_out_limit",
                    "desc": [
                        "the number of search probes in a row",
                        "that don't find any new peers",
                        "before giving up and returning"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return during paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page during pagination"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "List of contact dictionaries"
                ],
                "type": "list"
            },
            "group": "peer",
            "cli": "peer list",
            "help": "Get peers for blob hash\n\nUsage:\n    peer list (<blob_hash> | --blob_hash=<blob_hash>)\n        [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]\n        [--page=<page>] [--page_size=<page_size>]\n\nOptions:\n    --blob_hash=<blob_hash>                              : (str) find available peers for\n                                                            this blob hash\n    --search_bottom_out_limit=<search_bottom_out_limit>  : (int) the number of search\n                                                            probes in a row that don't find\n                                                            any new peers before giving up\n                                                            and returning\n    --page=<page>                                        : (int) page to return during\n                                                            paginating\n    --page_size=<page_size>                              : (int) number of items on page\n                                                            during pagination\n\nReturns:\n    (list) List of contact dictionaries\n    {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>, 'node_id': <peer node id>}"
        },
        "peer_ping": {
            "name": "ping",
            "desc": {
                "text": [
                    "Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,",
                    "if not provided the peer is located first."
                ],
                "usage": [
                    "    peer ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)"
                ]
            },
            "arguments": [
                {
                    "name": "node_id",
                    "desc": [
                        "node id"
                    ],
                    "type": "str"
                },
                {
                    "name": "address",
                    "desc": [
                        "ip address"
                    ],
                    "type": "str"
                },
                {
                    "name": "port",
                    "desc": [
                        "ip port"
                    ],
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "pong, or {'error': <error message>} if an error is encountered"
                ],
                "type": "str"
            },
            "group": "peer",
            "cli": "peer ping",
            "help": "Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,\nif not provided the peer is located first.\n\nUsage:\n    peer ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)\n\nOptions:\n    --node_id=<node_id>  : (str) node id\n    --address=<address>  : (str) ip address\n    --port=<port>        : (int) ip port\n\nReturns:\n    (str) pong, or {'error': <error message>} if an error is encountered"
        },
        "preference_get": {
            "name": "get",
            "desc": {
                "text": [
                    "Get preference value for key or all values if not key is passed in."
                ],
                "usage": [
                    "    preference get [<key>] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "key",
                    "desc": [
                        "key associated with value"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "preferences"
                ],
                "type": "dict"
            },
            "group": "preference",
            "cli": "preference get",
            "help": "Get preference value for key or all values if not key is passed in.\n\nUsage:\n    preference get [<key>] [--wallet_id=<wallet_id>]\n\nOptions:\n    --key=<key>              : (str) key associated with value\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) preferences"
        },
        "preference_set": {
            "name": "set",
            "desc": {
                "text": [
                    "Set preferences"
                ],
                "usage": [
                    "    preference set (<key>) (<value>) [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "key",
                    "desc": [
                        "key for the value"
                    ],
                    "type": "str"
                },
                {
                    "name": "value",
                    "desc": [
                        "the value itself"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "updated user preference"
                ],
                "type": "dict"
            },
            "group": "preference",
            "cli": "preference set",
            "help": "Set preferences\n\nUsage:\n    preference set (<key>) (<value>) [--wallet_id=<wallet_id>]\n\nOptions:\n    --key=<key>              : (str) key for the value\n    --value=<value>          : (str) the value itself\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n\nReturns:\n    (dict) updated user preference"
        },
        "publish": {
            "name": "publish",
            "desc": {
                "text": [
                    "Create or replace a stream claim at a given name (use 'stream create/update' for more control)."
                ],
                "usage": [
                    "    publish (<name> | --name=<name>) [--bid=<bid>]"
                ],
                "kwargs": 12
            },
            "arguments": [
                {
                    "name": "name",
                    "desc": [
                        "name for the content (can only consist of a-z A-Z 0-9 and -(dash))"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the stream"
                    ],
                    "type": "str"
                },
                {
                    "name": "clear_fee",
                    "desc": [
                        "clear fee"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_channel",
                    "desc": [
                        "clear channel signature"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction for the published claim"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "clear_fee",
                    "desc": [
                        "clear fee"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_channel",
                    "desc": [
                        "clear channel signature"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "cli": "publish",
            "help": "Create or replace a stream claim at a given name (use 'stream create/update' for more control).\n\nUsage:\n    publish (<name> | --name=<name>) [--bid=<bid>]\n            [--clear_fee] [--clear_channel] [--file_path=<file_path>] [--validate_file]\n            [--optimize_file] [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]\n            [--fee_address=<fee_address>] [--author=<author>] [--license=<license>]\n            [--license_url=<license_url>] [--release_time=<release_time>]\n            [--width=<width>] [--height=<height>] [--duration=<duration>]\n            [--title=<title>] [--description=<description>]\n            [--thumbnail_url=<thumbnail_url>] [--tag=<tag>...] [--language=<language>...]\n            [--location=<location>...] [--account_id=<account_id>]\n            [--claim_address=<claim_address>] [--channel_id=<channel_id>]\n            [--channel_name=<channel_name>] [--replace] [--clear_tags] [--clear_languages]\n            [--clear_locations] [--change_account_id=<change_account_id>]\n            [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --name=<name>                            : (str) name for the content (can only\n                                                consist of a-z A-Z 0-9 and -(dash))\n    --bid=<bid>                              : (str) amount to back the stream\n    --clear_fee                              : (bool) clear fee\n    --clear_channel                          : (bool) clear channel signature\n    --file_path=<file_path>                  : (str) path to file to be associated with\n                                                name.\n    --validate_file                          : (bool) validate that the video container\n                                                and encodings match common web browser\n                                                support or that optimization succeeds if\n                                                specified. FFmpeg is required\n    --optimize_file                          : (bool) transcode the video & audio if\n                                                necessary to ensure common web browser\n                                                support. FFmpeg is required\n    --fee_currency=<fee_currency>            : (str) specify fee currency\n    --fee_amount=<fee_amount>                : (str) content download fee\n    --fee_address=<fee_address>              : (str) address where to send fee payments,\n                                                will use the claim holding address by\n                                                default\n    --author=<author>                        : (str) author of the publication. The usage\n                                                for this field is not the same as for\n                                                channels. The author field is used to\n                                                credit an author who is not the publisher\n                                                and is not represented by the channel. For\n                                                example, a pdf file of 'The Odyssey' has an\n                                                author of 'Homer' but may by published to a\n                                                channel such as '@classics', or to no\n                                                channel at all\n    --license=<license>                      : (str) publication license\n    --license_url=<license_url>              : (str) publication license url\n    --release_time=<release_time>            : (int) original public release of content,\n                                                seconds since UNIX epoch\n    --width=<width>                          : (int) image/video width, automatically\n                                                calculated from media file\n    --height=<height>                        : (int) image/video height, automatically\n                                                calculated from media file\n    --duration=<duration>                    : (int) audio/video duration in seconds,\n                                                automatically calculated\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --replace                                : (bool) instead of modifying specific values\n                                                on the claim, this will clear all existing\n                                                values and only save passed in values,\n                                                useful for form submissions where all\n                                                values are always set\n    --clear_tags                             : (bool) clear existing tags (prior to adding\n                                                new ones)\n    --clear_languages                        : (bool) clear existing languages (prior to\n                                                adding new ones)\n    --clear_locations                        : (bool) clear existing locations (prior to\n                                                adding new ones)\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction for the published claim\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "purchase_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Purchase a claim."
                ],
                "usage": [
                    "    purchase create (--claim_id=<claim_id> | --url=<url>)",
                    "                    [--allow_duplicate_purchase] [--override_max_key_fee]"
                ],
                "kwargs": 20
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id of claim to purchase"
                    ],
                    "type": "str"
                },
                {
                    "name": "url",
                    "desc": [
                        "lookup claim to purchase by url"
                    ],
                    "type": "str"
                },
                {
                    "name": "allow_duplicate_purchase",
                    "desc": [
                        "allow purchasing claim_id you already own"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "override_max_key_fee",
                    "desc": [
                        "ignore max key fee for this purchase"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "purchase transaction"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "purchase",
            "cli": "purchase create",
            "help": "Purchase a claim.\n\nUsage:\n    purchase create (--claim_id=<claim_id> | --url=<url>)\n                    [--allow_duplicate_purchase] [--override_max_key_fee]\n                    [--change_account_id=<change_account_id>]\n                    [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim id of claim to purchase\n    --url=<url>                              : (str) lookup claim to purchase by url\n    --allow_duplicate_purchase               : (bool) allow purchasing claim_id you\n                                                already own\n    --override_max_key_fee                   : (bool) ignore max key fee for this purchase\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) purchase transaction\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "purchase_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my claim purchases."
                ],
                "usage": [
                    "    purchase list [<claim_id> | --claim_id=<claim_id>] [--resolve]",
                    "                  [--account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 18
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "purchases for specific claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "resolve",
                    "desc": [
                        "include resolved claim information"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "purchase outputs"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "purchase",
            "cli": "purchase list",
            "help": "List my claim purchases.\n\nUsage:\n    purchase list [<claim_id> | --claim_id=<claim_id>] [--resolve]\n                  [--account_id=<account_id>] [--wallet_id=<wallet_id>]\n                  [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --claim_id=<claim_id>      : (str) purchases for specific claim\n    --resolve                  : (bool) include resolved claim information\n    --account_id=<account_id>  : (str) restrict operation to specific account, otherwise\n                                  all accounts in wallet\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n    --page=<page>              : (int) page to return for paginating\n    --page_size=<page_size>    : (int) number of items on page for pagination\n    --include_total            : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) purchase outputs\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "resolve": {
            "name": "resolve",
            "desc": {
                "text": [
                    "Get the claim that a URL refers to."
                ],
                "usage": [
                    "    resolve <urls>... [--wallet_id=<wallet_id>]",
                    "            [--include_purchase_receipt]",
                    "            [--include_is_my_output]",
                    "            [--include_sent_supports]",
                    "            [--include_sent_tips]",
                    "            [--include_received_tips]",
                    "            [--protobuf]"
                ],
                "returns": [
                    "    '<url>': {",
                    "            If a resolution error occurs:",
                    "            'error': Error message",
                    "            If the url resolves to a channel or a claim in a channel:",
                    "            'certificate': {",
                    "                'address': (str) claim address,",
                    "                'amount': (float) claim amount,",
                    "                'effective_amount': (float) claim amount including supports,",
                    "                'claim_id': (str) claim id,",
                    "                'claim_sequence': (int) claim sequence number (or -1 if unknown),",
                    "                'decoded_claim': (bool) whether or not the claim value was decoded,",
                    "                'height': (int) claim height,",
                    "                'confirmations': (int) claim depth,",
                    "                'timestamp': (int) timestamp of the block that included this claim tx,",
                    "                'has_signature': (bool) included if decoded_claim",
                    "                'name': (str) claim name,",
                    "                'permanent_url': (str) permanent url of the certificate claim,",
                    "                'supports: (list) list of supports [{'txid': (str) txid,",
                    "                                                     'nout': (int) nout,",
                    "                                                     'amount': (float) amount}],",
                    "                'txid': (str) claim txid,",
                    "                'nout': (str) claim nout,",
                    "                'signature_is_valid': (bool), included if has_signature,",
                    "                'value': ClaimDict if decoded, otherwise hex string",
                    "            }",
                    "            If the url resolves to a channel:",
                    "            'claims_in_channel': (int) number of claims in the channel,",
                    "            If the url resolves to a claim:",
                    "            'claim': {",
                    "                'address': (str) claim address,",
                    "                'amount': (float) claim amount,",
                    "                'effective_amount': (float) claim amount including supports,",
                    "                'claim_id': (str) claim id,",
                    "                'claim_sequence': (int) claim sequence number (or -1 if unknown),",
                    "                'decoded_claim': (bool) whether or not the claim value was decoded,",
                    "                'height': (int) claim height,",
                    "                'depth': (int) claim depth,",
                    "                'has_signature': (bool) included if decoded_claim",
                    "                'name': (str) claim name,",
                    "                'permanent_url': (str) permanent url of the claim,",
                    "                'channel_name': (str) channel name if claim is in a channel",
                    "                'supports: (list) list of supports [{'txid': (str) txid,",
                    "                                                     'nout': (int) nout,",
                    "                                                     'amount': (float) amount}]",
                    "                'txid': (str) claim txid,",
                    "                'nout': (str) claim nout,",
                    "                'signature_is_valid': (bool), included if has_signature,",
                    "                'value': ClaimDict if decoded, otherwise hex string",
                    "            }",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "urls",
                    "desc": [
                        "one or more urls to resolve"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet to check for claim purchase reciepts"
                    ],
                    "type": "str"
                },
                {
                    "name": "include_purchase_receipt",
                    "desc": [
                        "lookup and include a receipt if this wallet",
                        "has purchased the claim being resolved"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_is_my_output",
                    "desc": [
                        "lookup and include a boolean indicating",
                        "if claim being resolved is yours"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_sent_supports",
                    "desc": [
                        "lookup and sum the total amount",
                        "of supports you've made to this claim"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_sent_tips",
                    "desc": [
                        "lookup and sum the total amount",
                        "of tips you've made to this claim"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "include_received_tips",
                    "desc": [
                        "lookup and sum the total amount",
                        "of tips you've received to this claim"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "protobuf",
                    "desc": [
                        "protobuf encoded result"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "resolve results, keyed by url"
                ],
                "type": "dict"
            },
            "cli": "resolve",
            "help": "Get the claim that a URL refers to.\n\nUsage:\n    resolve <urls>... [--wallet_id=<wallet_id>]\n            [--include_purchase_receipt]\n            [--include_is_my_output]\n            [--include_sent_supports]\n            [--include_sent_tips]\n            [--include_received_tips]\n            [--protobuf]\n\nOptions:\n    --urls=<urls>               : (str, list) one or more urls to resolve\n    --wallet_id=<wallet_id>     : (str) wallet to check for claim purchase reciepts\n    --include_purchase_receipt  : (bool) lookup and include a receipt if this wallet has\n                                   purchased the claim being resolved\n    --include_is_my_output      : (bool) lookup and include a boolean indicating if claim\n                                   being resolved is yours\n    --include_sent_supports     : (bool) lookup and sum the total amount of supports\n                                   you've made to this claim\n    --include_sent_tips         : (bool) lookup and sum the total amount of tips you've\n                                   made to this claim\n    --include_received_tips     : (bool) lookup and sum the total amount of tips you've\n                                   received to this claim\n    --protobuf                  : (bool) protobuf encoded result\n\nReturns:\n    (dict) resolve results, keyed by url\n    '<url>': {\n            If a resolution error occurs:\n            'error': Error message\n            If the url resolves to a channel or a claim in a channel:\n            'certificate': {\n                'address': (str) claim address,\n                'amount': (float) claim amount,\n                'effective_amount': (float) claim amount including supports,\n                'claim_id': (str) claim id,\n                'claim_sequence': (int) claim sequence number (or -1 if unknown),\n                'decoded_claim': (bool) whether or not the claim value was decoded,\n                'height': (int) claim height,\n                'confirmations': (int) claim depth,\n                'timestamp': (int) timestamp of the block that included this claim tx,\n                'has_signature': (bool) included if decoded_claim\n                'name': (str) claim name,\n                'permanent_url': (str) permanent url of the certificate claim,\n                'supports: (list) list of supports [{'txid': (str) txid,\n                                                     'nout': (int) nout,\n                                                     'amount': (float) amount}],\n                'txid': (str) claim txid,\n                'nout': (str) claim nout,\n                'signature_is_valid': (bool), included if has_signature,\n                'value': ClaimDict if decoded, otherwise hex string\n            }\n            If the url resolves to a channel:\n            'claims_in_channel': (int) number of claims in the channel,\n            If the url resolves to a claim:\n            'claim': {\n                'address': (str) claim address,\n                'amount': (float) claim amount,\n                'effective_amount': (float) claim amount including supports,\n                'claim_id': (str) claim id,\n                'claim_sequence': (int) claim sequence number (or -1 if unknown),\n                'decoded_claim': (bool) whether or not the claim value was decoded,\n                'height': (int) claim height,\n                'depth': (int) claim depth,\n                'has_signature': (bool) included if decoded_claim\n                'name': (str) claim name,\n                'permanent_url': (str) permanent url of the claim,\n                'channel_name': (str) channel name if claim is in a channel\n                'supports: (list) list of supports [{'txid': (str) txid,\n                                                     'nout': (int) nout,\n                                                     'amount': (float) amount}]\n                'txid': (str) claim txid,\n                'nout': (str) claim nout,\n                'signature_is_valid': (bool), included if has_signature,\n                'value': ClaimDict if decoded, otherwise hex string\n            }\n    }"
        },
        "routing_table_get": {
            "name": "routing_table_get",
            "desc": {
                "text": [
                    "Get DHT routing information"
                ],
                "returns": [
                    "    {",
                    "        \"buckets\": {",
                    "            <bucket index>: [",
                    "                {",
                    "                    \"address\": (str) peer address,",
                    "                    \"udp_port\": (int) peer udp port,",
                    "                    \"tcp_port\": (int) peer tcp port,",
                    "                    \"node_id\": (str) peer node id,",
                    "                }",
                    "            ]",
                    "        },",
                    "        \"node_id\": (str) the local dht node id",
                    "    }"
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "dictionary containing routing and peer information"
                ],
                "type": "dict"
            },
            "cli": "routing_table_get",
            "help": "Get DHT routing information\n\nUsage:\n    routing_table_get\n\nReturns:\n    (dict) dictionary containing routing and peer information\n    {\n        \"buckets\": {\n            <bucket index>: [\n                {\n                    \"address\": (str) peer address,\n                    \"udp_port\": (int) peer udp port,\n                    \"tcp_port\": (int) peer tcp port,\n                    \"node_id\": (str) peer node id,\n                }\n            ]\n        },\n        \"node_id\": (str) the local dht node id\n    }"
        },
        "settings_clear": {
            "name": "clear",
            "desc": {
                "text": [
                    "Clear daemon settings"
                ],
                "usage": [
                    "    settings clear (<key>)"
                ]
            },
            "arguments": [
                {
                    "name": "key",
                    "desc": [],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "updated daemon setting"
                ],
                "type": "dict"
            },
            "group": "settings",
            "cli": "settings clear",
            "help": "Clear daemon settings\n\nUsage:\n    settings clear (<key>)\n\nOptions:\n    --key=<key>  : (str)\n\nReturns:\n    (dict) updated daemon setting"
        },
        "settings_get": {
            "name": "get",
            "desc": {
                "text": [
                    "Get daemon settings "
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "daemon settings"
                ],
                "type": "dict"
            },
            "group": "settings",
            "cli": "settings get",
            "help": "Get daemon settings \n\nUsage:\n    settings get\n\nReturns:\n    (dict) daemon settings"
        },
        "settings_set": {
            "name": "set",
            "desc": {
                "text": [
                    "Set daemon settings"
                ],
                "usage": [
                    "    settings set <key> <value>"
                ]
            },
            "arguments": [
                {
                    "name": "key",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "value",
                    "desc": [],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "updated daemon setting"
                ],
                "type": "dict"
            },
            "group": "settings",
            "cli": "settings set",
            "help": "Set daemon settings\n\nUsage:\n    settings set <key> <value>\n\nOptions:\n    --key=<key>      : (str)\n    --value=<value>  : (str)\n\nReturns:\n    (dict) updated daemon setting"
        },
        "status": {
            "name": "status",
            "desc": {
                "text": [
                    "Get daemon status"
                ],
                "returns": [
                    "    {",
                    "        'installation_id': (str) installation id - base58,",
                    "        'is_running': (bool),",
                    "        'skipped_components': (list) [names of skipped components (str)],",
                    "        'startup_status': { Does not include components which have been skipped",
                    "            'blob_manager': (bool),",
                    "            'blockchain_headers': (bool),",
                    "            'database': (bool),",
                    "            'dht': (bool),",
                    "            'exchange_rate_manager': (bool),",
                    "            'hash_announcer': (bool),",
                    "            'peer_protocol_server': (bool),",
                    "            'stream_manager': (bool),",
                    "            'upnp': (bool),",
                    "            'wallet': (bool),",
                    "        },",
                    "        'connection_status': {",
                    "            'code': (str) connection status code,",
                    "            'message': (str) connection status message",
                    "        },",
                    "        'blockchain_headers': {",
                    "            'downloading_headers': (bool),",
                    "            'download_progress': (float) 0-100.0",
                    "        },",
                    "        'wallet': {",
                    "            'connected': (str) host and port of the connected spv server,",
                    "            'blocks': (int) local blockchain height,",
                    "            'blocks_behind': (int) remote_height - local_height,",
                    "            'best_blockhash': (str) block hash of most recent block,",
                    "            'is_encrypted': (bool),",
                    "            'is_locked': (bool),",
                    "            'connected_servers': (list) [",
                    "                {",
                    "                    'host': (str) server hostname,",
                    "                    'port': (int) server port,",
                    "                    'latency': (int) milliseconds",
                    "                }",
                    "            ],",
                    "        },",
                    "        'dht': {",
                    "            'node_id': (str) lbry dht node id - hex encoded,",
                    "            'peers_in_routing_table': (int) the number of peers in the routing table,",
                    "        },",
                    "        'blob_manager': {",
                    "            'finished_blobs': (int) number of finished blobs in the blob manager,",
                    "            'connections': {",
                    "                'incoming_bps': {",
                    "                    <source ip and tcp port>: (int) bytes per second received,",
                    "                },",
                    "                'outgoing_bps': {",
                    "                    <destination ip and tcp port>: (int) bytes per second sent,",
                    "                },",
                    "                'total_outgoing_mps': (float) megabytes per second sent,",
                    "                'total_incoming_mps': (float) megabytes per second received,",
                    "                'time': (float) timestamp",
                    "            }",
                    "        },",
                    "        'hash_announcer': {",
                    "            'announce_queue_size': (int) number of blobs currently queued to be announced",
                    "        },",
                    "        'stream_manager': {",
                    "            'managed_files': (int) count of files in the stream manager,",
                    "        },",
                    "        'upnp': {",
                    "            'aioupnp_version': (str),",
                    "            'redirects': {",
                    "                <TCP | UDP>: (int) external_port,",
                    "            },",
                    "            'gateway': (str) manufacturer and model,",
                    "            'dht_redirect_set': (bool),",
                    "            'peer_redirect_set': (bool),",
                    "            'external_ip': (str) external ip address,",
                    "        }",
                    "    }"
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "lbrynet daemon status"
                ],
                "type": "dict"
            },
            "cli": "status",
            "help": "Get daemon status\n\nUsage:\n    status\n\nReturns:\n    (dict) lbrynet daemon status\n    {\n        'installation_id': (str) installation id - base58,\n        'is_running': (bool),\n        'skipped_components': (list) [names of skipped components (str)],\n        'startup_status': { Does not include components which have been skipped\n            'blob_manager': (bool),\n            'blockchain_headers': (bool),\n            'database': (bool),\n            'dht': (bool),\n            'exchange_rate_manager': (bool),\n            'hash_announcer': (bool),\n            'peer_protocol_server': (bool),\n            'stream_manager': (bool),\n            'upnp': (bool),\n            'wallet': (bool),\n        },\n        'connection_status': {\n            'code': (str) connection status code,\n            'message': (str) connection status message\n        },\n        'blockchain_headers': {\n            'downloading_headers': (bool),\n            'download_progress': (float) 0-100.0\n        },\n        'wallet': {\n            'connected': (str) host and port of the connected spv server,\n            'blocks': (int) local blockchain height,\n            'blocks_behind': (int) remote_height - local_height,\n            'best_blockhash': (str) block hash of most recent block,\n            'is_encrypted': (bool),\n            'is_locked': (bool),\n            'connected_servers': (list) [\n                {\n                    'host': (str) server hostname,\n                    'port': (int) server port,\n                    'latency': (int) milliseconds\n                }\n            ],\n        },\n        'dht': {\n            'node_id': (str) lbry dht node id - hex encoded,\n            'peers_in_routing_table': (int) the number of peers in the routing table,\n        },\n        'blob_manager': {\n            'finished_blobs': (int) number of finished blobs in the blob manager,\n            'connections': {\n                'incoming_bps': {\n                    <source ip and tcp port>: (int) bytes per second received,\n                },\n                'outgoing_bps': {\n                    <destination ip and tcp port>: (int) bytes per second sent,\n                },\n                'total_outgoing_mps': (float) megabytes per second sent,\n                'total_incoming_mps': (float) megabytes per second received,\n                'time': (float) timestamp\n            }\n        },\n        'hash_announcer': {\n            'announce_queue_size': (int) number of blobs currently queued to be announced\n        },\n        'stream_manager': {\n            'managed_files': (int) count of files in the stream manager,\n        },\n        'upnp': {\n            'aioupnp_version': (str),\n            'redirects': {\n                <TCP | UDP>: (int) external_port,\n            },\n            'gateway': (str) manufacturer and model,\n            'dht_redirect_set': (bool),\n            'peer_redirect_set': (bool),\n            'external_ip': (str) external ip address,\n        }\n    }"
        },
        "stop": {
            "name": "stop",
            "desc": {
                "text": [
                    "Stop lbrynet API server. "
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "Shutdown message"
                ],
                "type": "str"
            },
            "cli": "stop",
            "help": "Stop lbrynet API server. \n\nUsage:\n    stop\n\nReturns:\n    (str) Shutdown message"
        },
        "stream_abandon": {
            "name": "abandon",
            "desc": {
                "text": [
                    "Abandon one of my stream claims."
                ],
                "usage": [
                    "    stream abandon"
                ],
                "kwargs": 19
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction abandoning the stream"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "stream",
            "cli": "stream abandon",
            "help": "Abandon one of my stream claims.\n\nUsage:\n    stream abandon\n                   [--claim_id=<claim_id>] [--txid=<txid>] [--nout=<nout>]\n                   [--account_id=<account_id>] [--change_account_id=<change_account_id>]\n                   [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the claim to abandon\n    --txid=<txid>                            : (str) txid of the claim to abandon\n    --nout=<nout>                            : (int) nout of the claim to abandon\n                                                [default: 0]\n    --account_id=<account_id>                : (str) restrict operation to specific\n                                                account, otherwise all accounts in wallet\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction abandoning the stream\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "stream_cost_estimate": {
            "name": "cost_estimate",
            "desc": {
                "text": [
                    "Get estimated cost for a lbry stream"
                ],
                "usage": [
                    "    stream_cost_estimate (<uri> | --uri=<uri>)"
                ]
            },
            "arguments": [
                {
                    "name": "uri",
                    "desc": [
                        "uri to use"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "Estimated cost in lbry credits, returns None if uri is not resolvable"
                ],
                "type": "float"
            },
            "group": "stream",
            "cli": "stream cost_estimate",
            "help": "Get estimated cost for a lbry stream\n\nUsage:\n    stream_cost_estimate (<uri> | --uri=<uri>)\n\nOptions:\n    --uri=<uri>  : (str) uri to use\n\nReturns:\n    (float) Estimated cost in lbry credits, returns None if uri is not resolvable"
        },
        "stream_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Make a new stream claim and announce the associated file to lbrynet."
                ],
                "usage": [
                    "    stream create (<name> | --name=<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]"
                ],
                "kwargs": 18
            },
            "arguments": [
                {
                    "name": "name",
                    "desc": [
                        "name for the stream (can only consist of a-z A-Z 0-9 and -(dash))"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the content"
                    ],
                    "type": "str"
                },
                {
                    "name": "allow_duplicate_name",
                    "desc": [
                        "create new stream even if one already exists with given name"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "stream",
            "cli": "stream create",
            "help": "Make a new stream claim and announce the associated file to lbrynet.\n\nUsage:\n    stream create (<name> | --name=<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]\n                  [--file_path=<file_path>] [--validate_file] [--optimize_file]\n                  [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]\n                  [--fee_address=<fee_address>] [--author=<author>] [--license=<license>]\n                  [--license_url=<license_url>] [--release_time=<release_time>]\n                  [--width=<width>] [--height=<height>] [--duration=<duration>]\n                  [--title=<title>] [--description=<description>]\n                  [--thumbnail_url=<thumbnail_url>] [--tag=<tag>...]\n                  [--language=<language>...] [--location=<location>...]\n                  [--account_id=<account_id>] [--claim_address=<claim_address>]\n                  [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n                  [--change_account_id=<change_account_id>]\n                  [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --name=<name>                            : (str) name for the stream (can only consist\n                                                of a-z A-Z 0-9 and -(dash))\n    --bid=<bid>                              : (str) amount to back the content\n    --allow_duplicate_name                   : (bool) create new stream even if one\n                                                already exists with given name\n    --file_path=<file_path>                  : (str) path to file to be associated with\n                                                name.\n    --validate_file                          : (bool) validate that the video container\n                                                and encodings match common web browser\n                                                support or that optimization succeeds if\n                                                specified. FFmpeg is required\n    --optimize_file                          : (bool) transcode the video & audio if\n                                                necessary to ensure common web browser\n                                                support. FFmpeg is required\n    --fee_currency=<fee_currency>            : (str) specify fee currency\n    --fee_amount=<fee_amount>                : (str) content download fee\n    --fee_address=<fee_address>              : (str) address where to send fee payments,\n                                                will use the claim holding address by\n                                                default\n    --author=<author>                        : (str) author of the publication. The usage\n                                                for this field is not the same as for\n                                                channels. The author field is used to\n                                                credit an author who is not the publisher\n                                                and is not represented by the channel. For\n                                                example, a pdf file of 'The Odyssey' has an\n                                                author of 'Homer' but may by published to a\n                                                channel such as '@classics', or to no\n                                                channel at all\n    --license=<license>                      : (str) publication license\n    --license_url=<license_url>              : (str) publication license url\n    --release_time=<release_time>            : (int) original public release of content,\n                                                seconds since UNIX epoch\n    --width=<width>                          : (int) image/video width, automatically\n                                                calculated from media file\n    --height=<height>                        : (int) image/video height, automatically\n                                                calculated from media file\n    --duration=<duration>                    : (int) audio/video duration in seconds,\n                                                automatically calculated\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) \n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "stream_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my stream claims."
                ],
                "usage": [
                    "    stream list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]",
                    "                [--is_spent] [--resolve]"
                ],
                "kwargs": 16
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "shows previous stream updates and abandons"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "resolve",
                    "desc": [
                        "resolves each stream to provide additional metadata"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "name",
                    "desc": [
                        "claim name (normalized)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full or partial claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "text",
                    "desc": [
                        "full text search"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_height",
                    "desc": [
                        "created at block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "creation_timestamp",
                    "desc": [
                        "created at timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "any_tag",
                    "desc": [
                        "containing any of the tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_tag",
                    "desc": [
                        "containing every tag"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_tag",
                    "desc": [
                        "not containing any of these tags"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_language",
                    "desc": [
                        "containing any of the languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_language",
                    "desc": [
                        "containing every language"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_language",
                    "desc": [
                        "not containing any of these languages"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "any_location",
                    "desc": [
                        "containing any of the locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "all_location",
                    "desc": [
                        "containing every location"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "not_location",
                    "desc": [
                        "not containing any of these locations"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "limit to claims self-described as having been released",
                        "to the public on or after this UTC timestamp, when claim",
                        "does not provide a release time the publish time is used",
                        "instead (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "stream",
            "cli": "stream list",
            "help": "List my stream claims.\n\nUsage:\n    stream list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n                [--is_spent] [--resolve]\n                [--name=<name>...] [--claim_id=<claim_id>...] [--text=<text>]\n                [--txid=<txid>] [--nout=<nout>] [--height=<height>]\n                [--timestamp=<timestamp>] [--creation_height=<creation_height>]\n                [--creation_timestamp=<creation_timestamp>] [--amount=<amount>]\n                [--any_tag=<any_tag>...] [--all_tag=<all_tag>...] [--not_tag=<not_tag>...]\n                [--any_language=<any_language>...] [--all_language=<all_language>...]\n                [--not_language=<not_language>...] [--any_location=<any_location>...]\n                [--all_location=<all_location>...] [--not_location=<not_location>...]\n                [--release_time=<release_time>] [--page=<page>] [--page_size=<page_size>]\n                [--include_total]\n\nOptions:\n    --account_id=<account_id>                  : (str) restrict operation to specific\n                                                  account\n    --wallet_id=<wallet_id>                    : (str) restrict operation to specific\n                                                  wallet\n    --is_spent                                 : (bool) shows previous stream updates and\n                                                  abandons\n    --resolve                                  : (bool) resolves each stream to provide\n                                                  additional metadata\n    --name=<name>                              : (str, list) claim name (normalized)\n    --claim_id=<claim_id>                      : (str, list) full or partial claim id\n    --text=<text>                              : (str) full text search\n    --txid=<txid>                              : (str) transaction id\n    --nout=<nout>                              : (int) position in the transaction\n    --height=<height>                          : (int) last updated block height (supports\n                                                  equality constraints)\n    --timestamp=<timestamp>                    : (int) last updated timestamp (supports\n                                                  equality constraints)\n    --creation_height=<creation_height>        : (int) created at block height (supports\n                                                  equality constraints)\n    --creation_timestamp=<creation_timestamp>  : (int) created at timestamp (supports\n                                                  equality constraints)\n    --amount=<amount>                          : (str) claim amount (supports equality\n                                                  constraints)\n    --any_tag=<any_tag>                        : (str, list) containing any of the tags\n    --all_tag=<all_tag>                        : (str, list) containing every tag\n    --not_tag=<not_tag>                        : (str, list) not containing any of these\n                                                  tags\n    --any_language=<any_language>              : (str, list) containing any of the\n                                                  languages\n    --all_language=<all_language>              : (str, list) containing every language\n    --not_language=<not_language>              : (str, list) not containing any of these\n                                                  languages\n    --any_location=<any_location>              : (str, list) containing any of the\n                                                  locations\n    --all_location=<all_location>              : (str, list) containing every location\n    --not_location=<not_location>              : (str, list) not containing any of these\n                                                  locations\n    --release_time=<release_time>              : (int) limit to claims self-described as\n                                                  having been released to the public on or\n                                                  after this UTC timestamp, when claim does\n                                                  not provide a release time the publish\n                                                  time is used instead (supports equality\n                                                  constraints)\n    --page=<page>                              : (int) page to return for paginating\n    --page_size=<page_size>                    : (int) number of items on page for\n                                                  pagination\n    --include_total                            : (bool) calculate total number of items\n                                                  and pages\n\nReturns:\n    (Paginated[Output]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "stream_repost": {
            "name": "repost",
            "desc": {
                "text": [
                    "Creates a claim that references an existing stream by its claim id."
                ],
                "usage": [
                    "    stream repost (<name> | --name=<name>) (<bid> | --bid=<bid>) (<claim_id> | --claim_id=<claim_id>)",
                    "                  [--allow_duplicate_name] [--account_id=<account_id>] [--claim_address=<claim_address>]"
                ],
                "kwargs": 18
            },
            "arguments": [
                {
                    "name": "name",
                    "desc": [
                        "name of the repost (can only consist of a-z A-Z 0-9 and -(dash))"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "amount to back the repost"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "id of the claim being reposted"
                    ],
                    "type": "str"
                },
                {
                    "name": "allow_duplicate_name",
                    "desc": [
                        "create new repost even if one already exists with given name"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the repost"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the repost is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction for the repost"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "stream",
            "cli": "stream repost",
            "help": "Creates a claim that references an existing stream by its claim id.\n\nUsage:\n    stream repost (<name> | --name=<name>) (<bid> | --bid=<bid>) (<claim_id> | --claim_id=<claim_id>)\n                  [--allow_duplicate_name] [--account_id=<account_id>] [--claim_address=<claim_address>]\n                  [--channel_id=<channel_id>] [--channel_name=<channel_name>]\n                  [--change_account_id=<change_account_id>]\n                  [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --name=<name>                            : (str) name of the repost (can only consist\n                                                of a-z A-Z 0-9 and -(dash))\n    --bid=<bid>                              : (str) amount to back the repost\n    --claim_id=<claim_id>                    : (str) id of the claim being reposted\n    --allow_duplicate_name                   : (bool) create new repost even if one\n                                                already exists with given name\n    --account_id=<account_id>                : (str) account to hold the repost\n    --claim_address=<claim_address>          : (str) specific address where the repost is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction for the repost\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "stream_update": {
            "name": "update",
            "desc": {
                "text": [
                    "Update an existing stream claim and if a new file is provided announce it to lbrynet."
                ],
                "usage": [
                    "    stream update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]"
                ],
                "kwargs": 18
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the stream to update"
                    ],
                    "type": "str"
                },
                {
                    "name": "bid",
                    "desc": [
                        "update amount backing the stream"
                    ],
                    "type": "str"
                },
                {
                    "name": "clear_fee",
                    "desc": [
                        "clear fee"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_channel",
                    "desc": [
                        "clear channel signature"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "stream update transaction"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "clear_fee",
                    "desc": [
                        "clear fee"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_channel",
                    "desc": [
                        "clear channel signature"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "file_path",
                    "desc": [
                        "path to file to be associated with name."
                    ],
                    "type": "str"
                },
                {
                    "name": "validate_file",
                    "desc": [
                        "validate that the video container and encodings match",
                        "common web browser support or that optimization succeeds if specified.",
                        "FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "optimize_file",
                    "desc": [
                        "transcode the video & audio if necessary to ensure",
                        "common web browser support. FFmpeg is required"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "fee_currency",
                    "desc": [
                        "specify fee currency"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_amount",
                    "desc": [
                        "content download fee"
                    ],
                    "type": "str"
                },
                {
                    "name": "fee_address",
                    "desc": [
                        "address where to send fee payments, will use",
                        "the claim holding address by default"
                    ],
                    "type": "str"
                },
                {
                    "name": "author",
                    "desc": [
                        "author of the publication. The usage for this field is not",
                        "the same as for channels. The author field is used to credit an author",
                        "who is not the publisher and is not represented by the channel. For",
                        "example, a pdf file of 'The Odyssey' has an author of 'Homer' but may",
                        "by published to a channel such as '@classics', or to no channel at all"
                    ],
                    "type": "str"
                },
                {
                    "name": "license",
                    "desc": [
                        "publication license"
                    ],
                    "type": "str"
                },
                {
                    "name": "license_url",
                    "desc": [
                        "publication license url"
                    ],
                    "type": "str"
                },
                {
                    "name": "release_time",
                    "desc": [
                        "original public release of content, seconds since UNIX epoch"
                    ],
                    "type": "int"
                },
                {
                    "name": "width",
                    "desc": [
                        "image/video width, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "image/video height, automatically calculated from media file"
                    ],
                    "type": "int"
                },
                {
                    "name": "duration",
                    "desc": [
                        "audio/video duration in seconds, automatically calculated"
                    ],
                    "type": "int"
                },
                {
                    "name": "title",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "description",
                    "desc": [],
                    "type": "str"
                },
                {
                    "name": "thumbnail_url",
                    "desc": [
                        "url to thumbnail image"
                    ],
                    "type": "str"
                },
                {
                    "name": "tag",
                    "desc": [],
                    "type": "str, list"
                },
                {
                    "name": "language",
                    "desc": [
                        "languages used by the channel,",
                        "using RFC 5646 format, eg:",
                        "for English `--language=en`",
                        "for Spanish (Spain) `--language=es-ES`",
                        "for Spanish (Mexican) `--language=es-MX`",
                        "for Chinese (Simplified) `--language=zh-Hans`",
                        "for Chinese (Traditional) `--language=zh-Hant`"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "location",
                    "desc": [
                        "locations of the channel, consisting of 2 letter",
                        "`country` code and a `state`, `city` and a postal",
                        "`code` along with a `latitude` and `longitude`.",
                        "for JSON RPC: pass a dictionary with aforementioned",
                        "attributes as keys, eg:",
                        "...",
                        "\"locations\": [{'country': 'US', 'state': 'NH'}]",
                        "...",
                        "for command line: pass a colon delimited list",
                        "with values in the following order:",
                        "\"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"",
                        "making sure to include colon for blank values, for",
                        "example to provide only the city:",
                        "...--locations=\"::Manchester\"",
                        "with all values set:",
                        "...--locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"",
                        "optionally, you can just pass the \"LATITUDE:LONGITUDE\":",
                        "...--locations=\"42.990605:-71.460989\"",
                        "finally, you can also pass JSON string of dictionary",
                        "on the command line as you would via JSON RPC",
                        "...--locations=\"{'country': 'US', 'state': 'NH'}\""
                    ],
                    "type": "str, list"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to hold the claim"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_address",
                    "desc": [
                        "specific address where the claim is held, if not specified",
                        "it will be determined automatically from the account"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claim id of the publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "channel_name",
                    "desc": [
                        "name of publishing channel"
                    ],
                    "type": "str"
                },
                {
                    "name": "replace",
                    "desc": [
                        "instead of modifying specific values on",
                        "the claim, this will clear all existing values",
                        "and only save passed in values, useful for form",
                        "submissions where all values are always set"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_tags",
                    "desc": [
                        "clear existing tags (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_languages",
                    "desc": [
                        "clear existing languages (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "clear_locations",
                    "desc": [
                        "clear existing locations (prior to adding new ones)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "stream",
            "cli": "stream update",
            "help": "Update an existing stream claim and if a new file is provided announce it to lbrynet.\n\nUsage:\n    stream update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]\n                  [--clear_fee] [--clear_channel] [--file_path=<file_path>]\n                  [--validate_file] [--optimize_file] [--fee_currency=<fee_currency>]\n                  [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]\n                  [--author=<author>] [--license=<license>] [--license_url=<license_url>]\n                  [--release_time=<release_time>] [--width=<width>] [--height=<height>]\n                  [--duration=<duration>] [--title=<title>] [--description=<description>]\n                  [--thumbnail_url=<thumbnail_url>] [--tag=<tag>...]\n                  [--language=<language>...] [--location=<location>...]\n                  [--account_id=<account_id>] [--claim_address=<claim_address>]\n                  [--channel_id=<channel_id>] [--channel_name=<channel_name>] [--replace]\n                  [--clear_tags] [--clear_languages] [--clear_locations]\n                  [--change_account_id=<change_account_id>]\n                  [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the stream to update\n    --bid=<bid>                              : (str) update amount backing the stream\n    --clear_fee                              : (bool) clear fee\n    --clear_channel                          : (bool) clear channel signature\n    --file_path=<file_path>                  : (str) path to file to be associated with\n                                                name.\n    --validate_file                          : (bool) validate that the video container\n                                                and encodings match common web browser\n                                                support or that optimization succeeds if\n                                                specified. FFmpeg is required\n    --optimize_file                          : (bool) transcode the video & audio if\n                                                necessary to ensure common web browser\n                                                support. FFmpeg is required\n    --fee_currency=<fee_currency>            : (str) specify fee currency\n    --fee_amount=<fee_amount>                : (str) content download fee\n    --fee_address=<fee_address>              : (str) address where to send fee payments,\n                                                will use the claim holding address by\n                                                default\n    --author=<author>                        : (str) author of the publication. The usage\n                                                for this field is not the same as for\n                                                channels. The author field is used to\n                                                credit an author who is not the publisher\n                                                and is not represented by the channel. For\n                                                example, a pdf file of 'The Odyssey' has an\n                                                author of 'Homer' but may by published to a\n                                                channel such as '@classics', or to no\n                                                channel at all\n    --license=<license>                      : (str) publication license\n    --license_url=<license_url>              : (str) publication license url\n    --release_time=<release_time>            : (int) original public release of content,\n                                                seconds since UNIX epoch\n    --width=<width>                          : (int) image/video width, automatically\n                                                calculated from media file\n    --height=<height>                        : (int) image/video height, automatically\n                                                calculated from media file\n    --duration=<duration>                    : (int) audio/video duration in seconds,\n                                                automatically calculated\n    --title=<title>                          : (str)\n    --description=<description>              : (str)\n    --thumbnail_url=<thumbnail_url>          : (str) url to thumbnail image\n    --tag=<tag>                              : (str, list)\n    --language=<language>                    : (str, list) languages used by the channel,\n                                                using RFC 5646 format, eg: for English\n                                                `--language=en` for Spanish (Spain)\n                                                `--language=es-ES` for Spanish (Mexican)\n                                                `--language=es-MX` for Chinese (Simplified)\n                                                `--language=zh-Hans` for Chinese\n                                                (Traditional) `--language=zh-Hant`\n    --location=<location>                    : (str, list) locations of the channel,\n                                                consisting of 2 letter `country` code and a\n                                                `state`, `city` and a postal `code` along\n                                                with a `latitude` and `longitude`. for JSON\n                                                RPC: pass a dictionary with aforementioned\n                                                attributes as keys, eg: ... \"locations\":\n                                                [{'country': 'US', 'state': 'NH'}] ... for\n                                                command line: pass a colon delimited list\n                                                with values in the following order:\n                                                \"COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE\"\n                                                making sure to include colon for blank\n                                                values, for example to provide only the\n                                                city: ...--locations=\"::Manchester\" with\n                                                all values set: ...--\n                                                locations=\"US:NH:Manchester:03101:42.990605:-71.460989\"\n                                                optionally, you can just pass the\n                                                \"LATITUDE:LONGITUDE\": ...--\n                                                locations=\"42.990605:-71.460989\" finally,\n                                                you can also pass JSON string of dictionary\n                                                on the command line as you would via JSON\n                                                RPC ...--locations=\"{'country': 'US',\n                                                'state': 'NH'}\"\n    --account_id=<account_id>                : (str) account to hold the claim\n    --claim_address=<claim_address>          : (str) specific address where the claim is\n                                                held, if not specified it will be\n                                                determined automatically from the account\n    --channel_id=<channel_id>                : (str) claim id of the publishing channel\n    --channel_name=<channel_name>            : (str) name of publishing channel\n    --replace                                : (bool) instead of modifying specific values\n                                                on the claim, this will clear all existing\n                                                values and only save passed in values,\n                                                useful for form submissions where all\n                                                values are always set\n    --clear_tags                             : (bool) clear existing tags (prior to adding\n                                                new ones)\n    --clear_languages                        : (bool) clear existing languages (prior to\n                                                adding new ones)\n    --clear_locations                        : (bool) clear existing locations (prior to\n                                                adding new ones)\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) stream update transaction\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "support_abandon": {
            "name": "abandon",
            "desc": {
                "text": [
                    "Abandon supports, including tips, of a specific claim, optionally",
                    "keeping some amount as supports."
                ],
                "usage": [
                    "    support abandon [--keep=<keep>]"
                ],
                "kwargs": 20
            },
            "arguments": [
                {
                    "name": "keep",
                    "desc": [
                        "amount of lbc to keep as support"
                    ],
                    "type": "str"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transaction abandoning the supports"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "txid",
                    "desc": [
                        "txid of the claim to abandon"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "nout of the claim to abandon"
                    ],
                    "type": "int",
                    "default": 0
                },
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account, otherwise all accounts in wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "support",
            "cli": "support abandon",
            "help": "Abandon supports, including tips, of a specific claim, optionally\nkeeping some amount as supports.\n\nUsage:\n    support abandon [--keep=<keep>]\n                    [--claim_id=<claim_id>] [--txid=<txid>] [--nout=<nout>]\n                    [--account_id=<account_id>] [--change_account_id=<change_account_id>]\n                    [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --keep=<keep>                            : (str) amount of lbc to keep as support\n    --claim_id=<claim_id>                    : (str) claim_id of the claim to abandon\n    --txid=<txid>                            : (str) txid of the claim to abandon\n    --nout=<nout>                            : (int) nout of the claim to abandon\n                                                [default: 0]\n    --account_id=<account_id>                : (str) restrict operation to specific\n                                                account, otherwise all accounts in wallet\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) transaction abandoning the supports\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "support_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create a support or a tip for name claim."
                ],
                "usage": [
                    "    support create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)",
                    "                   [--tip] [--account_id=<account_id>]"
                ],
                "kwargs": 19
            },
            "arguments": [
                {
                    "name": "claim_id",
                    "desc": [
                        "claim_id of the claim to support"
                    ],
                    "type": "str"
                },
                {
                    "name": "amount",
                    "desc": [
                        "amount of support"
                    ],
                    "type": "str"
                },
                {
                    "name": "tip",
                    "desc": [
                        "send support to claim owner"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "account to use for holding the support"
                    ],
                    "type": "str"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "new support transaction"
                ],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "support",
            "cli": "support create",
            "help": "Create a support or a tip for name claim.\n\nUsage:\n    support create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)\n                   [--tip] [--account_id=<account_id>]\n                   [--change_account_id=<change_account_id>]\n                   [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --claim_id=<claim_id>                    : (str) claim_id of the claim to support\n    --amount=<amount>                        : (str) amount of support\n    --tip                                    : (bool) send support to claim owner\n    --account_id=<account_id>                : (str) account to use for holding the\n                                                support\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) new support transaction\n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "support_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List staked supports and sent/received tips."
                ],
                "usage": [
                    "    support list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]",
                    "                 [--name=<name>...] [--claim_id=<claim_id>...]",
                    "                 [--received | --sent | --staked] [--is_spent]"
                ],
                "kwargs": 17
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "name",
                    "desc": [
                        "support for specific claim name(s)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "support for specific claim id(s)"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "received",
                    "desc": [
                        "only show received (tips)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "sent",
                    "desc": [
                        "only show sent (tips)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "staked",
                    "desc": [
                        "only show my staked supports"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "show abandoned supports"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "support",
            "cli": "support list",
            "help": "List staked supports and sent/received tips.\n\nUsage:\n    support list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n                 [--name=<name>...] [--claim_id=<claim_id>...]\n                 [--received | --sent | --staked] [--is_spent]\n                 [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --account_id=<account_id>  : (str) restrict operation to specific account\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n    --name=<name>              : (str, list) support for specific claim name(s)\n    --claim_id=<claim_id>      : (str, list) support for specific claim id(s)\n    --received                 : (bool) only show received (tips)\n    --sent                     : (bool) only show sent (tips)\n    --staked                   : (bool) only show my staked supports\n    --is_spent                 : (bool) show abandoned supports\n    --page=<page>              : (int) page to return for paginating\n    --page_size=<page_size>    : (int) number of items on page for pagination\n    --include_total            : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "support_search": {
            "name": "search",
            "desc": {
                "text": [
                    "Search for supports on the blockchain.",
                    "Arguments marked with \"supports equality constraints\" allow prepending the",
                    "value with an equality constraint such as '>', '>=', '<' and '<='",
                    "eg. --height=\">400000\" would limit results to only supports above 400k block height."
                ],
                "usage": [
                    "    support search [--wallet_id=<wallet_id>] [--order_by=<order_by>...]"
                ],
                "kwargs": 19
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet to check if support is owned by user"
                    ],
                    "type": "str"
                },
                {
                    "name": "order_by",
                    "desc": [
                        "field to order by"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "full claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "search results"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "claim_id",
                    "desc": [
                        "full claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id"
                    ],
                    "type": "str"
                },
                {
                    "name": "nout",
                    "desc": [
                        "position in the transaction"
                    ],
                    "type": "int"
                },
                {
                    "name": "height",
                    "desc": [
                        "last updated block height (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "timestamp",
                    "desc": [
                        "last updated timestamp (supports equality constraints)"
                    ],
                    "type": "int"
                },
                {
                    "name": "amount",
                    "desc": [
                        "claim amount (supports equality constraints)"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "support",
            "cli": "support search",
            "help": "Search for supports on the blockchain.\nArguments marked with \"supports equality constraints\" allow prepending the\nvalue with an equality constraint such as '>', '>=', '<' and '<='\neg. --height=\">400000\" would limit results to only supports above 400k block height.\n\nUsage:\n    support search [--wallet_id=<wallet_id>] [--order_by=<order_by>...]\n                   [--claim_id=<claim_id>...] [--txid=<txid>] [--nout=<nout>]\n                   [--height=<height>] [--timestamp=<timestamp>] [--amount=<amount>]\n                   [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) wallet to check if support is owned by user\n    --order_by=<order_by>    : (str, list) field to order by\n    --claim_id=<claim_id>    : (str, list) full claim id\n    --txid=<txid>            : (str) transaction id\n    --nout=<nout>            : (int) position in the transaction\n    --height=<height>        : (int) last updated block height (supports equality\n                                constraints)\n    --timestamp=<timestamp>  : (int) last updated timestamp (supports equality\n                                constraints)\n    --amount=<amount>        : (str) claim amount (supports equality constraints)\n    --page=<page>            : (int) page to return for paginating\n    --page_size=<page_size>  : (int) number of items on page for pagination\n    --include_total          : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) search results\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "sync_apply": {
            "name": "apply",
            "desc": {
                "text": [
                    "Apply incoming synchronization data, if provided, and return a sync hash and update wallet data.",
                    "Wallet must be unlocked to perform this operation.",
                    "If \"encrypt-on-disk\" preference is True and supplied password is different from local password,",
                    "or there is no local password (because local wallet was not encrypted), then the supplied password",
                    "will be used for local encryption (overwriting previous local encryption password)."
                ],
                "usage": [
                    "    sync apply <password> [--data=<data>] [--wallet_id=<wallet_id>] [--blocking]"
                ],
                "returns": [
                    "    {",
                    "        'hash': (str) hash of wallet,",
                    "        'data': (str) encrypted wallet",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "password",
                    "desc": [
                        "password to decrypt incoming and encrypt outgoing data"
                    ],
                    "type": "str"
                },
                {
                    "name": "data",
                    "desc": [
                        "incoming sync data, if any"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet being sync'ed"
                    ],
                    "type": "str"
                },
                {
                    "name": "blocking",
                    "desc": [
                        "wait until any new accounts have sync'ed"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "sync hash and data"
                ],
                "type": "dict"
            },
            "group": "sync",
            "cli": "sync apply",
            "help": "Apply incoming synchronization data, if provided, and return a sync hash and update wallet data.\nWallet must be unlocked to perform this operation.\nIf \"encrypt-on-disk\" preference is True and supplied password is different from local password,\nor there is no local password (because local wallet was not encrypted), then the supplied password\nwill be used for local encryption (overwriting previous local encryption password).\n\nUsage:\n    sync apply <password> [--data=<data>] [--wallet_id=<wallet_id>] [--blocking]\n\nOptions:\n    --password=<password>    : (str) password to decrypt incoming and encrypt outgoing\n                                data\n    --data=<data>            : (str) incoming sync data, if any\n    --wallet_id=<wallet_id>  : (str) wallet being sync'ed\n    --blocking               : (bool) wait until any new accounts have sync'ed\n\nReturns:\n    (dict) sync hash and data\n    {\n        'hash': (str) hash of wallet,\n        'data': (str) encrypted wallet\n    }"
        },
        "sync_hash": {
            "name": "hash",
            "desc": {
                "text": [
                    "Deterministic hash of the wallet."
                ],
                "usage": [
                    "    sync hash [<wallet_id> | --wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet for which to generate hash"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "sha256 hash of wallet"
                ],
                "type": "str"
            },
            "group": "sync",
            "cli": "sync hash",
            "help": "Deterministic hash of the wallet.\n\nUsage:\n    sync hash [<wallet_id> | --wallet_id=<wallet_id>]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) wallet for which to generate hash\n\nReturns:\n    (str) sha256 hash of wallet"
        },
        "tracemalloc_disable": {
            "name": "disable",
            "desc": {
                "text": [
                    "Disable tracemalloc memory tracing "
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "is it tracing?"
                ],
                "type": "bool"
            },
            "group": "tracemalloc",
            "cli": "tracemalloc disable",
            "help": "Disable tracemalloc memory tracing \n\nUsage:\n    tracemalloc disable\n\nReturns:\n    (bool) is it tracing?"
        },
        "tracemalloc_enable": {
            "name": "enable",
            "desc": {
                "text": [
                    "Enable tracemalloc memory tracing "
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "is it tracing?"
                ],
                "type": "bool"
            },
            "group": "tracemalloc",
            "cli": "tracemalloc enable",
            "help": "Enable tracemalloc memory tracing \n\nUsage:\n    tracemalloc enable\n\nReturns:\n    (bool) is it tracing?"
        },
        "tracemalloc_top": {
            "name": "top",
            "desc": {
                "text": [
                    "Show most common objects, the place that created them and their size."
                ],
                "usage": [
                    "    tracemalloc top [(<items> | --items=<items>)]"
                ],
                "returns": [
                    "    {",
                    "        \"line\": (str) filename and line number where it was created,",
                    "        \"code\": (str) code that created it,",
                    "        \"size\": (int) size in bytes, for each \"memory block\",",
                    "        \"count\" (int) number of memory blocks",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "items",
                    "desc": [
                        "maximum items to return, from the most common"
                    ],
                    "default": 10,
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [
                    "dictionary containing most common objects in memory"
                ],
                "type": "dict"
            },
            "group": "tracemalloc",
            "cli": "tracemalloc top",
            "help": "Show most common objects, the place that created them and their size.\n\nUsage:\n    tracemalloc top [(<items> | --items=<items>)]\n\nOptions:\n    --items=<items>  : (int) maximum items to return, from the most common [default: 10]\n\nReturns:\n    (dict) dictionary containing most common objects in memory\n    {\n        \"line\": (str) filename and line number where it was created,\n        \"code\": (str) code that created it,\n        \"size\": (int) size in bytes, for each \"memory block\",\n        \"count\" (int) number of memory blocks\n    }"
        },
        "transaction_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List transactions belonging to wallet"
                ],
                "usage": [
                    "    transaction_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ],
                "kwargs": 21,
                "returns": [
                    "    {",
                    "        \"claim_info\": (list) claim info if in txn [{",
                    "                                                \"address\": (str) address of claim,",
                    "                                                \"balance_delta\": (float) bid amount,",
                    "                                                \"amount\": (float) claim amount,",
                    "                                                \"claim_id\": (str) claim id,",
                    "                                                \"claim_name\": (str) claim name,",
                    "                                                \"nout\": (int) nout",
                    "                                                }],",
                    "        \"abandon_info\": (list) abandon info if in txn [{",
                    "                                                \"address\": (str) address of abandoned claim,",
                    "                                                \"balance_delta\": (float) returned amount,",
                    "                                                \"amount\": (float) claim amount,",
                    "                                                \"claim_id\": (str) claim id,",
                    "                                                \"claim_name\": (str) claim name,",
                    "                                                \"nout\": (int) nout",
                    "                                                }],",
                    "        \"confirmations\": (int) number of confirmations for the txn,",
                    "        \"date\": (str) date and time of txn,",
                    "        \"fee\": (float) txn fee,",
                    "        \"support_info\": (list) support info if in txn [{",
                    "                                                \"address\": (str) address of support,",
                    "                                                \"balance_delta\": (float) support amount,",
                    "                                                \"amount\": (float) support amount,",
                    "                                                \"claim_id\": (str) claim id,",
                    "                                                \"claim_name\": (str) claim name,",
                    "                                                \"is_tip\": (bool),",
                    "                                                \"nout\": (int) nout",
                    "                                                }],",
                    "        \"timestamp\": (int) timestamp,",
                    "        \"txid\": (str) txn id,",
                    "        \"update_info\": (list) update info if in txn [{",
                    "                                                \"address\": (str) address of claim,",
                    "                                                \"balance_delta\": (float) credited/debited",
                    "                                                \"amount\": (float) absolute amount,",
                    "                                                \"claim_id\": (str) claim id,",
                    "                                                \"claim_name\": (str) claim name,",
                    "                                                \"nout\": (int) nout",
                    "                                                }],",
                    "        \"value\": (float) value of txn",
                    "    }"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "transactions"
                ],
                "type": "list"
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "transaction",
            "cli": "transaction list",
            "help": "List transactions belonging to wallet\n\nUsage:\n    transaction_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n                     [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --account_id=<account_id>  : (str) restrict operation to specific account\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n    --page=<page>              : (int) page to return for paginating\n    --page_size=<page_size>    : (int) number of items on page for pagination\n    --include_total            : (bool) calculate total number of items and pages\n\nReturns:\n    (list) transactions\n    {\n        \"claim_info\": (list) claim info if in txn [{\n                                                \"address\": (str) address of claim,\n                                                \"balance_delta\": (float) bid amount,\n                                                \"amount\": (float) claim amount,\n                                                \"claim_id\": (str) claim id,\n                                                \"claim_name\": (str) claim name,\n                                                \"nout\": (int) nout\n                                                }],\n        \"abandon_info\": (list) abandon info if in txn [{\n                                                \"address\": (str) address of abandoned claim,\n                                                \"balance_delta\": (float) returned amount,\n                                                \"amount\": (float) claim amount,\n                                                \"claim_id\": (str) claim id,\n                                                \"claim_name\": (str) claim name,\n                                                \"nout\": (int) nout\n                                                }],\n        \"confirmations\": (int) number of confirmations for the txn,\n        \"date\": (str) date and time of txn,\n        \"fee\": (float) txn fee,\n        \"support_info\": (list) support info if in txn [{\n                                                \"address\": (str) address of support,\n                                                \"balance_delta\": (float) support amount,\n                                                \"amount\": (float) support amount,\n                                                \"claim_id\": (str) claim id,\n                                                \"claim_name\": (str) claim name,\n                                                \"is_tip\": (bool),\n                                                \"nout\": (int) nout\n                                                }],\n        \"timestamp\": (int) timestamp,\n        \"txid\": (str) txn id,\n        \"update_info\": (list) update info if in txn [{\n                                                \"address\": (str) address of claim,\n                                                \"balance_delta\": (float) credited/debited\n                                                \"amount\": (float) absolute amount,\n                                                \"claim_id\": (str) claim id,\n                                                \"claim_name\": (str) claim name,\n                                                \"nout\": (int) nout\n                                                }],\n        \"value\": (float) value of txn\n    }"
        },
        "transaction_search": {
            "name": "search",
            "desc": {
                "text": [
                    "Search for transaction(s) in the entire blockchain."
                ],
                "usage": [
                    "    transaction_search <txid>..."
                ]
            },
            "arguments": [
                {
                    "name": "txids",
                    "desc": [
                        "transaction ids to find"
                    ],
                    "type": "str, list"
                }
            ],
            "returns": {
                "desc": [],
                "type": "List[Transaction]"
            },
            "group": "transaction",
            "cli": "transaction search",
            "help": "Search for transaction(s) in the entire blockchain.\n\nUsage:\n    transaction_search <txid>...\n\nOptions:\n    --txids=<txids>  : (str, list) transaction ids to find\n\nReturns:\n    (List[Transaction]) "
        },
        "txo_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List my transaction outputs."
                ],
                "usage": [
                    "    txo list [--include_received_tips] [--resolve] [--order_by]"
                ],
                "kwargs": 13
            },
            "arguments": [
                {
                    "name": "include_received_tips",
                    "desc": [
                        "calculate the amount of tips recieved for claim outputs"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "resolve",
                    "desc": [
                        "resolves each claim to provide additional metadata"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "order_by",
                    "desc": [
                        "field to order by: 'name', 'height', 'amount' and 'none'"
                    ],
                    "type": "str"
                },
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "txo",
            "cli": "txo list",
            "help": "List my transaction outputs.\n\nUsage:\n    txo list [--include_received_tips] [--resolve] [--order_by]\n             [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]\n             [--channel_id=<channel_id>...] [--name=<name>...] [--is_spent]\n             [--is_not_spent] [--is_my_input_or_output] [--is_my_output]\n             [--is_not_my_output] [--is_my_input] [--is_not_my_input]\n             [--exclude_internal_transfers] [--account_id=<account_id>...] [--page=<page>]\n             [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --include_received_tips       : (bool) calculate the amount of tips recieved for claim\n                                     outputs\n    --resolve                     : (bool) resolves each claim to provide additional\n                                     metadata\n    --order_by=<order_by>         : (str) field to order by: 'name', 'height', 'amount'\n                                     and 'none'\n    --type=<type>                 : (str, list) claim type: stream, channel, support,\n                                     purchase, collection, repost, other\n    --txid=<txid>                 : (str, list) transaction id of outputs\n    --claim_id=<claim_id>         : (str, list) claim id\n    --channel_id=<channel_id>     : (str, list) claims in this channel\n    --name=<name>                 : (str, list) claim name\n    --is_spent                    : (bool) only show spent txos\n    --is_not_spent                : (bool) only show not spent txos\n    --is_my_input_or_output       : (bool) txos which have your inputs or your outputs, if\n                                     using this flag the other related flags are ignored.\n                                     (\"--is_my_output\", \"--is_my_input\", etc)\n    --is_my_output                : (bool) show outputs controlled by you\n    --is_not_my_output            : (bool) show outputs not controlled by you\n    --is_my_input                 : (bool) show outputs created by you\n    --is_not_my_input             : (bool) show outputs not created by you\n    --exclude_internal_transfers  : (bool) excludes any outputs that are exactly this\n                                     combination: \"--is_my_input\" + \"--is_my_output\" + \"--\n                                     type=other\" this allows to exclude \"change\" payments,\n                                     this flag can be used in combination with any of the\n                                     other flags\n    --account_id=<account_id>     : (str, list) id(s) of the account(s) to query\n    --page=<page>                 : (int) page to return for paginating\n    --page_size=<page_size>       : (int) number of items on page for pagination\n    --include_total               : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "txo_plot": {
            "name": "plot",
            "desc": {
                "text": [
                    "Plot transaction output sum over days."
                ],
                "usage": [
                    "    txo_plot [--days_back=<days_back> |",
                    "                [--start_day=<start_day> [--days_after=<days_after> | --end_day=<end_day>]]",
                    "             ]"
                ],
                "kwargs": 13
            },
            "arguments": [
                {
                    "name": "days_back",
                    "desc": [
                        "number of days back from today",
                        "(not compatible with --start_day, --days_after, --end_day)"
                    ],
                    "default": 0,
                    "type": "int"
                },
                {
                    "name": "start_day",
                    "desc": [
                        "start on specific date (format: YYYY-MM-DD) (instead of --days_back)"
                    ],
                    "type": "str"
                },
                {
                    "name": "days_after",
                    "desc": [
                        "end number of days after --start_day (instead of using --end_day)"
                    ],
                    "type": "int"
                },
                {
                    "name": "end_day",
                    "desc": [
                        "end on specific date (format: YYYY-MM-DD) (instead of --days_after)"
                    ],
                    "type": "str"
                },
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "List"
            },
            "kwargs": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "txo",
            "cli": "txo plot",
            "help": "Plot transaction output sum over days.\n\nUsage:\n    txo_plot [--days_back=<days_back> |\n                [--start_day=<start_day> [--days_after=<days_after> | --end_day=<end_day>]]\n             ]\n             [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]\n             [--channel_id=<channel_id>...] [--name=<name>...] [--is_spent]\n             [--is_not_spent] [--is_my_input_or_output] [--is_my_output]\n             [--is_not_my_output] [--is_my_input] [--is_not_my_input]\n             [--exclude_internal_transfers] [--account_id=<account_id>...] [--page=<page>]\n             [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --days_back=<days_back>       : (int) number of days back from today (not compatible\n                                     with --start_day, --days_after, --end_day) [default:\n                                     0]\n    --start_day=<start_day>       : (str) start on specific date (format: YYYY-MM-DD)\n                                     (instead of --days_back)\n    --days_after=<days_after>     : (int) end number of days after --start_day (instead of\n                                     using --end_day)\n    --end_day=<end_day>           : (str) end on specific date (format: YYYY-MM-DD)\n                                     (instead of --days_after)\n    --type=<type>                 : (str, list) claim type: stream, channel, support,\n                                     purchase, collection, repost, other\n    --txid=<txid>                 : (str, list) transaction id of outputs\n    --claim_id=<claim_id>         : (str, list) claim id\n    --channel_id=<channel_id>     : (str, list) claims in this channel\n    --name=<name>                 : (str, list) claim name\n    --is_spent                    : (bool) only show spent txos\n    --is_not_spent                : (bool) only show not spent txos\n    --is_my_input_or_output       : (bool) txos which have your inputs or your outputs, if\n                                     using this flag the other related flags are ignored.\n                                     (\"--is_my_output\", \"--is_my_input\", etc)\n    --is_my_output                : (bool) show outputs controlled by you\n    --is_not_my_output            : (bool) show outputs not controlled by you\n    --is_my_input                 : (bool) show outputs created by you\n    --is_not_my_input             : (bool) show outputs not created by you\n    --exclude_internal_transfers  : (bool) excludes any outputs that are exactly this\n                                     combination: \"--is_my_input\" + \"--is_my_output\" + \"--\n                                     type=other\" this allows to exclude \"change\" payments,\n                                     this flag can be used in combination with any of the\n                                     other flags\n    --account_id=<account_id>     : (str, list) id(s) of the account(s) to query\n    --page=<page>                 : (int) page to return for paginating\n    --page_size=<page_size>       : (int) number of items on page for pagination\n    --include_total               : (bool) calculate total number of items and pages\n\nReturns:\n    (List) "
        },
        "txo_spend": {
            "name": "spend",
            "desc": {
                "text": [
                    "Spend transaction outputs, batching into multiple transactions as necessary."
                ],
                "usage": [
                    "    txo spend [--batch_size=<batch_size>] [--include_full_tx]"
                ],
                "kwargs": 14
            },
            "arguments": [
                {
                    "name": "batch_size",
                    "desc": [
                        "number of txos to spend per transactions"
                    ],
                    "default": 500,
                    "type": "int"
                },
                {
                    "name": "include_full_tx",
                    "desc": [
                        "include entire tx in output and not just the txid"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict results to specific wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "List[Transaction]"
            },
            "kwargs": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "txo",
            "cli": "txo spend",
            "help": "Spend transaction outputs, batching into multiple transactions as necessary.\n\nUsage:\n    txo spend [--batch_size=<batch_size>] [--include_full_tx]\n              [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]\n              [--channel_id=<channel_id>...] [--name=<name>...] [--is_spent]\n              [--is_not_spent] [--is_my_input_or_output] [--is_my_output]\n              [--is_not_my_output] [--is_my_input] [--is_not_my_input]\n              [--exclude_internal_transfers] [--account_id=<account_id>...]\n              [--change_account_id=<change_account_id>]\n              [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --batch_size=<batch_size>                : (int) number of txos to spend per\n                                                transactions [default: 500]\n    --include_full_tx                        : (bool) include entire tx in output and not\n                                                just the txid\n    --wallet_id=<wallet_id>                  : (str) restrict results to specific wallet\n    --type=<type>                            : (str, list) claim type: stream, channel,\n                                                support, purchase, collection, repost,\n                                                other\n    --txid=<txid>                            : (str, list) transaction id of outputs\n    --claim_id=<claim_id>                    : (str, list) claim id\n    --channel_id=<channel_id>                : (str, list) claims in this channel\n    --name=<name>                            : (str, list) claim name\n    --is_spent                               : (bool) only show spent txos\n    --is_not_spent                           : (bool) only show not spent txos\n    --is_my_input_or_output                  : (bool) txos which have your inputs or your\n                                                outputs, if using this flag the other\n                                                related flags are ignored. (\"--\n                                                is_my_output\", \"--is_my_input\", etc)\n    --is_my_output                           : (bool) show outputs controlled by you\n    --is_not_my_output                       : (bool) show outputs not controlled by you\n    --is_my_input                            : (bool) show outputs created by you\n    --is_not_my_input                        : (bool) show outputs not created by you\n    --exclude_internal_transfers             : (bool) excludes any outputs that are\n                                                exactly this combination: \"--is_my_input\" +\n                                                \"--is_my_output\" + \"--type=other\" this\n                                                allows to exclude \"change\" payments, this\n                                                flag can be used in combination with any of\n                                                the other flags\n    --account_id=<account_id>                : (str, list) id(s) of the account(s) to\n                                                query\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (List[Transaction]) "
        },
        "txo_sum": {
            "name": "sum",
            "desc": {
                "text": [
                    "Sum of transaction outputs."
                ],
                "usage": [
                    "    txo sum"
                ],
                "kwargs": 12
            },
            "arguments": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "sum of filtered outputs"
                ],
                "type": "int"
            },
            "kwargs": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "txo",
            "cli": "txo sum",
            "help": "Sum of transaction outputs.\n\nUsage:\n    txo sum\n            [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]\n            [--channel_id=<channel_id>...] [--name=<name>...] [--is_spent]\n            [--is_not_spent] [--is_my_input_or_output] [--is_my_output]\n            [--is_not_my_output] [--is_my_input] [--is_not_my_input]\n            [--exclude_internal_transfers] [--account_id=<account_id>...]\n            [--change_account_id=<change_account_id>]\n            [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --type=<type>                            : (str, list) claim type: stream, channel,\n                                                support, purchase, collection, repost,\n                                                other\n    --txid=<txid>                            : (str, list) transaction id of outputs\n    --claim_id=<claim_id>                    : (str, list) claim id\n    --channel_id=<channel_id>                : (str, list) claims in this channel\n    --name=<name>                            : (str, list) claim name\n    --is_spent                               : (bool) only show spent txos\n    --is_not_spent                           : (bool) only show not spent txos\n    --is_my_input_or_output                  : (bool) txos which have your inputs or your\n                                                outputs, if using this flag the other\n                                                related flags are ignored. (\"--\n                                                is_my_output\", \"--is_my_input\", etc)\n    --is_my_output                           : (bool) show outputs controlled by you\n    --is_not_my_output                       : (bool) show outputs not controlled by you\n    --is_my_input                            : (bool) show outputs created by you\n    --is_not_my_input                        : (bool) show outputs not created by you\n    --exclude_internal_transfers             : (bool) excludes any outputs that are\n                                                exactly this combination: \"--is_my_input\" +\n                                                \"--is_my_output\" + \"--type=other\" this\n                                                allows to exclude \"change\" payments, this\n                                                flag can be used in combination with any of\n                                                the other flags\n    --account_id=<account_id>                : (str, list) id(s) of the account(s) to\n                                                query\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (int) sum of filtered outputs"
        },
        "utxo_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List unspent transaction outputs"
                ],
                "usage": [
                    "    utxo_list"
                ],
                "kwargs": 14
            },
            "arguments": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "unspent outputs"
                ],
                "type": "Paginated[Output]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "type",
                    "desc": [
                        "claim type: stream, channel, support, purchase, collection, repost, other"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "txid",
                    "desc": [
                        "transaction id of outputs"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "claim_id",
                    "desc": [
                        "claim id"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "channel_id",
                    "desc": [
                        "claims in this channel"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "name",
                    "desc": [
                        "claim name"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "is_spent",
                    "desc": [
                        "only show spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_spent",
                    "desc": [
                        "only show not spent txos"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input_or_output",
                    "desc": [
                        "txos which have your inputs or your outputs,",
                        "if using this flag the other related flags",
                        "are ignored. (\"--is_my_output\", \"--is_my_input\", etc)"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_output",
                    "desc": [
                        "show outputs controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_output",
                    "desc": [
                        "show outputs not controlled by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_my_input",
                    "desc": [
                        "show outputs created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "is_not_my_input",
                    "desc": [
                        "show outputs not created by you"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "exclude_internal_transfers",
                    "desc": [
                        "excludes any outputs that are exactly this combination:",
                        "\"--is_my_input\" + \"--is_my_output\" + \"--type=other\"",
                        "this allows to exclude \"change\" payments, this",
                        "flag can be used in combination with any of the other flags"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "account_id",
                    "desc": [
                        "id(s) of the account(s) to query"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "utxo",
            "cli": "utxo list",
            "help": "List unspent transaction outputs\n\nUsage:\n    utxo_list\n              [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]\n              [--channel_id=<channel_id>...] [--name=<name>...] [--is_spent]\n              [--is_not_spent] [--is_my_input_or_output] [--is_my_output]\n              [--is_not_my_output] [--is_my_input] [--is_not_my_input]\n              [--exclude_internal_transfers] [--account_id=<account_id>...]\n              [--page=<page>] [--page_size=<page_size>] [--include_total]\n\nOptions:\n    --type=<type>                 : (str, list) claim type: stream, channel, support,\n                                     purchase, collection, repost, other\n    --txid=<txid>                 : (str, list) transaction id of outputs\n    --claim_id=<claim_id>         : (str, list) claim id\n    --channel_id=<channel_id>     : (str, list) claims in this channel\n    --name=<name>                 : (str, list) claim name\n    --is_spent                    : (bool) only show spent txos\n    --is_not_spent                : (bool) only show not spent txos\n    --is_my_input_or_output       : (bool) txos which have your inputs or your outputs, if\n                                     using this flag the other related flags are ignored.\n                                     (\"--is_my_output\", \"--is_my_input\", etc)\n    --is_my_output                : (bool) show outputs controlled by you\n    --is_not_my_output            : (bool) show outputs not controlled by you\n    --is_my_input                 : (bool) show outputs created by you\n    --is_not_my_input             : (bool) show outputs not created by you\n    --exclude_internal_transfers  : (bool) excludes any outputs that are exactly this\n                                     combination: \"--is_my_input\" + \"--is_my_output\" + \"--\n                                     type=other\" this allows to exclude \"change\" payments,\n                                     this flag can be used in combination with any of the\n                                     other flags\n    --account_id=<account_id>     : (str, list) id(s) of the account(s) to query\n    --page=<page>                 : (int) page to return for paginating\n    --page_size=<page_size>       : (int) number of items on page for pagination\n    --include_total               : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Output]) unspent outputs\n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ]\n    }"
        },
        "utxo_release": {
            "name": "release",
            "desc": {
                "text": [
                    "When spending a UTXO it is locally locked to prevent double spends;",
                    "occasionally this can result in a UTXO being locked which ultimately",
                    "did not get spent (failed to broadcast, spend transaction was not",
                    "accepted by blockchain node, etc). This command releases the lock",
                    "on all UTXOs in your account."
                ],
                "usage": [
                    "    utxo_release [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "account_id",
                    "desc": [
                        "restrict operation to specific account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [],
                "type": None
            },
            "group": "utxo",
            "cli": "utxo release",
            "help": "When spending a UTXO it is locally locked to prevent double spends;\noccasionally this can result in a UTXO being locked which ultimately\ndid not get spent (failed to broadcast, spend transaction was not\naccepted by blockchain node, etc). This command releases the lock\non all UTXOs in your account.\n\nUsage:\n    utxo_release [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]\n\nOptions:\n    --account_id=<account_id>  : (str) restrict operation to specific account\n    --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet\n"
        },
        "version": {
            "name": "version",
            "desc": {
                "text": [
                    "Get lbrynet API server version information"
                ],
                "returns": [
                    "    {",
                    "        'processor': (str) processor type,",
                    "        'python_version': (str) python version,",
                    "        'platform': (str) platform string,",
                    "        'os_release': (str) os release string,",
                    "        'os_system': (str) os name,",
                    "        'version': (str) lbrynet version,",
                    "        'build': (str) \"dev\" | \"qa\" | \"rc\" | \"release\",",
                    "    }"
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [
                    "lbrynet version information"
                ],
                "type": "dict"
            },
            "cli": "version",
            "help": "Get lbrynet API server version information\n\nUsage:\n    version\n\nReturns:\n    (dict) lbrynet version information\n    {\n        'processor': (str) processor type,\n        'python_version': (str) python version,\n        'platform': (str) platform string,\n        'os_release': (str) os release string,\n        'os_system': (str) os name,\n        'version': (str) lbrynet version,\n        'build': (str) \"dev\" | \"qa\" | \"rc\" | \"release\",\n    }"
        },
        "wallet_add": {
            "name": "add",
            "desc": {
                "text": [
                    "Add existing wallet."
                ],
                "usage": [
                    "    wallet add (<wallet_id> | --wallet_id=<wallet_id>)"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet file name"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "added wallet"
                ],
                "type": "Wallet",
                "json": {
                    "id": "wallet_id",
                    "name": "optional wallet name"
                }
            },
            "group": "wallet",
            "cli": "wallet add",
            "help": "Add existing wallet.\n\nUsage:\n    wallet add (<wallet_id> | --wallet_id=<wallet_id>)\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) wallet file name\n\nReturns:\n    (Wallet) added wallet\n    {\n        \"id\": \"wallet_id\",\n        \"name\": \"optional wallet name\"\n    }"
        },
        "wallet_balance": {
            "name": "balance",
            "desc": {
                "text": [
                    "Return the balance of a wallet"
                ],
                "usage": [
                    "    wallet balance [<wallet_id>] [--confirmations=<confirmations>]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "balance for specific wallet, other than default wallet"
                    ],
                    "type": "str"
                },
                {
                    "name": "confirmations",
                    "desc": [
                        "only include transactions with this many confirmed blocks."
                    ],
                    "default": 0,
                    "type": "int"
                }
            ],
            "returns": {
                "desc": [],
                "type": "dict"
            },
            "group": "wallet",
            "cli": "wallet balance",
            "help": "Return the balance of a wallet\n\nUsage:\n    wallet balance [<wallet_id>] [--confirmations=<confirmations>]\n\nOptions:\n    --wallet_id=<wallet_id>          : (str) balance for specific wallet, other than\n                                        default wallet\n    --confirmations=<confirmations>  : (int) only include transactions with this many\n                                        confirmed blocks. [default: 0]\n\nReturns:\n    (dict) "
        },
        "wallet_create": {
            "name": "create",
            "desc": {
                "text": [
                    "Create a new wallet."
                ],
                "usage": [
                    "    wallet create (<wallet_id> | --wallet_id=<wallet_id>) [--skip_on_startup]",
                    "                  [--create_account] [--single_key]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "wallet file name"
                    ],
                    "type": "str"
                },
                {
                    "name": "skip_on_startup",
                    "desc": [
                        "don't add wallet to daemon_settings.yml"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "create_account",
                    "desc": [
                        "generates the default account"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "single_key",
                    "desc": [
                        "used with --create_account, creates single-key account"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [
                    "newly created wallet"
                ],
                "type": "Wallet",
                "json": {
                    "id": "wallet_id",
                    "name": "optional wallet name"
                }
            },
            "group": "wallet",
            "cli": "wallet create",
            "help": "Create a new wallet.\n\nUsage:\n    wallet create (<wallet_id> | --wallet_id=<wallet_id>) [--skip_on_startup]\n                  [--create_account] [--single_key]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) wallet file name\n    --skip_on_startup        : (bool) don't add wallet to daemon_settings.yml\n    --create_account         : (bool) generates the default account\n    --single_key             : (bool) used with --create_account, creates single-key\n                                account\n\nReturns:\n    (Wallet) newly created wallet\n    {\n        \"id\": \"wallet_id\",\n        \"name\": \"optional wallet name\"\n    }"
        },
        "wallet_decrypt": {
            "name": "decrypt",
            "desc": {
                "text": [
                    "Decrypt an encrypted wallet, this will remove the wallet password. The wallet must be unlocked to decrypt it"
                ],
                "usage": [
                    "    wallet decrypt [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "true if wallet has been decrypted"
                ],
                "type": "bool"
            },
            "group": "wallet",
            "cli": "wallet decrypt",
            "help": "Decrypt an encrypted wallet, this will remove the wallet password. The wallet must be unlocked to decrypt it\n\nUsage:\n    wallet decrypt [--wallet_id=<wallet_id>]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n\nReturns:\n    (bool) true if wallet has been decrypted"
        },
        "wallet_encrypt": {
            "name": "encrypt",
            "desc": {
                "text": [
                    "Encrypt an unencrypted wallet with a password"
                ],
                "usage": [
                    "    wallet encrypt (<new_password> | --new_password=<new_password>)",
                    "                   [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "new_password",
                    "desc": [
                        "password to encrypt account"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "true if wallet has been encrypted"
                ],
                "type": "bool"
            },
            "group": "wallet",
            "cli": "wallet encrypt",
            "help": "Encrypt an unencrypted wallet with a password\n\nUsage:\n    wallet encrypt (<new_password> | --new_password=<new_password>)\n                   [--wallet_id=<wallet_id>]\n\nOptions:\n    --new_password=<new_password>  : (str) password to encrypt account\n    --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet\n\nReturns:\n    (bool) true if wallet has been encrypted"
        },
        "wallet_list": {
            "name": "list",
            "desc": {
                "text": [
                    "List wallets."
                ],
                "usage": [
                    "    wallet list [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "show specific wallet only"
                    ],
                    "type": "str"
                },
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Paginated[Wallet]",
                "json": {
                    "page": "Page number of the current items.",
                    "page_size": "Number of items to show on a page.",
                    "total_pages": "Total number of pages.",
                    "total_items": "Total number of items.",
                    "items": [
                        {
                            "id": "wallet_id",
                            "name": "optional wallet name"
                        }
                    ]
                }
            },
            "kwargs": [
                {
                    "name": "page",
                    "desc": [
                        "page to return for paginating"
                    ],
                    "type": "int"
                },
                {
                    "name": "page_size",
                    "desc": [
                        "number of items on page for pagination"
                    ],
                    "type": "int"
                },
                {
                    "name": "include_total",
                    "desc": [
                        "calculate total number of items and pages"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "wallet",
            "cli": "wallet list",
            "help": "List wallets.\n\nUsage:\n    wallet list [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) show specific wallet only\n    --page=<page>            : (int) page to return for paginating\n    --page_size=<page_size>  : (int) number of items on page for pagination\n    --include_total          : (bool) calculate total number of items and pages\n\nReturns:\n    (Paginated[Wallet]) \n    {\n        \"page\": \"Page number of the current items.\",\n        \"page_size\": \"Number of items to show on a page.\",\n        \"total_pages\": \"Total number of pages.\",\n        \"total_items\": \"Total number of items.\",\n        \"items\": [\n            {\n                \"id\": \"wallet_id\",\n                \"name\": \"optional wallet name\"\n            }\n        ]\n    }"
        },
        "wallet_lock": {
            "name": "lock",
            "desc": {
                "text": [
                    "Lock an unlocked wallet"
                ],
                "usage": [
                    "    wallet lock [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "true if wallet has become locked"
                ],
                "type": "bool"
            },
            "group": "wallet",
            "cli": "wallet lock",
            "help": "Lock an unlocked wallet\n\nUsage:\n    wallet lock [--wallet_id=<wallet_id>]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n\nReturns:\n    (bool) true if wallet has become locked"
        },
        "wallet_reconnect": {
            "name": "reconnect",
            "desc": {
                "text": [
                    "Reconnects ledger network client, applying new configurations. "
                ]
            },
            "arguments": [],
            "returns": {
                "desc": [],
                "type": None
            },
            "group": "wallet",
            "cli": "wallet reconnect",
            "help": "Reconnects ledger network client, applying new configurations. \n\nUsage:\n    wallet reconnect\n"
        },
        "wallet_remove": {
            "name": "remove",
            "desc": {
                "text": [
                    "Remove an existing wallet."
                ],
                "usage": [
                    "    wallet remove (<wallet_id> | --wallet_id=<wallet_id>)"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "id of wallet to remove"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "removed wallet"
                ],
                "type": "Wallet",
                "json": {
                    "id": "wallet_id",
                    "name": "optional wallet name"
                }
            },
            "group": "wallet",
            "cli": "wallet remove",
            "help": "Remove an existing wallet.\n\nUsage:\n    wallet remove (<wallet_id> | --wallet_id=<wallet_id>)\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) id of wallet to remove\n\nReturns:\n    (Wallet) removed wallet\n    {\n        \"id\": \"wallet_id\",\n        \"name\": \"optional wallet name\"\n    }"
        },
        "wallet_send": {
            "name": "send",
            "desc": {
                "text": [
                    "Send the same number of credits to multiple addresses using all accounts in wallet to",
                    "fund the transaction and the default account to receive any change."
                ],
                "usage": [
                    "    wallet send <amount> <addresses>..."
                ],
                "kwargs": 16
            },
            "arguments": [
                {
                    "name": "amount",
                    "desc": [
                        "amount to send to each address"
                    ],
                    "type": "str"
                },
                {
                    "name": "addresses",
                    "desc": [
                        "addresses to send amounts to"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "returns": {
                "desc": [],
                "type": "Transaction",
                "json": {
                    "txid": "hash of transaction in hex",
                    "height": "block where transaction was recorded",
                    "inputs": [
                        "spent outputs..."
                    ],
                    "outputs": [
                        {
                            "txid": "hash of transaction in hex",
                            "nout": "position in the transaction",
                            "height": "block where transaction was recorded",
                            "amount": "value of the txo as a decimal",
                            "address": "address of who can spend the txo",
                            "confirmations": "number of confirmed blocks",
                            "is_change": "payment to change address, only available when it can be determined",
                            "is_received": "true if txo was sent from external account to this account",
                            "is_spent": "true if txo is spent",
                            "is_mine": "payment to one of your accounts, only available when it can be determined",
                            "type": "one of 'claim', 'support' or 'purchase'",
                            "name": "when type is 'claim' or 'support', this is the claim name",
                            "claim_id": "when type is 'claim', 'support' or 'purchase', this is the claim id",
                            "claim_op": "when type is 'claim', this determines if it is 'create' or 'update'",
                            "value": "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
                            "value_type": "determines the type of the 'value' field: 'channel', 'stream', etc",
                            "protobuf": "hex encoded raw protobuf version of 'value' field",
                            "permanent_url": "when type is 'claim' or 'support', this is the long permanent claim URL",
                            "claim": "for purchase outputs only, metadata of purchased claim",
                            "reposted_claim": "for repost claims only, metadata of claim being reposted",
                            "signing_channel": "for signed claims only, metadata of signing channel",
                            "is_channel_signature_valid": "for signed claims only, whether signature is valid",
                            "purchase_receipt": "metadata for the purchase transaction associated with this claim"
                        }
                    ],
                    "total_input": "sum of inputs as a decimal",
                    "total_output": "sum of outputs, sans fee, as a decimal",
                    "total_fee": "fee amount",
                    "hex": "entire transaction encoded in hex"
                }
            },
            "kwargs": [
                {
                    "name": "change_account_id",
                    "desc": [
                        "account to send excess change (LBC)"
                    ],
                    "type": "str"
                },
                {
                    "name": "fund_account_id",
                    "desc": [
                        "accounts to fund the transaction"
                    ],
                    "type": "str, list"
                },
                {
                    "name": "preview",
                    "desc": [
                        "do not broadcast the transaction"
                    ],
                    "default": False,
                    "type": "bool"
                },
                {
                    "name": "no_wait",
                    "desc": [
                        "do not wait for mempool confirmation"
                    ],
                    "default": False,
                    "type": "bool"
                }
            ],
            "group": "wallet",
            "cli": "wallet send",
            "help": "Send the same number of credits to multiple addresses using all accounts in wallet to\nfund the transaction and the default account to receive any change.\n\nUsage:\n    wallet send <amount> <addresses>...\n                [--change_account_id=<change_account_id>]\n                [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]\n\nOptions:\n    --amount=<amount>                        : (str) amount to send to each address\n    --addresses=<addresses>                  : (str, list) addresses to send amounts to\n    --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)\n    --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the\n                                                transaction\n    --preview                                : (bool) do not broadcast the transaction\n    --no_wait                                : (bool) do not wait for mempool confirmation\n\nReturns:\n    (Transaction) \n    {\n        \"txid\": \"hash of transaction in hex\",\n        \"height\": \"block where transaction was recorded\",\n        \"inputs\": [\n            \"spent outputs...\"\n        ],\n        \"outputs\": [\n            {\n                \"txid\": \"hash of transaction in hex\",\n                \"nout\": \"position in the transaction\",\n                \"height\": \"block where transaction was recorded\",\n                \"amount\": \"value of the txo as a decimal\",\n                \"address\": \"address of who can spend the txo\",\n                \"confirmations\": \"number of confirmed blocks\",\n                \"is_change\": \"payment to change address, only available when it can be determined\",\n                \"is_received\": \"true if txo was sent from external account to this account\",\n                \"is_spent\": \"true if txo is spent\",\n                \"is_mine\": \"payment to one of your accounts, only available when it can be determined\",\n                \"type\": \"one of 'claim', 'support' or 'purchase'\",\n                \"name\": \"when type is 'claim' or 'support', this is the claim name\",\n                \"claim_id\": \"when type is 'claim', 'support' or 'purchase', this is the claim id\",\n                \"claim_op\": \"when type is 'claim', this determines if it is 'create' or 'update'\",\n                \"value\": \"when type is 'claim' or 'support' with payload, this is the decoded protobuf payload\",\n                \"value_type\": \"determines the type of the 'value' field: 'channel', 'stream', etc\",\n                \"protobuf\": \"hex encoded raw protobuf version of 'value' field\",\n                \"permanent_url\": \"when type is 'claim' or 'support', this is the long permanent claim URL\",\n                \"claim\": \"for purchase outputs only, metadata of purchased claim\",\n                \"reposted_claim\": \"for repost claims only, metadata of claim being reposted\",\n                \"signing_channel\": \"for signed claims only, metadata of signing channel\",\n                \"is_channel_signature_valid\": \"for signed claims only, whether signature is valid\",\n                \"purchase_receipt\": \"metadata for the purchase transaction associated with this claim\"\n            }\n        ],\n        \"total_input\": \"sum of inputs as a decimal\",\n        \"total_output\": \"sum of outputs, sans fee, as a decimal\",\n        \"total_fee\": \"fee amount\",\n        \"hex\": \"entire transaction encoded in hex\"\n    }"
        },
        "wallet_status": {
            "name": "status",
            "desc": {
                "text": [
                    "Status of wallet including encryption/lock state."
                ],
                "usage": [
                    "    wallet status [<wallet_id> | --wallet_id=<wallet_id>]"
                ],
                "returns": [
                    "    {'is_encrypted': (bool), 'is_syncing': (bool), 'is_locked': (bool)}"
                ]
            },
            "arguments": [
                {
                    "name": "wallet_id",
                    "desc": [
                        "status of specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "status of the wallet"
                ],
                "type": "dict"
            },
            "group": "wallet",
            "cli": "wallet status",
            "help": "Status of wallet including encryption/lock state.\n\nUsage:\n    wallet status [<wallet_id> | --wallet_id=<wallet_id>]\n\nOptions:\n    --wallet_id=<wallet_id>  : (str) status of specific wallet\n\nReturns:\n    (dict) status of the wallet\n    {'is_encrypted': (bool), 'is_syncing': (bool), 'is_locked': (bool)}"
        },
        "wallet_unlock": {
            "name": "unlock",
            "desc": {
                "text": [
                    "Unlock an encrypted wallet"
                ],
                "usage": [
                    "    wallet unlock (<password> | --password=<password>) [--wallet_id=<wallet_id>]"
                ]
            },
            "arguments": [
                {
                    "name": "password",
                    "desc": [
                        "password to use for unlocking"
                    ],
                    "type": "str"
                },
                {
                    "name": "wallet_id",
                    "desc": [
                        "restrict operation to specific wallet"
                    ],
                    "type": "str"
                }
            ],
            "returns": {
                "desc": [
                    "true if wallet has become unlocked"
                ],
                "type": "bool"
            },
            "group": "wallet",
            "cli": "wallet unlock",
            "help": "Unlock an encrypted wallet\n\nUsage:\n    wallet unlock (<password> | --password=<password>) [--wallet_id=<wallet_id>]\n\nOptions:\n    --password=<password>    : (str) password to use for unlocking\n    --wallet_id=<wallet_id>  : (str) restrict operation to specific wallet\n\nReturns:\n    (bool) true if wallet has become unlocked"
        }
    }
}
