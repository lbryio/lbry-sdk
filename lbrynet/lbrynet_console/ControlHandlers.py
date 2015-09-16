import logging
from zope.interface import implements
from lbrynet.core.StreamDescriptor import PlainStreamDescriptorWriter, BlobStreamDescriptorWriter
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.lbryfilemanager.LBRYFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from lbrynet.lbrynet_console.interfaces import IControlHandler, IControlHandlerFactory
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.core.Error import UnknownNameError, InvalidBlobHashError
from twisted.internet import defer


log = logging.getLogger(__name__)


class InvalidChoiceError(Exception):
    pass


class InvalidValueError(Exception):
    pass


class ControlHandlerFactory(object):
    implements(IControlHandlerFactory)

    control_handler_class = None

    def get_prompt_description(self):
        return self.control_handler_class.prompt_description

    def __init__(self, *args):
        self.args = args

    def get_handler(self):
        args = self.args
        return self.control_handler_class(*args)


class ControlHandler(object):
    implements(IControlHandler)

    prompt_description = None


class RecursiveControlHandler(ControlHandler):

    def __init__(self, exit_after_one_done=False, reset_after_each_done=False):
        self.current_handler = None
        self.exit_after_one_done = exit_after_one_done
        self.reset_after_each_done = reset_after_each_done
        self._set_control_handlers()

    def _get_control_handler_factories(self):
        pass

    def _set_control_handlers(self):
        self.control_handlers = {i + 1: handler for i, handler in enumerate(self._get_control_handler_factories())}

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
                return True, None
            if num in self.control_handlers:
                self.current_handler = self.control_handlers[num].get_handler()
                line = None
        ds = []
        if self.current_handler is not None:
            r = self.current_handler.handle_line(line)
            done, ds = r[0], list(r[1:])
            if done is True:
                self.current_handler = None
                if self.exit_after_one_done is True:
                    return r
                if self.reset_after_each_done:
                    self._set_control_handlers()
        if self.current_handler is None:
            ds += [self.get_prompt()]
        return (False,) + tuple(ds)

    def get_prompt(self):
        prompt_string = "Options:\n"
        prompt_string += "[0] Exit this menu\n"
        for num, handler in self.control_handlers.iteritems():
            prompt_string += "[" + str(num) + "] " + handler.get_prompt_description() + "\n"
        return defer.succeed(prompt_string)


class ModifyPaymentRate(ControlHandler):

    def __init__(self):
        self._prompt_choices = {'cancel': (self._cancel, "Don't change anything")}

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self._get_prompt_string())
        elif line.lower() in self._prompt_choices:
            return self._prompt_choices[line.lower()][0]()
        else:
            try:
                rate = float(line)
            except ValueError:
                return True, defer.succeed("Rate must be a number")
            d = self._set_rate(rate)
            d.addCallback(lambda _: "Successfully set the rate")
            return True, d

    def _cancel(self):
        return True, defer.succeed("No change was made")

    def _set_rate(self, rate):
        pass

    def _get_current_status(self):
        pass

    def _get_prompt_string(self):
        prompt_string = self._get_current_status() + "\n"
        for prompt_choice, (func, help_string) in self._prompt_choices.iteritems():
            prompt_string += prompt_choice + ": " + help_string + "\n"
        prompt_string += "To change the current rate, enter the desired rate\n"
        prompt_string += "Then hit enter\n"
        return prompt_string


class ApplicationStatus(ControlHandler):
    prompt_description = "Application Status"

    def __init__(self, rate_limiter, dht_node):
        self.rate_limiter = rate_limiter
        self.dht_node = dht_node

    def handle_line(self, line):
        assert line is None, "Application status should not be passed any arguments"
        status = "Total bytes uploaded: " + str(self.rate_limiter.total_ul_bytes) + "\n"
        status += "Total bytes downloaded: " + str(self.rate_limiter.total_dl_bytes) + "\n"
        if self.dht_node is not None:
            status += "Approximate number of nodes in DHT: " + str(self.dht_node.getApproximateTotalDHTNodes()) + "\n"
            status += "Approximate number of blobs in DHT: " + str(self.dht_node.getApproximateTotalHashes()) + "\n"
        return True, defer.succeed(status)


class ApplicationStatusFactory(ControlHandlerFactory):
    control_handler_class = ApplicationStatus


