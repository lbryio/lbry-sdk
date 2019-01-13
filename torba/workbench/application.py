import sys
import json
import math

from PySide2 import QtCore, QtGui, QtWidgets, QtNetwork, QtWebSockets, QtSvg

from torba.workbench._output_dock import Ui_OutputDock as OutputDock
from torba.workbench._blockchain_dock import Ui_BlockchainDock as BlockchainDock


def dict_to_post_data(d):
    query = QtCore.QUrlQuery()
    for key, value in d.items():
        query.addQueryItem(str(key), str(value))
    return QtCore.QByteArray(query.toString().encode())


class LoggingOutput(QtWidgets.QDockWidget, OutputDock):

    def __init__(self, title, parent):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle(title)


class BlockchainControls(QtWidgets.QDockWidget, BlockchainDock):

    def __init__(self, parent):
        super().__init__(parent)
        self.setupUi(self)
        self.generate.clicked.connect(self.on_generate)
        self.transfer.clicked.connect(self.on_transfer)

    def on_generate(self):
        print('generating')
        self.parent().run_command('generate', blocks=self.blocks.value())

    def on_transfer(self):
        print('transfering')
        self.parent().run_command('transfer', amount=self.amount.value())


class Arrow(QtWidgets.QGraphicsLineItem):

    def __init__(self, start_node, end_node, parent=None, scene=None):
        super().__init__(parent, scene)
        self.start_node = start_node
        self.start_node.connect_arrow(self)
        self.end_node = end_node
        self.end_node.connect_arrow(self)
        self.arrow_head = QtGui.QPolygonF()
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(-1000.0)
        self.arrow_color = QtCore.Qt.black
        self.setPen(QtGui.QPen(
            self.arrow_color, 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin
        ))

    def boundingRect(self):
        extra = (self.pen().width() + 20) / 2.0
        p1 = self.line().p1()
        p2 = self.line().p2()
        size = QtCore.QSizeF(p2.x() - p1.x(), p2.y() - p1.y())
        return QtCore.QRectF(p1, size).normalized().adjusted(-extra, -extra, extra, extra)

    def shape(self):
        path = super().shape()
        path.addPolygon(self.arrow_head)
        return path

    def update_position(self):
        line = QtCore.QLineF(
            self.mapFromItem(self.start_node, 0, 0),
            self.mapFromItem(self.end_node, 0, 0)
        )
        self.setLine(line)

    def paint(self, painter, option, widget=None):
        if self.start_node.collidesWithItem(self.end_node):
            return

        start_node = self.start_node
        end_node = self.end_node
        color = self.arrow_color
        pen = self.pen()
        pen.setColor(self.arrow_color)
        arrow_size = 20.0
        painter.setPen(pen)
        painter.setBrush(self.arrow_color)

        end_rectangle = end_node.sceneBoundingRect()
        start_center = start_node.sceneBoundingRect().center()
        end_center = end_rectangle.center()
        center_line = QtCore.QLineF(start_center, end_center)
        end_polygon = QtGui.QPolygonF(end_rectangle)
        p1 = end_polygon.at(0)

        intersect_point = QtCore.QPointF()
        for p2 in end_polygon:
            poly_line = QtCore.QLineF(p1, p2)
            intersect_type, intersect_point = poly_line.intersect(center_line)
            if intersect_type == QtCore.QLineF.BoundedIntersection:
                break
            p1 = p2

        self.setLine(QtCore.QLineF(intersect_point, start_center))
        line = self.line()

        angle = math.acos(line.dx() / line.length())
        if line.dy() >= 0:
            angle = (math.pi * 2.0) - angle

        arrow_p1 = line.p1() + QtCore.QPointF(
            math.sin(angle + math.pi / 3.0) * arrow_size,
            math.cos(angle + math.pi / 3.0) * arrow_size
        )
        arrow_p2 = line.p1() + QtCore.QPointF(
            math.sin(angle + math.pi - math.pi / 3.0) * arrow_size,
            math.cos(angle + math.pi - math.pi / 3.0) * arrow_size
        )

        self.arrow_head.clear()
        for point in [line.p1(), arrow_p1, arrow_p2]:
            self.arrow_head.append(point)

        painter.drawLine(line)
        painter.drawPolygon(self.arrow_head)
        if self.isSelected():
            painter.setPen(QtGui.QPen(color, 1, QtCore.Qt.DashLine))
            line = QtCore.QLineF(line)
            line.translate(0, 4.0)
            painter.drawLine(line)
            line.translate(0, -8.0)
            painter.drawLine(line)


