import curses
import time
import datetime
from jsonrpc.proxy import JSONRPCProxy

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


def refresh(node_index):
    height, width = stdscr.getmaxyx()
    node_ids = api.get_node_ids()
    node_id = node_ids[node_index]
    node_statuses = api.node_status()
    running = node_statuses[node_id]
    buckets = api.node_routing_table(node_id=node_id)

    for y in range(height):
        stdscr.addstr(y, 0, " " * (width - 1))

    stdscr.addstr(0, 0, "node id: %s, running: %s (%i/%i running)" % (node_id, running, sum(node_statuses.values()), len(node_ids)))
    stdscr.addstr(1, 0, "%i buckets, %i contacts" %
                  (len(buckets), sum([len(buckets[b]['contacts']) for b in buckets])))

    y = 3
    for i in sorted(buckets.keys()):
        stdscr.addstr(y, 0, "bucket %s" % i)
        y += 1
        for h in sorted(buckets[i]['contacts'], key=lambda x: x['node_id'].decode('hex')):
            stdscr.addstr(y, 0, '%s (%s:%i) failures: %i, last replied to us: %s, last requested from us: %s' %
                          (h['node_id'], h['address'], h['port'], h['failedRPCs'],
                           datetime.datetime.fromtimestamp(float(h['lastReplied'] or 0)),
                           datetime.datetime.fromtimestamp(float(h['lastRequested'] or 0))))
            y += 1
        y += 1

    stdscr.addstr(y + 1, 0, str(time.time()))
    stdscr.refresh()
    return len(node_ids)


def do_main():
    c = None
    nodes = 1
    node_index = 0
    while c not in [ord('q'), ord('Q')]:
        try:
            nodes = refresh(node_index)
        except:
            pass
        c = stdscr.getch()
        if c == curses.KEY_LEFT:
            node_index -= 1
            node_index = max(node_index, 0)
        elif c == curses.KEY_RIGHT:
            node_index += 1
            node_index = min(node_index, nodes - 1)
        time.sleep(0.1)


def main():
    try:
        init_curses()
        do_main()
    finally:
        teardown_curses()


if __name__ == "__main__":
    main()
