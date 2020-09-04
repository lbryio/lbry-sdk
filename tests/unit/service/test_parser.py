from unittest import TestCase, mock
from textwrap import dedent

from docopt import docopt, DocoptExit

from lbry.service.api import API, Paginated, Wallet, expander
from lbry.service.parser import (
    parse_method, get_expanders, get_api_definitions,
    generate_options
)


class FakeAPI:

    THING_DOC = "thing doc"

    def thing_create(
        self,
        name: str,    # the name
        value1='hi',  # the first value
        value2=9,      # the second value
        _ignored=9
    ) -> str:  # thing name
        """create command doc"""

    def thing_list(
            self,
            value1: str = None,  # the first value
            value2: int = None,  # the second value with a very very long description which needs to be wrapped
            value3=False,        # a bool
                                 # multi-line
            **pagination_kwargs
    ) -> Paginated[Wallet]:  # list of wallets
        """list command doc"""

    def thing_update(self, value1: str) -> Wallet:  # updated wallet
        """update command doc"""

    def thing_delete(self, value1: str, **tx_and_pagination_kwargs) -> Wallet:  # deleted thing
        """
        delete command doc

        Usage:
            thing delete <value1>
                         {kwargs}
        """

    def not_grouped(self) -> str:  # cheese
        """
        group command doc

        Usage:
          not_grouped [--foo]

        Options:
            --foo  : (bool) blah

        Returns:
            foo bar
        """


@expander
def test_kwargs(
    somevalue=1
):
    pass


@expander
def another_test_kwargs(
    somevalue=1,
    bad_description=3,  # using linebreaks makes docopt very very --angry
):
    pass


class CommandWithRepeatedArgs(FakeAPI):
    def thing_bad(self, **test_and_another_test_kwargs) -> Wallet:
        """bad thing"""


class CommandWithDoubleDashAtLineStart(FakeAPI):
    def thing_bad(self, **another_test_kwargs):
        """bad thing"""


class TestParser(TestCase):
    maxDiff = None

    def test_parse_does_not_allow_duplicate_arguments(self):
        with self.assertRaises(Exception) as exc:
            parse_method(CommandWithRepeatedArgs.thing_bad, get_expanders())
        self.assertEqual(
            exc.exception.args[0],
            "Duplicate argument 'somevalue' in 'thing_bad'. "
            "Expander 'another_test' is attempting to add an argument which is already defined "
            "in the 'thing_bad' command (possibly by another expander)."
        )

    def test_parse_does_not_allow_two_dashes_at_start_of_line(self):
        with self.assertRaises(Exception) as exc:
            get_api_definitions(CommandWithDoubleDashAtLineStart)
        self.assertEqual(
            exc.exception.args[0],
            "Word wrapping the description for argument 'bad_description' in method 'thing_bad' "
            "resulted in a line which starts with '--' and this will break docopt. Try wrapping "
            "the '--' in quotes. Instead of --foo do \"--foo\". Line which caused this issue is:"
            "\n--angry [default: 3]"
        )

    def test_parse_method(self):
        expanders = get_expanders()
        self.assertEqual(
            parse_method(FakeAPI.thing_create, expanders), {
                'name': 'thing_create',
                'desc': {'text': ['create command doc']},
                'method': FakeAPI.thing_create,
                'arguments': [
                    {'name': 'name', 'type': 'str', 'desc': ['the name']},
                    {'name': 'value1', 'type': 'str', 'default': "'hi'", 'desc': ['the first value']},
                    {'name': 'value2', 'type': 'int', 'default': 9, 'desc': ['the second value']},
                ],
                'returns': {
                    'type': 'str',
                    'desc': ['thing name']
                }
            }
        )
        self.assertEqual(
            parse_method(FakeAPI.thing_list, expanders), {
                'name': 'thing_list',
                'desc': {'text': ['list command doc']},
                'method': FakeAPI.thing_list,
                'arguments': [
                    {'name': 'value1', 'type': 'str', 'desc': ['the first value']},
                    {'name': 'value2', 'type': 'int', 'desc': [
                        'the second value with a very very long description which needs to be wrapped']},
                    {'name': 'value3', 'type': 'bool', 'default': False, 'desc': ['a bool', 'multi-line']},
                    {'name': 'page', 'type': 'int', 'desc': ['page to return for paginating']},
                    {'name': 'page_size', 'type': 'int', 'desc': ['number of items on page for pagination']},
                    {'name': 'include_total', 'type': 'bool', 'default': False,
                     'desc': ['calculate total number of items and pages']},
                ],
                'kwargs': [
                    {'name': 'page', 'type': 'int', 'desc': ['page to return for paginating']},
                    {'name': 'page_size', 'type': 'int', 'desc': ['number of items on page for pagination']},
                    {'name': 'include_total', 'type': 'bool', 'default': False,
                     'desc': ['calculate total number of items and pages']},
                ],
                'returns': {
                    'type': 'Paginated[Wallet]',
                    'desc': ['list of wallets'],
                    'json': {
                        'page': 'Page number of the current items.',
                        'page_size': 'Number of items to show on a page.',
                        'total_pages': 'Total number of pages.',
                        'total_items': 'Total number of items.',
                        'items': [
                            {'id': 'wallet_id', 'name': 'optional wallet name'}
                        ]
                    },
                }
            }
        )
        self.assertEqual(
            parse_method(FakeAPI.thing_update, expanders), {
                'name': 'thing_update',
                'desc': {'text': ['update command doc']},
                'method': FakeAPI.thing_update,
                'arguments': [
                    {'name': 'value1', 'type': 'str', 'desc': []},
                ],
                'returns': {
                    'type': 'Wallet',
                    'desc': ['updated wallet'],
                    'json': {'id': 'wallet_id', 'name': 'optional wallet name'},
                }
            }
        )
        self.assertEqual(
            parse_method(FakeAPI.not_grouped, expanders), {
                'name': 'not_grouped',
                'desc': {
                    'text': ['group command doc'],
                    'usage': ['  not_grouped [--foo]'],
                    'options': ['    --foo  : (bool) blah'],
                    'returns': ['    foo bar']
                },
                'method': FakeAPI.not_grouped,
                'arguments': [],
                'returns': {'desc': ['cheese'], 'type': 'str'}
            }
        )