ONLINE_COLOR = "limegreen"
OFFLINE_COLOR = "lightsteelblue"


class NodeItem(QtSvg.QGraphicsSvgItem):

    def __init__(self, context_menu):
        super().__init__()
        self._port = ''
        self._color = OFFLINE_COLOR
        self.context_menu = context_menu
        self.arrows = set()
        self.renderer = QtSvg.QSvgRenderer()
        self.update_svg()
        self.setSharedRenderer(self.renderer)
        #self.setScale(2.0)
        #self.setTransformOriginPoint(24, 24)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)

    def get_svg(self):
        return self.SVG.format(
            port=self.port,
            color=self._color
        )

    def update_svg(self):
        self.renderer.load(QtCore.QByteArray(self.get_svg().encode()))
        self.update()

    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, port):
        self._port = port
        self.update_svg()

    @property
    def online(self):
        return self._color == ONLINE_COLOR

    @online.setter
    def online(self, online):
        if online:
            self._color = ONLINE_COLOR
        else:
            self._color = OFFLINE_COLOR
        self.update_svg()

    def connect_arrow(self, arrow):
        self.arrows.add(arrow)

    def disconnect_arrow(self, arrow):
        self.arrows.discard(arrow)

    def contextMenuEvent(self, event):
        self.scene().clearSelection()
        self.setSelected(True)
        self.myContextMenu.exec_(event.screenPos())

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            for arrow in self.arrows:
                arrow.update_position()
        return value


class BlockchainNode(NodeItem):
    SVG = """
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">
        <path fill="white" d="M2 0h20v24H2z"/>
        <path fill="{color}" d="M8 7A 5.5 5 0 0 0 8 17h8A 5.5 5 0 0 0 16 7z"/>
        <path d="M17 7h-4v2h4c1.65 0 3 1.35 3 3s-1.35 3-3 3h-4v2h4c2.76 0 5-2.24 5-5s-2.24-5-5-5zm-6 8H7c-1.65 0-3-1.35-3-3s1.35-3 3-3h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-2zm-3-4h8v2H8z"/>
        <text x="4" y="6" font-size="6" font-weight="900">{port}</text>
        <text x="4" y="23" font-size="6" font-weight="900">{block}</text>
    </svg>
    """

    def __init__(self, *args):
        self._block_height = ''
        super().__init__(*args)

    @property
    def block_height(self):
        return self._block_height

    @block_height.setter
    def block_height(self, block_height):
        self._block_height = block_height
        self.update_svg()

    def get_svg(self):
        return self.SVG.format(
            port=self.port,
            block=self.block_height,
            color=self._color
        )


class SPVNode(NodeItem):
    SVG = """
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">
        <path fill="white" d="M3 1h18v10H3z"/>
        <g transform="translate(0 3)">
        <path fill="{color}" d="M19.21 12.04l-1.53-.11-.3-1.5C16.88 7.86 14.62 6 12 6 9.94 6 8.08 7.14 7.12 8.96l-.5.95-1.07.11C3.53 10.24 2 11.95 2 14c0 2.21 1.79 4 4 4h13c1.65 0 3-1.35 3-3 0-1.55-1.22-2.86-2.79-2.96z"/>
        <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3z"/>
        </g>
        <text x="4" y="6" font-size="6" font-weight="900">{port}</text>
    </svg>
    """

    def __init__(self, *args):
        super().__init__(*args)


class WalletNode(NodeItem):
    SVG = """
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">
        <path fill="white" d="M3 3h17v17H3z"/>
        <g transform="translate(0 -3)">
        <path fill="{color}" d="M13 17c-1.1 0-2-.9-2-2V9c0-1.1.9-2 2-2h6V5H5v14h14v-2h-6z"/>
        <path d="M21 7.28V5c0-1.1-.9-2-2-2H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-2.28c.59-.35 1-.98 1-1.72V9c0-.74-.41-1.38-1-1.72zM20 9v6h-7V9h7zM5 19V5h14v2h-6c-1.1 0-2 .9-2 2v6c0 1.1.9 2 2 2h6v2H5z"/>
        <circle cx="16" cy="12" r="1.5"/>
        </g>
        <text x="4" y="23" font-size="6" font-weight="900">{coins}</text>
    </svg>
    """

    def __init__(self, *args):
        self._coins = '--'
        super().__init__(*args)

    @property
    def coins(self):
        return self._coins

    @coins.setter
    def coins(self, coins):
        self._coins = coins
        self.update_svg()

    def get_svg(self):
        return self.SVG.format(
            coins=self.coins,
            color=self._color
        )


