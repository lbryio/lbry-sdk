#!/usr/bin/env python3

import asyncio
import logging
import os
import sys

from lbry.wallet import database


def enable_logging():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')  # %(asctime)s - %(levelname)s -
    handler.setFormatter(formatter)
    root.addHandler(handler)


async def initialize_tables(queue, old_file, db):

    await db.executescript("PRAGMA journal_mode=WAL")
    await db.executescript("PRAGMA case_sensitive_like=true")
    await db.executescript("CREATE TABLE IF NOT EXISTS claim_with_metadata "
                           "(claimID BLOB NOT NULL PRIMARY KEY, "
                           "name BLOB NOT NULL, "
                           "originalHeight INTEGER NOT NULL, "
                           "updateHeight INTEGER NOT NULL, "
                           "activationHeight INTEGER NOT NULL, "
                           "metadataField1 TEXT)")

    await db.executescript(f"ATTACH '{old_file}' AS crd")

    await db.create_function("NEEDS_UPDATE", 5, lambda id, name, original, update, activation:
                                  queue.put_nowait({
                                      "claimID": id, "name": name, "originalHeight": original,
                                      "updateHeight": update, "activationHeight": activation
                                  }))
    await db.executescript("CREATE TEMP TRIGGER on_claim_insert AFTER INSERT ON crd.claim "
                           "FOR EACH ROW BEGIN SELECT NEEDS_UPDATE(NEW.claimID, NEW.nodeName, "
                           "NEW.originalHeight, NEW.updateHeight, NEW.ActivationHeight); END")
    await db.executescript("CREATE TEMP TRIGGER on_claim_update AFTER UPDATE ON crd.claim "
                           "FOR EACH ROW BEGIN SELECT NEEDS_UPDATE(NEW.claimID, NEW.nodeName, "
                           "NEW.originalHeight, NEW.updateHeight, NEW.ActivationHeight); END")
    await db.executescript("CREATE TEMP TRIGGER on_claim_delete AFTER DELETE ON crd.claim "
                           "FOR EACH ROW BEGIN SELECT NEEDS_UPDATE(OLD.claimID, OLD.nodeName, 0, 0, 0); END")


async def catch_up_on_missing(queue, db):
    # items removed from crd are those that are in claim_with_metadata but not in crd
    # items inserted into crd are those in crd but not in claim_with_metadata
    # items updated are those that are in both but some columns don't match
    await db.executescript("DELETE FROM claim_with_metadata WHERE claimID NOT IN"
                           "(SELECT c.claimID FROM crd.claim c)")
    await db.executescript("INSERT INTO claim_with_metadata(claimID, name, originalHeight, updateHeight, activationHeight) "
                           "SELECT c.claimID, c.nodeName, c.originalHeight, c.updateHeight, c.activationHeight "
                           "FROM crd.claim c LEFT JOIN claim_with_metadata m ON c.claimID = m.claimID "
                           "WHERE m.claimID IS NULL OR c.nodeName != m.name OR c.updateHeight != m.updateHeight "
                           "OR c.activationHeight != m.activationHeight ON CONFLICT(claimID) DO UPDATE SET "
                           "name = excluded.name, originalHeight = excluded.originalHeight, "
                           "updateHeight = excluded.updateHeight, activationHeight = excluded.activationHeight")


async def remove_claim(claim, db):
    await db.executescript("DELETE FROM claim_with_metadata WHERE claimID = :claimID", claim)


async def insert_update(claim, db):
    # TODO: lookup and parse metadata here
    await db.executescript("INSERT INTO claim_with_metadata(claimID, name, originalHeight, updateHeight, activationHeight) "
                           "VALUES(:claimID, :name, :originalHeight, :updateHeight, :activationHeight) "
                           "ON CONFLICT(claimID) DO UPDATE SET name = excluded.name, "
                           "originalHeight = excluded.originalHeight, updateHeight = excluded.updateHeight, "
                           "activationHeight = excluded.activationHeight", claim)


async def handle_changes():
    old_file = os.path.expanduser("~/.lbrycrd/claims.sqlite")
    new_file = os.path.expanduser("~/.lbrycrd/duplicate.sqlite")
    db = database.AIOSQLite()
    db = await db.connect(new_file)  # super confusing that you have to use the return value here

    queue = asyncio.Queue()
    await initialize_tables(queue, old_file, db)
    await catch_up_on_missing(queue, db)

    while True:
        claim = await queue.get()
        if claim.updateHeight <= 0:
            await remove_claim(claim, db)
        else:
            await insert_update(claim, db)


def main():
    enable_logging()

    try:
        asyncio.run(handle_changes())
    except KeyboardInterrupt:
        logging.info("Process interrupted")


if __name__ == '__main__':
    main()
