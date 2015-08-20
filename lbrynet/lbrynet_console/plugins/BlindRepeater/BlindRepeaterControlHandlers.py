from lbrynet.lbrynet_console.ControlHandlers import ControlHandler, ControlHandlerFactory
from lbrynet.lbrynet_console.ControlHandlers import RecursiveControlHandler, ModifyPaymentRate
from twisted.internet import defer


class StartRepeater(ControlHandler):
    prompt_description = "Start the blind repeater"

    def __init__(self, repeater, settings):
        self.repeater = repeater
        self.settings = settings

    def handle_line(self, line):
        assert line is None, "Start repeater should not be passed any arguments"
        d = self.settings.save_repeater_status(running=True)
        d.addCallback(lambda _: self.repeater.start())
        d.addCallback(lambda _: "Started the repeater")
        return True, d


class StartRepeaterFactory(ControlHandlerFactory):
    control_handler_class = StartRepeater


class StopRepeater(ControlHandler):
    prompt_description = "Stop the blind repeater"

    def __init__(self, repeater, settings):
        self.repeater = repeater
        self.settings = settings

    def handle_line(self, line):
        assert line is None, "Stop repeater should not be passed any arguments"
        d = self.settings.save_repeater_status(running=False)
        d.addCallback(lambda _: self.repeater.stop())
        d.addCallback(lambda _: "Stopped the repeater")
        return True, d


class StopRepeaterFactory(ControlHandlerFactory):
    control_handler_class = StopRepeater


class UpdateMaxSpace(ControlHandler):
    prompt_description = "Set the maximum space to be used by the blind repeater"
    line_prompt = "Maximum space (in bytes):"

    def __init__(self, repeater, settings):
        self.repeater = repeater
        self.settings = settings

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        return True, self._set_max_space(line)

    def _set_max_space(self, line):
        max_space = int(line)
        d = self.settings.save_max_space(max_space)
        d.addCallback(lambda _: self.repeater.set_max_space(max_space))
        d.addCallback(lambda _: "Set the maximum space to " + str(max_space) + " bytes")
        return d


class UpdateMaxSpaceFactory(ControlHandlerFactory):
    control_handler_class = UpdateMaxSpace


class AddApprovedPeer(ControlHandler):
    prompt_description = "Add a peer to the approved list of peers to check for valuable blob hashes"
    host_prompt = "Peer host in dotted quad (e.g. 127.0.0.1)"
    port_prompt = "Peer port (e.g. 4444)"

    def __init__(self, repeater, peer_manager, settings):
        self.repeater = repeater
        self.peer_manager = peer_manager
        self.settings = settings
        self.host_to_add = None

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.host_prompt)
        elif self.host_to_add is None:
            self.host_to_add = line
            return False, defer.succeed(self.port_prompt)
        else:
            self.host_to_add, host = None, self.host_to_add
            return True, self._add_peer(host, line)

    def _add_peer(self, host, port):
        peer = self.peer_manager.get_peer(host, int(port))
        d = self.settings.save_approved_peer(host, int(port))
        d.addCallback(lambda _: self.repeater.add_approved_peer(peer))
        d.addCallback(lambda _: "Successfully added peer")
        return d


class AddApprovedPeerFactory(ControlHandlerFactory):
    control_handler_class = AddApprovedPeer


