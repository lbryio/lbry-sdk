import json
import logging
from time import sleep

from bitcoinrpc.authproxy import AuthServiceProxy
from twisted.internet.task import LoopingCall
from zope.interface import implements
#from lbrynet.core.StreamDescriptor import PlainStreamDescriptorWriter, BlobStreamDescriptorWriter
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.lbryfilemanager.LBRYFileCreator import create_lbry_file
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
# from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob, create_plain_sd
from lbrynet.lbrynet_console.interfaces import ICommandHandler, ICommandHandlerFactory
from lbrynet.core.StreamDescriptor import download_sd_blob#, BlobStreamDescriptorReader
from lbrynet.core.Error import UnknownNameError, InvalidBlobHashError, InsufficientFundsError
from lbrynet.core.Error import InvalidStreamInfoError
from lbrynet.core.utils import is_valid_blobhash
from twisted.internet import defer, threads
import datetime
import os


log = logging.getLogger(__name__)


class InvalidChoiceError(Exception):
    pass


class InvalidValueError(Exception):
    pass


#class ControlHandlerFactory(object):
#    implements(IControlHandlerFactory)

#    control_handler_class = None

#    def get_prompt_description(self):
#        return self.control_handler_class.prompt_description

#    def __init__(self, *args):
#        self.args = args

#    def get_handler(self):
#        args = self.args
#        return self.control_handler_class(*args)


#class ControlHandler(object):
#    implements(IControlHandler)

#    prompt_description = None


class RoundedTime(object):
    SECOND = 0
    MINUTE = 1
    HOUR = 2
    DAY = 3
    WEEK = 4
    units = ['second', 'minute', 'hour', 'day', 'week']

    def __init__(self, unit, val):
        assert unit < len(self.units)
        self.unit = unit
        self.val = val

    def __str__(self):
        assert self.unit < len(self.units)
        unit_str = self.units[self.unit]
        if self.val != 1:
            unit_str += "s"
        return "%d %s" % (self.val, unit_str)


def get_time_behind_blockchain(best_block_time):
    best_time = datetime.datetime.utcfromtimestamp(best_block_time)
    diff = datetime.datetime.utcnow() - best_time
    if diff.days > 0:
        if diff.days >= 7:
            val = diff.days // 7
            unit = RoundedTime.WEEK
        else:
            val = diff.days
            unit = RoundedTime.DAY
    elif diff.seconds >= 60 * 60:
        val = diff.seconds // (60 * 60)
        unit = RoundedTime.HOUR
    elif diff.seconds >= 60:
        val = diff.seconds // 60
        unit = RoundedTime.MINUTE
    else:
        val = diff.seconds
        unit = RoundedTime.SECOND
    return RoundedTime(unit, val)


class CommandHandlerFactory(object):
    implements(ICommandHandlerFactory)
    priority = 0
    short_help = "This should be overridden"
    full_help = "This should really be overridden"
    command = "this-must-be-overridden"
    control_handler_class = None

    def __init__(self, *args):
        self.args = args

    def get_prompt_description(self):
        return self.control_handler_class.prompt_description

    def get_handler(self, console):
        return self.control_handler_class(console, *self.args)


class CommandHandler(object):
    implements(ICommandHandler)

    prompt_description = None

    def __init__(self, console):
        self.console = console
        self.finished_deferred = defer.Deferred()

    def start(self):
        pass

    def handle_line(self, line):
        pass


def get_shortcuts_for_options(option_names):
    shortcut_keys = []
    names_with_shortcuts = []
    for option_name in option_names:
        name_with_shortcut = ''
        found_shortcut = False
        for c in option_name:
            if not found_shortcut and not c.lower() in shortcut_keys:
                name_with_shortcut += '[' + c.lower() + ']'
                shortcut_keys.append(c.lower())
                found_shortcut = True
            else:
                name_with_shortcut += c
        if found_shortcut is False:
            shortcut_keys.append("")
        names_with_shortcuts.append(name_with_shortcut)
    return shortcut_keys, names_with_shortcuts


class RecursiveCommandHandler(CommandHandler):

    def __init__(self, console, exit_after_one_done=False, reset_after_each_done=False):
        CommandHandler.__init__(self, console)
        self.current_handler = None
        self.exit_after_one_done = exit_after_one_done
        self.reset_after_each_done = reset_after_each_done
        self._set_control_handlers()

    def _get_control_handler_factories(self):
        raise NotImplementedError()

    def _set_control_handlers(self):
        self.control_handlers = {i + 1: handler for i, handler in enumerate(self._get_control_handler_factories())}

    def start(self):
        self._show_prompt()

    def handler_finished(self):
        self.current_handler = None
        if self.exit_after_one_done is True:
            self.finished_deferred.callback(None)
        else:
            if self.reset_after_each_done:
                self._set_control_handlers()
            self._show_prompt()

    def handler_failed(self, err):
        log.error("An error occurred in some handler: %s", err.getTraceback())
        self.finished_deferred.callback(None)

    def handle_line(self, line):
        if self.current_handler is None:
            if line is None:
                num = None
            else:
                try:
                    num = int(line)
                except ValueError:
                    num = None
            if num == 0:
                self.finished_deferred.callback(None)
                return
            if num in self.control_handlers:
                self.current_handler = self.control_handlers[num].get_handler(self.console)
                self.current_handler.finished_deferred.addCallbacks(lambda _: self.handler_finished(),
                                                                    self.handler_failed)
                self.current_handler.start()
                return
        if self.current_handler is not None:
            self.current_handler.handle_line(line)
            return
        if self.current_handler is None:
            self._show_prompt()

    def _show_prompt(self):
        prompt_string = "Options:\n"
        prompt_string += "[0] Exit this menu\n"
        for num, handler in self.control_handlers.iteritems():
            prompt_string += "[" + str(num) + "] " + handler.get_prompt_description() + "\n"
        self.console.sendLine(prompt_string)


class ModifyPaymentRate(CommandHandler):

    def __init__(self, console):
        CommandHandler.__init__(self, console)
        self._prompt_choices = {'cancel': (self._cancel, "Don't change anything")}
        self.got_input = False

    def start(self):
        self._show_prompt_string()

    def handle_line(self, line):
        if self.got_input is False:
            self.got_input = True
            if line.lower() in self._prompt_choices:
                d = self._prompt_choices[line.lower()][0]()
                d.addCallback(self._choice_made)
            else:
                try:
                    rate = float(line)
                except ValueError:
                    self.console.sendLine("Rate must be a number")
                    self.finished_deferred.callback(None)
                    return
                d = self._set_rate(rate)

                d.addCallback(lambda _: self._choice_made("Successfully set the rate"))

    @staticmethod
    def _cancel():
        return defer.succeed("No change was made")

    def _set_rate(self, rate):
        pass

    def _get_current_status(self):
        pass

    def _choice_made(self, result=None):
        if result is not None:
            self.console.sendLine(result)
        self.finished_deferred.callback(None)

    def _show_prompt_string(self):
        prompt_string = self._get_current_status() + "\n"
        for prompt_choice, (func, help_string) in self._prompt_choices.iteritems():
            prompt_string += prompt_choice + ": " + help_string + "\n"
        prompt_string += "To change the current rate, enter the desired rate\n"
        prompt_string += "Then hit enter\n"
        self.console.sendLine(prompt_string)


class ApplicationStatus(CommandHandler):
    #prompt_description = "Application Status"

    def __init__(self, console, rate_limiter, dht_node):
        CommandHandler.__init__(self, console)
        self.rate_limiter = rate_limiter
        self.dht_node = dht_node

    def start(self):
        d = self._show_status()
        d.chainDeferred(self.finished_deferred)
        return d

    def _show_status(self):
        status = "Total bytes uploaded: " + str(self.rate_limiter.total_ul_bytes) + "\n"
        status += "Total bytes downloaded: " + str(self.rate_limiter.total_dl_bytes) + "\n"
        if self.dht_node is not None:
            status += "Approximate number of nodes in DHT: " + str(self.dht_node.getApproximateTotalDHTNodes()) + "\n"
            status += "Approximate number of blobs in DHT: " + str(self.dht_node.getApproximateTotalHashes()) + "\n"
        self.console.sendLine(status)
        return defer.succeed(None)


class ApplicationStatusFactory(CommandHandlerFactory):
    control_handler_class = ApplicationStatus
    command = "application-status"
    short_help = "Show application status"
    full_help = "Show total bytes uploaded to other peers, total bytes downloaded from peers," \
                " approximate number of nodes in the DHT, and approximate number of hashes" \
                " in the DHT"


class GetWalletBalances(CommandHandler):
    #prompt_description = "Show wallet point balances"

    def __init__(self, console, wallet):
        CommandHandler.__init__(self, console)
        self.wallet = wallet

    def start(self):
        d = self._get_wallet_balances()
        d.chainDeferred(self.finished_deferred)
        return d

    #def handle_line(self, line):
    #    assert line is None, "Show wallet balances should not be passed any arguments"
    #    return True, self._get_wallet_balances()

    def _show_time_behind_blockchain(self, rounded_time):
        if rounded_time.unit >= RoundedTime.HOUR:
            self.console.sendLine("\n\nYour balance may be out of date. This application\n"
                                  "is %s behind the LBC blockchain. It should take a few minutes to\n"
                                  "catch up the first time you run this early version of LBRY.\n"
                                  "Please be patient =).\n\n" % str(rounded_time))
        else:
            self.console.sendLine("")

    def _log_recent_blocktime_error(self, err):
        log.error("An error occurred looking up the most recent blocktime: %s", err.getTraceback())
        self.console.sendLine("")

    def _get_wallet_balances(self):
        d = self.wallet.get_balance()

        def format_balance(balance):
            if balance == 0:
                balance = 0
            balance_string = "balance: " + str(balance) + " LBC"
            self.console.sendLine(balance_string)
            d = self.wallet.get_most_recent_blocktime()
            d.addCallback(get_time_behind_blockchain)
            d.addCallback(self._show_time_behind_blockchain)
            d.addErrback(self._log_recent_blocktime_error)
            return d

        d.addCallback(format_balance)
        return d


class GetWalletBalancesFactory(CommandHandlerFactory):
    control_handler_class = GetWalletBalances
    priority = 10
    command = "balance"
    short_help = "Show LBRYcrd balance"
    full_help = "Show the LBRYcrd balance of the wallet to which this application is connected"


class GetNewWalletAddress(CommandHandler):
    #prompt_description = "Get a new LBRYcrd address"

    def __init__(self, console, wallet):
        CommandHandler.__init__(self, console)
        self.wallet = wallet

    def start(self):
        d = self._get_new_address()
        d.chainDeferred(self.finished_deferred)
        return d

    def _get_new_address(self):
        #assert line is None, "Get new LBRYcrd address should not be passed any arguments"
        d = self.wallet.get_new_address()

        def show_address(address):
            self.console.sendLine(str(address))

        d.addCallback(show_address)
        return d


class GetNewWalletAddressFactory(CommandHandlerFactory):
    control_handler_class = GetNewWalletAddress
    command = "get-new-address"
    short_help = "Get a new LBRYcrd address"
    full_help = "Get a new LBRYcrd address from the wallet to which this application is connected"


