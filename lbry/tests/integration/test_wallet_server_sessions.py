import asyncio
import socket
import time
import logging
from unittest.mock import Mock
from torba.testcase import IntegrationTestCase, Conductor
import lbry.wallet
from lbry.schema.claim import Claim
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.dewies import dewies_to_lbc as d2l, lbc_to_dewies as l2d


log = logging.getLogger(__name__)
def wrap_callback_event(fn, callback):
    def inner(*a, **kw):
        callback()
        return fn(*a, **kw)
    return inner


class TestSessionBloat(IntegrationTestCase):
    """
    ERROR:asyncio:Fatal read error on socket transport
    protocol: <lbrynet.wallet.server.session.LBRYElectrumX object at 0x7f7e3bfcaf60>
    transport: <_SelectorSocketTransport fd=3236 read=polling write=<idle, bufsize=0>>
    Traceback (most recent call last):
      File "/usr/lib/python3.7/asyncio/selector_events.py", line 801, in _read_ready__data_received
        data = self._sock.recv(self.max_size)
    TimeoutError: [Errno 110] Connection timed out
    """

    LEDGER = lbry.wallet

    async def asyncSetUp(self):
        self.conductor = Conductor(
            ledger_module=self.LEDGER, manager_module=self.MANAGER, verbosity=self.VERBOSITY
        )
        await self.conductor.start_blockchain()
        self.addCleanup(self.conductor.stop_blockchain)

        await self.conductor.start_spv()

        self.session_manager = self.conductor.spv_node.server.session_mgr
        self.session_manager.servers['TCP'].sockets[0].setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64)
        self.session_manager.servers['TCP'].sockets[0].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64)

        self.addCleanup(self.conductor.stop_spv)
        await self.conductor.start_wallet()
        self.addCleanup(self.conductor.stop_wallet)

        self.client_session = list(self.session_manager.sessions)[0]
        self.client_session.transport.set_write_buffer_limits(0, 0)

        self.paused_session = asyncio.Event(loop=self.loop)
        self.resumed_session = asyncio.Event(loop=self.loop)

        def paused():
            self.resumed_session.clear()
            self.paused_session.set()

        def delayed_resume():
            self.paused_session.clear()

            time.sleep(1)
            self.resumed_session.set()

        self.client_session.pause_writing = wrap_callback_event(self.client_session.pause_writing, paused)
        self.client_session.resume_writing = wrap_callback_event(self.client_session.resume_writing, delayed_resume)

        self.blockchain = self.conductor.blockchain_node
        self.wallet_node = self.conductor.wallet_node
        self.manager = self.wallet_node.manager
        self.ledger = self.wallet_node.ledger
        self.wallet = self.wallet_node.wallet
        self.account = self.wallet_node.wallet.default_account

    async def test_session_bloat_from_socket_timeout(self):
        await self.account.ensure_address_gap()

        address1, address2 = await self.account.receiving.get_addresses(limit=2, only_usable=True)
        sendtxid1 = await self.blockchain.send_to_address(address1, 5)
        sendtxid2 = await self.blockchain.send_to_address(address2, 5)

        await self.blockchain.generate(1)
        await asyncio.wait([
            self.on_transaction_id(sendtxid1),
            self.on_transaction_id(sendtxid2)
        ])

        self.assertEqual(d2l(await self.account.get_balance()), '10.0')

        channel = Claim()
        channel_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), '@bar', channel, self.account.ledger.address_to_hash160(address1)
        )
        channel_txo.generate_channel_private_key()
        channel_txo.script.generate()
        channel_tx = await Transaction.create([], [channel_txo], [self.account], self.account)

        stream = Claim()
        stream.stream.description = "0" * 8000
        stream_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), 'foo', stream, self.account.ledger.address_to_hash160(address1)
        )
        stream_tx = await Transaction.create([], [stream_txo], [self.account], self.account)
        stream_txo.sign(channel_txo)
        await stream_tx.sign([self.account])
        self.paused_session.clear()
        self.resumed_session.clear()

        await self.broadcast(channel_tx)
        await self.broadcast(stream_tx)
        await asyncio.wait_for(self.paused_session.wait(), 2)
        self.assertEqual(1, len(self.session_manager.sessions))

        real_sock = self.client_session.transport._extra.pop('socket')
        mock_sock = Mock(spec=socket.socket)

        for attr in dir(real_sock):
            if not attr.startswith('__'):
                setattr(mock_sock, attr, getattr(real_sock, attr))

        def recv(*a, **kw):
            raise TimeoutError("[Errno 110] Connection timed out")

        mock_sock.recv = recv
        self.client_session.transport._sock = mock_sock
        self.client_session.transport._extra['socket'] = mock_sock
        self.assertFalse(self.resumed_session.is_set())
        self.assertFalse(self.session_manager.session_event.is_set())
        await self.session_manager.session_event.wait()
        self.assertEqual(0, len(self.session_manager.sessions))
