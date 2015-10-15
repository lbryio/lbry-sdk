from lbrynet.lbrynet_console.ControlHandlers import CommandHandler, CommandHandlerFactory
from lbrynet.lbrynet_console.ControlHandlers import RecursiveCommandHandler, ModifyPaymentRate
from twisted.internet import defer


class StartRepeater(CommandHandler):
    prompt_description = "Start the blind repeater"

    def __init__(self, console, repeater, settings):
        CommandHandler.__init__(self, console)
        self.repeater = repeater
        self.settings = settings

    def start(self):
        #assert line is None, "Start repeater should not be passed any arguments"
        d = self.settings.save_repeater_status(running=True)
        d.addCallback(lambda _: self.repeater.start())
        d.addCallback(lambda _: self.console.sendLine("Started the repeater"))
        d.chainDeferred(self.finished_deferred)


class StartRepeaterFactory(CommandHandlerFactory):
    control_handler_class = StartRepeater


class StopRepeater(CommandHandler):
    prompt_description = "Stop the blind repeater"

    def __init__(self, console, repeater, settings):
        CommandHandler.__init__(self, console)
        self.repeater = repeater
        self.settings = settings

    def start(self):
        #assert line is None, "Stop repeater should not be passed any arguments"
        d = self.settings.save_repeater_status(running=False)
        d.addCallback(lambda _: self.repeater.stop())
        d.addCallback(lambda _: self.console.sendLine("Stopped the repeater"))
        d.chainDeferred(self.finished_deferred)


class StopRepeaterFactory(CommandHandlerFactory):
    control_handler_class = StopRepeater


class UpdateMaxSpace(CommandHandler):
    prompt_description = "Set the maximum space to be used by the blind repeater"
    line_prompt = "Maximum space (in bytes):"

    def __init__(self, console, repeater, settings):
        CommandHandler.__init__(self, console)
        self.repeater = repeater
        self.settings = settings

    def start(self):
        self.console.sendLine(self.line_prompt)

    def handle_line(self, line):
        d = self._set_max_space(line)
        d.chainDeferred(self.finished_deferred)

    def _set_max_space(self, line):
        max_space = int(line)
        d = self.settings.save_max_space(max_space)
        d.addCallback(lambda _: self.repeater.set_max_space(max_space))
        d.addCallback(lambda _: self.console.sendLine("Set the maximum space to " + str(max_space) + " bytes"))
        return d


class UpdateMaxSpaceFactory(CommandHandlerFactory):
    control_handler_class = UpdateMaxSpace


class AddApprovedPeer(CommandHandler):
    prompt_description = "Add a peer to the approved list of peers to check for valuable blob hashes"
    host_prompt = "Peer host in dotted quad (e.g. 127.0.0.1)"
    port_prompt = "Peer port (e.g. 4444)"

    def __init__(self, console, repeater, peer_manager, settings):
        CommandHandler.__init__(self, console)
        self.repeater = repeater
        self.peer_manager = peer_manager
        self.settings = settings
        self.host_to_add = None

    def start(self):
        self.console.sendLine(self.host_prompt)

    def handle_line(self, line):
        #if line is None:
        #    return False, defer.succeed(self.host_prompt)
        if self.host_to_add is None:
            self.host_to_add = line
            self.console.sendLine(self.port_prompt)
        else:
            self.host_to_add, host = None, self.host_to_add
            d = self._add_peer(host, line)
            d.chainDeferred(self.finished_deferred)

    def _add_peer(self, host, port):
        peer = self.peer_manager.get_peer(host, int(port))
        d = self.settings.save_approved_peer(host, int(port))
        d.addCallback(lambda _: self.repeater.add_approved_peer(peer))
        d.addCallback(lambda _: self.console.sendLine("Successfully added peer"))
        return d


class AddApprovedPeerFactory(CommandHandlerFactory):
    control_handler_class = AddApprovedPeer


