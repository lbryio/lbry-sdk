import logging
import os


def migrate_db(db_dir, start, end):
    current = start
    old_dirs = []
    if os.name == "nt":
        return old_dirs
    while current < end:
        if current == 0:
            from lbrynet.db_migrator.migrate0to1 import do_migration
            old_dirs.append(do_migration(db_dir))
            current += 1
    return old_dirs


def run_migration_script():
    import sys
    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format, filename="migrator.log")
    sys.stdout = open("migrator.out.log", 'w')
    sys.stderr = open("migrator.err.log", 'w')
    migrate_db(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
    
    
if __name__ == "__main__":
    run_migration_script()