class GetWalletBalances(ControlHandler):
    prompt_description = "Show wallet point balances"

    def __init__(self, wallet):
        self.wallet = wallet

    def handle_line(self, line):
        assert line is None, "Show wallet balances should not be passed any arguments"
        return True, self._get_wallet_balances()

    def _get_wallet_balances(self):
        d = self.wallet.get_balance()

        def format_balance(balance):
            if balance == 0:
                balance = 0
            balance_string = "balance: " + str(balance) + " LBC\n"
            return balance_string

        d.addCallback(format_balance)
        return d


class GetWalletBalancesFactory(ControlHandlerFactory):
    control_handler_class = GetWalletBalances


class ShutDown(ControlHandler):
    prompt_description = "Shut down"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service

    def handle_line(self, line):
        assert line is None, "Shut down should not be passed any arguments"
        return True, self._shut_down()

    def _shut_down(self):
        d = self.lbry_service.shut_down()

        def stop_reactor():
            from twisted.internet import reactor
            reactor.stop()

        d.addBoth(lambda _: stop_reactor())

        d.addCallback(lambda _: "Shut down successfully")
        return d


class ShutDownFactory(ControlHandlerFactory):
    control_handler_class = ShutDown


class LBRYFileStatus(ControlHandler):
    prompt_description = "Print status information for all LBRY Files"

    def __init__(self, lbry_file_manager):
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        assert line is None, "print status should not be passed any arguments"
        d = self.lbry_file_manager.get_lbry_file_status_reports()
        d.addCallback(self.format_statuses)
        return True, d

    def format_statuses(self, status_reports):
        status_strings = []
        for status_report in status_reports:
            s = status_report.name + " status: " + status_report.running_status + "\n"
            s += str(status_report.num_completed) + " completed out of " + str(status_report.num_known) + "\n"
            status_strings.append(s)
        return ''.join(status_strings)


class LBRYFileStatusFactory(ControlHandlerFactory):
    control_handler_class = LBRYFileStatus


