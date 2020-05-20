import os
from typing import Dict, Any

import tqdm

from lbry import __version__
from lbry.service.base import Service
from lbry.service.full_node import FullNode
from lbry.service.light_client import LightClient


class Console:  # silent

    def __init__(self, service: Service):
        self.service = service

    def starting(self):
        pass

    def stopping(self):
        pass


class Basic(Console):

    def __init__(self, service: Service):
        super().__init__(service)
        self.service.sync.on_progress.listen(self.on_sync_progress)

    def starting(self):
        conf = self.service.conf
        s = [f'LBRY v{__version__}']
        if isinstance(self.service, FullNode):
            s.append('Full Node')
        elif isinstance(self.service, LightClient):
            s.append('Light Client')
        if conf.processes == -1:
            s.append(f'Single Process')
        else:
            s.append(f'{conf.processes} Processes')
        s.append(f'({os.cpu_count()} CPU(s) available)')
        print(' '.join(s))

    def stopping(self):
        print('bye.')

    def on_sync_progress(self, event):
        print(event)


class Advanced(Basic):

    FORMAT = '{l_bar}{bar}| {n_fmt:>7}/{total_fmt:>8} [{elapsed}<{remaining:>5}, {rate_fmt:>15}]'

    def __init__(self, service: Service):
        super().__init__(service)
        self.bars: Dict[Any, tqdm.tqdm] = {}

    def get_or_create_bar(self, name, desc, unit, total):
        bar = self.bars.get(name)
        if bar is None:
            bar = self.bars[name] = tqdm.tqdm(
                desc=desc, unit=unit, total=total, bar_format=self.FORMAT, leave=False
            )
        return bar

    def parsing_bar(self, d):
        return self.get_or_create_bar(
            f"parsing-{d['block_file']}",
            f"├─ blk{d['block_file']:05}.dat parsing", 'blocks', d['total']
        )

    def saving_bar(self, d):
        return self.get_or_create_bar(
            f"saving-{d['block_file']}",
            f"├─ blk{d['block_file']:05}.dat  saving", "txs", d['total']
        )

    def initialize_sync_bars(self, d):
        self.bars.clear()
        self.get_or_create_bar("parsing", "total parsing", "blocks", d['blocks'])
        self.get_or_create_bar("saving", "total  saving", "txs", d['txs'])

    @staticmethod
    def update_sync_bars(main, bar, d):
        diff = d['step']-bar.last_print_n
        main.update(diff)
        bar.update(diff)
        if d['step'] == d['total']:
            bar.close()

    def on_sync_progress(self, event):
        e, d = event['event'], event.get('data', {})
        if e.endswith("start"):
            self.initialize_sync_bars(d)
        elif e.endswith('parsing'):
            self.update_sync_bars(self.bars['parsing'], self.parsing_bar(d), d)
        elif e.endswith('saving'):
            self.update_sync_bars(self.bars['saving'], self.saving_bar(d), d)
        return
        bars: Dict[int, tqdm.tqdm] = {}
        while True:
            msg = self.queue.get()
            if msg == self.STOP:
                return
            file_num, msg_type, done = msg
            bar, state = bars.get(file_num, None), self.state[file_num]
            if msg_type == 1:
                if bar is None:
                    bar = bars[file_num] = tqdm.tqdm(
                        desc=f'├─ blk{file_num:05}.dat parsing', total=state['total_blocks'],
                        unit='blocks', bar_format=self.FORMAT
                    )
                change = done - state['done_blocks']
                state['done_blocks'] = done
                bar.update(change)
                block_bar.update(change)
                if state['total_blocks'] == done:
                    bar.set_description('✔  '+bar.desc[3:])
                    bar.close()
                    bars.pop(file_num)
            elif msg_type == 2:
                if bar is None:
                    bar = bars[file_num] = tqdm.tqdm(
                        desc=f'├─ blk{file_num:05}.dat loading', total=state['total_txs'],
                        unit='txs', bar_format=self.FORMAT
                    )
                change = done - state['done_txs']
                state['done_txs'] = done
                bar.update(change)
                tx_bar.update(change)
                if state['total_txs'] == done:
                    bar.set_description('✔  '+bar.desc[3:])
                    bar.close()
                    bars.pop(file_num)
