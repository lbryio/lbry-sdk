import curses
import time
import asyncio
from lbry.conf import Config
from lbry.extras.daemon.client import daemon_rpc

stdscr = curses.initscr()


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


def refresh(routing_table_info):
    height, width = stdscr.getmaxyx()

    node_id = routing_table_info['node_id']

    for y in range(height):
        stdscr.addstr(y, 0, " " * (width - 1))

    buckets = routing_table_info['buckets']
    stdscr.addstr(0, 0, f"node id: {node_id}")
    stdscr.addstr(1, 0, f"{len(buckets)} buckets")

    y = 3
    for i in range(len(buckets)):
        stdscr.addstr(y, 0, "bucket %s" % i)
        y += 1
        for peer in buckets[str(i)]:
            stdscr.addstr(y, 0, f"{peer['node_id'][:8]} ({peer['address']}:{peer['udp_port']})")
            y += 1
        y += 1

    stdscr.addstr(y + 1, 0, str(time.time()))
    stdscr.refresh()


async def main():
    conf = Config()
    try:
        init_curses()
        c = None
        while c not in [ord('q'), ord('Q')]:
            routing_info = await daemon_rpc(conf, 'routing_table_get')
            refresh(routing_info)
            c = stdscr.getch()
            time.sleep(0.1)
    finally:
        teardown_curses()


if __name__ == "__main__":
    asyncio.run(main())