class AddStream(ControlHandler):
    prompt_description = None
    line_prompt = None
    cancel_prompt = "Trying to locate the stream's metadata. Type \"cancel\" to cancel..."
    canceled_message = "Canceled locating the stream descriptor"
    line_prompt2 = "Modify options? (y/n)"
    line_prompt3 = "Start download? (y/n)"

    def __init__(self, sd_identifier, base_payment_rate_manager):
        self.sd_identifier = sd_identifier
        self.loading_info_and_factories_deferred = None
        self.factories = None
        self.factory = None
        self.info_validator = None
        self.options = None
        self.options_left = []
        self.options_chosen = []
        self.current_option = None
        self.current_choice = None
        self.downloader = None
        self.got_options_response = False
        self.loading_failed = False
        self.payment_rate_manager = PaymentRateManager(base_payment_rate_manager)

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        if self.loading_failed is True:
            return True, None
        if self.loading_info_and_factories_deferred is not None:
            if line.lower() == "cancel":
                self.loading_info_and_factories_deferred.cancel()
                self.loading_info_and_factories_deferred = None
                return True, None
            else:
                return False, defer.succeed(self.cancel_prompt)
        if self.factories is None:
            self.loading_info_and_factories_deferred = self._load_info_and_factories(line)
            cancel_prompt_d = defer.succeed(self.cancel_prompt)
            self.loading_info_and_factories_deferred.addCallback(self._choose_factory)
            self.loading_info_and_factories_deferred.addErrback(self._handle_load_canceled)
            self.loading_info_and_factories_deferred.addErrback(self._handle_load_failed)
            return False, cancel_prompt_d, self.loading_info_and_factories_deferred
        if self.factory is None:
            try:
                choice = int(line)
            except ValueError:
                return False, defer.succeed(self._show_factory_choices())
            if choice in xrange(len(self.factories)):
                self.factory = self.factories[choice]
                return False, defer.succeed(self._show_info_and_options())
            else:
                return False, defer.succeed(self._show_factory_choices())
        if self.got_options_response is False:
            self.got_options_response = True
            if line == 'y' or line == 'Y' and self.options_left:
                return False, defer.succeed(self._get_next_option_prompt())
            else:
                self.options_chosen = [option.default_value for option in self.options_left]
                self.options_left = []
                return False, defer.succeed(self.line_prompt3)
        if self.current_option is not None:
            if self.current_choice is None:
                try:
                    self.current_choice = self._get_choice_from_input(line)
                except InvalidChoiceError:
                    return False, defer.succeed(self._get_next_option_prompt(invalid_choice=True))
                choice = self.current_option.option_types[self.current_choice]
                if choice.value == float or choice.value == bool:
                    return False, defer.succeed(self._get_choice_value_prompt())
                else:
                    value = choice.value
            else:
                try:
                    value = self._get_value_for_choice(line)
                except InvalidValueError:
                    return False, defer.succeed(self._get_choice_value_prompt(invalid_value=True))
            self.options_chosen.append(value)
            self.current_choice = None
            self.current_option = None
            self.options_left = self.options_left[1:]
            if self.options_left:
                return False, defer.succeed(self._get_next_option_prompt())
            else:
                self.current_option = None
                return False, defer.succeed(self.line_prompt3)
        if line == 'y' or line == 'Y':
            d = self._start_download()
        else:
            d = defer.succeed("Download cancelled")
        return True, d

    def _get_choice_from_input(self, line):
        try:
            choice_num = int(line)
        except ValueError:
            raise InvalidChoiceError()
        if 0 <= choice_num < len(self.current_option.option_types):
            return choice_num
        raise InvalidChoiceError()

    def _load_info_and_factories(self, sd_file):
        return defer.fail(NotImplementedError())

    def _handle_load_canceled(self, err):
        err.trap(defer.CancelledError)
        return defer.succeed(self.canceled_message)

    def _handle_load_failed(self, err):
        self.loading_failed = True
        log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback())
        return defer.succeed("An unexpected error occurred attempting to load the stream's metadata.\n"
                             "See console.log for further details.\n\n"
                             "Press enter to continue" % err.getErrorMessage())

    def _choose_factory(self, info_and_factories):
        self.loading_info_and_factories_deferred = None
        self.info_validator, self.options, self.factories = info_and_factories
        if len(self.factories) == 1:
            self.factory = self.factories[0]
            return self._show_info_and_options()
        return self._show_factory_choices()

    def _show_factory_choices(self):
        prompt = "Choose what to do with the file:\n"
        for i, factory in enumerate(self.factories):
            prompt += "[" + str(i) + "] " + factory.get_description() + '\n'
        return str(prompt)

    def _show_info_and_options(self):
        self.options_left = self.options.get_downloader_options(self.info_validator,
                                                                self.payment_rate_manager)
        prompt = "Stream info:\n"
        for info_line in self.info_validator.info_to_show():
            prompt += info_line[0] + ": " + info_line[1] + "\n"
        prompt += "\nOptions:\n"
        for option in self.options_left:
            prompt += option.long_description + ": " + str(option.default_value_description) + "\n"
        prompt += "\nModify options? (y/n)"
        return str(prompt)

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

    def _get_value_for_choice(self, input):
        choice = self.current_option.option_types[self.current_choice]
        if choice.value == float:
            try:
                return float(input)
            except ValueError:
                raise InvalidValueError()
        elif choice.value == bool:
            if input == "0":
                return True
            elif input == "1":
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
        return d

    def _make_downloader(self):
        return self.factory.make_downloader(self.info_validator, self.options_chosen,
                                            self.payment_rate_manager)


class AddStreamFromSD(AddStream):
    prompt_description = "Add a stream from a stream descriptor file"
    line_prompt = "Stream descriptor file name:"

    def _load_info_and_factories(self, sd_file):
        return self.sd_identifier.get_info_and_factories_for_sd_file(sd_file)


class AddStreamFromSDFactory(ControlHandlerFactory):
    control_handler_class = AddStreamFromSD


class AddStreamFromHash(AddStream):
    prompt_description = "Add a stream from a hash"
    line_prompt = "Stream descriptor hash:"

    def __init__(self, sd_identifier, session):
        AddStream.__init__(self, sd_identifier, session.base_payment_rate_manager)
        self.session = session

    def _load_info_and_factories(self, sd_hash):
        d = download_sd_blob(self.session, sd_hash, self.payment_rate_manager)
        d.addCallback(self.sd_identifier.get_info_and_factories_for_sd_blob)
        return d

    def _handle_load_failed(self, err):
        err.trap(InvalidBlobHashError)
        self.loading_failed = True
        return defer.succeed("The hash you entered is invalid. It must be 96 characters long and "
                             "contain only hex characters.\n\nPress enter to continue")


