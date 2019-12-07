from torba.client.basedatabase import constraints_to_sql

CREATE_FULL_TEXT_SEARCH = """
create virtual table if not exists search using fts5(
    claim_name, channel_name, title, description, author, tags,
    content=claim, tokenize=porter
);
"""

FTS_ORDER_BY = "bm25(search, 4.0, 8.0, 1.0, 0.5, 1.0, 0.5)"


def fts_action_sql(claims=None, action='insert'):
    select = {
        'rowid': "claim.rowid",
        'claim_name': "claim.normalized",
        'channel_name': "channel.normalized",
        'title': "claim.title",
        'description': "claim.description",
        'author': "claim.author",
        'tags': "(select group_concat(tag, ' ') from tag where tag.claim_hash=claim.claim_hash)"
    }
    if action == 'delete':
        select['search'] = '"delete"'

    where, values = "", {}
    if claims:
        where, values = constraints_to_sql({'claim.claim_hash__in': claims})
        where = 'WHERE '+where

    return f"""
        INSERT INTO search ({','.join(select.keys())})
        SELECT {','.join(select.values())} FROM claim
            LEFT JOIN claim as channel ON (claim.channel_hash=channel.claim_hash) {where}
    """, values


def update_full_text_search(action, outputs, db, is_first_sync):
    if is_first_sync:
        return
    if not outputs:
        return
    if action in ("before-delete", "before-update"):
        db.execute(*fts_action_sql(outputs, 'delete'))
    elif action in ("after-insert", "after-update"):
        db.execute(*fts_action_sql(outputs, 'insert'))
    else:
        raise ValueError(f"Invalid action for updating full text search: '{action}'")


def first_sync_finished(db):
    db.execute(*fts_action_sql())
