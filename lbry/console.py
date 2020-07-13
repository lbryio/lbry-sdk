import os
import sys
import time
import itertools
from typing import Dict, Any
from tempfile import TemporaryFile

from tqdm.std import tqdm, Bar
from tqdm.utils import FormatReplace, _unicode, disp_len, disp_trim, _is_ascii

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
        self.backup = None
        self.file = None

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

    def stopping(self):
        print('bye.')

    @staticmethod
    def on_sync_progress(event):
        print(event)


class Bar2(Bar):

    def __init__(self, frac, default_len=10, charset=None):
        super().__init__(frac[0], default_len, charset)
        self.frac2 = frac[1]

    def __format__(self, format_spec):
        width = self.default_len
        row1 = (1,)*int(self.frac2 * width * 2)
        row2 = (2,)*int(self.frac * width * 2)
        fill = []
        for one, two, _ in itertools.zip_longest(row1, row2, range(width*2)):
            fill.append((one or 0)+(two or 0))
        bar = []
        for i in range(0, width*2, 2):
            if fill[i] == 1:
                if fill[i+1] == 1:
                    bar.append('▀')
                else:
                    bar.append('▘')
            elif fill[i] == 2:
                if fill[i+1] == 2:
                    bar.append('▄')
                else:
                    bar.append('▖')
            elif fill[i] == 3:
                if fill[i+1] == 1:
                    bar.append('▛')
                elif fill[i+1] == 2:
                    bar.append('▙')
                elif fill[i+1] == 3:
                    bar.append('█')
                else:
                    bar.append('▌')
            else:
                bar.append(' ')
        return ''.join(bar)


