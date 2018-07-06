import os
import time
from random import Random

from pyqtgraph.Qt import QtCore, QtGui
app = QtGui.QApplication([])
from qtreactor import pyqt4reactor
pyqt4reactor.install()

from twisted.internet import defer, task, threads
from orchstr8.services import LbryServiceStack

import pyqtgraph as pg


class Profiler:
    pens = [
        (230, 25, 75),   # red
        (60, 180, 75),   # green
        (255, 225, 25),  # yellow
        (0, 130, 200),   # blue
        (245, 130, 48),  # orange
        (145, 30, 180),  # purple
        (70, 240, 240),  # cyan
        (240, 50, 230),  # magenta
        (210, 245, 60),  # lime
        (250, 190, 190),  # pink
        (0, 128, 128),   # teal
    ]

    def __init__(self, graph=None):
        self.times = {}
        self.graph = graph

    def start(self, name):
        if name in self.times:
            self.times[name]['start'] = time.time()
        else:
            self.times[name] = {
                'start': time.time(),
                'data': [],
                'plot': self.graph.plot(
                    pen=self.pens[len(self.times)],
                    symbolBrush=self.pens[len(self.times)],
                    name=name
                )
            }

    def stop(self, name):
        elapsed = time.time() - self.times[name]['start']
        self.times[name]['start'] = None
        self.times[name]['data'].append(elapsed)

    def draw(self):
        for plot in self.times.values():
            plot['plot'].setData(plot['data'])


class ThePublisherOfThings:

    def __init__(self, blocks=100, txns_per_block=100, seed=2015, start_blocks=110):
        self.blocks = blocks
        self.txns_per_block = txns_per_block
        self.start_blocks = start_blocks
        self.random = Random(seed)
        self.profiler = Profiler()
        self.service = LbryServiceStack(verbose=True, profiler=self.profiler)
        self.publish_file = None

    @defer.inlineCallbacks
    def start(self):
        yield self.service.startup(
            after_lbrycrd_start=lambda: self.service.lbrycrd.generate(1010)
        )
        wallet = self.service.lbry.wallet
        address = yield wallet.get_least_used_address()
        sendtxid = yield self.service.lbrycrd.sendtoaddress(address, 100)
        yield self.service.lbrycrd.generate(1)
        yield wallet.wait_for_tx_in_wallet(sendtxid)
        yield wallet.update_balance()
        self.publish_file = os.path.join(self.service.lbry.download_directory, 'the_file')
        with open(self.publish_file, 'w') as _publish_file:
            _publish_file.write('message that will be heard around the world\n')
        yield threads.deferToThread(time.sleep, 0.5)

    @defer.inlineCallbacks
    def generate_publishes(self):

        win = pg.GraphicsLayoutWidget(show=True)
        win.setWindowTitle('orchstr8: performance monitor')
        win.resize(1800, 600)

        p4 = win.addPlot()
        p4.addLegend()
        p4.setDownsampling(mode='peak')
        p4.setClipToView(True)
        self.profiler.graph = p4

        for block in range(self.blocks):
            for txn in range(self.txns_per_block):
                name = 'block{}txn{}'.format(block, txn)
                self.profiler.start('total')
                yield self.service.lbry.daemon.jsonrpc_publish(
                    name=name, bid=self.random.randrange(1, 5)/1000.0,
                    file_path=self.publish_file, metadata={
                        "description": "Some interesting content",
                        "title": "My interesting content",
                        "author": "Video shot by me@example.com",
                        "language": "en", "license": "LBRY Inc", "nsfw": False
                    }
                )
                self.profiler.stop('total')
                self.profiler.draw()

            yield self.service.lbrycrd.generate(1)

    def stop(self):
        return self.service.shutdown(cleanup=False)


@defer.inlineCallbacks
def generate_publishes(_):
    pub = ThePublisherOfThings(50, 10)
    yield pub.start()
    yield pub.generate_publishes()
    yield pub.stop()
    print('lbrycrd: {}'.format(pub.service.lbrycrd.data_path))
    print('lbrynet: {}'.format(pub.service.lbry.data_path))
    print('lbryumserver: {}'.format(pub.service.lbryumserver.data_path))


if __name__ == "__main__":
    task.react(generate_publishes)
