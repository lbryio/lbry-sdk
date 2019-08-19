import sys
import json
import random
import asyncio
import argparse
import traceback
from time import time
from datetime import datetime

try:
    import aiohttp
    import psycopg2
    import slack
except ImportError:
    print(f"To run {sys.argv[0]} you need to install aiohttp, psycopg2 and slackclient:")
    print(f"")
    print(f"  $ pip install aiohttp psycopg2 slackclient")
    print("")
    sys.exit(1)

if not sys.version_info >= (3, 7):
    print("Please use Python 3.7 or higher, this script expects that dictionary keys preserve order.")
    sys.exit(1)


async def handle_slow_query(cursor, server, command, queries):
    for query in queries:
        cursor.execute("""
        INSERT INTO wallet_server_slow_queries (server, command, query, event_time) VALUES (%s,%s,%s,%s);
        """, (server, command, query, datetime.now()))


async def handle_analytics_event(cursor, event, server):
    cursor.execute("""
    INSERT INTO wallet_server_stats (server, sessions, event_time) VALUES (%s,%s,%s);
    """, (server, event['status']['sessions'], datetime.now()))

    for command, stats in event["api"].items():
        data = {
            'server': server,
            'command': command,
            'event_time': datetime.now()
        }
        for key, value in stats.items():
            if key.endswith("_queries"):
                if key == "interrupted_queries":
                    await handle_slow_query(cursor, server, command, value)
                continue
            if isinstance(value, list):
                data.update({
                    key + '_avg': value[0],
                    key + '_min': value[1],
                    key + '_five': value[2],
                    key + '_twenty_five': value[3],
                    key + '_fifty': value[4],
                    key + '_seventy_five': value[5],
                    key + '_ninety_five': value[6],
                    key + '_max': value[7],
                })
            else:
                data[key] = value

        cursor.execute(f"""
        INSERT INTO wallet_server_command_stats ({','.join(data)})
        VALUES ({','.join('%s' for _ in data)});
        """, list(data.values()))


SLACKCLIENT = None


async def boris_says(what_boris_says):
    if SLACKCLIENT:
        await SLACKCLIENT.chat_postMessage(
            username="boris the wallet monitor",
            icon_emoji=":boris:",
            channel='#tech-sdk',
            text=what_boris_says
        )
    else:
        print(what_boris_says)


async def monitor(db, server):
    c = db.cursor()
    delay = 30
    height_changed = None, time()
    height_change_reported = False
    first_attempt = True
    while True:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(10)) as session:
                try:
                    ws = await session.ws_connect(server)
                except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
                    if first_attempt:
                        print(f"failed connecting to {server}")
                        await boris_says(random.choice([
                            f"{server} is not responding, probably dead, will not connect again.",
                        ]))
                        return
                    raise

                if first_attempt:
                    await boris_says(f"{server} is online")
                else:
                    await boris_says(f"{server} is back online")

                delay = 30
                first_attempt = False
                print(f"connected to {server}")

                async for msg in ws:
                    event = json.loads(msg.data)
                    height = event['status']['height']
                    height_change_time = int(time()-height_changed[1])
                    if height_changed[0] != height:
                        height_changed = (height, time())
                        if height_change_reported:
                            await boris_says(
                                f"Server {server} received new block after {height_change_time / 60:.1f} minutes.",
                            )
                            height_change_reported = False
                    elif height_change_time > 10*60:
                        if not height_change_reported or height_change_time % (2*60) == 0:
                            await boris_says(
                                f"It's been {height_change_time/60:.1f} minutes since {server} received a new block.",
                            )
                            height_change_reported = True
                    await handle_analytics_event(c, event, server)
                    db.commit()

        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            await boris_says(random.choice([
                f"<!channel> Guys, we have a problem! Nobody home at {server}. Will check on it again in {delay} seconds.",
                f"<!channel> Something wrong with {server}. I think dead. Will poke it again in {delay} seconds.",
                f"<!channel> Don't hear anything from {server}, maybe dead. Will try it again in {delay} seconds.",
            ]))
            await asyncio.sleep(delay)
            delay += 30


async def main(dsn, servers):
    db = ensure_database(dsn)
    await boris_says(random.choice([
        "No fear, Boris is here! I will monitor the servers now and will try not to fall asleep again.",
        "Comrad the Cat and Boris are here now, monitoring wallet servers.",
    ]))
    await asyncio.gather(*(
        asyncio.create_task(monitor(db, server))
        for server in servers
    ))