class tqdm2(tqdm):  # pylint: disable=invalid-name

    def __init__(self, initial=(0, 0), unit=('it', 'it'), total=(None, None), **kwargs):
        self.n2 = self.last_print_n2 = initial[1]  # pylint: disable=invalid-name
        self.unit2 = unit[1]
        self.total2 = total[1]
        super().__init__(initial=initial[0], unit=unit[0], total=total[0], **kwargs)

    @property
    def format_dict(self):
        d = super().format_dict
        d.update({
            'n2': self.n2,
            'unit2': self.unit2,
            'total2': self.total2,
        })
        return d

    def update(self, n=(1, 1)):
        if self.disable:
            return
        last_last_print_t = self.last_print_t
        self.n2 += n[1]
        super().update(n[0])
        if last_last_print_t != self.last_print_t:
            self.last_print_n2 = self.n2

    @staticmethod
    def format_meter(
        n, total, elapsed, ncols=None, prefix='', ascii=False,  # pylint: disable=redefined-builtin
        unit='it', unit_scale=False, rate=None, bar_format=None,
        postfix=None, unit_divisor=1000, **extra_kwargs
    ):

        # sanity check: total
        if total and n >= (total + 0.5):  # allow float imprecision (#849)
            total = None

        # apply custom scale if necessary
        if unit_scale and unit_scale not in (True, 1):
            if total:
                total *= unit_scale
            n *= unit_scale
            if rate:
                rate *= unit_scale  # by default rate = 1 / self.avg_time
            unit_scale = False

        elapsed_str = tqdm.format_interval(elapsed)

        # if unspecified, attempt to use rate = average speed
        # (we allow manual override since predicting time is an arcane art)
        if rate is None and elapsed:
            rate = n / elapsed
        inv_rate = 1 / rate if rate else None
        format_sizeof = tqdm.format_sizeof
        rate_noinv_fmt = ((format_sizeof(rate) if unit_scale else
                           '{0:5.2f}'.format(rate))
                          if rate else '?') + unit + '/s'
        rate_inv_fmt = ((format_sizeof(inv_rate) if unit_scale else
                         '{0:5.2f}'.format(inv_rate))
                        if inv_rate else '?') + 's/' + unit
        rate_fmt = rate_inv_fmt if inv_rate and inv_rate > 1 else rate_noinv_fmt

        if unit_scale:
            n_fmt = format_sizeof(n, divisor=unit_divisor)
            total_fmt = format_sizeof(total, divisor=unit_divisor) \
                if total is not None else '?'
        else:
            n_fmt = str(n)
            total_fmt = str(total) if total is not None else '?'

        try:
            postfix = ', ' + postfix if postfix else ''
        except TypeError:
            pass

        remaining = (total - n) / rate if rate and total else 0
        remaining_str = tqdm.format_interval(remaining) if rate else '?'

        # format the stats displayed to the left and right sides of the bar
        if prefix:
            # old prefix setup work around
            bool_prefix_colon_already = (prefix[-2:] == ": ")
            l_bar = prefix if bool_prefix_colon_already else prefix + ": "
        else:
            l_bar = ''

        r_bar = '| {0}/{1} [{2}<{3}, {4}{5}]'.format(
            n_fmt, total_fmt, elapsed_str, remaining_str, rate_fmt, postfix)

        # Custom bar formatting
        # Populate a dict with all available progress indicators
        format_dict = dict(
            # slight extension of self.format_dict
            n=n, n_fmt=n_fmt, total=total, total_fmt=total_fmt,
            elapsed=elapsed_str, elapsed_s=elapsed,
            ncols=ncols, desc=prefix or '', unit=unit,
            rate=inv_rate if inv_rate and inv_rate > 1 else rate,
            rate_fmt=rate_fmt, rate_noinv=rate,
            rate_noinv_fmt=rate_noinv_fmt, rate_inv=inv_rate,
            rate_inv_fmt=rate_inv_fmt,
            postfix=postfix, unit_divisor=unit_divisor,
            # plus more useful definitions
            remaining=remaining_str, remaining_s=remaining,
            l_bar=l_bar, r_bar=r_bar,
            **extra_kwargs)

        # total is known: we can predict some stats
        if total:
            n2, total2 = extra_kwargs['n2'], extra_kwargs['total2']  # pylint: disable=invalid-name

            # fractional and percentage progress
            frac = n / total
            frac2 = n2 / total2
            percentage = frac * 100

            l_bar += '{0:3.0f}%|'.format(percentage)

            if ncols == 0:
                return l_bar[:-1] + r_bar[1:]

            format_dict.update(l_bar=l_bar)
            if bar_format:
                format_dict.update(percentage=percentage)

                # auto-remove colon for empty `desc`
                if not prefix:
                    bar_format = bar_format.replace("{desc}: ", '')
            else:
                bar_format = "{l_bar}{bar}{r_bar}"

            full_bar = FormatReplace()
            try:
                nobar = bar_format.format(bar=full_bar, **format_dict)
            except UnicodeEncodeError:
                bar_format = _unicode(bar_format)
                nobar = bar_format.format(bar=full_bar, **format_dict)
            if not full_bar.format_called:
                # no {bar}, we can just format and return
                return nobar

            # Formatting progress bar space available for bar's display
            full_bar = Bar2(
                (frac, frac2),
                max(1, ncols - disp_len(nobar))
                if ncols else 10,
                charset=Bar2.ASCII if ascii is True else ascii or Bar2.UTF)
            if not _is_ascii(full_bar.charset) and _is_ascii(bar_format):
                bar_format = _unicode(bar_format)
            res = bar_format.format(bar=full_bar, **format_dict)
            return disp_trim(res, ncols) if ncols else res

        elif bar_format:
            # user-specified bar_format but no total
            l_bar += '|'
            format_dict.update(l_bar=l_bar, percentage=0)
            full_bar = FormatReplace()
            nobar = bar_format.format(bar=full_bar, **format_dict)
            if not full_bar.format_called:
                return nobar
            full_bar = Bar2(
                (0, 0),
                max(1, ncols - disp_len(nobar))
                if ncols else 10,
                charset=Bar2.BLANK)
            res = bar_format.format(bar=full_bar, **format_dict)
            return disp_trim(res, ncols) if ncols else res
        else:
            # no total: no progressbar, ETA, just progress stats
            return ((prefix + ": ") if prefix else '') + \
                   '{0}{1} [{2}, {3}{4}]'.format(
                       n_fmt, unit, elapsed_str, rate_fmt, postfix)