class Stage(QtWidgets.QGraphicsScene):

    def __init__(self, parent):
        super().__init__(parent)
        self.blockchain = b = BlockchainNode(None)
        b.port = ''
        b.block_height = ''
        b.setZValue(0)
        b.setPos(-25, -100)
        self.addItem(b)
        self.spv = s = SPVNode(None)
        s.port = ''
        s.setZValue(0)
        self.addItem(s)
        s.setPos(-10, -10)
        self.wallet = w = WalletNode(None)
        w.coins = ''
        w.setZValue(0)
        w.update_svg()
        self.addItem(w)
        w.setPos(0, 100)

        self.addItem(Arrow(b, s))
        self.addItem(Arrow(s, w))


class Orchstr8Workbench(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.stage = Stage(self)
        self.view = QtWidgets.QGraphicsView(self.stage)
        self.status_bar = QtWidgets.QStatusBar(self)

        self.setWindowTitle('Orchstr8 Workbench')
        self.setCentralWidget(self.view)
        self.setStatusBar(self.status_bar)

        self.block_height = self.make_status_label('Height: -- ')
        self.user_balance = self.make_status_label('User Balance: -- ')
        self.mining_balance = self.make_status_label('Mining Balance: -- ')

        self.wallet_log = LoggingOutput('Wallet', self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.wallet_log)
        self.spv_log = LoggingOutput('SPV Server', self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.spv_log)
        self.blockchain_log = LoggingOutput('Blockchain', self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.blockchain_log)

        self.blockchain_controls = BlockchainControls(self)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.blockchain_controls)

        self.network = QtNetwork.QNetworkAccessManager(self)
        self.socket = QtWebSockets.QWebSocket()
        self.socket.connected.connect(lambda: self.run_command('start'))
        self.socket.error.connect(lambda e: print(f'errored: {e}'))
        self.socket.textMessageReceived.connect(self.on_message)
        self.socket.open('ws://localhost:7954/log')

    def make_status_label(self, text):
        label = QtWidgets.QLabel(text)
        label.setFrameStyle(QtWidgets.QLabel.Panel | QtWidgets.QLabel.Sunken)
        self.status_bar.addPermanentWidget(label)
        return label

    def on_message(self, text):
        msg = json.loads(text)
        if msg['type'] == 'status':
            self.stage.wallet.coins = msg['balance']
            self.stage.blockchain.block_height = msg['height']
            self.block_height.setText(f"Height: {msg['height']} ")
            self.user_balance.setText(f"User Balance: {msg['balance']} ")
            self.mining_balance.setText(f"Mining Balance: {msg['miner']} ")
        elif msg['type'] == 'service':
            node = {
                'blockchain': self.stage.blockchain,
                'spv': self.stage.spv,
                'wallet': self.stage.wallet
            }[msg['name']]
            node.online = True
            node.port = f":{msg['port']}"
        elif msg['type'] == 'log':
            log = {
                'blockchain': self.blockchain_log,
                'electrumx': self.spv_log,
                'lbryumx': self.spv_log,
                'Controller': self.spv_log,
                'LBRYBlockProcessor': self.spv_log,
                'LBCDaemon': self.spv_log,
            }.get(msg['name'].split('.')[-1], self.wallet_log)
            log.textEdit.append(msg['message'])

    def run_command(self, command, **kwargs):
        request = QtNetwork.QNetworkRequest(QtCore.QUrl('http://localhost:7954/'+command))
        request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")
        reply = self.network.post(request, dict_to_post_data(kwargs))
        # reply.finished.connect(cb)
        reply.error.connect(self.on_command_error)

    @staticmethod
    def on_command_error(error):
        print('failed executing command:')
        print(error)


def main():
    app = QtWidgets.QApplication(sys.argv)
    workbench = Orchstr8Workbench()
    workbench.setGeometry(100, 100, 1200, 600)
    workbench.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
