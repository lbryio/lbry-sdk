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

    FORMAT = '{l_bar}{bar}| {n_fmt:>8}/{total_fmt:>8} [{elapsed:>7}<{remaining:>8}, {rate_fmt:>17}]'

    def __init__(self, service: Service):
        super().__init__(service)
        self.bars: Dict[Any, tqdm.tqdm] = {}
        self.is_single_sync_bar = False
        self.single_bar_relative_steps = 0
        self.last_stats = ""
        self.sync_steps = []

    def get_or_create_bar(self, name, desc, unit, total, leave=False, bar_format=None, postfix=None, position=None):
        bar = self.bars.get(name)
        if bar is None:
            bar = self.bars[name] = tqdm.tqdm(
                desc=desc, unit=unit, total=total,
                bar_format=bar_format or self.FORMAT, leave=leave,
                postfix=postfix, position=position
            )
        return bar

    def sync_start(self, d):
        self.bars.clear()
        self.sync_steps = d['sync_steps']
        if d['ending_height']-d['starting_height'] > 0:
            label = f"sync {d['starting_height']:,d}-{d['ending_height']:,d}"
        else:
            label = f"sync {d['ending_height']:,d}"
        self.last_stats = f"{d['txs']:,d} txs, {d['claims']:,d} claims and {d['supports']:,d} supports"
        self.get_or_create_bar(
            "sync", label, "tasks", len(d['sync_steps']), True,
            "{l_bar}{bar}| {postfix[0]:<55}", (self.last_stats,)
        )
        self.get_or_create_bar("read", "├─  blocks read", "blocks", d['blocks'], True)
        self.get_or_create_bar("save", "└─┬   txs saved", "txs", d['txs'], True)

    def update_progress(self, e, d):
        if e in ('blockchain.sync.block.read', 'blockchain.sync.block.save'):
            self.update_block_bars(e, d)
        else:
            self.update_steps_bar(e, d)
            self.update_other_bars(e, d)

    def update_steps_bar(self, e, d):
        sync_bar = self.bars['sync']
        if d['step'] == d['total']:
            sync_done = (self.sync_steps.index(e)+1)-sync_bar.last_print_n
            sync_bar.postfix = (f'finished: {e}',)
            sync_bar.update(sync_done)

    def update_block_bars(self, event, d):
        bar_name = f"block-{d['block_file']}"
        bar = self.bars.get(bar_name)
        if bar is None:
            return self.get_or_create_bar(
                bar_name,
                f"  ├─ blk{d['block_file']:05}.dat reading", 'blocks', d['total']
            )

        if event.endswith("save") and bar.unit == "blocks":
            bar.desc = f"  ├─ blk{d['block_file']:05}.dat  saving"
            bar.unit = "txs"
            bar.reset(d['total'])
            return

        diff = d['step']-bar.last_print_n
        bar.update(diff)
        if event.endswith("save") and d['step'] == d['total']:
            bar.close()

        total_bar = self.bars[event[-4:]]
        total_bar.update(diff)
        if total_bar.total == total_bar.last_print_n:
            self.update_steps_bar(event, {'step': 1, 'total': 1})
            if total_bar.desc.endswith('txs saved'):
                total_bar.desc = "├─    txs saved"
                total_bar.refresh()

    def update_other_bars(self, e, d):
        if d['total'] == 0:
            return
        bar = self.bars.get(e)
        if not bar:
            name = (
                ' '.join(e.split('.')[-2:])
                .replace('support', 'suprt')
                .replace('channels', 'chanls')
                .replace('signatures', 'sigs')
            )
            bar = self.get_or_create_bar(e, f"├─ {name:>12}", d['unit'], d['total'], True)
        diff = d['step']-bar.last_print_n
        bar.update(diff)
        #if d['step'] == d['total']:
            #bar.close()

    def sync_complete(self):
        self.bars['sync'].postfix = (self.last_stats,)
        for bar in self.bars.values():
            bar.close()

    def on_sync_progress(self, event):
        e, d = event['event'], event.get('data', {})
        if e.endswith("sync.start"):
            self.sync_start(d)
        elif e.endswith("sync.complete"):
            self.sync_complete()
        else:
            self.update_progress(e, d)