class ApprovedPeerChooser(RecursiveControlHandler):

    def __init__(self, repeater, factory_class, *args, **kwargs):
        self.repeater = repeater
        self.factory_class = factory_class
        self.args = args
        RecursiveControlHandler.__init__(self, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for peer in self.repeater.approved_peers:
            control_handler_factories.append(self.factory_class(peer, *self.args))
        return control_handler_factories


class ApprovedPeerChooserFactory(ControlHandlerFactory):
    def get_prompt_description(self):
        peer = self.args[0]
        return str(peer)


class DeleteApprovedPeerChooser(ApprovedPeerChooser):
    prompt_description = "Remove a peer from the approved list of peers to check for valuable blob hashes"

    def __init__(self, repeater, settings):
        ApprovedPeerChooser.__init__(self, repeater, DeleteApprovedPeerFactory, repeater, settings,
                                     exit_after_one_done=True)


class DeleteApprovedPeerChooserFactory(ControlHandlerFactory):
    control_handler_class = DeleteApprovedPeerChooser


class DeleteApprovedPeer(ControlHandler):
    prompt_description = "Remove a peer from the approved list of peers to check for valuable blob hashes"

    def __init__(self, peer, repeater, settings):
        self.repeater = repeater
        self.settings = settings
        self.peer_to_remove = peer

    def handle_line(self, line):
        return True, self._remove_peer()

    def _remove_peer(self):
        d = self.settings.remove_approved_peer(self.peer_to_remove.host, int(self.peer_to_remove.port))
        d.addCallback(lambda _: self.repeater.remove_approved_peer(self.peer_to_remove))
        d.addCallback(lambda _: "Successfully removed peer")
        return d


class DeleteApprovedPeerFactory(ApprovedPeerChooserFactory):
    control_handler_class = DeleteApprovedPeer


class ShowApprovedPeers(ControlHandler):
    prompt_description = "Show the list of peers approved to be checked for valuable blob hashes"

    def __init__(self, repeater):
        self.repeater = repeater

    def handle_line(self, line):
        assert line is None, "Show approved peers should not be passed any arguments"
        return True, self._show_peers()

    def _show_peers(self):
        peer_string = "Approved peers:\n"
        for peer in self.repeater.approved_peers:
            peer_string += str(peer) + "\n"
        return defer.succeed(peer_string)


class ShowApprovedPeersFactory(ControlHandlerFactory):
    control_handler_class = ShowApprovedPeers


class RepeaterStatus(ControlHandler):
    prompt_description = "Show the repeater's status"

    def __init__(self, repeater):
        self.repeater = repeater

    def handle_line(self, line):
        assert line is None, "Show repeater status should not be passed any arguments"
        return True, defer.maybeDeferred(self._get_status)

    def _get_status(self):
        status_string = "Repeater status: " + self.repeater.status() + "\n"

        if self.repeater.stopped is False:
            max_space = self.repeater.progress_manager.max_space
            space_used = 0
            for blob in self.repeater.download_manager.blobs:
                if blob.is_validated():
                    space_used += blob.get_length()

            status_string += "Maximum space: " + str(max_space) + " bytes\n"
            status_string += "Space used: " + str(space_used) + " bytes\n"
        return defer.succeed(status_string)


class RepeaterStatusFactory(ControlHandlerFactory):
    control_handler_class = RepeaterStatus


class ModifyDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater data payment rate"

    def __init__(self, repeater, settings):
        ModifyPaymentRate.__init__(self)
        self._prompt_choices['unset'] = (self._unset, "Use the application default data rate")
        self.payment_rate_manager = repeater.payment_rate_manager
        self.settings = settings

    def _unset(self):
        self._set_rate(None)
        return True, defer.succeed("Using the application default data rate")

    def _set_rate(self, rate):

        def set_data_payment_rate(rate):
            self.payment_rate_manager.min_blob_data_payment_rate = rate

        d = self.settings.save_data_payment_rate(rate)
        d.addCallback(lambda _: set_data_payment_rate(rate))
        return d

    def _get_current_status(self):
        effective_rate = self.payment_rate_manager.get_effective_min_blob_data_payment_rate()
        if self.payment_rate_manager.min_blob_data_payment_rate is None:
            status = "The current data payment rate is set to use the application default, "
            status += str(effective_rate)
        else:
            status = "The current data payment rate is "
            status += str(effective_rate)
        return status


class ModifyDataPaymentRateFactory(ControlHandlerFactory):
    control_handler_class = ModifyDataPaymentRate


class ModifyInfoPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater valuable info payment rate"

    def __init__(self, repeater, settings):
        ModifyPaymentRate.__init__(self)
        self.payment_rate_manager = repeater.payment_rate_manager
        self.settings = settings

    def _set_rate(self, rate):

        def set_info_payment_rate(rate):
            self.payment_rate_manager.min_valuable_blob_info_payment_rate = rate

        d = self.settings.save_valuable_info_payment_rate(rate)
        d.addCallback(lambda _: set_info_payment_rate(rate))
        return d

    def _get_current_status(self):
        status = "The current valuable blob info payment rate is "
        status += str(self.payment_rate_manager.min_valuable_blob_info_payment_rate)
        return status


class ModifyInfoPaymentRateFactory(ControlHandlerFactory):
    control_handler_class = ModifyInfoPaymentRate


class ModifyHashPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater valuable hash payment rate"

    def __init__(self, repeater, settings):
        ModifyPaymentRate.__init__(self)
        self.payment_rate_manager = repeater.payment_rate_manager
        self.settings = settings

    def _set_rate(self, rate):

        def set_hash_payment_rate(rate):
            self.payment_rate_manager.min_valuable_blob_hash_payment_rate = rate

        d = self.settings.save_valuable_hash_payment_rate(rate)
        d.addCallback(lambda _: set_hash_payment_rate(rate))
        return d

    def _get_current_status(self):
        status = "The current valuable blob hash payment rate is "
        status += str(self.payment_rate_manager.min_valuable_blob_hash_payment_rate)
        return status


class ModifyHashPaymentRateFactory(ControlHandlerFactory):
    control_handler_class = ModifyHashPaymentRate


class ModifyRepeaterOptions(RecursiveControlHandler):
    prompt_description = "Modify Blind Repeater options"

    def __init__(self, repeater, lbry_session, settings):
        self.repeater = repeater
        self.lbry_session = lbry_session
        self.settings = settings
        RecursiveControlHandler.__init__(self)

    def _get_control_handler_factories(self):
        return [ModifyDataPaymentRateFactory(self.repeater, self.settings),
                ModifyInfoPaymentRateFactory(self.repeater, self.settings),
                ModifyHashPaymentRateFactory(self.repeater, self.settings),
                UpdateMaxSpaceFactory(self.repeater, self.settings),
                AddApprovedPeerFactory(self.repeater, self.lbry_session.peer_manager, self.settings),
                DeleteApprovedPeerChooserFactory(self.repeater, self.settings),
                ]


class ModifyRepeaterOptionsFactory(ControlHandlerFactory):
    control_handler_class = ModifyRepeaterOptions