def ensure_database(dsn):
    db = psycopg2.connect(**dsn)
    c = db.cursor()

    c.execute("SELECT to_regclass('wallet_server_stats');")
    if c.fetchone()[0] is None:
        print("creating table 'wallet_server_stats'...")
        c.execute("""
        CREATE TABLE wallet_server_stats (
            server text,
            sessions integer,
            event_time timestamp
        );
        """)

    c.execute("SELECT to_regclass('wallet_server_slow_queries');")
    if c.fetchone()[0] is None:
        print("creating table 'wallet_server_slow_queries'...")
        c.execute("""
        CREATE TABLE wallet_server_slow_queries (
            server text,
            command text,
            query text,
            event_time timestamp
        );
        """)

    c.execute("SELECT to_regclass('wallet_server_command_stats');")
    if c.fetchone()[0] is None:
        print("creating table 'wallet_server_command_stats'...")
        c.execute("""
        CREATE TABLE wallet_server_command_stats (
            server text,
            command text,
            event_time timestamp,

            -- total requests received during event window
            receive_count integer,

            -- sum of these is total responses made
            cache_response_count integer,
            query_response_count integer,
            intrp_response_count integer,
            error_response_count integer,

            -- millisecond timings for non-cache responses (response_*, interrupt_*, error_*)

            response_avg float,
            response_min float,
            response_five float,
            response_twenty_five float,
            response_fifty float,
            response_seventy_five float,
            response_ninety_five float,
            response_max float,

            interrupt_avg float,
            interrupt_min float,
            interrupt_five float,
            interrupt_twenty_five float,
            interrupt_fifty float,
            interrupt_seventy_five float,
            interrupt_ninety_five float,
            interrupt_max float,

            error_avg float,
            error_min float,
            error_five float,
            error_twenty_five float,
            error_fifty float,
            error_seventy_five float,
            error_ninety_five float,
            error_max float,

            -- response, interrupt and error each also report the python, wait and sql stats

            python_avg float,
            python_min float,
            python_five float,
            python_twenty_five float,
            python_fifty float,
            python_seventy_five float,
            python_ninety_five float,
            python_max float,

            wait_avg float,
            wait_min float,
            wait_five float,
            wait_twenty_five float,
            wait_fifty float,
            wait_seventy_five float,
            wait_ninety_five float,
            wait_max float,

            sql_avg float,
            sql_min float,
            sql_five float,
            sql_twenty_five float,
            sql_fifty float,
            sql_seventy_five float,
            sql_ninety_five float,
            sql_max float,

            -- extended timings for individual sql executions
            individual_sql_avg float,
            individual_sql_min float,
            individual_sql_five float,
            individual_sql_twenty_five float,
            individual_sql_fifty float,
            individual_sql_seventy_five float,
            individual_sql_ninety_five float,
            individual_sql_max float,

            individual_sql_count integer
        );
        """)
        db.commit()
    return db


def get_dsn(args):
    dsn = {}
    for attr in ('dbname', 'user', 'password', 'host', 'port'):
        value = getattr(args, f'pg_{attr}')
        if value:
            dsn[attr] = value
    return dsn


def get_servers(args):
    if '..' in args.server_range:
        start, end = args.server_range.split('..')
    else:
        start = end = args.server_range
    return [
        args.server_url.format(i)
        for i in range(int(start), int(end)+1)
    ]


def get_slack_client(args):
    if args.slack_token:
        return slack.WebClient(token=args.slack_token, run_async=True)


def get_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--pg-dbname", default="analytics", help="PostgreSQL database name")
    parser.add_argument("--pg-user", help="PostgreSQL username")
    parser.add_argument("--pg-password", help="PostgreSQL password")
    parser.add_argument("--pg-host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--pg-port", default="5432", help="PostgreSQL port")
    parser.add_argument("--server-url", default="http://spv{}.lbry.com:50005", help="URL with '{}' placeholder")
    parser.add_argument("--server-range", default="1..5", help="Range of numbers or single number to use in URL placeholder")
    parser.add_argument("--slack-token")
    return parser.parse_args()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    args = get_args()
    SLACKCLIENT = get_slack_client(args)
    try:
        loop.run_until_complete(main(get_dsn(args), get_servers(args)))
    except KeyboardInterrupt as e:
        pass
    except Exception as e:
        loop.run_until_complete(boris_says("<!channel> I crashed with the following exception:"))
        loop.run_until_complete(boris_says(traceback.format_exc()))
    finally:
        loop.run_until_complete(
            boris_says(random.choice([
                "Wallet servers will have to watch themselves, I'm leaving now.",
                "I'm going to go take a nap, hopefully nothing blows up while I'm gone.",
                "Babushka is calling, I'll be back later, someone else watch the servers while I'm gone.",
            ]))
        )
