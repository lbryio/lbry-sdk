import os
import sys
import time
from typing import Dict, Any
from tempfile import TemporaryFile

import tqdm

from lbry import __version__
from lbry.service.base import Service
from lbry.service.full_node import FullNode
from lbry.service.light_client import LightClient


class RedirectOutput:

    silence_lines = [
        b'libprotobuf ERROR google/protobuf/wire_format_lite.cc:626',
    ]

    def __init__(self, stream_type: str):
        assert stream_type in ('stderr', 'stdout')
        self.stream_type = stream_type
        self.stream_no = getattr(sys, stream_type).fileno()
        self.last_flush = time.time()
        self.last_read = 0

    def __enter__(self):
        self.backup = os.dup(self.stream_no)
        setattr(sys, self.stream_type, os.fdopen(self.backup, 'w'))
        self.file = TemporaryFile()
        self.backup = os.dup2(self.file.fileno(), self.stream_no)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()
        os.dup2(self.backup, self.stream_no)
        os.close(self.backup)
        setattr(sys, self.stream_type, os.fdopen(self.stream_no, 'w'))

    def capture(self):
        self.__enter__()

    def release(self):
        self.__exit__(None, None, None)

    def flush(self, writer, force=False):
        if not force and (time.time() - self.last_flush) < 5:
            return
        self.file.seek(self.last_read)
        for line in self.file.readlines():
            silence = False
            for bad_line in self.silence_lines:
                if bad_line in line:
                    silence = True
                    break
            if not silence:
                writer(line.decode().rstrip())
        self.last_read = self.file.tell()
        self.last_flush = time.time()


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
        self.block_savers = 0
        self.block_readers = 0
        self.stderr = RedirectOutput('stderr')

    def starting(self):
        self.stderr.capture()
        super().starting()

    def stopping(self):
        super().stopping()
        self.stderr.flush(self.bars['read'].write, True)
        self.stderr.release()

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
        if d['ending_height']-d['starting_height'] > 0:
            label = f"sync {d['starting_height']:,d}-{d['ending_height']:,d}"
        else:
            label = f"sync {d['ending_height']:,d}"
        print(label)
        self.last_stats = f"{d['txs']:,d} txs, {d['claims']:,d} claims and {d['supports']:,d} supports"
        self.get_or_create_bar("read", "├─  blocks read", "blocks", d['blocks'], True)
        self.get_or_create_bar("save", "└─┬   txs saved", "txs", d['txs'], True)

    def update_progress(self, e, d):
        if e in ('blockchain.sync.block.read', 'blockchain.sync.block.save'):
            self.update_block_bars(e, d)
        else:
            self.update_other_bars(e, d)

    def update_block_bars(self, event, d):
        total_bar = self.bars[event[-4:]]
        if event.endswith("read") and self.block_readers == 0:
            total_bar.unpause()
        if event.endswith("read") and d['step'] == d['total']:
            self.block_readers -= 1

        bar_name = f"block-{d['block_file']}"
        bar = self.bars.get(bar_name)
        if bar is None:
            self.block_readers += 1
            return self.get_or_create_bar(
                bar_name,
                f"  ├─ blk{d['block_file']:05}.dat reading", 'blocks', d['total']
            )

        if event.endswith("save") and bar.unit == "blocks":
            if self.block_savers == 0:
                total_bar.unpause()
            self.block_savers += 1
            bar.desc = f"  ├─ blk{d['block_file']:05}.dat  saving"
            bar.unit = "txs"
            bar.reset(d['total'])
            return

        diff = d['step']-bar.last_print_n
        bar.update(diff)
        if event.endswith("save") and d['step'] == d['total']:
            self.block_savers -= 1
            bar.close()

        total_bar.update(diff)
        if total_bar.total == total_bar.last_print_n:
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
        self.bars['read'].postfix = (self.last_stats,)
        for bar in self.bars.values():
            bar.close()

    def on_sync_progress(self, event):
        e, d = event['event'], event.get('data', {})
        if e.endswith("sync.start"):
            self.sync_start(d)
            self.stderr.flush(self.bars['read'].write)
        elif e.endswith("sync.complete"):
            self.stderr.flush(self.bars['read'].write, True)
            self.sync_complete()
        else:
            self.stderr.flush(self.bars['read'].write)
            self.update_progress(e, d)
