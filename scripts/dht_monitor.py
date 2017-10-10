import curses
import time
from jsonrpc.proxy import JSONRPCProxy
import logging

log = logging.getLogger(__name__)
log.addHandler(logging.FileHandler("dht contacts.log"))
# log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)
stdscr = curses.initscr()

api = JSONRPCProxy.from_url("http://localhost:5280")


def init_curses():
    curses.noecho()
    curses.cbreak()
    stdscr.nodelay(1)
    stdscr.keypad(1)


def teardown_curses():
    curses.nocbreak()
    stdscr.keypad(0)
    curses.echo()
    curses.endwin()


def refresh(last_contacts, last_blobs):
    height, width = stdscr.getmaxyx()

    try:
        routing_table_info = api.routing_table_get()
        node_id = routing_table_info['node id']
    except:
        node_id = "UNKNOWN"
        routing_table_info = {
            'buckets': {},
            'contacts': [],
            'blob hashes': []
        }
    for y in range(height):
        stdscr.addstr(y, 0, " " * (width - 1))

    buckets = routing_table_info['buckets']
    stdscr.addstr(0, 0, "node id: %s" % node_id)
    stdscr.addstr(1, 0, "%i buckets, %i contacts, %i blobs" %
                  (len(buckets), len(routing_table_info['contacts']),
                   len(routing_table_info['blob hashes'])))

    y = 3
    for i in sorted(buckets.keys()):
        stdscr.addstr(y, 0, "bucket %s" % i)
        y += 1
        for h in sorted(buckets[i], key=lambda x: x['id'].decode('hex')):
            stdscr.addstr(y, 0, '%s (%s) - %i blobs' % (h['id'], h['address'], len(h['blobs'])))
            y += 1
        y += 1

    new_contacts = set(routing_table_info['contacts']) - last_contacts
    lost_contacts = last_contacts - set(routing_table_info['contacts'])

    if new_contacts:
        for c in new_contacts:
            log.debug("added contact %s", c)
    if lost_contacts:
        for c in lost_contacts:
            log.info("lost contact %s", c)

    new_blobs = set(routing_table_info['blob hashes']) - last_blobs
    lost_blobs = last_blobs - set(routing_table_info['blob hashes'])

    if new_blobs:
        for c in new_blobs:
            log.debug("added blob %s", c)
    if lost_blobs:
        for c in lost_blobs:
            log.info("lost blob %s", c)

    stdscr.addstr(y + 1, 0, str(time.time()))
    stdscr.refresh()
    return set(routing_table_info['contacts']), set(routing_table_info['blob hashes'])


def do_main():
    c = None
    last_contacts, last_blobs = set(), set()
    while c not in [ord('q'), ord('Q')]:
        last_contacts, last_blobs = refresh(last_contacts, last_blobs)
        c = stdscr.getch()
        time.sleep(0.1)


def main():
    try:
        init_curses()
        do_main()
    finally:
        teardown_curses()


if __name__ == "__main__":
    main()
