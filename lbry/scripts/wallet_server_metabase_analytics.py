import sys
import json
import asyncio
import argparse
from datetime import datetime

try:
    import aiohttp
    import psycopg2
except ImportError:
    print(f"To run {sys.argv[0]} you need to install aiohttp and psycopg2:")
    print(f"")
    print(f"  $ pip install aiohttp psycopg2")
    print("")
    sys.exit(1)

if not sys.version_info >= (3, 7):
    print("Please use Python 3.7 or higher, this script expects that dictionary keys preserve order.")
    sys.exit(1)


async def monitor(db, server):
    c = db.cursor()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(10)) as session:
        try:
            ws = await session.ws_connect(server)
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            print(f"failed connecting to {server}")
            return
        print(f"connected to {server}")

        async for msg in ws:
            r = json.loads(msg.data)

            c.execute("""
            INSERT INTO wallet_server_stats (server, sessions, event_time) VALUES (%s,%s,%s);
            """, (server, r['status']['sessions'], datetime.now()))

            for command, stats in r["api"].items():
                data = {
                    'server': server,
                    'command': command,
                    'event_time': datetime.now()
                }
                for key, value in stats.items():
                    if key.endswith("_queries"):
                        continue
                    if isinstance(value, list):
                        data.update({
                            key+'_avg': value[0],
                            key+'_min': value[1],
                            key+'_five': value[2],
                            key+'_twenty_five': value[3],
                            key+'_fifty': value[4],
                            key+'_seventy_five': value[5],
                            key+'_ninety_five': value[6],
                            key+'_max': value[7],
                        })
                    else:
                        data[key] = value

                c.execute(f"""
                INSERT INTO wallet_server_command_stats ({','.join(data)})
                VALUES ({','.join('%s' for _ in data)});
                """, list(data.values()))

            db.commit()


async def main(dsn, servers):
    db = ensure_database(dsn)
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


def get_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--pg-dbname", default="analytics", help="PostgreSQL database name")
    parser.add_argument("--pg-user", help="PostgreSQL username")
    parser.add_argument("--pg-password", help="PostgreSQL password")
    parser.add_argument("--pg-host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--pg-port", default="5432", help="PostgreSQL port")
    parser.add_argument("--server-url", default="http://spv{}.lbry.com:50005", help="URL with '{}' placeholder")
    parser.add_argument("--server-range", default="1..5", help="Range of numbers or single number to use in URL placeholder")
    return parser.parse_args()


if __name__ == "__main__":
    args = get_args()
    asyncio.run(main(get_dsn(args), get_servers(args)))