class ShutDown(CommandHandler):
    #prompt_description = "Shut down"

    def __init__(self, console, lbry_service):
        CommandHandler.__init__(self, console)
        self.lbry_service = lbry_service

    def start(self):
        d = self._shut_down()
        return d

    #def handle_line(self, line):
    #    assert line is None, "Shut down should not be passed any arguments"
    #    return True, self._shut_down()

    def _shut_down(self):
        #d = self.lbry_service.shut_down()

        #def stop_reactor():
        from twisted.internet import reactor
        self.console.sendLine("Shutting down.")
        reactor.stop()

        #d.addBoth(lambda _: stop_reactor())
        return defer.succeed(True)


class ShutDownFactory(CommandHandlerFactory):
    control_handler_class = ShutDown
    priority = 5
    command = "exit"
    short_help = "Shut down"
    full_help = "Shut down"


class LBRYFileStatus(CommandHandler):
    #prompt_description = "Print status information for all LBRY Files"

    def __init__(self, console, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file_manager = lbry_file_manager

    def start(self):
        d = self.lbry_file_manager.get_lbry_file_status_reports()
        d.addCallback(self._show_statuses)
        d.chainDeferred(self.finished_deferred)
        return d

    #def handle_line(self, line):
    #    assert line is None, "print status should not be passed any arguments"
    #    d = self.lbry_file_manager.get_lbry_file_status_reports()
    #    d.addCallback(self.format_statuses)
    #    return True, d

    def _show_statuses(self, status_reports):
        status_strings = []
        for status_report in status_reports:
            s = status_report.name + " status: " + status_report.running_status + "\n"
            s += str(status_report.num_completed) + " completed out of " + str(status_report.num_known) + "\n"
            status_strings.append(s)
        self.console.sendLine(''.join(status_strings))


class LBRYFileStatusFactory(CommandHandlerFactory):
    control_handler_class = LBRYFileStatus
    command = "lbryfile-status"
    short_help = "Print status information for LBRY files"
    full_help = "Print the status information for all streams that are being saved to disk." \
                "This includes whether the stream is currently downloading and the progress" \
                "of the download."


class AddStream(CommandHandler):
    #prompt_description = None
    #line_prompt = None
    cancel_prompt = "Trying to locate the stream's metadata. Type \"cancel\" to cancel..."
    canceled_message = "Canceled downloading."

    def __init__(self, console, sd_identifier, base_payment_rate_manager, wallet):
        CommandHandler.__init__(self, console)
        self.sd_identifier = sd_identifier
        self.wallet = wallet
        self.loading_metadata_deferred = None
        self.metadata = None
        self.factory = None
        self.factory_choice_strings = None  # (command, command_string, shortcut)
        self.factory_choices = None  # {command: factory}
        self.download_options = []
        self.options_left = []
        self.options_chosen = []
        self.current_option = None
        self.current_choice = None
        self.downloader = None
        self.got_options_response = False
        self.loading_failed = False
        self.payment_rate_manager = PaymentRateManager(base_payment_rate_manager)

    def start(self):
        self.console.sendLine(self.cancel_prompt)
        self.loading_metadata_deferred.addCallback(self._handle_metadata)
        self.loading_metadata_deferred.addErrback(self._handle_load_canceled)
        self.loading_metadata_deferred.addErrback(self._handle_load_failed)

    def handle_line(self, line):
        # first, print that metadata is being looked up. give the option to cancel, and
        # listen for the word cancel
        # when that's done, present the metadata, how to change options, how to cancel,
        # and list the ways to download
        #
        #
        #if line is None:
        #    return False, defer.succeed(self.line_prompt)
        #if self.loading_failed is True:
        #    return True, None
        if self.loading_metadata_deferred is not None:
            if line.lower() == "cancel":
                self.loading_metadata_deferred.cancel()
                self.loading_metadata_deferred = None
            else:
                self.console.sendLine(self.cancel_prompt)
            return

        #if self.metadata is None:
        #    self.loading_metadata_deferred = self._load_metadata(line)
        #    cancel_prompt_d = defer.succeed(self.cancel_prompt)
        #    self.loading_metadata_deferred.addCallback(self._choose_factory)
        #    self.loading_metadata_deferred.addErrback(self._handle_load_canceled)
        #    self.loading_metadata_deferred.addErrback(self._handle_load_failed)
        #    return False, cancel_prompt_d, self.loading_metadata_deferred

        if self.current_option is not None:
            if self.current_choice is None:
                try:
                    self.current_choice = self._get_choice_from_input(line)
                except InvalidChoiceError:
                    self.console.sendLine(self._get_next_option_prompt(invalid_choice=True))
                    return
                choice = self.current_option.option_types[self.current_choice]
                if choice.value == float or choice.value == bool:
                    self.console.sendLine(self._get_choice_value_prompt())
                    return
                else:
                    value = choice.value
            else:
                try:
                    value = self._get_value_for_choice(line)
                except InvalidValueError:
                    self.console.sendLine(self._get_choice_value_prompt(invalid_value=True))
                    return
            self.options_chosen.append(value)
            self.current_choice = None
            self.current_option = None
            self.options_left = self.options_left[1:]
            if self.options_left:
                self.console.sendLine(self._get_next_option_prompt())
                return
            else:
                self.current_option = None
                self._show_factory_choices()
                return
        if self.factory_choice_strings is not None:
            command = self._get_factory_choice_command(line)
            if command == "cancel":
                self.console.sendLine(self.canceled_message)
                self.finished_deferred.callback(None)
            elif command == "options":
                self.options_left = self.download_options[:]
                self.options_chosen = []
                self.console.sendLine(self._get_next_option_prompt())
            else:
                if command in self.factory_choices:
                    self.factory = self.factory_choices[command]
                    self._start_download()
                    self.console.sendLine("Downloading in the background")
                    self.finished_deferred.callback(None)
                else:
                    self._show_factory_choices()
            return

        #if self.factory is None:
        #    try:
        #        choice = int(line)
        #    except ValueError:
        #        return False, defer.succeed(self._show_factory_choices())
        #    if choice in xrange(len(self.metadata.factories)):
        #        self.factory = self.metadata.factories[choice]
        #        return False, defer.succeed(self._show_info_and_options())
        #    else:
        #        return False, defer.succeed(self._show_factory_choices())
        #if self.got_options_response is False:
        #    self.got_options_response = True
        #    if line == 'y' or line == 'Y' and self.options_left:
        #        return False, defer.succeed(self._get_next_option_prompt())
        #    else:
        #        self.options_chosen = [option.default_value for option in self.options_left]
        #        self.options_left = []
        #        return False, defer.succeed(self.line_prompt3)

        #if line == 'y' or line == 'Y':
        #    d = self._start_download()
        #else:
        #    d = defer.succeed("Download cancelled")
        #return True, d

    def _get_choice_from_input(self, line):
        try:
            choice_num = int(line)
        except ValueError:
            raise InvalidChoiceError()
        if 0 <= choice_num < len(self.current_option.option_types):
            return choice_num
        raise InvalidChoiceError()

    def _get_factory_choice_command(self, line):
        for command, printed_command, shortcut in self.factory_choice_strings:
            if line == command or line == shortcut:
                return command

    def _load_metadata(self, sd_file):
        return defer.fail(NotImplementedError())

    def _handle_load_canceled(self, err):
        err.trap(defer.CancelledError)
        self.console.sendLine(self.canceled_message)
        self.finished_deferred.callback(None)

    def _handle_load_failed(self, err):
        self.loading_failed = True
        log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback())
        log_file = "console.log"
        if len(log.handlers):
            log_file = log.handlers[0].baseFilename
        self.console.sendLine("An unexpected error occurred attempting to load the stream's metadata.\n"
                              "See %s for further details.\n\n" % log_file)
        self.finished_deferred.callback(None)

    def _handle_metadata(self, metadata):
        self.loading_metadata_deferred = None
        self.metadata = metadata
        self.factory_choices = {}
        for factory in self.metadata.factories:
            self.factory_choices[factory.get_description()] = factory
        self.download_options = self.metadata.options.get_downloader_options(self.metadata.validator,
                                                                             self.payment_rate_manager)
        self.options_chosen = [option.default_value for option in self.download_options]
        self.factory_choice_strings = []
        factory_choice_names = ['cancel']
        if self.download_options:
            factory_choice_names.append('options')
        factory_choice_names += self.factory_choices.keys()
        shortcuts, names_with_shortcuts = get_shortcuts_for_options(factory_choice_names)
        self.factory_choice_strings = zip(factory_choice_names, names_with_shortcuts, shortcuts)
        #if len(self.metadata.factories) == 1:
        #    self.factory = self.metadata.factories[0]
        #    return self._show_info_and_options()
        self._show_info_and_options()
        return self._show_factory_choices()

    def _show_factory_choices(self):
        prompt = "\n"
        for factory_choice_string in self.factory_choice_strings:
            prompt += factory_choice_string[1] + '\n'
        self.console.sendLine(str(prompt))

    def _show_info_and_options(self):
        #self.download_options = self.metadata.options.get_downloader_options(self.metadata.validator,
        #                                                                     self.payment_rate_manager)
        prompt = "Stream info:\n"
        for info_line in self._get_info_to_show():
            prompt += info_line[0] + ": " + info_line[1] + "\n"
        prompt += "\nOptions:\n"
        for option in self.download_options:
            prompt += option.long_description + ": " + str(option.default_value_description) + "\n"
        self.console.sendLine(str(prompt))

    def _get_info_to_show(self):
        return self.metadata.validator.info_to_show()

    def _get_list_of_option_types(self):
        options_string = ""
        for i, option_type in enumerate(self.current_option.option_types):
            options_string += "[%s] %s\n" % (str(i), option_type.long_description)
        options_string += "Enter choice:"
        return options_string

    def _get_choice_value_prompt(self, invalid_value=False):
        choice = self.current_option.option_types[self.current_choice]
        choice_string = ""
        if invalid_value is True:
            "Invalid value entered. Try again.\n"
        if choice.short_description is not None:
            choice_string += choice.short_description + "\n"
        if choice.value == float:
            choice_string += "Enter floating point number (e.g. 1.0):"
        elif choice.value == bool:
            true_string = "Yes"
            false_string = "No"
            if choice.bool_options_description is not None:
                true_string, false_string = choice.bool_options_description
            choice_string += "[0] %s\n[1] %s\nEnter choice:" % (true_string, false_string)
        else:
            NotImplementedError()
        return choice_string

    def _get_value_for_choice(self, choice_input):
        choice = self.current_option.option_types[self.current_choice]
        if choice.value == float:
            try:
                return float(choice_input)
            except ValueError:
                raise InvalidValueError()
        elif choice.value == bool:
            if choice_input == "0":
                return True
            elif choice_input == "1":
                return False
            raise InvalidValueError()
        raise NotImplementedError()

    def _get_next_option_prompt(self, invalid_choice=False):
        assert len(self.options_left), "Something went wrong. There were no options left"
        self.current_option = self.options_left[0]
        choice_string = ""
        if invalid_choice is True:
            choice_string += "Invalid response entered. Try again.\n"

        choice_string += self.current_option.long_description + "\n"
        if len(self.current_option.option_types) > 1:
            choice_string += self._get_list_of_option_types()
        elif len(self.current_option.option_types) == 1:
            self.current_choice = 0
            choice_string += self._get_choice_value_prompt()
        return choice_string

    def _start_download(self):
        d = self._make_downloader()
        d.addCallback(lambda stream_downloader: stream_downloader.start())
        d.addErrback(self._handle_download_error)
        return d

    def _handle_download_error(self, err):
        if err.check(InsufficientFundsError):
            self.console.sendLine("Download stopped due to insufficient funds.")
            d = self.wallet.get_most_recent_blocktime()
            d.addCallback(get_time_behind_blockchain)
            d.addCallback(self._show_time_behind_blockchain_download)
            d.addErrback(self._log_recent_blockchain_time_error_download)
        else:
            log.error("An unexpected error has caused the download to stop: %s" % err.getTraceback())
            log_file = "console.log"
            if len(log.handlers):
                log_file = log.handlers[0].baseFilename
            self.console.sendLine("An unexpected error has caused the download to stop. See %s for details." % log_file)

    def _make_downloader(self):
        return self.factory.make_downloader(self.metadata, self.options_chosen,
                                            self.payment_rate_manager)

    def _show_time_behind_blockchain_download(self, rounded_time):
        if rounded_time.unit >= RoundedTime.HOUR:
            self.console.sendLine("\nThis application is %s behind the LBC blockchain, so some of your\n"
                                  "funds may not be available. Use 'get-blockchain-status' to check if\n"
                                  "your application is up to date with the blockchain.\n\n"
                                  "It should take a few minutes to catch up the first time you run this\n"
                                  "early version of LBRY. Please be patient =).\n\n" % str(rounded_time))

    def _log_recent_blockchain_time_error_download(self, err):
        log.error("An error occurred trying to look up the most recent blocktime: %s", err.getTraceback())


