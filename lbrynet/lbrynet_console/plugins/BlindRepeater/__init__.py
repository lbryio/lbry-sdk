from lbrynet.lbrynet_console import LBRYPlugin
from twisted.internet import defer
from lbrynet.conf import MIN_VALUABLE_BLOB_HASH_PAYMENT_RATE, MIN_VALUABLE_BLOB_INFO_PAYMENT_RATE
from BlindRepeater import BlindRepeater
from BlindInfoManager import BlindInfoManager
from BlindRepeaterSettings import BlindRepeaterSettings
from BlindRepeaterControlHandlers import StartRepeaterFactory, StopRepeaterFactory, UpdateMaxSpaceFactory
from BlindRepeaterControlHandlers import AddApprovedPeerFactory, DeleteApprovedPeerFactory, RepeaterStatusFactory
from BlindRepeaterControlHandlers import ShowApprovedPeersFactory, ModifyRepeaterOptionsFactory
from ValuableBlobQueryHandler import ValuableBlobLengthQueryHandlerFactory
from ValuableBlobQueryHandler import ValuableBlobHashQueryHandlerFactory

from PaymentRateManager import BlindRepeaterPaymentRateManager


class BlindRepeaterPlugin(LBRYPlugin.LBRYPlugin):

    def __init__(self):
        LBRYPlugin.LBRYPlugin.__init__(self)
        self.blind_info_manager = None
        self.valuable_blob_length_query_handler = None
        self.valuable_blob_hash_query_handler = None
        self.repeater = None
        self.control_handlers = None
        self.payment_rate_manager = None
        self.settings = None

    def setup(self, lbry_console):
        lbry_session = lbry_console.session
        d = self._setup_settings(lbry_session.db_dir)
        d.addCallback(lambda _: self._get_payment_rate_manager(lbry_session.base_payment_rate_manager))
        d.addCallback(lambda _: self._setup_blind_info_manager(lbry_session.peer_manager, lbry_session.db_dir))
        d.addCallback(lambda _: self._setup_blind_repeater(lbry_session))
        d.addCallback(lambda _: self._setup_valuable_blob_query_handler(lbry_session))
        d.addCallback(lambda _: self._create_control_handlers(lbry_session))
        d.addCallback(lambda _: self._restore_repeater_status(lbry_session))
        d.addCallback(lambda _: self._add_to_lbry_console(lbry_console))
        return d

    def stop(self):
        return self.settings.stop()

    def _setup_settings(self, db_dir):
        self.settings = BlindRepeaterSettings(db_dir)
        return self.settings.setup()

    def _get_payment_rate_manager(self, default_payment_rate_manager):
        d1 = self.settings.get_data_payment_rate()
        d2 = self.settings.get_valuable_info_payment_rate()
        d3 = self.settings.get_valuable_hash_payment_rate()

        dl = defer.DeferredList([d1, d2, d3])

        def get_payment_rate_manager(rates):
            data_rate = rates[0][1] if rates[0][0] is True else None
            info_rate = rates[1][1] if rates[1][0] is True else None
            info_rate = info_rate if info_rate is not None else MIN_VALUABLE_BLOB_INFO_PAYMENT_RATE
            hash_rate = rates[2][1] if rates[2][0] is True else None
            hash_rate = hash_rate if hash_rate is not None else MIN_VALUABLE_BLOB_HASH_PAYMENT_RATE
            self.payment_rate_manager = BlindRepeaterPaymentRateManager(default_payment_rate_manager,
                                                                        info_rate, hash_rate,
                                                                        blob_data_rate=data_rate)

        dl.addCallback(get_payment_rate_manager)
        return dl

    def _setup_blind_info_manager(self, peer_manager, db_dir):
        self.blind_info_manager = BlindInfoManager(db_dir, peer_manager)
        return self.blind_info_manager.setup()

    def _setup_valuable_blob_query_handler(self, lbry_session):
        self.valuable_blob_length_query_handler = ValuableBlobLengthQueryHandlerFactory(lbry_session.blob_manager,
                                                                                        lbry_session.wallet,
                                                                                        self.payment_rate_manager)
        self.valuable_blob_hash_query_handler = ValuableBlobHashQueryHandlerFactory(lbry_session.peer_finder,
                                                                                    lbry_session.wallet,
                                                                                    self.payment_rate_manager)

    def _setup_blind_repeater(self, lbry_session):
        self.repeater = BlindRepeater(lbry_session.peer_finder, lbry_session.rate_limiter,
                                      lbry_session.blob_manager, self.blind_info_manager,
                                      lbry_session.wallet, self.payment_rate_manager)
        return self.repeater.setup()

    def _restore_repeater_status(self, lbry_session):
        d = self.settings.get_saved_max_space()

        def set_max_space(max_space):
            self.repeater.set_max_space(max_space)

        d.addCallback(set_max_space)

        d.addCallback(lambda _: self.settings.get_approved_peers())

        def set_approved_peers(peers):
            for host, port in peers:
                peer = lbry_session.peer_manager.get_peer(host, int(port))
                self.repeater.add_approved_peer(peer)

        d.addCallback(set_approved_peers)

        d.addCallback(lambda _: self.settings.get_repeater_saved_status())

        def restore_running(running):
            if running:
                return self.repeater.start()
            else:
                return defer.succeed(True)

        d.addCallback(restore_running)
        return d

    def _create_control_handlers(self, lbry_session):
        category = "Blind Repeater"
        control_handlers = [StartRepeaterFactory(self.repeater, self.settings),
                            StopRepeaterFactory(self.repeater, self.settings),
                            RepeaterStatusFactory(self.repeater),
                            ShowApprovedPeersFactory(self.repeater),
                            ModifyRepeaterOptionsFactory(self.repeater, lbry_session, self.settings)]
        self.control_handlers = zip([category] * len(control_handlers), control_handlers)

    def _add_to_lbry_console(self, lbry_console):
        lbry_console.add_control_handlers(self.control_handlers)
        lbry_console.add_query_handlers([self.valuable_blob_length_query_handler,
                                       self.valuable_blob_hash_query_handler])