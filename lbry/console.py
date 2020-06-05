import os
from typing import Dict, Any

import tqdm

from lbry import __version__
from lbry.service.base import Service
from lbry.service.full_node import FullNode
from lbry.service.light_client import LightClient


class Console:

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
            s.append('Threads Only')
        elif conf.processes == 0:
            s.append(f'{os.cpu_count()} Process(es)')
        else:
            s.append(f'{conf.processes} Process(es)')
        s.append(f'({os.cpu_count()} CPU(s) available)')
        print(' '.join(s))

    @staticmethod
    def stopping():
        print('bye.')

    @staticmethod
    def on_sync_progress(event):
        print(event)


class Advanced(Basic):

    FORMAT = '{l_bar}{bar}| {n_fmt:>8}/{total_fmt:>8} [{elapsed:>7}<{remaining:>8}, {rate_fmt:>15}]'

    def __init__(self, service: Service):
        super().__init__(service)
        self.bars: Dict[Any, tqdm.tqdm] = {}

    def get_or_create_bar(self, name, desc, unit, total, leave=False):
        bar = self.bars.get(name)
        if bar is None:
            bar = self.bars[name] = tqdm.tqdm(
                desc=desc, unit=unit, total=total,
                bar_format=self.FORMAT, leave=leave
            )
        return bar

    def start_sync_block_bars(self, d):
        self.bars.clear()
        self.get_or_create_bar("parse", "total parsing", "blocks", d['blocks'], True)
        self.get_or_create_bar("save", "total  saving", "txs", d['txs'], True)

    def close_sync_block_bars(self):
        self.bars.pop("parse").close()
        self.bars.pop("save").close()

    def update_sync_block_bars(self, event, d):
        bar_name = f"block-{d['block_file']}"
        bar = self.bars.get(bar_name)
        if bar is None:
            return self.get_or_create_bar(
                bar_name,
                f"├─ blk{d['block_file']:05}.dat parsing", 'blocks', d['total']
            )

        if event == "save" and bar.unit == "blocks":
            bar.desc = f"├─ blk{d['block_file']:05}.dat  saving"
            bar.unit = "txs"
            bar.reset(d['total'])
            return

        diff = d['step']-bar.last_print_n
        bar.update(diff)
        self.bars[event].update(diff)

        if event == "save" and d['step'] == d['total']:
            bar.close()

    def on_sync_progress(self, event):
        e, d = event['event'], event.get('data', {})
        if e.endswith("start"):
            self.start_sync_block_bars(d)
        elif e.endswith("block.done"):
            self.close_sync_block_bars()
        elif e.endswith("block.parse"):
            self.update_sync_block_bars("parse", d)
        elif e.endswith("block.save"):
            self.update_sync_block_bars("save", d)