class AddStreamFromSD(AddStream):
    #prompt_description = "Add a stream from a stream descriptor file"
    #line_prompt = "Stream descriptor file name:"

    def start(self, sd_file):
        self.loading_metadata_deferred = self.sd_identifier.get_metadata_for_sd_file(sd_file)
        return AddStream.start(self)


class AddStreamFromSDFactory(CommandHandlerFactory):
    control_handler_class = AddStreamFromSD
    command = "get-sd"
    short_help = "Download a stream from a plaintext stream descriptor file"
    full_help = "Download a stream from a plaintext stream descriptor file.\n" \
                "Takes one argument, the filename of the stream descriptor.\n\n" \
                "get-sd <stream descriptor filename>"


class AddStreamFromHash(AddStream):
    #prompt_description = "Add a stream from a hash"
    #line_prompt = "Stream descriptor hash:"

    def __init__(self, console, sd_identifier, session, wallet):
        AddStream.__init__(self, console, sd_identifier, session.base_payment_rate_manager, wallet)
        self.session = session

    def start(self, sd_hash):
        self.loading_metadata_deferred = download_sd_blob(self.session, sd_hash,
                                                          self.payment_rate_manager)
        self.loading_metadata_deferred.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        AddStream.start(self)

    def _handle_load_failed(self, err):
        self.loading_failed = True
        if err.check(InvalidBlobHashError):
            self.console.sendLine("The hash you entered is invalid. It must be 96 characters long"
                                  " and contain only hex characters.\n\n")
            self.finished_deferred.callback(None)
            return
        if err.check(InsufficientFundsError):
            self.console.sendLine("Insufficient funds to download the metadata blob.")
            d = self.wallet.get_most_recent_blocktime()
            d.addCallback(get_time_behind_blockchain)
            d.addCallback(self._show_time_behind_blockchain_download)
            d.addErrback(self._log_recent_blockchain_time_error_download)
            d.addCallback(lambda _: self.console.sendLine("\n"))
            d.chainDeferred(self.finished_deferred)
            return
        return AddStream._handle_load_failed(self, err)


class AddStreamFromHashFactory(CommandHandlerFactory):
    control_handler_class = AddStreamFromHash
    command = "get-hash"
    short_help = "Download a stream from a hash"
    full_help = "Download a stream from the hash of the stream descriptor. The stream " \
                "descriptor file will be downloaded from LBRYnet and then read.\n" \
                "Takes one argument, the sha384 hashsum of the stream descriptor.\n\n" \
                "get-hash <stream descriptor sha384 hashsum>"


class AddStreamFromLBRYcrdName(AddStreamFromHash):
    #prompt_description = "Add a stream from a short name"
    #line_prompt = "Short name:"

    def __init__(self, console, sd_identifier, session, wallet):
        AddStreamFromHash.__init__(self, console, sd_identifier, session, wallet)
        self.wallet = wallet
        self.resolved_name = None
        self.description = None
        self.key_fee = None
        self.key_fee_address = None
        self.name = None

    def start(self, name):
        self.name = name
        self.loading_metadata_deferred = self._resolve_name(name)
        self.loading_metadata_deferred.addCallback(lambda stream_hash: download_sd_blob(self.session,
                                                                                        stream_hash,
                                                                                        self.payment_rate_manager))
        self.loading_metadata_deferred.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        AddStream.start(self)

    def _resolve_name(self, name):
        def get_name_from_info(stream_info):
            if 'stream_hash' not in stream_info:
                raise InvalidStreamInfoError(name)
            self.resolved_name = stream_info.get('name', None)
            self.description = stream_info.get('description', None)
            try:
                if 'key_fee' in stream_info:
                    self.key_fee = float(stream_info['key_fee'])
            except ValueError:
                self.key_fee = None
            self.key_fee_address = stream_info.get('key_fee_address', None)
            return stream_info['stream_hash']
        d = self.wallet.get_most_recent_blocktime()
        d.addCallback(get_time_behind_blockchain)
        d.addCallback(self._show_time_behind_blockchain_resolve)
        d.addErrback(self._log_recent_blockchain_time_error_resolve)
        d.addCallback(lambda _: self.wallet.get_stream_info_for_name(name))
        d.addCallback(get_name_from_info)
        return d

    def _show_time_behind_blockchain_resolve(self, rounded_time):
        if rounded_time.unit >= RoundedTime.HOUR:
            self.console.sendLine("\nThis application is %s behind the LBC blockchain, which may be\n"
                                  "preventing this name from being resolved correctly. Use 'get-blockchain-status'\n"
                                  "to check if your application is up to date with the blockchain.\n\n"
                                  "It should take a few minutes to catch up the first time you run\n"
                                  "this early version of LBRY. Please be patient =).\n\n" % str(rounded_time))
        else:
            self.console.sendLine("\n")

    def _log_recent_blockchain_time_error_resolve(self, err):
        log.error("An error occurred trying to look up the most recent blocktime: %s", err.getTraceback())

    def _handle_load_failed(self, err):
        self.loading_failed = True
        if err.check(UnknownNameError):
            if is_valid_blobhash(self.name):
                self.loading_failed = False
                self.loading_metadata_deferred = None
                AddStreamFromHash.start(self, self.name)
                return
            else:
                self.console.sendLine("The name %s could not be found." % err.getErrorMessage())
                self.finished_deferred.callback(True)
                return
        elif err.check(InvalidBlobHashError):
            self.console.sendLine("The metadata for this name is invalid. The stream cannot be downloaded.\n\n")
            self.finished_deferred.callback(None)
            return
        return AddStreamFromHash._handle_load_failed(self, err)

    def _start_download(self):
        d = self._pay_key_fee()
        d.addCallback(lambda _: AddStream._start_download(self))
        return d

    def _pay_key_fee(self):
        if self.key_fee is not None and self.key_fee_address is not None:
            reserved_points = self.wallet.reserve_points(self.key_fee_address, self.key_fee)
            if reserved_points is None:
                return defer.fail(InsufficientFundsError())
            return self.wallet.send_points_to_address(reserved_points, self.key_fee)
        return defer.succeed(True)

    def _get_info_to_show(self):
        i = AddStream._get_info_to_show(self)
        if self.description is not None:
            i.append(("description", self.description))
        if self.key_fee is None or self.key_fee_address is None:
            i.append(("decryption key fee", "Free"))
        else:
            i.append(("decryption key fee", str(self.key_fee)))
            i.append(("address to pay key fee", str(self.key_fee_address)))
        return i


class AddStreamFromLBRYcrdNameFactory(CommandHandlerFactory):
    control_handler_class = AddStreamFromLBRYcrdName
    priority = 100
    command = "get"
    short_help = "Download a stream from a name"
    full_help = "Download a stream associated with a name on the LBRYcrd blockchain. The name will be" \
                " looked up on the blockchain, and if it is associated with a stream descriptor hash," \
                " that stream descriptor will be downloaded and read. If the given name is itself a valid " \
                "hash, and the name doesn't exist on the blockchain, then the name will be used as the " \
                "stream descriptor hash as in get-hash. Use get-hash if you want no ambiguity.\n" \
                "Takes one argument, the name.\n\n" \
                "Usage: get <name>"