class TestGenerator(TestCase):
    maxDiff = None

    def test_generated_api_works_in_docopt(self):
        from lbry.service.metadata import interface
        for command in interface["commands"].values():
            with mock.patch('sys.exit') as exit:
                with self.assertRaises(DocoptExit):
                    docopt(command["help"], ["--help"])
                self.assertTrue(exit.called)

    def test_generate_options(self):
        expanders = get_expanders()
        self.assertEqual(
            generate_options(parse_method(FakeAPI.thing_list, expanders), indent=' '), [
                ' --value1=<value1>        : (str) the first value',
                ' --value2=<value2>        : (int) the second value with a very very long description which',
                '                             needs to be wrapped',
                ' --value3                 : (bool) a bool multi-line',
                ' --page=<page>            : (int) page to return for paginating',
                ' --page_size=<page_size>  : (int) number of items on page for pagination',
                ' --include_total          : (bool) calculate total number of items and pages',
            ]
        )

    def test_get_api_definitions(self):
        defs = get_api_definitions(FakeAPI)
        self.assertEqual({'groups', 'commands'}, set(defs))
        self.assertEqual(defs['groups'], {'thing': 'thing doc'})
        self.assertEqual(defs['commands']['thing_create']['group'], 'thing')
        self.assertEqual(defs['commands']['thing_create']['name'], 'create')
        self.assertEqual(defs['commands']['thing_list']['group'], 'thing')
        self.assertEqual(defs['commands']['thing_list']['name'], 'list')
        self.assertEqual(defs['commands']['not_grouped']['name'], 'not_grouped')
        self.assertNotIn('group', defs['commands']['not_grouped'])
        self.assertEqual(
            defs['commands']['thing_create']['help'],
            dedent("""\
            create command doc

            Usage:
                thing create

            Options:
                --name=<name>      : (str) the name
                --value1=<value1>  : (str) the first value [default: 'hi']
                --value2=<value2>  : (int) the second value [default: 9]

            Returns:
                (str) thing name""")
        )
        self.assertEqual(
            defs['commands']['thing_delete']['help'],
            dedent("""\
            delete command doc

            Usage:
                thing delete <value1>
                             [--change_account_id=<change_account_id>]
                             [--fund_account_id=<fund_account_id>...] [--preview] [--no_wait]
                             [--page=<page>] [--page_size=<page_size>] [--include_total]

            Options:
                --value1=<value1>                        : (str)
                --change_account_id=<change_account_id>  : (str) account to send excess change (LBC)
                --fund_account_id=<fund_account_id>      : (str, list) accounts to fund the
                                                            transaction
                --preview                                : (bool) do not broadcast the transaction
                --no_wait                                : (bool) do not wait for mempool confirmation
                --page=<page>                            : (int) page to return for paginating
                --page_size=<page_size>                  : (int) number of items on page for
                                                            pagination
                --include_total                          : (bool) calculate total number of items and
                                                            pages

            Returns:
                (Wallet) deleted thing
                {
                    "id": "wallet_id",
                    "name": "optional wallet name"
                }""")
        )
        self.assertEqual(
            defs['commands']['thing_list']['help'],
            dedent("""\
            list command doc

            Usage:
                thing list

            Options:
                --value1=<value1>        : (str) the first value
                --value2=<value2>        : (int) the second value with a very very long description
                                            which needs to be wrapped
                --value3                 : (bool) a bool multi-line
                --page=<page>            : (int) page to return for paginating
                --page_size=<page_size>  : (int) number of items on page for pagination
                --include_total          : (bool) calculate total number of items and pages

            Returns:
                (Paginated[Wallet]) list of wallets
                {
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
                }""")
        )
        self.assertEqual(
            defs['commands']['not_grouped']['help'],
            dedent("""\
            group command doc

            Usage:
              not_grouped [--foo]

            Options:
                --foo  : (bool) blah

            Returns:
                (str) cheese
                foo bar""")
        )
