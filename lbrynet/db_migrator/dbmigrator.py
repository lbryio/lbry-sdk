def migrate_db(db_dir, start, end):
    current = start
    old_dirs = []
    while current < end:
        if current == 0:
            from lbrynet.db_migrator.migrate0to1 import do_migration
            old_dirs.append(do_migration(db_dir))
            current += 1
    return old_dirs


def run_migration_script():
    import sys
    migrate_db(sys.argv[1], sys.argv[2], sys.argv[3])