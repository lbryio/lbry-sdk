import time
import asyncio
import random
from argparse import ArgumentParser
from torba.client.basenetwork import ClientSession


class AgentSmith(ClientSession):

    async def do_nefarious_things(self):
        await self.send_request('blockchain.claimtrie.search', {
            'no_totals': True,
            'offset': random.choice(range(0, 300, 20)),
            'limit': 20,
            'any_tags': (
                random.choice([[
                        random.choice(['gaming', 'games', 'game']) +
                        random.choice(['entertainment', 'playthrough', 'funny']) +
                        random.choice(['xbox', 'xbox one', 'xbox news'])
                    ], [
                        random.choice(['aliens', 'alien', 'ufo', 'ufos']) +
                        random.choice(['news', 'sighting', 'sightings'])
                    ], [
                        random.choice(['art', 'automotive']),
                        random.choice(['blockchain', 'economics', 'food']),
                        random.choice(['funny', 'learnings', 'nature']),
                        random.choice(['news', 'science', 'technology'])
                    ]
                ])
            ),
            'not_tags': random.choice([[], [
                'porn', 'mature', 'xxx', 'nsfw'
            ]]),
            'order_by': random.choice([
                ['release_time'],
                ['trending_global', 'trending_mixed'],
                ['effective_amount']
            ])
        })


class AgentSmithProgram:

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.agent_smiths = []

    async def make_one_more_of_them(self):
        smith = AgentSmith(network=None, server=(self.host, self.port))
        await smith.create_connection()
        self.agent_smiths.append(smith)

    async def coordinate_nefarious_activity(self):
        start = time.perf_counter()
        await asyncio.gather(
            *(s.do_nefarious_things() for s in self.agent_smiths),
            return_exceptions=True
        )
        return time.perf_counter() - start

    def __len__(self):
        return len(self.agent_smiths)

    async def delete_one_smith(self):
        if self.agent_smiths:
            await self.agent_smiths.pop().close()

    async def delete_program(self):
        await asyncio.gather(*(
            s.close() for s in self.agent_smiths
        ))


async def main(host, port):
    smiths = AgentSmithProgram(host, port)
    await smiths.make_one_more_of_them()
    activity = asyncio.create_task(smiths.coordinate_nefarious_activity())
    ease_off = 0
    for i in range(1000):
        await asyncio.sleep(1)
        if activity.done() and activity.result() < .9:
            print('more, more, more...')
            await asyncio.gather(*(
                asyncio.create_task(smiths.make_one_more_of_them()) for _ in range(20)
            ))
        else:
            print('!!!!!!!!!!!!!!')
            print('IS NEO LOSING?')
            print('!!!!!!!!!!!!!!')
            await asyncio.gather(*(
                asyncio.create_task(smiths.delete_one_smith()) for _ in range(21)
            ))
        print(f'coordinate all {len(smiths)} smiths to action')
        activity = asyncio.create_task(smiths.coordinate_nefarious_activity())
    print('finishing up any remaining actions')
    await activity
    print('neo has won, deleting agents...')
    await smiths.delete_program()
    print('done.')


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('--host', dest='host', default='localhost', type=str)
    parser.add_argument('--port', dest='port', default=50001, type=int)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
