import apsw
import atexit
import datetime
import logging
import os
import time
import threading

log = logging.getLogger(__name__)

SAVE_INTERVAL = 120

class DataNetworkStats:
    """
    Collect statistics on your data network activity
    and saves them to a database.
    """
    instance = None

    def __init__(self, conf):
        if DataNetworkStats.instance is not None:
            return self

        self.hour = None
        self._set_hour()
        self._reset_counts()
        self.conn = apsw.Connection(os.path.join(conf.data_dir,
                                                 "data_network_stats.db"))
        self.db = self.conn.cursor()

        self.db.execute("PRAGMA JOURNAL_MODE = WAL;")
        self.db.execute("PRAGMA SYNCHRONOUS = 0;")
        self.db.execute("BEGIN;")
        self.db.execute("CREATE TABLE IF NOT EXISTS hours\
            (timestamp            INTEGER NOT NULL PRIMARY KEY,\
             blobs_up             INTEGER NOT NULL DEFAULT 0,\
             blobs_down           INTEGER NOT NULL DEFAULT 0,\
             blobs_announced      INTEGER NOT NULL DEFAULT 0,\
             announcements_stored INTEGER NOT NULL DEFAULT 0,\
             findnode_responses   INTEGER NOT NULL DEFAULT 0,\
             findvalue_responses  INTEGER NOT NULL DEFAULT 0);")
        self.db.execute("COMMIT;")

        self.lock = threading.Lock()
        self.th = None

        # Cleanup
        atexit.register(self.save)

        # Start the loop
        self.start()

        DataNetworkStats.instance = self

    def __del__(self):
        if self.th is not None:
            self.th.join()

    def start(self):
        log.info("Starting data network stats save loop")
        self.th = threading.Thread(None, self.save_periodically, daemon=True)
        self.th.start()


    def save_periodically(self):
        while True:
            time.sleep(SAVE_INTERVAL)
            self.save()


    def _set_hour(self):
        """
        Get the current unix time, and update self.hour if necessary.
        Returns True if self.hour changed, False otherwise.
        """
        now = datetime.datetime.now()
        hour = now.replace(minute=0, second=0, microsecond=0)
        hour = int(hour.timestamp())
        if self.hour is None or hour != self.hour:
            self.hour = hour
            return True
        return False

    def _reset_counts(self):
        """
        Reset in-memory event counts to zero.
        """
        self.blobs_up   = 0
        self.blobs_down = 0
        self.blobs_announced = 0
        self.announcements_stored = 0
        self.findnode_responses = 0
        self.findvalue_responses = 0

    def log_event(self, what):
        """
        Log the occurrence of a data network event to RAM (it gets written
        to disk later). `what` must be one of
        "up", "down", "announce", "store", "findnode", "findvalue".
        """
        assert what in set(["up", "down", "announce",
                            "store", "findnode", "findvalue"])
        changed = self._set_hour()
        if changed:
            self.save()

        if what == "up":
            self.blobs_up += 1
        elif what == "down":
            self.blobs_down += 1
        elif what == "announce":
            self.blobs_announced += 1
        elif what == "store":
            self.announcements_stored += 1
        elif what == "findnode":
            self.findnode_responses += 1
        elif what == "findvalue":
            self.findvalue_responses += 1

    def save(self):
        """
        Save the in-memory counts to disk, and then reset the in-memory counts.
        """

        self.lock.acquire()

        if self.blobs_up == 0 and self.blobs_down == 0 \
                and self.blobs_announced == 0 and self.announcements_stored == 0 \
                and self.findnode_responses == 0 and self.findvalue_responses == 0:
            log.info(f"Nothing to save to data_network_stats.db")
            self.lock.release()
            return

        data = (self.hour, self.blobs_up, self.blobs_down,
                self.blobs_announced, self.announcements_stored,
                self.findnode_responses, self.findvalue_responses)

        self.db.execute("INSERT INTO hours VALUES (?, ?, ?, ?, ?, ?, ?)\
                         ON CONFLICT (timestamp) DO UPDATE\
                         SET blobs_up = blobs_up + excluded.blobs_up,\
                             blobs_down = blobs_down + excluded.blobs_down,\
                             blobs_announced = blobs_announced + excluded.blobs_announced,\
                             announcements_stored = announcements_stored + excluded.announcements_stored,\
                             findnode_responses = findnode_responses + excluded.findnode_responses,\
                             findvalue_responses = findvalue_responses + excluded.findvalue_responses;",
                        data)
        log.info(f"Saved events to data_network_stats.db")

        self._reset_counts()

        self.lock.release()


    def get_data(self, max_hours):
        """
        Return the entire contents of the hours table but in a list.
        Inefficient if the history gets really large...the pagination
        will load everything just to truncate it. But easy to start this way.
        """

        # Just save to disk, then assume disk is up-to-date
        self.save()

        if max_hours is None:
            max_hours = self.db.execute("SELECT COUNT(*) FROM hours;").fetchone()[0]

        result = []
        for row in self.db.execute("SELECT * FROM hours ORDER BY timestamp DESC\
                               LIMIT ?;", (max_hours, )):
            hour, up, down, announced, stored, findnode, findvalue = row
            result.append(dict(timestamp=hour,
                               blobs_up=up, blobs_down=down,
                               blobs_announced=announced,
                               announcements_stored=stored,
                               findnode_responses=findnode,
                               findvalue_responses=findvalue))
        return result