class LBRYFileChooser(RecursiveCommandHandler):

    def __init__(self, console, lbry_file_manager, factory_class, *args, **kwargs):
        """
        @param lbry_file_manager:

        @param factory_class:

        @param args: all arguments that will be passed to the factory

        @param kwargs: all arguments that will be passed to the superclass' __init__

        @return:
        """
        self.lbry_file_manager = lbry_file_manager
        self.factory_class = factory_class
        self.args = args
        RecursiveCommandHandler.__init__(self, console, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for lbry_file in self.lbry_file_manager.lbry_files:
            control_handler_factories.append(self.factory_class(self.console, lbry_file, *self.args))
        return control_handler_factories


class LBRYFileChooserFactory(CommandHandlerFactory):
    def get_prompt_description(self):
        lbry_file = self.args[0]
        return lbry_file.file_name


class DeleteLBRYFileChooser(LBRYFileChooser):
    #prompt_description = "Delete LBRY File"

    def __init__(self, console, stream_info_manager, blob_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, DeleteLBRYFileFactory,
                                 stream_info_manager, blob_manager, lbry_file_manager,
                                 exit_after_one_done=True)


class DeleteLBRYFileChooserFactory(CommandHandlerFactory):
    control_handler_class = DeleteLBRYFileChooser
    command = "delete-lbryfile"
    short_help = "Delete an LBRY file"
    full_help = "Delete an LBRY file which has been downloaded or created by this application.\n" \
                "\nGives the option to also delete the encrypted chunks of data associated with " \
                "the file. If they are deleted, they will all have to be downloaded again if " \
                "lbrynet-console is asked to download that file again, and lbrynet-console will " \
                "not be able to upload those chunks of data to other peers on LBRYnet."


class DeleteLBRYFile(CommandHandler):
    #prompt_description = "Delete LBRY File"
    delete_data_prompt = "Also delete data? (y/n): "
    confirm_prompt = "Are you sure? (y/n): "

    def __init__(self, console, lbry_file, stream_info_manager, blob_manager, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.blob_manager = blob_manager
        self.lbry_file_manager = lbry_file_manager
        self.got_delete_data = False
        self.delete_data = False
        self.got_confirmation = False

    def start(self):
        self.console.send(self.delete_data_prompt)

    def handle_line(self, line):
        #if line is None:
        #    return False, defer.succeed(self.line_prompt)
        if self.got_delete_data is False:
            self.got_delete_data = True
            if line.lower() in ['y', 'yes']:
                self.delete_data = True
            self.console.send(self.confirm_prompt)
            return
        if self.got_confirmation is False:
            self.got_confirmation = True
            if line.lower() in ['y', 'yes']:
                d = self._delete_lbry_file()

                def show_done():
                    self.console.sendLine("Successfully deleted " + str(self.lbry_file.stream_name))

                def delete_failed(err):
                    self.console.sendLine("Deletion unsuccessful. Reason: %s" % err.getErrorMessage())

                d.addCallbacks(lambda _: show_done(), delete_failed)
                d.chainDeferred(self.finished_deferred)
            else:
                self.console.sendLine("Canceled deletion.")
                self.finished_deferred.callback(None)

    def _delete_lbry_file(self):
        d = self.lbry_file_manager.delete_lbry_file(self.lbry_file.stream_hash)

        def finish_deletion():
            if self.delete_data is True:
                d = self._delete_data()
            else:
                d = defer.succeed(True)
            d.addCallback(lambda _: self._delete_stream_data())
            return d

        d.addCallback(lambda _: finish_deletion())
        return d

    def _delete_data(self):
        d1 = self.stream_info_manager.get_blobs_for_stream(self.lbry_file.stream_hash)

        def get_blob_hashes(blob_infos):
            return [b[0] for b in blob_infos if b[0] is not None]

        d1.addCallback(get_blob_hashes)
        d2 = self.stream_info_manager.get_sd_blob_hashes_for_stream(self.lbry_file.stream_hash)

        def combine_blob_hashes(results):
            blob_hashes = []
            for success, result in results:
                if success is True:
                    blob_hashes.extend(result)
            return blob_hashes

        def delete_blobs(blob_hashes):
            self.blob_manager.delete_blobs(blob_hashes)
            return True

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True)
        dl.addCallback(combine_blob_hashes)
        dl.addCallback(delete_blobs)
        return dl

    def _delete_stream_data(self):
        return self.stream_info_manager.delete_stream(self.lbry_file.stream_hash)


class DeleteLBRYFileFactory(LBRYFileChooserFactory):
    control_handler_class = DeleteLBRYFile


class ToggleLBRYFileRunningChooser(LBRYFileChooser):
    #prompt_description = "Toggle whether an LBRY File is running"

    def __init__(self, console, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, ToggleLBRYFileRunningFactory,
                                 lbry_file_manager, exit_after_one_done=True)


class ToggleLBRYFileRunningChooserFactory(CommandHandlerFactory):
    control_handler_class = ToggleLBRYFileRunningChooser
    command = "toggle-running"
    short_help = "Toggle whether an LBRY file is running"
    full_help = "Toggle whether an LBRY file, which is being saved by this application," \
                "is currently being downloaded."


class ToggleLBRYFileRunning(CommandHandler):
    #prompt_description = "Toggle whether an LBRY File is running"

    def __init__(self, console, lbry_file, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager

    def start(self):
        d = self.lbry_file_manager.toggle_lbry_file_running(self.lbry_file.stream_hash)
        d.addErrback(self._handle_download_error)
        self.finished_deferred.callback(None)

    @staticmethod
    def _handle_download_error(err):
        if err.check(InsufficientFundsError):
            return "Download stopped due to insufficient funds."
        else:
            log.error("An unexpected error occurred due to toggling an LBRY file running. %s", err.getTraceback())
            log_file = "console.log"
            if len(log.handlers):
                log_file = log.handlers[0].baseFilename
            return "An unexpected error occurred. See %s for details." % log_file


class ToggleLBRYFileRunningFactory(LBRYFileChooserFactory):
    control_handler_class = ToggleLBRYFileRunning


class CreateLBRYFile(CommandHandler):
    #prompt_description = "Create an LBRY File from file"
    line_prompt = "File name: "

    def __init__(self, console, session, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.session = session
        self.lbry_file_manager = lbry_file_manager

    def start(self, file_name):
        d = create_lbry_file(self.session, self.lbry_file_manager, file_name, open(file_name))
        d.addCallback(self.add_to_lbry_files)
        d.addCallback(lambda _: self.console.sendLine("Successfully created " + str(file_name)))
        self.console.sendLine("Creating an LBRY file from " + str(file_name) + " in the background.")
        self.finished_deferred.callback(None)

    def add_to_lbry_files(self, stream_hash):
        prm = PaymentRateManager(self.session.base_payment_rate_manager)
        d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        d.addCallback(self.set_status, stream_hash)
        return d

    def set_status(self, lbry_file_downloader, stream_hash):
        d = self.lbry_file_manager.change_lbry_file_status(stream_hash,
                                                           ManagedLBRYFileDownloader.STATUS_FINISHED)
        d.addCallback(lambda _: lbry_file_downloader.restore())
        return d


class CreateLBRYFileFactory(CommandHandlerFactory):
    control_handler_class = CreateLBRYFile
    command = "create-lbryfile"
    short_help = "LBRYize a file"
    full_help = "Encrypt a file, split it into chunks, and make those chunks available on LBRYnet. Also " \
                "create a 'stream descriptor file' which contains all of the metadata needed to download " \
                "the encrypted chunks from LBRYnet and put them back together. This plain stream descriptor " \
                "can be passed around via other file sharing methods like email. Additionally, this " \
                "application can publish the stream descriptor to LBRYnet so that the LBRY file can be " \
                "downloaded via the hash of the stream descriptor."


class PublishStreamDescriptorChooser(LBRYFileChooser):
    #prompt_description = "Publish a stream descriptor file to the DHT for an LBRY File"

    def __init__(self, console, stream_info_manager, blob_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, PublishStreamDescriptorFactory,
                                 stream_info_manager, blob_manager, lbry_file_manager,
                                 exit_after_one_done=True)


class PublishStreamDescriptorChooserFactory(CommandHandlerFactory):
    control_handler_class = PublishStreamDescriptorChooser
    command = "release-lbryfile"
    short_help = "Put a stream descriptor onto LBRYnet"
    full_help = "Make a stream descriptor available on LBRYnet at its sha384 hashsum. If the stream " \
                "descriptor is made available on LBRYnet, anyone will be able to download it via its " \
                "hash via LBRYnet, and the LBRY file can then be downloaded if it is available."


class PublishStreamDescriptor(CommandHandler):
    #prompt_description = "Publish a stream descriptor file to the DHT for an LBRY File"

    def __init__(self, console, lbry_file, stream_info_manager, blob_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.blob_manager = blob_manager

    def start(self):
        d = publish_sd_blob(self.stream_info_manager, self.blob_manager, self.lbry_file.stream_hash)
        d.addCallback(lambda sd_hash: self.console.sendLine(sd_hash))
        d.chainDeferred(self.finished_deferred)

    #def _publish_sd_blob(self):
    #    descriptor_writer = BlobStreamDescriptorWriter(self.blob_manager)

    #    d = get_sd_info(self.stream_info_manager, self.lbry_file.stream_hash, True)
    #    d.addCallback(descriptor_writer.create_descriptor)

    #    def add_sd_blob_to_stream(sd_blob_hash):
    #        d = self.stream_info_manager.save_sd_blob_hash_to_stream(self.lbry_file.stream_hash, sd_blob_hash)
    #        d.addCallback(lambda _: sd_blob_hash)
    #        return d

    #    d.addCallback(add_sd_blob_to_stream)
    #    return d


class PublishStreamDescriptorFactory(LBRYFileChooserFactory):
    control_handler_class = PublishStreamDescriptor


class ShowPublishedSDHashesChooser(LBRYFileChooser):
    #prompt_description = "Show published stream descriptors for an LBRY File"

    def __init__(self, console, stream_info_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, ShowPublishedSDHashesFactory,
                                 stream_info_manager, lbry_file_manager)


class ShowPublishedSDHashesChooserFactory(CommandHandlerFactory):
    control_handler_class = ShowPublishedSDHashesChooser
    command = "show-lbryfile-sd-hashes"
    short_help = "Show the published stream descriptor files associated with an LBRY file"
    full_help = "Show the published stream descriptor files associated with an LBRY file. " \
                "These files contain the metadata for LBRY files. These files can be accessed " \
                "on lbrynet via their hash. From that, lbrynet-console can download the LBRY file " \
                "if it is available on lbrynet."


class ShowPublishedSDHashes(CommandHandler):
    #prompt_description = "Show published stream descriptors for an LBRY File"

    def __init__(self, console, lbry_file, stream_info_manager, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.lbry_file_manager = lbry_file_manager

    def start(self):
        d = self._show_sd_hashes()
        d.chainDeferred(self.finished_deferred)

    def _show_sd_hashes(self):
        d = self.stream_info_manager.get_sd_blob_hashes_for_stream(self.lbry_file.stream_hash)

        def format_blob_hashes(sd_blob_hashes):
            self.console.sendLine("\n".join([str(b) for b in sd_blob_hashes]))

        d.addCallback(format_blob_hashes)
        return d


class ShowPublishedSDHashesFactory(LBRYFileChooserFactory):
    control_handler_class = ShowPublishedSDHashes


class CreatePlainStreamDescriptorChooser(LBRYFileChooser):
    #prompt_description = "Create a plain stream descriptor file for an LBRY File"

    def __init__(self, console, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager,
                                 CreatePlainStreamDescriptorFactory, lbry_file_manager,
                                 exit_after_one_done=True)


class CreatePlainStreamDescriptorChooserFactory(CommandHandlerFactory):
    control_handler_class = CreatePlainStreamDescriptorChooser
    command = "create-stream-descriptor"
    short_help = "Create a plaintext stream descriptor file for an LBRY file"
    full_help = "Create a plaintext stream descriptor file for an LBRY file. This file, " \
                "which traditionally has the file extension .cryptsd, can be shared " \
                "through a variety of means, including email and file transfer. Anyone " \
                "possessing this file will be able to download the LBRY file if it is " \
                "available on lbrynet."


class CreatePlainStreamDescriptor(CommandHandler):
    prompt_description = "Create a plain stream descriptor file for an LBRY File"

    def __init__(self, console, lbry_file, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        self.sd_file_name = None
        self.overwrite_old = False

    def start(self):
        self.console.sendLine(self._get_file_name_prompt())

    def handle_line(self, line):
        if self.sd_file_name is None:
            self.sd_file_name = line
            d = self._get_file_name()
            d.addCallback(lambda file_name: create_plain_sd(self.lbry_file_manager.stream_info_manager,
                                                            self.lbry_file.stream_hash, file_name,
                                                            self.overwrite_old))
            d.addCallback(lambda sd_file_name: self.console.sendLine("Wrote stream metadata to " + sd_file_name))
            d.chainDeferred(self.finished_deferred)

    def _get_file_name_prompt(self):
        file_name = self.lbry_file.file_name
        if not file_name:
            file_name = "_"
        file_name += ".cryptsd"
        return "Stream Descriptor file name (blank for default, %s):" % file_name

    def _get_file_name(self):
        if self.sd_file_name:
            file_name = self.sd_file_name
            self.overwrite_old = True
        else:
            file_name = self.lbry_file.file_name
        file_name = file_name + ".cryptsd"
        return defer.succeed(file_name)


class CreatePlainStreamDescriptorFactory(LBRYFileChooserFactory):
    control_handler_class = CreatePlainStreamDescriptor


class ShowLBRYFileStreamHashChooser(LBRYFileChooser):
    #prompt_description = "Show an LBRY File's stream hash (not usually what you want)"

    def __init__(self, console, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, ShowLBRYFileStreamHashFactory)


class ShowLBRYFileStreamHashChooserFactory(CommandHandlerFactory):
    control_handler_class = ShowLBRYFileStreamHashChooser
    command = "lbryfile-streamhash"
    short_help = "Show an LBRY file's stream hash"
    full_help = "Show the stream hash of an LBRY file, which is how the LBRY file is referenced internally" \
                " by this application and therefore not usually what you want to see."


class ShowLBRYFileStreamHash(CommandHandler):
    #prompt_description = "Show an LBRY File's stream hash (not usually what you want)"

    def __init__(self, console, lbry_file):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file

    def start(self):
        self.console.sendLine(str(self.lbry_file.stream_hash))
        self.finished_deferred.callback(None)


class ShowLBRYFileStreamHashFactory(LBRYFileChooserFactory):
    control_handler_class = ShowLBRYFileStreamHash


class ModifyLBRYFileDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify LBRY File data payment rate"

    def __init__(self, console, lbry_file, lbry_file_manager):
        ModifyPaymentRate.__init__(self, console)
        self._prompt_choices['unset'] = (self._unset, "Use the default LBRY file data rate")
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        self.payment_rate_manager = lbry_file.payment_rate_manager

    def _unset(self):
        d = self._set_rate(None)
        d.addCallback(lambda _: "Using the default LBRY file data rate")
        return d

    def _set_rate(self, rate):
        self.payment_rate_manager.min_blob_data_payment_rate = rate
        return self.lbry_file_manager.set_lbry_file_data_payment_rate(self.lbry_file.stream_hash, rate)

    def _get_current_status(self):
        status = "The LBRY file's current data payment rate is "
        effective_rate = self.payment_rate_manager.get_effective_min_blob_data_payment_rate()
        if self.payment_rate_manager.min_blob_data_payment_rate is None:
            status += "set to use the default LBRY file data payment rate, "
        status += str(effective_rate)
        return status


class ModifyLBRYFileDataPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyLBRYFileDataPaymentRate


class ModifyLBRYFileOptionsChooser(LBRYFileChooser):
    #prompt_description = "Modify an LBRY File's options"

    def __init__(self, console, lbry_file_manager):
        LBRYFileChooser.__init__(self, console, lbry_file_manager, ModifyLBRYFileOptionsFactory, lbry_file_manager)


class ModifyLBRYFileOptionsChooserFactory(CommandHandlerFactory):
    control_handler_class = ModifyLBRYFileOptionsChooser
    command = "modify-lbryfile-options"
    short_help = "Modify an LBRY file's options"
    full_help = "Modify an LBRY file's options. Options include, and are limited to, " \
                "changing the rate that the application will pay for data related to " \
                "this LBRY file."


class ModifyLBRYFileOptions(RecursiveCommandHandler):
    #prompt_description = "Modify an LBRY File's options"

    def __init__(self, console, lbry_file, lbry_file_manager):
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        RecursiveCommandHandler.__init__(self, console)

    def _get_control_handler_factories(self):
        factories = []
        factories.append(ModifyLBRYFileDataPaymentRateFactory(self.lbry_file, self.lbry_file_manager))
        return factories


class ModifyLBRYFileOptionsFactory(LBRYFileChooserFactory):
    control_handler_class = ModifyLBRYFileOptions


class ClaimName(CommandHandler):
    #prompt_description = "Publish to an lbry:// address"
    other_hash_prompt = "Enter the hash you would like to publish:"
    short_desc_prompt = "Enter a short description:"
    #sd_failure_message = "Unable to find a stream descriptor for that file."
    requested_price_prompt = "Enter the fee others should pay for the decryption key for this stream. Leave blank for no fee:"
    lbrycrd_address_prompt = "Enter the LBRYcrd address to which the key fee should be sent. If left blank a new address will be used from the wallet:"
    bid_amount_prompt = "Enter the number of credits you wish to use to support your bid for the name:"
    choose_name_prompt = "Enter the name to which you would like to publish:"

    def __init__(self, console, wallet, lbry_file_manager, blob_manager):
        CommandHandler.__init__(self, console)
        self.wallet = wallet
        self.lbry_file_manager = lbry_file_manager
        self.blob_manager = blob_manager
        self.file_type_options = []
        self.file_type_chosen = None
        self.lbry_file_list = []
        self.sd_hash = None
        self.key_fee = None
        self.key_fee_chosen = False
        self.need_address = True
        self.chosen_address = None
        self.bid_amount = None
        self.chosen_name = None
        self.short_description = None
        self.verified = False

    def start(self):
        self.console.sendLine(self._get_file_type_options())

    def handle_line(self, line):
        #if line is None:
        #    return False, defer.succeed(self._get_file_type_options())
        #if self.failed is True:
        #    return True, defer.succeed(None)
        if self.file_type_chosen is None:
            try:
                choice = int(line)
            except ValueError:
                choice = -1
            if choice < 0 or choice >= len(self.file_type_options):
                self.console.sendLine("You must enter a valid number.\n\n%s" % self._get_file_type_options())
                return
            if self.file_type_options[choice][0] is None:
                self.console.sendLine("Publishing canceled.")
                self.finished_deferred.callback(None)
                return
            self.file_type_chosen = self.file_type_options[choice][0]
            if self.file_type_chosen == "hash":
                self.console.sendLine(self.other_hash_prompt)
                return
            else:
                self._set_sd_hash_and_get_desc_prompt()
                return
        if self.sd_hash is None:
            self.sd_hash = line
            self.console.sendLine(self.short_desc_prompt)
            return
        if self.short_description is None:
            self.short_description = line
            self.console.sendLine(self.requested_price_prompt)
            return
        if self.key_fee_chosen is False:
            if line:
                try:
                    self.key_fee = float(line)
                except ValueError:
                    self.console.sendLine("Leave blank or enter a floating point number.\n\n%s" % self.requested_price_prompt)
                    return
            self.key_fee_chosen = True
            if self.key_fee is None or self.key_fee <= 0:
                self.need_address = False
                self.console.sendLine(self.bid_amount_prompt)
                return
            self.console.sendLine(self.lbrycrd_address_prompt)
            return
        if self.need_address is True:
            if line:
                self.chosen_address = line
                d = defer.succeed(None)
            else:
                d = self._get_new_address()
            self.need_address = False
            d.addCallback(lambda _: self.console.sendLine(self.bid_amount_prompt))
            return
        if self.bid_amount is None:
            try:
                self.bid_amount = float(line)
            except ValueError:
                self.console.sendLine("Must be a floating point number.\n\n%s" % self.bid_amount_prompt)
                return
            self.console.sendLine(self.choose_name_prompt)
            return
        if self.chosen_name is None:
            self.chosen_name = line
            self.console.sendLine(self._get_verification_prompt())
            return
        if self.verified is False:
            if line.lower() == "yes":
                d = self._claim_name()
            else:
                d = defer.succeed("Claim canceled")
            d.chainDeferred(self.finished_deferred)

    def _get_file_type_options(self):
        options = []
        pattern = "[%d] %s\n"
        prompt_string = "What would you like to publish?\n"
        prompt_string += "LBRY Files:\n"
        i = 0
        for lbry_file in self.lbry_file_manager.lbry_files:
            options.append((lbry_file, lbry_file.file_name))
            prompt_string += pattern % (i, lbry_file.file_name)
            i += 1
        prompt_string += "Other:\n"
        options.append(("hash", "Enter a hash"))
        prompt_string += pattern % (i, "Enter a hash")
        i += 1
        options.append((None, "Cancel"))
        prompt_string += pattern % (i, "Cancel")
        self.file_type_options = options
        return prompt_string

    def _choose_sd(self, sd_blob_hashes):
        if not sd_blob_hashes:
            return publish_sd_blob(self.lbry_file_manager.stream_info_manager, self.blob_manager,
                                   self.file_type_chosen.stream_hash)

        else:
            return defer.succeed(sd_blob_hashes[0])

    def _set_sd_hash_and_get_desc_prompt(self):
        d = self.lbry_file_manager.stream_info_manager.get_sd_blob_hashes_for_stream(self.file_type_chosen.stream_hash)
        d.addCallback(self._choose_sd)

        def set_sd_hash(sd_hash):
            self.sd_hash = sd_hash
            self.console.sendLine(self.short_desc_prompt)

        def sd_hash_failed(err):
            self.console.sendLine("An error occurred getting the stream descriptor hash: %s" % err.getErrorMessage())
            self.finished_deferred.callback(None)

        d.addCallback(set_sd_hash)
        d.addErrback(sd_hash_failed)
        return d

    def _get_new_address(self):
        d = self.wallet.get_new_address()

        def set_address(address):
            self.chosen_address = address

        d.addCallback(set_address)
        return d

    def _get_verification_prompt(self):
        v_string = "Ensure the following details are correct:\n"
        if self.file_type_chosen != "hash":
            v_string += "File name: %s\n" % str(self.file_type_chosen.file_name)
        v_string += "Hash: %s\n" % str(self.sd_hash)
        v_string += "Description: %s\n" % str(self.short_description)
        v_string += "Key fee: %s\n" % str(self.key_fee)
        if self.chosen_address is not None:
            v_string += "Key fee address: %s\n" % str(self.chosen_address)
        v_string += "Bid amount: %s\n" % str(self.bid_amount)
        v_string += "Name: %s\n" % str(self.chosen_name)
        v_string += "\nIf this is correct, type 'yes'. Otherwise, type 'no' and the bid will be aborted:"
        return v_string

    def _claim_name(self):
        d = self.wallet.claim_name(self.chosen_name, self.sd_hash, float(self.bid_amount),
                                   description=self.short_description, key_fee=self.key_fee,
                                   key_fee_address=self.chosen_address)
        d.addCallback(lambda response: self.console.sendLine(response))
        return d


class ClaimNameFactory(CommandHandlerFactory):
    control_handler_class = ClaimName
    command = "claim"
    short_help = "Dedicate some LBC toward an lbry:// address"
    full_help = "Dedicate some LBY toward associate an LBRY file, or any hash, with " \
                "an lbry:// address. On lbry, whoever dedicates the most credits to an " \
                "lbry:// address controls that address. This command will let you choose " \
                "to associate either on LBRY file or any given value with the address.\n" \
                "This command will ask for a few additional fields, explained here:\n\n" \
                "The title will be presented to users before they download the file.\n" \
                "The bid amount is the number of LBC that will be dedicated toward " \
                "the lbry://address being registered. On lbry, whoever dedicates the most " \
                "credits to the address controls that address.\n" \
                "The decryption key fee is the amount of LBC that users will be charged " \
                "when consuming this file. The fees will be sent to the provided key fee address.\n" \
                "The description will be presented to users before they download the file.\n"


class Publish(CommandHandler):
    couldnt_read_file_error = "Unable to read %s. The file must exist and you must have permission to read it."
    bid_amount_not_number = "Bid amount must be a number (e.g. 5 or 10.0)"
    key_fee_not_number = "Decryption key fee must be a number (e.g. 5 or 10.0)"

    def __init__(self, console, session, lbry_file_manager, wallet):
        CommandHandler.__init__(self, console)
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.received_file_name = False
        self.file_path = None
        self.file_name = None
        self.title = None
        self.publish_name = None
        self.bid_amount = None
        self.key_fee = None
        self.key_fee_address = None
        self.key_fee_address_chosen = False
        self.description = None
        self.verified = False
        self.lbry_file = None
        self.sd_hash = None
        self.tx_hash = None

    def start(self, file_name=None):#, title=None, publish_name=None, bid_amount=None,
        #      key_fee=None, key_fee_address=None):

        #def set_other_fields():
        #    self.title = title
        #    self.publish_name = publish_name
        #    if bid_amount is not None:
        #        try:
        #            self.bid_amount = float(bid_amount)
        #        except ValueError:
        #            self.console.sendLine(self.bid_amount_not_number)
        #            self.finished_deferred.callback(None)
        #            return
        #    if key_fee is not None:
        #        try:
        #            self.key_fee = float(key_fee)
        #        except ValueError:
        #            self.console.sendLine(self.key_fee_not_number)
        #            self.finished_deferred.callback(None)
        #            return
        #    if key_fee_address is not None:
        #        self.key_fee_address = key_fee_address
        #        self.key_fee_address_chosen = True
        #    self._send_next_prompt()

        def handle_error(err):
            if err.check(IOError):
                self.console.sendLine(self.couldnt_read_file_error % str(file_name))
            else:
                self.console.sendLine("An unexpected error occurred: %s" % str(err.getErrorMessage()))
            self.finished_deferred.callback(None)

        if file_name is not None:
            self.received_file_name = True
            d = self._check_file_path(file_name)
            #d.addCallback(lambda _: set_other_fields())
            d.addCallbacks(lambda _: self._send_next_prompt(), handle_error)
        else:
            self._send_next_prompt()

    def handle_line(self, line):
        d = defer.succeed(True)
        if self.file_name is None:
            if self.received_file_name is False:
                self.received_file_name = True
                d = self._check_file_path(line)

                def file_name_failed(err):
                    err.trap(IOError)
                    self.console.sendLine(self.couldnt_read_file_error % line)
                    self.finished_deferred.callback(None)
                    return False

                d.addErrback(file_name_failed)
        elif self.title is None:
            self.title = line
        elif self.publish_name is None:
            self.publish_name = line
        elif self.bid_amount is None:
            try:
                self.bid_amount = float(line)
            except ValueError:
                self.console.sendLine(self.bid_amount_not_number)
        elif self.key_fee is None:
            try:
                self.key_fee = float(line)
            except ValueError:
                self.console.sendLine(self.key_fee_not_number)
        elif self.key_fee_address_chosen is False and self.key_fee > 0:
            if line:
                self.key_fee_address = line
            else:
                d = self._get_new_address()
            self.key_fee_address_chosen = True
        elif self.description is None:
            self.description = line
        elif self.verified is False:
            if line.lower() in ['yes', 'y']:
                self._do_publish()
                self.console.sendLine("Publishing in the background.")
            else:
                self.console.sendLine("Canceled.")
            self.finished_deferred.callback(None)
            return
        else:
            return
        d.addCallbacks(lambda s: self._send_next_prompt() if s is True else None,
                       self.finished_deferred.errback)

    def _check_file_path(self, file_path):
        def check_file_threaded():
            f = open(file_path)
            f.close()
            self.file_path = file_path
            self.file_name = os.path.basename(self.file_path)
            return True
        return threads.deferToThread(check_file_threaded)

    def _get_new_address(self):
        d = self.wallet.get_new_address()

        def set_address(address):
            self.key_fee_address = address
            return True

        d.addCallback(set_address)
        return d

    def _send_next_prompt(self):
        prompt = None
        if self.file_name is None:
            prompt = "Path to file: "
        elif self.title is None:
            prompt = "Title: "
        elif self.publish_name is None:
            prompt = "Publish to: lbry://"
        elif self.bid_amount is None:
            prompt = "Bid amount for published name in LBC: "
        elif self.key_fee is None:
            prompt = "Decryption key fee in LBC: "
        elif self.key_fee_address_chosen is False and self.key_fee > 0:
            prompt = "Decryption key fee sent to (leave blank for a new address): "
        elif self.description is None:
            prompt = "Description: "
        elif self.verified is False:
            prompt = self._get_verification_prompt()
        if prompt is not None:
            self.console.send(prompt)

    def _get_verification_prompt(self):
        v_string = "\nPlease review the following details.\n\n"
        v_string += "Path to file: %s\n" % str(self.file_path)
        v_string += "File name: %s\n" % str(self.file_name)
        v_string += "Title: %s\n" % str(self.title)
        v_string += "Published to: lbry://%s\n" % str(self.publish_name)
        v_string += "Bid amount: %s LBC\n" % str(self.bid_amount)
        v_string += "Fee for decryption key: %s LBC\n" % str(self.key_fee)
        if self.key_fee > 0:
            v_string += "Decryption key address: %s\n" % str(self.key_fee_address)
        v_string += "Description: %s\n" % str(self.description)
        v_string += "Is this correct? (y/n): "
        return v_string

    def set_status(self, lbry_file_downloader, stream_hash):
        self.lbry_file = lbry_file_downloader
        d = self.lbry_file_manager.change_lbry_file_status(stream_hash,
                                                           ManagedLBRYFileDownloader.STATUS_FINISHED)
        d.addCallback(lambda _: lbry_file_downloader.restore())
        return d

    def add_to_lbry_files(self, stream_hash):
        prm = PaymentRateManager(self.session.base_payment_rate_manager)
        d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        d.addCallback(self.set_status, stream_hash)
        return d

    def _create_sd_blob(self):
        d = publish_sd_blob(self.lbry_file_manager.stream_info_manager, self.session.blob_manager,
                            self.lbry_file.stream_hash)

        def set_sd_hash(sd_hash):
            self.sd_hash = sd_hash

        d.addCallback(set_sd_hash)
        return d

    def _claim_name(self):
        d = self.wallet.claim_name(self.publish_name, self.sd_hash, self.bid_amount,
                                   description=self.description, key_fee=self.key_fee,
                                   key_fee_address=self.key_fee_address)

        def set_tx_hash(tx_hash):
            self.tx_hash = tx_hash

        d.addCallback(set_tx_hash)
        return d

    def _show_result(self):
        message = "Finished publishing %s to %s. The txid of the LBRYcrd claim is %s."
        self.console.sendLine(message % (str(self.file_name), str(self.publish_name), str(self.tx_hash)))

    def _show_time_behind_blockchain(self, rounded_time):
        if rounded_time.unit >= RoundedTime.HOUR:
            self.console.sendLine("This application is %s behind the LBC blockchain\n"
                                  "and therefore may not have all of the funds you expect\n"
                                  "available at this time. It should take a few minutes to\n"
                                  "catch up the first time you run this early version of LBRY.\n"
                                  "Please be patient =).\n" % str(rounded_time))

    def _log_best_blocktime_error(self, err):
        log.error("An error occurred checking the best time of the blockchain: %s", err.getTraceback())

    def _show_publish_error(self, err):
        message = "An error occurred publishing %s to %s. Error: %s."
        if err.check(InsufficientFundsError):
            d = self.wallet.get_most_recent_blocktime()
            d.addCallback(get_time_behind_blockchain)
            d.addCallback(self._show_time_behind_blockchain)
            d.addErrback(self._log_best_blocktime_error)
            error_message = "Insufficient funds"
        else:
            d = defer.succeed(True)
            error_message = err.getErrorMessage()
        self.console.sendLine(message % (str(self.file_name), str(self.publish_name), error_message))
        log.error(message, str(self.file_name), str(self.publish_name), err.getTraceback())
        return d

    def _do_publish(self):
        d = create_lbry_file(self.session, self.lbry_file_manager, self.file_name, open(self.file_path))
        d.addCallback(self.add_to_lbry_files)
        d.addCallback(lambda _: self._create_sd_blob())
        d.addCallback(lambda _: self._claim_name())
        d.addCallbacks(lambda _: self._show_result(), self._show_publish_error)
        return d


class PublishFactory(CommandHandlerFactory):
    control_handler_class = Publish
    priority = 90
    command = "publish"
    short_help = "Publish a file to lbrynet"
    full_help = "Publish a file to lbrynet.\n\n" \
                "Usage: publish [file_name]\n\n" \
                "This command takes (or prompts) for a file, prompts for additional " \
                "information about that file, and then makes that file available on " \
                "lbrynet via an lbry:// address.\n" \
                "The file given must exist or publish will fail.\n" \
                "The title will be presented to users before they download the file.\n" \
                "The bid amount is the number of LBC that will be dedicated toward " \
                "the lbry://address being registered. On lbry, whoever dedicates the most " \
                "credits to the address controls that address.\n" \
                "The decryption key fee is the amount of LBC that users will be charged " \
                "when consuming this file. The fees will be sent to the provided key fee address.\n" \
                "The description will be presented to users before they download the file.\n"


class ModifyDefaultDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify default data payment rate"

    def __init__(self, console, payment_rate_manager, settings):
        ModifyPaymentRate.__init__(self, console)
        self.settings = settings
        self.payment_rate_manager = payment_rate_manager

    def _set_rate(self, rate):
        self.payment_rate_manager.min_blob_data_payment_rate = rate
        return self.settings.save_default_data_payment_rate(rate)

    def _get_current_status(self):
        status = "The current default data payment rate is "
        status += str(self.payment_rate_manager.min_blob_data_payment_rate)
        return status


class ModifyDefaultDataPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyDefaultDataPaymentRate


class ForceCheckBlobFileConsistency(CommandHandler):
    prompt_description = "Verify consistency of stored chunks"

    def __init__(self, console, blob_manager):
        CommandHandler.__init__(self, console)
        self.blob_manager = blob_manager

    def start(self):
        self._check_consistency()
        self.console.sendLine("Checking consistency in the background.")
        self.finished_deferred.callback(None)

    def _check_consistency(self):
        d = self.blob_manager.check_consistency()
        d.addCallback(lambda _: self.console.sendLine("Finished checking stored blobs"))
        return d


class ForceCheckBlobFileConsistencyFactory(CommandHandlerFactory):
    control_handler_class = ForceCheckBlobFileConsistency


class ModifyApplicationDefaults(RecursiveCommandHandler):
    #prompt_description = "Modify application settings"

    def __init__(self, console, lbry_service):
        self.lbry_service = lbry_service
        RecursiveCommandHandler.__init__(self, console)

    def _get_control_handler_factories(self):
        return [ModifyDefaultDataPaymentRateFactory(self.lbry_service.session.base_payment_rate_manager,
                                                    self.lbry_service.settings),
                ForceCheckBlobFileConsistencyFactory(self.lbry_service.session.blob_manager)]


class ModifyApplicationDefaultsFactory(CommandHandlerFactory):
    control_handler_class = ModifyApplicationDefaults
    command = "modify-application-defaults"
    short_help = "Modify application settings"
    full_help = "Either change the default rate to pay for data downloads or check " \
                "that the chunks of data on disk match up with the chunks of data " \
                "the application thinks are on disk."


class ShowServerStatus(CommandHandler):
    #prompt_description = "Show the status of the server"

    def __init__(self, console, lbry_service):
        CommandHandler.__init__(self, console)
        self.lbry_service = lbry_service

    def start(self):
        #assert line is None, "Show server status should not be passed any arguments"
        d = self._get_status()
        d.chainDeferred(self.finished_deferred)

    def _get_status(self):
        status_string = "Server status:\n"
        status_string += "Port: " + str(self.lbry_service.peer_port) + "\n"
        status_string += "Running: " + str(self.lbry_service.lbry_server_port is not None) + "\n"
        if self.lbry_service.blob_request_payment_rate_manager is not None:
            rate = self.lbry_service.blob_request_payment_rate_manager.get_effective_min_blob_data_payment_rate()
            status_string += "Min blob data payment rate: "
            if self.lbry_service.blob_request_payment_rate_manager.min_blob_data_payment_rate is None:
                status_string += "Using application default (" + str(rate) + ")\n"
            else:
                status_string += str(rate)
            status_string += "\n"
        #status_string += "Min crypt info payment rate: "
        #status_string += str(self.lbry_service._server_payment_rate_manager.get_min_live_blob_info_payment_rate())
        #status_string += "\n"
        self.console.sendLine(status_string)
        return defer.succeed(None)


class ShowServerStatusFactory(CommandHandlerFactory):
    control_handler_class = ShowServerStatus
    command = "server-status"
    short_help = "Show the server's status"
    full_help = "Show the port on which the server is running, whether the server is running, and the" \
                " payment rate which the server accepts for data uploads"


class StartServer(CommandHandler):
    prompt_description = "Start the server"

    def __init__(self, console, lbry_service):
        CommandHandler.__init__(self, console)
        self.lbry_service = lbry_service

    def start(self):
        #assert line is None, "Start server should not be passed any arguments"
        d = self.lbry_service.start_server()
        d.addCallback(lambda _: self.lbry_service.settings.save_server_running_status(running=True))
        d.addCallback(lambda _: self.console.sendLine("Successfully started the server"))
        d.chainDeferred(self.finished_deferred)
        #return True, d


class StartServerFactory(CommandHandlerFactory):
    control_handler_class = StartServer


class StopServer(CommandHandler):
    prompt_description = "Stop the server"

    def __init__(self, console, lbry_service):
        CommandHandler.__init__(self, console)
        self.lbry_service = lbry_service

    def start(self):
        #assert line is None, "Stop server should not be passed any arguments"
        d = self.lbry_service.stop_server()
        d.addCallback(lambda _: self.lbry_service.settings.save_server_running_status(running=False))
        d.addCallback(lambda _: self.console.sendLine("Successfully stopped the server"))
        d.chainDeferred(self.finished_deferred)
        #return True, d


class StopServerFactory(CommandHandlerFactory):
    control_handler_class = StopServer


class ModifyServerDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify server data payment rate"

    def __init__(self, console, payment_rate_manager, settings):
        ModifyPaymentRate.__init__(self, console)
        self._prompt_choices['unset'] = (self._unset, "Use the application default data rate")
        self.settings = settings
        self.payment_rate_manager = payment_rate_manager

    def _unset(self):
        d = self._set_rate(None)
        d.addCallback(lambda _: "Using the application default data rate")
        return d

    def _set_rate(self, rate):
        self.payment_rate_manager.min_blob_data_payment_rate = rate
        return self.settings.save_server_data_payment_rate(rate)

    def _get_current_status(self):
        effective_rate = self.payment_rate_manager.get_effective_min_blob_data_payment_rate()
        status = "The current server data payment rate is "
        if self.payment_rate_manager.min_blob_data_payment_rate is None:
            status += "set to use the application default, "
        status += str(effective_rate)
        return status


class ModifyServerDataPaymentRateFactory(CommandHandlerFactory):
    control_handler_class = ModifyServerDataPaymentRate


# class ModifyServerCryptInfoPaymentRate(ModifyPaymentRate):
#     prompt_description = "Modify server live stream metadata payment rate"
#
#     def __init__(self, payment_rate_manager, settings):
#         ModifyPaymentRate.__init__(self)
#         self._prompt_choices['unset'] = (self._unset,
#                                          "Use the application default live stream metadata rate")
#         self.settings = settings
#         self.payment_rate_manager = payment_rate_manager
#
#     def _unset(self):
#         d = self._set_rate(None)
#         d.addCallback(lambda _: "Using the application default live stream metadata rate")
#         return True, d
#
#     def _set_rate(self, rate):
#         self.payment_rate_manager.min_live_blob_info_payment_rate = rate
#         return self.settings.save_server_crypt_info_payment_rate(rate)
#
#     def _get_current_status(self):
#         effective_rate = self.payment_rate_manager.get_effective_min_live_blob_info_payment_rate()
#         status = "The current server live stream metadata payment rate is "
#         if self.payment_rate_manager.get_min_blob_data_payment_rate() is None:
#             status += "set to use the application default, "
#             status += str(effective_rate)
#         else:
#             status += str(effective_rate)
#         return status
#
#
# class ModifyServerCryptInfoPaymentRateFactory(ControlHandlerFactory):
#     control_handler_class = ModifyServerCryptInfoPaymentRate


class DisableQueryHandler(CommandHandler):
    def __init__(self, console, query_handlers, query_handler, settings):
        CommandHandler.__init__(self, console)
        self.query_handlers = query_handlers
        self.query_handler = query_handler
        self.settings = settings

    def start(self):
        #assert line is None, "DisableQueryHandler should not be passed any arguments"
        self.query_handlers[self.query_handler] = False
        d = self.settings.disable_query_handler(self.query_handler.get_primary_query_identifier())
        d.addCallback(lambda _: self.console.sendLine("Disabled the query handler"))
        d.chainDeferred(self.finished_deferred)


class DisableQueryHandlerFactory(CommandHandlerFactory):
    control_handler_class = DisableQueryHandler

    def get_prompt_description(self):
        query_handler = self.args[1]
        return "Disable " + str(query_handler.get_description())


class EnableQueryHandler(CommandHandler):
    def __init__(self, console, query_handlers, query_handler, settings):
        CommandHandler.__init__(self, console)
        self.query_handlers = query_handlers
        self.query_handler = query_handler
        self.settings = settings

    def start(self):
        #assert line is None, "EnableQueryHandler should not be passed any arguments"
        self.query_handlers[self.query_handler] = True
        d = self.settings.enable_query_handler(self.query_handler.get_primary_query_identifier())
        d.addCallback(lambda _: self.console.sendLine("Enabled the query handler"))
        d.chainDeferred(self.finished_deferred)


class EnableQueryHandlerFactory(CommandHandlerFactory):
    control_handler_class = EnableQueryHandler

    def get_prompt_description(self):
        query_handler = self.args[1]
        return "Enable " + str(query_handler.get_description())


class ModifyServerEnabledQueries(RecursiveCommandHandler):
    prompt_description = "Modify which queries the server will respond to"

    def __init__(self, console, query_handlers, settings):
        self.query_handlers = query_handlers
        self.settings = settings
        RecursiveCommandHandler.__init__(self, console, reset_after_each_done=True)

    def _get_control_handler_factories(self):
        factories = []
        for query_handler, enabled in self.query_handlers.iteritems():
            if enabled:
                factories.append(DisableQueryHandlerFactory(self.query_handlers, query_handler, self.settings))
            else:
                factories.append(EnableQueryHandlerFactory(self.query_handlers, query_handler, self.settings))
        return factories


class ModifyServerEnabledQueriesFactory(CommandHandlerFactory):
    control_handler_class = ModifyServerEnabledQueries


class ImmediateAnnounceAllBlobs(CommandHandler):
    prompt_description = "Immediately announce all hashes to the DHT"

    def __init__(self, console, blob_manager):
        CommandHandler.__init__(self, console)
        self.blob_manager = blob_manager

    def start(self):
        #assert line is None, "Immediate Announce should not be passed any arguments"
        d = self.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: self.console.sendLine("Done announcing"))
        d.chainDeferred(self.finished_deferred)


class ImmediateAnnounceAllBlobsFactory(CommandHandlerFactory):
    control_handler_class = ImmediateAnnounceAllBlobs
    command = "announce-blobs"
    short_help = "Announce all blobs to the dht"
    full_help = "Immediately re-broadcast all hashes associated with the server to " \
                "the distributed hash table."


class ModifyServerSettings(RecursiveCommandHandler):
    #prompt_description = "Modify server settings"

    def __init__(self, console, lbry_service):
        self.lbry_service = lbry_service
        RecursiveCommandHandler.__init__(self, console, reset_after_each_done=True)

    def _get_control_handler_factories(self):
        factories = []
        if self.lbry_service.lbry_server_port is not None:
            factories.append(StopServerFactory(self.lbry_service))
        else:
            factories.append(StartServerFactory(self.lbry_service))
        factories.append(
            ModifyServerDataPaymentRateFactory(
                self.lbry_service.blob_request_payment_rate_manager,
                self.lbry_service.settings
            )
        )
        #factories.append(ModifyServerCryptInfoPaymentRateFactory(self.lbry_service._server_payment_rate_manager,
        #                                                         self.lbry_service.settings))
        factories.append(ModifyServerEnabledQueriesFactory(self.lbry_service.query_handlers,
                                                           self.lbry_service.settings))
        factories.append(ImmediateAnnounceAllBlobsFactory(self.lbry_service.session.blob_manager))
        return factories


class ModifyServerSettingsFactory(CommandHandlerFactory):
    control_handler_class = ModifyServerSettings
    command = "modify-server-settings"
    short_help = "Modify server settings"
    full_help = "Modify server settings. Settings that can be modified:\n\n" \
                "1) Queries that the server will answer from other peers. For example, " \
                "stop the server from responding to requests for metadata, or stop " \
                "the server from uploading data.\n" \
                "2) Change whether the server is running at all.\n" \
                "3) Change the minimum rate the server will accept for data uploads.\n" \
                "4) Immediately re-broadcast all hashes associated with the server to " \
                "the distributed hash table."


class PeerChooser(RecursiveCommandHandler):

    def __init__(self, console, peer_manager, factory_class, *args, **kwargs):
        """
        @param peer_manager:

        @param factory_class:

        @param args: all arguments that will be passed to the factory

        @param kwargs: all arguments that will be passed to the superclass' __init__

        @return:
        """
        self.peer_manager = peer_manager
        self.factory_class = factory_class
        self.args = args
        RecursiveCommandHandler.__init__(self, console, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for peer in self.peer_manager.peers:
            control_handler_factories.append(self.factory_class(peer, *self.args))
        return control_handler_factories


class PeerChooserFactory(CommandHandlerFactory):
    def get_prompt_description(self):
        peer = self.args[0]
        return str(peer)


class ShowPeerStats(CommandHandler):
    prompt_description = "Show the peer's stats"

    def __init__(self, console, peer):
        CommandHandler.__init__(self, console)
        self.peer = peer

    def start(self):
        self.console.sendLine(self._get_peer_stats_string())
        self.finished_deferred.callback(None)

    def _get_peer_stats_string(self):
        stats = "Statistics for " + str(self.peer) + '\n'
        stats += "  current_score: " + str(self.peer.score) + '\n'
        stats += "  is_available: " + str(self.peer.is_available()) + '\n'
        for stat_type, amount in self.peer.stats.iteritems():
            stats += "  " + stat_type + ": " + str(amount) + "\n"
        return stats


class ShowPeerStatsFactory(CommandHandlerFactory):
    control_handler_class = ShowPeerStats


class PeerStatsAndSettings(RecursiveCommandHandler):
    def __init__(self, console, peer):
        self.peer = peer
        RecursiveCommandHandler.__init__(self, console, reset_after_each_done=True)

    def _get_control_handler_factories(self):
        factories = []
        factories.append(ShowPeerStatsFactory(self.peer))
        return factories


class PeerStatsAndSettingsFactory(PeerChooserFactory):
    control_handler_class = PeerStatsAndSettings


class PeerStatsAndSettingsChooser(PeerChooser):
    #prompt_description = "View peer stats and modify peer settings"

    def __init__(self, console, peer_manager):
        PeerChooser.__init__(self, console, peer_manager, PeerStatsAndSettingsFactory)


class PeerStatsAndSettingsChooserFactory(CommandHandlerFactory):
    control_handler_class = PeerStatsAndSettingsChooser
    command = "peer-stats"
    short_help = "Show some peer statistics"
    full_help = "Show the list of peers that this application has been " \
                "in contact with. Give the option to show further details " \
                "for each peer including the number of bytes transferred " \
                "and the 'score' of the peer which is used in deciding " \
                "which peers to connect to."


class LBRYFileStatusModifier(CommandHandler):
    def __init__(self, console, lbry_file, stream_info_manager, blob_manager, lbry_file_manager):
        CommandHandler.__init__(self, console)
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.blob_manager = blob_manager
        self.lbry_file_manager = lbry_file_manager
        self.current_handler = None

    def start(self):
        d = self.lbry_file.status()
        d.addCallback(self._show_prompt)

    def handle_line(self, line):
        if self.current_handler is None:
            if line:
                if line.lower() == 'd':
                    self.current_handler = DeleteLBRYFile(self.console, self.lbry_file,
                                                          self.stream_info_manager, self.blob_manager,
                                                          self.lbry_file_manager)
                elif line.lower() == 't':
                    self.current_handler = ToggleLBRYFileRunning(self.console, self.lbry_file,
                                                                 self.lbry_file_manager)
                else:
                    self.console.sendLine("Invalid selection\n")
                    self.finished_deferred.callback(None)
                    return
            else:
                self.console.sendLine("")
                self.finished_deferred.callback(None)
                return
            try:
                self.current_handler.start()
            except Exception as e:
                self.console.sendLine("Operation failed. Error: %s\n" % str(e))
                import traceback
                log.error(traceback.format_exc())
                self.finished_deferred.callback(None)
                return
            self.current_handler.finished_deferred.chainDeferred(self.finished_deferred)
        else:
            try:
                self.current_handler.handle_line(line)
            except Exception as e:
                self.console.sendLine("Operation failed. Error: %s\n" % str(e))
                import traceback
                log.error(traceback.format_exc())
                self.finished_deferred.callback(None)

    def _show_prompt(self, status_report):
        self.console.sendLine("\n%s - %d chunks downloaded out of %d - %s" % (str(status_report.name),
                                                                              status_report.num_completed,
                                                                              status_report.num_known,
                                                                              str(status_report.running_status)))
        self.console.sendLine("\nTo delete this file, type 'd'. To toggle its running status, type 't'. "
                              "Then hit enter. To do nothing, just hit enter.")
        self.console.send("Choice: ")


class Status(CommandHandler):
    lbry_file_status_format = "[%d] %s - %s bytes - %s - %s - %s%% - %s"

    def __init__(self, console, lbry_service, rate_limiter, lbry_file_manager, blob_manager, wallet=None):
        CommandHandler.__init__(self, console)
        self.lbry_service = lbry_service
        self.rate_limiter = rate_limiter
        self.lbry_file_manager = lbry_file_manager
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.chosen_lbry_file = None
        self.current_handler = None

    def start(self):
        d = self._show_general_status()
        d.addCallback(lambda _: self._show_lbry_file_status())
        d.addCallback(lambda _: self._show_prompt())

    def handle_line(self, line):
        if self.current_handler is None:
            if line:
                try:
                    index = int(line)
                except ValueError:
                    self.console.sendLine("Choice must be a number.\n")
                    self.finished_deferred.callback(None)
                    return
                if index < 0 or index >= len(self.lbry_files):
                    self.console.sendLine("Invalid choice.\n")
                    self.finished_deferred.callback(None)
                    return
                self.current_handler = LBRYFileStatusModifier(self.console, self.lbry_files[index],
                                                              self.lbry_file_manager.stream_info_manager,
                                                              self.blob_manager, self.lbry_file_manager)
                try:
                    self.current_handler.start()
                except Exception as e:
                    self.console.sendLine("Selection failed. Error: %s\n" % str(e))
                    import traceback
                    log.error(traceback.format_exc())
                    self.finished_deferred.callback(None)
                    return
                self.current_handler.finished_deferred.chainDeferred(self.finished_deferred)
            else:
                self.console.sendLine("")
                self.finished_deferred.callback(None)
        else:
            try:
                self.current_handler.handle_line(line)
            except Exception as e:
                self.console.sendLine("Operation failed. Error: %s\n" % str(e))
                import traceback
                log.error(traceback.format_exc())
                self.finished_deferred.callback(None)

    def _show_general_status(self):
        #self.console.sendLine("Total bytes uploaded: %s" % str(self.rate_limiter.total_ul_bytes))
        #self.console.sendLine("Total bytes downloaded: %s" % str(self.rate_limiter.total_dl_bytes))
        #self.console.sendLine("Server running: %s" % str(self.lbry_service.lbry_server_port is not None))
        #self.console.sendLine("Server port: %s" % str(self.lbry_service.peer_port))
        return defer.succeed(True)

    def _get_name_and_validity_for_lbry_file(self, lbry_file):
        if self.wallet is None:
            return defer.succeed(None)
        d = self.lbry_file_manager.stream_info_manager.get_sd_blob_hashes_for_stream(lbry_file.stream_hash)
        d.addCallback(lambda sd_blob_hashes: self.wallet.get_name_and_validity_for_sd_hash(sd_blob_hashes[0]) if len(sd_blob_hashes) else None)
        return d

    def _show_lbry_file_status(self):
        self.lbry_files = self.lbry_file_manager.lbry_files
        status_ds = map(lambda lbry_file: lbry_file.status(), self.lbry_files)
        status_dl = defer.DeferredList(status_ds)

        size_ds = map(lambda lbry_file: lbry_file.get_total_bytes(), self.lbry_files)
        size_dl = defer.DeferredList(size_ds)

        name_validity_ds = map(self._get_name_and_validity_for_lbry_file, self.lbry_files)
        name_validity_dl = defer.DeferredList(name_validity_ds)

        dl = defer.DeferredList([status_dl, size_dl, name_validity_dl])

        def show_statuses(statuses):
            status_reports = statuses[0][1]
            sizes = statuses[1][1]
            name_validities = statuses[2][1]
            for i, (lbry_file, (succ1, status), (succ2, size), (succ3, name_validity)) in enumerate(zip(self.lbry_files, status_reports, sizes, name_validities)):
                percent_done = "unknown"
                name = lbry_file.file_name
                claimed_name = ""
                claimed_name_valid = ""
                if succ3 and name_validity:
                    validity = name_validity[1]
                    if validity == "valid":
                        claimed_name_valid = ""
                    else:
                        claimed_name_valid = "(" + validity + ")"
                    claimed_name = name_validity[0]
                total_bytes = "unknown"
                running_status = "unknown"
                if succ1:
                    percent_done = "0"
                    if status.num_known > 0:
                        percent = 100.0 * status.num_completed / status.num_known
                        percent_done = "%.2f" % percent
                    running_status = status.running_status
                if succ2:
                    total_bytes = "%d" % size
                self.console.sendLine(self.lbry_file_status_format % (i, str(name), total_bytes,
                                                                      str(claimed_name_valid),
                                                                      str(claimed_name),
                                                                      percent_done, str(running_status)))

        dl.addCallback(show_statuses)
        return dl

    def _show_prompt(self):
        self.console.sendLine("\n\nTo alter the status of any file shown above, type the number next to it "
                              "and then hit 'enter'. Otherwise, just hit 'enter'.")
        self.console.send("Choice: ")


class StatusFactory(CommandHandlerFactory):
    control_handler_class = Status
    priority = 20
    command = "status"
    short_help = "Show or alter status of files being downloaded"
    full_help = "Show or alter status of files being downloaded\n\n" \
                "Show the list of files that are currently downloading " \
                "or have been downloaded, and give the option to " \
                "toggle whether the file is actively downloading or " \
                "to remove the file."


# class AutoFetcherStart(CommandHandler):
#     def __init__(self, console, autofetcher):
#         CommandHandler.__init__(self, console)
#         self.autofetcher = autofetcher
#
#     def start(self):
#         self.autofetcher.start(self.console)
#         self.finished_deferred.callback(None)
#
#
# class AutoFetcherStop(CommandHandler):
#     def __init__(self, console, autofetcher):
#         CommandHandler.__init__(self, console)
#         self.autofetcher = autofetcher
#
#     def start(self):
#         self.autofetcher.stop(self.console)
#         self.finished_deferred.callback(None)
#
#
# class AutoFetcherStatus(CommandHandler):
#     def __init__(self, console, autofetcher):
#         CommandHandler.__init__(self, console)
#         self.autofetcher = autofetcher
#
#     def start(self):
#         self.autofetcher.check_if_running(self.console)
#         self.finished_deferred.callback(None)


# class AutoFetcherStartFactory(CommandHandlerFactory):
#     control_handler_class = AutoFetcherStart
#     command = "start-autofetcher"
#     short_help = "Start downloading all lbry files as they are published"
#
#
# class AutoFetcherStopFactory(CommandHandlerFactory):
#     control_handler_class = AutoFetcherStop
#     command = "stop-autofetcher"
#     short_help = "Stop downloading all lbry files as they are published"
#
#
# class AutoFetcherStatusFactory(CommandHandlerFactory):
#     control_handler_class = AutoFetcherStatus
#     command = "autofetcher-status"
#     short_help = "Check autofetcher status"


class BlockchainStatus(CommandHandler):
    def __init__(self, console, wallet=None):
        CommandHandler.__init__(self, console)
        self.wallet = wallet

    def start(self):
        d = self.wallet.get_most_recent_blocktime()
        d.addCallback(get_time_behind_blockchain)
        d.addCallbacks(self._show_time_behind_blockchain, self._show_error)
        d.chainDeferred(self.finished_deferred)
        return d

    def _show_time_behind_blockchain(self, rounded_time):
        if rounded_time.unit >= RoundedTime.HOUR:
            self.console.sendLine("This application is %s behind the LBC blockchain. It\n"
                                  "should only take a few minutes to catch up." % str(rounded_time))
        else:
            self.console.sendLine("This application is up to date with the LBC blockchain.")

    def _show_error(self, err):
        log.error(err.getTraceback())
        self.console.sendLine("Unable to determine the status of the blockchain.")


class BlockchainStatusFactory(CommandHandlerFactory):
    control_handler_class = BlockchainStatus
    command = "get-blockchain-status"
    short_help = "Show whether this application has caught up with the LBC blockchain"
    full_help = "Show whether this applications has caught up with the LBC blockchain"