class AddStreamFromHashFactory(ControlHandlerFactory):
    control_handler_class = AddStreamFromHash


class AddStreamFromLBRYcrdName(AddStreamFromHash):
    prompt_description = "Add a stream from a short name"
    line_prompt = "Short name:"

    def __init__(self, sd_identifier, session, name_resolver):
        AddStreamFromHash.__init__(self, sd_identifier, session)
        self.name_resolver = name_resolver

    def _load_info_and_factories(self, name):
        d = self._resolve_name(name)
        d.addCallback(lambda stream_hash: AddStreamFromHash._load_info_and_factories(self, stream_hash))
        return d

    def _resolve_name(self, name):
        def get_name_from_info(stream_info):
            return stream_info['stream_hash']
        d = self.name_resolver.get_stream_info_for_name(name)
        d.addCallback(get_name_from_info)
        return d

    def _handle_load_failed(self, err):
        err.trap(UnknownNameError, InvalidBlobHashError)
        self.loading_failed = True
        if err.check(UnknownNameError):
            return defer.succeed("The name %s could not be found.\n\n"
                                 "Press enter to continue" % err.getErrorMessage())
        else:
            return defer.succeed("The metadata for this name is invalid. The stream cannot be downloaded.\n\n" +
                                 "Press enter to continue")


class AddStreamFromLBRYcrdNameFactory(ControlHandlerFactory):
    control_handler_class = AddStreamFromLBRYcrdName