class Advanced(Basic):

    FORMAT = '{l_bar}{bar}| {n_fmt:>8}/{total_fmt:>8} [{elapsed:>7}<{remaining:>8}, {rate_fmt:>17}]'

    def __init__(self, service: Service):
        super().__init__(service)
        self.bars: Dict[Any, tqdm] = {}
        self.stderr = RedirectOutput('stderr')

    def starting(self):
        self.stderr.capture()
        super().starting()

    def stopping(self):
        for bar in self.bars.values():
            bar.close()
        super().stopping()
        #self.stderr.flush(self.bars['read'].write, True)
        #self.stderr.release()

    def get_or_create_bar(self, name, desc, units, totals, leave=False, bar_format=None, postfix=None, position=None):
        bar = self.bars.get(name)
        if bar is None:
            if len(units) == 2:
                bar = self.bars[name] = tqdm2(
                    desc=desc, unit=units, total=totals,
                    bar_format=bar_format or self.FORMAT, leave=leave,
                    postfix=postfix, position=position
                )
            else:
                bar = self.bars[name] = tqdm(
                    desc=desc, unit=units[0], total=totals[0],
                    bar_format=bar_format or self.FORMAT, leave=leave,
                    postfix=postfix, position=position
                )
        return bar

    def sync_init(self, name, d):
        bar_name = f"{name}#{d['id']}"
        bar = self.bars.get(bar_name)
        if bar is None:
            label = d.get('label', name[-11:])
            self.get_or_create_bar(bar_name, label, d['units'], d['total'], True)
        else:
            if d['done'][0] != -1:
                bar.update(d['done'][0] - bar.n)
            if d['done'][0] == -1 or d['done'][0] == bar.total:
                bar.close()

    def sync_main(self, name, d):
        bar = self.bars.get(name)
        if bar is None:
            label = d.get('label', name[-11:])
            self.get_or_create_bar(name, label, d['units'], d['total'], True)
            #self.last_stats = f"{d['txs']:,d} txs, {d['claims']:,d} claims and {d['supports']:,d} supports"
            #self.get_or_create_bar("read", "├─  blocks read", "blocks", d['blocks'], True)
            #self.get_or_create_bar("save", "└─┬   txs saved", "txs", d['txs'], True)
        else:
            if d['done'] == (-1,)*len(d['done']):
                base_name = name[:name.rindex('.')]
                for child_name, child_bar in self.bars.items():
                    if child_name.startswith(base_name):
                        child_bar.close()
                bar.close()
            else:
                if len(d['done']) > 1:
                    bar.update(d['done']-bar.n)
                else:
                    bar.update(d['done'][0]-bar.n)

    def sync_task(self, name, d):
        bar_name = f"{name}#{d['id']}"
        bar = self.bars.get(bar_name)
        if bar is None:
            assert d['done'][0] == 0
            label = d.get('label', name[-11:])
            self.get_or_create_bar(
                f"{name}#{d['id']}", label, d['units'], d['total'],
                name.split('.')[-1] not in ('insert', 'update', 'file')
            )
        else:
            if d['done'][0] != -1:
                main_bar_name = f"{name[:name.rindex('.')]}.main"
                if len(d['done']) > 1:
                    diff = tuple(a-b for a, b in zip(d['done'], (bar.n, bar.n2)))
                else:
                    diff = d['done'][0] - bar.n
                if main_bar_name != name:
                    main_bar = self.bars.get(main_bar_name)
                    if main_bar.unit == bar.unit:
                        main_bar.update(diff)
                bar.update(diff)
            if d['done'][0] == -1 or d['done'][0] == bar.total:
                bar.close()

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
        diff = d['step']-bar.n
        bar.update(diff)
        #if d['step'] == d['total']:
            #bar.close()

    def on_sync_progress(self, event):
        e, d = event['event'], event.get('data', {})
        if e.endswith(".init"):
            self.sync_init(e, d)
        elif e.endswith(".main"):
            self.sync_main(e, d)
        else:
            self.sync_task(e, d)

#        if e.endswith("sync.start"):
#            self.sync_start(d)
#            self.stderr.flush(self.bars['read'].write)
#        elif e.endswith("sync.complete"):
#            self.stderr.flush(self.bars['read'].write, True)
#            self.sync_complete()
#        else:
#            self.stderr.flush(self.bars['read'].write)
#            self.update_progress(e, d)
