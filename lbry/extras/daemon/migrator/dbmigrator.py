# pylint: skip-file
import os
import sys
import logging

log = logging.getLogger(__name__)


def migrate_db(conf, start, end):
    current = start
    while current < end:
        if current == 1:
            from .migrate1to2 import do_migration
        elif current == 2:
            from .migrate2to3 import do_migration
        elif current == 3:
            from .migrate3to4 import do_migration
        elif current == 4:
            from .migrate4to5 import do_migration
        elif current == 5:
            from .migrate5to6 import do_migration
        elif current == 6:
            from .migrate6to7 import do_migration
        elif current == 7:
            from .migrate7to8 import do_migration
        elif current == 8:
            from .migrate8to9 import do_migration
        elif current == 9:
            from .migrate9to10 import do_migration
        elif current == 10:
            from .migrate10to11 import do_migration
        elif current == 11:
            from .migrate11to12 import do_migration
        elif current == 12:
            from .migrate12to13 import do_migration
        elif current == 13:
            from .migrate13to14 import do_migration
        elif current == 14:
            from .migrate14to15 import do_migration
        elif current == 15:
            from .migrate15to16 import do_migration
        else:
            raise Exception(f"DB migration of version {current} to {current+1} is not available")
        try:
            do_migration(conf)
        except Exception:
            log.exception("failed to migrate database")
            if os.path.exists(os.path.join(conf.data_dir, "lbrynet.sqlite")):
                backup_name = f"rev_{current}_unmigrated_database"
                count = 0
                while os.path.exists(os.path.join(conf.data_dir, backup_name + ".sqlite")):
                    count += 1
                    backup_name = f"rev_{current}_unmigrated_database_{count}"
                backup_path = os.path.join(conf.data_dir, backup_name + ".sqlite")
                os.rename(os.path.join(conf.data_dir, "lbrynet.sqlite"), backup_path)
                log.info("made a backup of the unmigrated database: %s", backup_path)
            if os.path.isfile(os.path.join(conf.data_dir, "db_revision")):
                os.remove(os.path.join(conf.data_dir, "db_revision"))
            return None
        current += 1
        log.info("successfully migrated the database from revision %i to %i", current - 1, current)
    return None


def run_migration_script():
    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format, filename="migrator.log")
    sys.stdout = open("migrator.out.log", 'w')
    sys.stderr = open("migrator.err.log", 'w')
    migrate_db(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))


if __name__ == "__main__":
    run_migration_script()