class LBRYFileChooser(RecursiveControlHandler):

    def __init__(self, lbry_file_manager, factory_class, *args, **kwargs):
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
        RecursiveControlHandler.__init__(self, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for lbry_file in self.lbry_file_manager.lbry_files:
            control_handler_factories.append(self.factory_class(lbry_file, *self.args))
        return control_handler_factories


class LBRYFileChooserFactory(ControlHandlerFactory):
    def get_prompt_description(self):
        lbry_file = self.args[0]
        return lbry_file.file_name


class DeleteLBRYFileChooser(LBRYFileChooser):
    prompt_description = "Delete LBRY File"

    def __init__(self, stream_info_manager, blob_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, DeleteLBRYFileFactory, stream_info_manager,
                                 blob_manager, lbry_file_manager, exit_after_one_done=True)


class DeleteLBRYFileChooserFactory(ControlHandlerFactory):
    control_handler_class = DeleteLBRYFileChooser


class DeleteLBRYFile(ControlHandler):
    prompt_description = "Delete LBRY File"
    line_prompt = "Also delete data? (y/n):"

    def __init__(self, lbry_file, stream_info_manager, blob_manager, lbry_file_manager):
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.blob_manager = blob_manager
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        delete_data = False
        if line == 'y' or line == 'Y':
            delete_data = True
        d = self._delete_lbry_file(delete_data)
        d.addCallback(lambda _: "Successfully deleted " + str(self.lbry_file.stream_name))
        return True, d

    def _delete_lbry_file(self, delete_data):
        d = self.lbry_file_manager.delete_lbry_file(self.lbry_file.stream_hash)

        def finish_deletion():
            if delete_data is True:
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
    prompt_description = "Toggle whether an LBRY File is running"

    def __init__(self, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, ToggleLBRYFileRunningFactory, lbry_file_manager,
                                 exit_after_one_done=True)


class ToggleLBRYFileRunningChooserFactory(ControlHandlerFactory):
    control_handler_class = ToggleLBRYFileRunningChooser


class ToggleLBRYFileRunning(ControlHandler):
    prompt_description = "Toggle whether an LBRY File is running"

    def __init__(self, lbry_file, lbry_file_manager):
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        d = self.lbry_file_manager.toggle_lbry_file_running(self.lbry_file.stream_hash)
        return True, d


class ToggleLBRYFileRunningFactory(LBRYFileChooserFactory):
    control_handler_class = ToggleLBRYFileRunning


class CreateLBRYFile(ControlHandler):
    prompt_description = "Create an LBRY File from file"
    line_prompt = "File name: "

    def __init__(self, session, lbry_file_manager):
        self.session = session
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        else:
            d = create_lbry_file(self.session, self.lbry_file_manager, line, open(line))
            d.addCallback(self.add_to_lbry_files)
            d.addCallback(lambda _: "Successfully created " + str(line))
            return True, d

    def add_to_lbry_files(self, stream_hash):
        prm = PaymentRateManager(self.session.base_payment_rate_manager)
        d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        d.addCallback(lambda lbry_file_downloader: lbry_file_downloader.restore())
        return d


class CreateLBRYFileFactory(ControlHandlerFactory):
    control_handler_class = CreateLBRYFile


class PublishStreamDescriptorChooser(LBRYFileChooser):
    prompt_description = "Publish a stream descriptor file to the DHT for an LBRY File"

    def __init__(self, stream_info_manager, blob_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, PublishStreamDescriptorFactory, stream_info_manager,
                                 blob_manager, lbry_file_manager, exit_after_one_done=True)


class PublishStreamDescriptorChooserFactory(ControlHandlerFactory):
    control_handler_class = PublishStreamDescriptorChooser


class PublishStreamDescriptor(ControlHandler):
    prompt_description = "Publish a stream descriptor file to the DHT for an LBRY File"

    def __init__(self, lbry_file, stream_info_manager, blob_manager, lbry_file_manager):
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.blob_manager = blob_manager
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        return True, self._publish_sd_blob()

    def _publish_sd_blob(self):
        descriptor_writer = BlobStreamDescriptorWriter(self.blob_manager)

        d = get_sd_info(self.lbry_file_manager.stream_info_manager, self.lbry_file.stream_hash, True)
        d.addCallback(descriptor_writer.create_descriptor)

        def add_sd_blob_to_stream(sd_blob_hash):
            d = self.stream_info_manager.save_sd_blob_hash_to_stream(self.lbry_file.stream_hash, sd_blob_hash)
            d.addCallback(lambda _: sd_blob_hash)
            return d

        d.addCallback(add_sd_blob_to_stream)
        return d


class PublishStreamDescriptorFactory(LBRYFileChooserFactory):
    control_handler_class = PublishStreamDescriptor


class ShowPublishedSDHashesChooser(LBRYFileChooser):
    prompt_description = "Show published stream descriptors for an LBRY File"

    def __init__(self, stream_info_manager, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, ShowPublishedSDHashesFactory, stream_info_manager,
                                 lbry_file_manager)


class ShowPublishedSDHashesChooserFactory(ControlHandlerFactory):
    control_handler_class = ShowPublishedSDHashesChooser


class ShowPublishedSDHashes(ControlHandler):
    prompt_description = "Show published stream descriptors for an LBRY File"

    def __init__(self, lbry_file, stream_info_manager, lbry_file_manager):
        self.lbry_file = lbry_file
        self.stream_info_manager = stream_info_manager
        self.lbry_file_manager = lbry_file_manager

    def handle_line(self, line):
        return True, self._show_sd_hashes()

    def _show_sd_hashes(self):
        d = self.stream_info_manager.get_sd_blob_hashes_for_stream(self.lbry_file.stream_hash)

        def format_blob_hashes(sd_blob_hashes):
            return "\n".join([str(b) for b in sd_blob_hashes])

        d.addCallback(format_blob_hashes)
        return d


class ShowPublishedSDHashesFactory(LBRYFileChooserFactory):
    control_handler_class = ShowPublishedSDHashes


class CreatePlainStreamDescriptorChooser(LBRYFileChooser):
    prompt_description = "Create a plain stream descriptor file for an LBRY File"

    def __init__(self, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, CreatePlainStreamDescriptorFactory, lbry_file_manager,
                                 exit_after_one_done=True)


class CreatePlainStreamDescriptorChooserFactory(ControlHandlerFactory):
    control_handler_class = CreatePlainStreamDescriptorChooser


class CreatePlainStreamDescriptor(ControlHandler):
    prompt_description = "Create a plain stream descriptor file for an LBRY File"
    line_prompt = "Stream Descriptor file name (blank for default):"

    def __init__(self, lbry_file, lbry_file_manager):
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        self.sd_file_name = None

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        self.sd_file_name = line
        return True, self._create_sd()

    def _create_sd(self):
        if not self.sd_file_name:
            self.sd_file_name = None
        descriptor_writer = PlainStreamDescriptorWriter(self.sd_file_name)
        d = get_sd_info(self.lbry_file_manager.stream_info_manager, self.lbry_file.stream_hash, True)
        d.addCallback(descriptor_writer.create_descriptor)
        return d


class CreatePlainStreamDescriptorFactory(LBRYFileChooserFactory):
    control_handler_class = CreatePlainStreamDescriptor


class ShowLBRYFileStreamHashChooser(LBRYFileChooser):
    prompt_description = "Show an LBRY File's stream hash (not usually what you want)"

    def __init__(self, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, ShowLBRYFileStreamHashFactory)


class ShowLBRYFileStreamHashChooserFactory(ControlHandlerFactory):
    control_handler_class = ShowLBRYFileStreamHashChooser


class ShowLBRYFileStreamHash(ControlHandler):
    prompt_description = "Show an LBRY File's stream hash (not usually what you want)"

    def __init__(self, lbry_file):
        self.lbry_file = lbry_file

    def handle_line(self, line):
        return True, defer.succeed(str(self.lbry_file.stream_hash))


class ShowLBRYFileStreamHashFactory(LBRYFileChooserFactory):
    control_handler_class = ShowLBRYFileStreamHash


class ModifyLBRYFileDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify LBRY File data payment rate"

    def __init__(self, lbry_file, lbry_file_manager):
        ModifyPaymentRate.__init__(self)
        self._prompt_choices['unset'] = (self._unset, "Use the default LBRY file data rate")
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        self.payment_rate_manager = lbry_file.payment_rate_manager

    def _unset(self):
        d = self._set_rate(None)
        d.addCallback(lambda _: "Using the default LBRY file data rate")
        return True, d

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


class ModifyLBRYFileDataPaymentRateFactory(ControlHandlerFactory):
    control_handler_class = ModifyLBRYFileDataPaymentRate


class ModifyLBRYFileOptionsChooser(LBRYFileChooser):
    prompt_description = "Modify an LBRY File's options"

    def __init__(self, lbry_file_manager):
        LBRYFileChooser.__init__(self, lbry_file_manager, ModifyLBRYFileOptionsFactory, lbry_file_manager)


class ModifyLBRYFileOptionsChooserFactory(ControlHandlerFactory):
    control_handler_class = ModifyLBRYFileOptionsChooser


class ModifyLBRYFileOptions(RecursiveControlHandler):
    prompt_description = "Modify an LBRY File's options"

    def __init__(self, lbry_file, lbry_file_manager):
        self.lbry_file = lbry_file
        self.lbry_file_manager = lbry_file_manager
        RecursiveControlHandler.__init__(self)

    def _get_control_handler_factories(self):
        factories = []
        factories.append(ModifyLBRYFileDataPaymentRateFactory(self.lbry_file, self.lbry_file_manager))
        return factories


class ModifyLBRYFileOptionsFactory(LBRYFileChooserFactory):
    control_handler_class = ModifyLBRYFileOptions


class ClaimName(ControlHandler):
    prompt_description = "Associate a short name with a stream descriptor hash"
    line_prompt = "Stream descriptor hash:"
    line_prompt_2 = "Short name:"
    line_prompt_3 = "Amount:"

    def __init__(self, name_resolver):
        self.name_resolver = name_resolver
        self.sd_hash = None
        self.short_name = None
        self.amount = None

    def handle_line(self, line):
        if line is None:
            return False, defer.succeed(self.line_prompt)
        if self.sd_hash is None:
            self.sd_hash = line
            return False, defer.succeed(self.line_prompt_2)
        if self.short_name is None:
            self.short_name = line
            return False, defer.succeed(self.line_prompt_3)
        self.amount = line
        return True, self._claim_name()

    def _claim_name(self):
        return self.name_resolver.claim_name(self.sd_hash, self.short_name, float(self.amount))


class ClaimNameFactory(ControlHandlerFactory):
    control_handler_class = ClaimName


class ModifyDefaultDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify default data payment rate"

    def __init__(self, payment_rate_manager, settings):
        ModifyPaymentRate.__init__(self)
        self.settings = settings
        self.payment_rate_manager = payment_rate_manager

    def _set_rate(self, rate):
        self.payment_rate_manager.min_blob_data_payment_rate = rate
        return self.settings.save_default_data_payment_rate(rate)

    def _get_current_status(self):
        status = "The current default data payment rate is "
        status += str(self.payment_rate_manager.min_blob_data_payment_rate)
        return status


class ModifyDefaultDataPaymentRateFactory(ControlHandlerFactory):
    control_handler_class = ModifyDefaultDataPaymentRate


class ForceCheckBlobFileConsistency(ControlHandler):
    prompt_description = "Verify consistency of stored blobs"

    def __init__(self, blob_manager):
        self.blob_manager = blob_manager

    def handle_line(self, line):
        assert line is None, "Check consistency should not be passed any arguments"
        return True, self._check_consistency()

    def _check_consistency(self):
        d = self.blob_manager.check_consistency()
        d.addCallback(lambda _: "Finished checking stored blobs")
        return d


class ForceCheckBlobFileConsistencyFactory(ControlHandlerFactory):
    control_handler_class = ForceCheckBlobFileConsistency


class ModifyApplicationDefaults(RecursiveControlHandler):
    prompt_description = "Modify application settings"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service
        RecursiveControlHandler.__init__(self)

    def _get_control_handler_factories(self):
        return [ModifyDefaultDataPaymentRateFactory(self.lbry_service.session.base_payment_rate_manager,
                                                    self.lbry_service.settings),
                ForceCheckBlobFileConsistencyFactory(self.lbry_service.session.blob_manager)]


class ModifyApplicationDefaultsFactory(ControlHandlerFactory):
    control_handler_class = ModifyApplicationDefaults


class ShowServerStatus(ControlHandler):
    prompt_description = "Show the status of the server"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service

    def handle_line(self, line):
        assert line is None, "Show server status should not be passed any arguments"
        return True, self._get_status()

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
        return defer.succeed(status_string)


class ShowServerStatusFactory(ControlHandlerFactory):
    control_handler_class = ShowServerStatus


class StartServer(ControlHandler):
    prompt_description = "Start the server"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service

    def handle_line(self, line):
        assert line is None, "Start server should not be passed any arguments"
        d = self.lbry_service.start_server()
        d.addCallback(lambda _: self.lbry_service.settings.save_server_running_status(running=True))
        d.addCallback(lambda _: "Successfully started the server")
        return True, d


class StartServerFactory(ControlHandlerFactory):
    control_handler_class = StartServer


class StopServer(ControlHandler):
    prompt_description = "Stop the server"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service

    def handle_line(self, line):
        assert line is None, "Stop server should not be passed any arguments"
        d = self.lbry_service.stop_server()
        d.addCallback(lambda _: self.lbry_service.settings.save_server_running_status(running=False))
        d.addCallback(lambda _: "Successfully stopped the server")
        return True, d


class StopServerFactory(ControlHandlerFactory):
    control_handler_class = StopServer


class ModifyServerDataPaymentRate(ModifyPaymentRate):
    prompt_description = "Modify server data payment rate"

    def __init__(self, payment_rate_manager, settings):
        ModifyPaymentRate.__init__(self)
        self._prompt_choices['unset'] = (self._unset, "Use the application default data rate")
        self.settings = settings
        self.payment_rate_manager = payment_rate_manager

    def _unset(self):
        d = self._set_rate(None)
        d.addCallback(lambda _: "Using the application default data rate")
        return True, d

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


class ModifyServerDataPaymentRateFactory(ControlHandlerFactory):
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


class DisableQueryHandler(ControlHandler):
    def __init__(self, query_handlers, query_handler, settings):
        self.query_handlers = query_handlers
        self.query_handler = query_handler
        self.settings = settings

    def handle_line(self, line):
        assert line is None, "DisableQueryHandler should not be passed any arguments"
        self.query_handlers[self.query_handler] = False
        d = self.settings.disable_query_handler(self.query_handler.get_primary_query_identifier())
        d.addCallback(lambda _: "Disabled the query handler")
        return True, d


class DisableQueryHandlerFactory(ControlHandlerFactory):
    control_handler_class = DisableQueryHandler

    def get_prompt_description(self):
        query_handler = self.args[1]
        return "Disable " + str(query_handler.get_description())


class EnableQueryHandler(ControlHandler):
    def __init__(self, query_handlers, query_handler, settings):
        self.query_handlers = query_handlers
        self.query_handler = query_handler
        self.settings = settings

    def handle_line(self, line):
        assert line is None, "EnableQueryHandler should not be passed any arguments"
        self.query_handlers[self.query_handler] = True
        d = self.settings.enable_query_handler(self.query_handler.get_primary_query_identifier())
        d.addCallback(lambda _: "Enabled the query handler")
        return True, d


class EnableQueryHandlerFactory(ControlHandlerFactory):
    control_handler_class = EnableQueryHandler

    def get_prompt_description(self):
        query_handler = self.args[1]
        return "Enable " + str(query_handler.get_description())


class ModifyServerEnabledQueries(RecursiveControlHandler):
    prompt_description = "Modify which queries the server will respond to"

    def __init__(self, query_handlers, settings):
        self.query_handlers = query_handlers
        self.settings = settings
        RecursiveControlHandler.__init__(self, reset_after_each_done=True)

    def _get_control_handler_factories(self):
        factories = []
        for query_handler, enabled in self.query_handlers.iteritems():
            if enabled:
                factories.append(DisableQueryHandlerFactory(self.query_handlers, query_handler, self.settings))
            else:
                factories.append(EnableQueryHandlerFactory(self.query_handlers, query_handler, self.settings))
        return factories


class ModifyServerEnabledQueriesFactory(ControlHandlerFactory):
    control_handler_class = ModifyServerEnabledQueries


class ImmediateAnnounceAllBlobs(ControlHandler):
    prompt_description = "Immediately announce all blob hashes to the DHT"

    def __init__(self, blob_manager):
        self.blob_manager = blob_manager

    def handle_line(self, line):
        assert line is None, "Immediate Announce should not be passed any arguments"
        d = self.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: "Done announcing")
        return True, d