class ApprovedPeerChooser(RecursiveCommandHandler):

    def __init__(self, console, repeater, factory_class, *args, **kwargs):
        self.repeater = repeater
        self.factory_class = factory_class
        self.args = args
        RecursiveCommandHandler.__init__(self, console, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for peer in self.repeater.approved_peers:
            control_handler_factories.append(self.factory_class(peer, *self.args))
        return control_handler_factories


class ApprovedPeerChooserFactory(CommandHandlerFactory):
    def get_prompt_description(self):
        peer = self.args[0]
        return str(peer)


class DeleteApprovedPeerChooser(ApprovedPeerChooser):
    prompt_description = "Remove a peer from the approved list of peers to check for valuable blob hashes"

    def __init__(self, console, repeater, settings):
        ApprovedPeerChooser.__init__(self, console, repeater, DeleteApprovedPeerFactory, repeater,
                                     settings, exit_after_one_done=True)


class DeleteApprovedPeerChooserFactory(CommandHandlerFactory):
    control_handler_class = DeleteApprovedPeerChooser


class DeleteApprovedPeer(CommandHandler):
    prompt_description = "Remove a peer from the approved list of peers to check for valuable blob hashes"

    def __init__(self, console, peer, repeater, settings):
        CommandHandler.__init__(self, console)
        self.repeater = repeater
        self.settings = settings
        self.peer_to_remove = peer

    def start(self):
        d = self._remove_peer()
        d.chainDeferred(self.finished_deferred)

    def _remove_peer(self):
        d = self.settings.remove_approved_peer(self.peer_to_remove.host, int(self.peer_to_remove.port))
        d.addCallback(lambda _: self.repeater.remove_approved_peer(self.peer_to_remove))
        d.addCallback(lambda _: self.console.sendLine("Successfully removed peer"))
        return d


class DeleteApprovedPeerFactory(ApprovedPeerChooserFactory):
    control_handler_class = DeleteApprovedPeer


class ShowApprovedPeers(CommandHandler):
    prompt_description = "Show the list of peers approved to be checked for valuable blob hashes"

    def __init__(self, console, repeater):
        CommandHandler.__init__(self, console)
        self.repeater = repeater

    def start(self):
        #assert line is None, "Show approved peers should not be passed any arguments"
        d = self._show_peers()
        d.chainDeferred(self.finished_deferred)

    def _show_peers(self):
        peer_string = "Approved peers:\n"
        for peer in self.repeater.approved_peers:
            peer_string += str(peer) + "\n"
        self.console.sendLine(peer_string)
        return defer.succeed(None)


class ShowApprovedPeersFactory(CommandHandlerFactory):
    control_handler_class = ShowApprovedPeers


class RepeaterStatus(CommandHandler):
    prompt_description = "Show the repeater's status"

    def __init__(self, console, repeater):
        CommandHandler.__init__(self, console)
        self.repeater = repeater

    def start(self):
        #assert line is None, "Show repeater status should not be passed any arguments"
        self._show_status()
        self.finished_deferred.callback(None)

    def _show_status(self):
        status_string = "Repeater status: " + self.repeater.status() + "\n"

        if self.repeater.stopped is False:
            max_space = self.repeater.progress_manager.max_space
            space_used = 0
            for blob in self.repeater.download_manager.blobs:
                if blob.is_validated():
                    space_used += blob.get_length()

            status_string += "Maximum space: " + str(max_space) + " bytes\n"
            status_string += "Space used: " + str(space_used) + " bytes\n"
        self.console.sendLine(status_string)


class RepeaterStatusFactory(CommandHandlerFactory):
    control_handler_class = RepeaterStatus


class ModifyDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater data payment rate"

    def __init__(self, console, repeater, settings):
        ModifyPaymentRate.__init__(self, console)
        self._prompt_choices['unset'] = (self._unset, "Use the application default data rate")
        self.payment_rate_manager = repeater.payment_rate_manager
        self.settings = settings

    def _unset(self):
        self._set_rate(None)
        return defer.succeed("Using the application default data rate")

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


class ModifyDataPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyDataPaymentRate


class ModifyInfoPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater valuable info payment rate"

    def __init__(self, console, repeater, settings):
        ModifyPaymentRate.__init__(self, console)
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


class ModifyInfoPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyInfoPaymentRate


class ModifyHashPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify Blind Repeater valuable hash payment rate"

    def __init__(self, console, repeater, settings):
        ModifyPaymentRate.__init__(self, console)
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


class ModifyHashPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyHashPaymentRate


class ModifyRepeaterOptions(RecursiveCommandHandler):
    prompt_description = "Modify Blind Repeater options"

    def __init__(self, console, repeater, lbry_session, settings):
        self.repeater = repeater
        self.lbry_session = lbry_session
        self.settings = settings
        RecursiveCommandHandler.__init__(self, console)

    def _get_control_handler_factories(self):
        return [ModifyDataPaymentRateFactory(self.repeater, self.settings),
                ModifyInfoPaymentRateFactory(self.repeater, self.settings),
                ModifyHashPaymentRateFactory(self.repeater, self.settings),
                UpdateMaxSpaceFactory(self.repeater, self.settings),
                AddApprovedPeerFactory(self.repeater, self.lbry_session.peer_manager, self.settings),
                DeleteApprovedPeerChooserFactory(self.repeater, self.settings),
                ]


class ModifyRepeaterOptionsFactory(CommandHandlerFactory):
    control_handler_class = ModifyRepeaterOptions