from itertools import islice
from typing import List, Union

from sqlalchemy import text, and_, or_
from sqlalchemy.sql.expression import Select, FunctionElement
from sqlalchemy.types import Numeric
from sqlalchemy.ext.compiler import compiles
try:
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # pylint: disable=unused-import
except ImportError:
    pg_insert = None

from .tables import AccountAddress


class greatest(FunctionElement):  # pylint: disable=invalid-name
    type = Numeric()
    name = 'greatest'


@compiles(greatest)
def default_greatest(element, compiler, **kw):
    return "greatest(%s)" % compiler.process(element.clauses, **kw)


@compiles(greatest, 'sqlite')
def sqlite_greatest(element, compiler, **kw):
    return "max(%s)" % compiler.process(element.clauses, **kw)


class least(FunctionElement):  # pylint: disable=invalid-name
    type = Numeric()
    name = 'least'


@compiles(least)
def default_least(element, compiler, **kw):
    return "least(%s)" % compiler.process(element.clauses, **kw)


@compiles(least, 'sqlite')
def sqlite_least(element, compiler, **kw):
    return "min(%s)" % compiler.process(element.clauses, **kw)


def chunk(rows, step):
    it, total = iter(rows), len(rows)
    for _ in range(0, total, step):
        yield list(islice(it, step))
        total -= step


def constrain_single_or_list(constraints, column, value, convert=lambda x: x):
    if value is not None:
        if isinstance(value, list):
            value = [convert(v) for v in value]
            if len(value) == 1:
                constraints[column] = value[0]
            elif len(value) > 1:
                constraints[f"{column}__in"] = value
        else:
            constraints[column] = convert(value)
    return constraints


def in_account_ids(account_ids: Union[List[str], str]):
    if isinstance(account_ids, list):
        if len(account_ids) > 1:
            return AccountAddress.c.account.in_(account_ids)
        account_ids = account_ids[0]
    return AccountAddress.c.account == account_ids


def query(table, s: Select, **constraints) -> Select:
    limit = constraints.pop('limit', None)
    if limit is not None:
        s = s.limit(limit)

    offset = constraints.pop('offset', None)
    if offset is not None:
        s = s.offset(offset)

    order_by = constraints.pop('order_by', None)
    if order_by:
        if isinstance(order_by, str):
            s = s.order_by(text(order_by))
        elif isinstance(order_by, list):
            s = s.order_by(text(', '.join(order_by)))
        else:
            raise ValueError("order_by must be string or list")

    group_by = constraints.pop('group_by', None)
    if group_by is not None:
        s = s.group_by(text(group_by))

    account_ids = constraints.pop('account_ids', [])
    if account_ids:
        s = s.where(in_account_ids(account_ids))

    if constraints:
        s = s.where(and_(*constraints_to_clause(table, constraints)))

    return s


def constraints_to_clause(tables, constraints):
    clause = []
    for key, constraint in constraints.items():
        if key.endswith('__not'):
            col, op = key[:-len('__not')], '__ne__'
        elif key.endswith('__is_null'):
            col = key[:-len('__is_null')]
            op = '__eq__'
            constraint = None
        elif key.endswith('__is_not_null'):
            col = key[:-len('__is_not_null')]
            op = '__ne__'
            constraint = None
        elif key.endswith('__lt'):
            col, op = key[:-len('__lt')], '__lt__'
        elif key.endswith('__lte'):
            col, op = key[:-len('__lte')], '__le__'
        elif key.endswith('__gt'):
            col, op = key[:-len('__gt')], '__gt__'
        elif key.endswith('__gte'):
            col, op = key[:-len('__gte')], '__ge__'
        elif key.endswith('__like'):
            col, op = key[:-len('__like')], 'like'
        elif key.endswith('__not_like'):
            col, op = key[:-len('__not_like')], 'notlike'
        elif key.endswith('__in') or key.endswith('__not_in'):
            if key.endswith('__in'):
                col, op, one_val_op = key[:-len('__in')], 'in_', '__eq__'
            else:
                col, op, one_val_op = key[:-len('__not_in')], 'notin_', '__ne__'
            if isinstance(constraint, Select):
                pass
            elif constraint:
                if isinstance(constraint, (list, set, tuple)):
                    if len(constraint) == 1:
                        op = one_val_op
                        constraint = next(iter(constraint))
                elif isinstance(constraint, str):
                    constraint = text(constraint)
                else:
                    raise ValueError(f"{col} requires a list, set or string as constraint value.")
            else:
                continue
        elif key.endswith('__or'):
            clause.append(or_(*constraints_to_clause(tables, constraint)))
            continue
        else:
            col, op = key, '__eq__'
        attr = None
        if '.' in col:
            table_name, col = col.split('.')
            _table = None
            for table in tables:
                if table.name == table_name.lower():
                    _table = table
                    break
            if _table is not None:
                attr = getattr(_table.c, col)
            else:
                raise ValueError(f"Table '{table_name}' not available: {', '.join([t.name for t in tables])}.")
        else:
            for table in tables:
                attr = getattr(table.c, col, None)
                if attr is not None:
                    break
        if attr is None:
            raise ValueError(f"Attribute '{col}' not found on tables: {', '.join([t.name for t in tables])}.")
        clause.append(getattr(attr, op)(constraint))
    return clause