class ImmediateAnnounceAllBlobsFactory(ControlHandlerFactory):
    control_handler_class = ImmediateAnnounceAllBlobs


class ModifyServerSettings(RecursiveControlHandler):
    prompt_description = "Modify server settings"

    def __init__(self, lbry_service):
        self.lbry_service = lbry_service
        RecursiveControlHandler.__init__(self, reset_after_each_done=True)

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


class ModifyServerSettingsFactory(ControlHandlerFactory):
    control_handler_class = ModifyServerSettings


class PeerChooser(RecursiveControlHandler):

    def __init__(self, peer_manager, factory_class, *args, **kwargs):
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
        RecursiveControlHandler.__init__(self, **kwargs)

    def _get_control_handler_factories(self):
        control_handler_factories = []
        for peer in self.peer_manager.peers:
            control_handler_factories.append(self.factory_class(peer, *self.args))
        return control_handler_factories


class PeerChooserFactory(ControlHandlerFactory):
    def get_prompt_description(self):
        peer = self.args[0]
        return str(peer)


class ShowPeerStats(ControlHandler):
    prompt_description = "Show the peer's stats"

    def __init__(self, peer):
        self.peer = peer

    def handle_line(self, line):
        return True, defer.succeed(self._get_peer_stats_string())

    def _get_peer_stats_string(self):
        stats = "Statistics for " + str(self.peer) + '\n'
        stats += "  current_score: " + str(self.peer.score) + '\n'
        stats += "  is_available: " + str(self.peer.is_available()) + '\n'
        for stat_type, amount in self.peer.stats.iteritems():
            stats += "  " + stat_type + ": " + str(amount) + "\n"
        return stats


class ShowPeerStatsFactory(ControlHandlerFactory):
    control_handler_class = ShowPeerStats


class PeerStatsAndSettings(RecursiveControlHandler):
    def __init__(self, peer):
        self.peer = peer
        RecursiveControlHandler.__init__(self, reset_after_each_done=True)

    def _get_control_handler_factories(self):
        factories = []
        factories.append(ShowPeerStatsFactory(self.peer))
        return factories


class PeerStatsAndSettingsFactory(PeerChooserFactory):
    control_handler_class = PeerStatsAndSettings


class PeerStatsAndSettingsChooser(PeerChooser):
    prompt_description = "View peer stats and modify peer settings"

    def __init__(self, peer_manager):
        PeerChooser.__init__(self, peer_manager, PeerStatsAndSettingsFactory)


class PeerStatsAndSettingsChooserFactory(ControlHandlerFactory):
    control_handler_class = PeerStatsAndSettingsChooser