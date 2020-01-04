import os, asyncio, aiohttp, json, slack, sqlparse


async def listen(slack_client, url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(3)) as session:
        print(f"connecting to {url}")
        try:
            ws = await session.ws_connect(url)
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            print(f"failed to connect to {url}")
            return
        print(f"connected to {url}")

        async for msg in ws:
            r = json.loads(msg.data)
            try:
                queries = r["api"]["search"]["interrupted_queries"]
            except KeyError:
                continue

            for q in queries:
                # clean = re.sub(r"\s+", " ", q)
                clean = sqlparse.format(q, reindent=True, keyword_case='upper')
                print(f'{url}: {clean}')
                response = await slack_client.chat_postMessage(
                    username=url,
                    icon_emoji=":hourglass_flowing_sand:",
                    channel='#clubhouse-de-obscure',
                    text="*Query timed out:* " + clean
                )
                if not response["ok"]:
                    print("SLACK ERROR:\n", response)
                print()


async def main():
    try:
        slack_client = slack.WebClient(token=os.environ['SLACK_TOKEN'], run_async=True)
    except KeyError:
        print("Error: SLACK_TOKEN env var required")
        return

    num_servers = 5
    tasks = []
    for i in range(1, num_servers+1):
        tasks.append(asyncio.create_task(listen(slack_client, f'http://spv{i}.lbry.com:50005')))
    await asyncio.gather(*tasks)

asyncio.run(main())
