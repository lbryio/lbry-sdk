from unittest import TestCase
from lbry.service.api import Paginated, Wallet
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
        value2=9      # the second value
    ) -> str:  # thing name
        """create command doc"""

    def thing_list(
            self,
            value1: str = None,  # the first value
            value2: int = None,  # the second value
            value3=False,        # a bool
                                 # multi-line
            **pagination_kwargs
    ) -> Paginated[Wallet]:  # list of wallets
        """list command doc"""

    def not_grouped(self) -> str:  # some string
        """
        group command doc

        Usage:
          not_grouped [--foo]

        Options:
            --foo  : (bool) blah

        Returns:
            (str) blah
        """


class TestParser(TestCase):
    maxDiff = None

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
                    {'name': 'value2', 'type': 'int', 'desc': ['the second value']},
                    {'name': 'value3', 'type': 'bool', 'default': False, 'desc': ['a bool', 'multi-line']},
                    {'name': 'page', 'type': 'int', 'desc': ['page to return during paginating']},
                    {'name': 'page_size', 'type': 'int', 'desc': ['number of items on page during pagination']}
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
            parse_method(FakeAPI.not_grouped, expanders), {
                'name': 'not_grouped',
                'desc': {
                    'text': ['group command doc'],
                    'usage': ['  not_grouped [--foo]'],
                    'options': ['    --foo  : (bool) blah'],
                    'returns': ['    (str) blah']
                },
                'method': FakeAPI.not_grouped,
                'arguments': [],
                'returns': {'desc': ['some string'], 'type': 'str'}
            }
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


class TestGenerator(TestCase):
    maxDiff = None

    def test_generate_options(self):
        expanders = get_expanders()
        self.assertEqual(
            generate_options(parse_method(FakeAPI.thing_list, expanders), indent=' '), [
                ' --value1=<value1>       : (str) the first value',
                ' --value2=<value2>       : (int) the second value',
                ' --value3                : (bool) a bool multi-line [default: False]',
                ' --page=<page>           : (int) page to return during paginating',
                ' --page_size=<page_size> : (int) number of items on page during pagination'
            ]
        )
