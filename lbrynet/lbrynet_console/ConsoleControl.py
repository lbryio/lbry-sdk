from twisted.protocols import basic
from twisted.internet import defer
import logging


log = logging.getLogger(__name__)


class ConsoleControl(basic.LineReceiver):
    from os import linesep as delimiter

    def __init__(self, control_handlers):
        self.control_handlers = {}
        self.categories = {}
        categories = set([category for category, handler in control_handlers])
        prompt_number = 0
        for category in categories:
            self.categories[prompt_number] = category
            for handler in [handler for cat, handler in control_handlers if cat == category]:
                self.control_handlers[prompt_number] = handler
                prompt_number += 1
        self.current_handler = None

    def connectionMade(self):
        self.show_prompt()

    def lineReceived(self, line):

        def show_response(response):
            if response is not None:
                self.sendLine(response)

        def show_error(err):
            self.sendLine(err.getErrorMessage())

        if self.current_handler is None:
            try:
                num = int(line)
            except ValueError:
                num = None
            if num in self.control_handlers:
                self.current_handler = self.control_handlers[num].get_handler()
                line = None
        if self.current_handler is not None:
            try:
                r = self.current_handler.handle_line(line)
                done, ds = r[0], [d for d in r[1:] if d is not None]
            except Exception as e:
                done = True
                ds = [defer.fail(e)]
            if done is True:
                self.current_handler = None
            map(lambda d: d.addCallbacks(show_response, show_error), ds)
        if self.current_handler is None:
            self.show_prompt()

    def show_prompt(self):
        self.sendLine("Options:")
        for num, handler in self.control_handlers.iteritems():
            if num in self.categories:
                self.sendLine("")
                self.sendLine(self.categories[num])
                self.sendLine("")
            self.sendLine("[" + str(num) + "] " + handler.get_prompt_description())


class ConsoleControl2(basic.LineReceiver):
    from os import linesep as delimiter

    def __init__(self, command_handlers):
        self.command_handlers = command_handlers
        self.current_handler = None

    def connectionMade(self):
        self.sendLine("Enter a command. Try 'get wonderfullife' or 'help' to see more options.")
        self.show_prompt()

    def send(self, s):
        self.transport.write(s)

    def show_prompt(self):
        self.send(">")

    def show_help_overview(self):
        self.sendLine("Available commands:")
        self.sendLine("")
        for command, handler in sorted(self.command_handlers.items(), key=lambda x: x[0]):
            self.sendLine(command + " - " + handler.short_help)
        self.sendLine("")
        self.sendLine("For more information about any command type 'help <command>'")

    def handler_done(self):
        self.current_handler = None
        self.show_prompt()

    def lineReceived(self, line):
        if self.current_handler is None:
            words = line.split()
            command, args = words[0], words[1:]
            if command == "help":
                if len(args) == 0:
                    self.show_help_overview()
                    self.show_prompt()
                    return
                if args[0] in self.command_handlers:
                    self.sendLine(self.command_handlers[args[0]].full_help)
                    self.show_prompt()
                    return
            if command in self.command_handlers:
                command_handler = self.command_handlers[command]
            else:
                candidates = [k for k in self.command_handlers.keys() if k.startswith(command)]
                if len(candidates) == 0:
                    self.sendLine("Unknown command. Type 'help' for a list of commands.")
                    self.show_prompt()
                    return
                if len(candidates) >= 2:
                    l = "Ambiguous command. Matches: "
                    for candidate in candidates:
                        l += candidate
                        l += ", "
                    l = l[:-2]
                    l += l
                    self.sendLine(l)
                    self.show_prompt()
                    return
                else:
                    command_handler = self.command_handlers[candidates[0]]
            try:
                self.current_handler = command_handler.get_handler(self, *args)
            except Exception as e:
                self.current_handler = None
                import traceback
                self.sendline(traceback.format_exc())
                log.error(traceback.format_exc())
                self.show_prompt()
                return
            self.current_handler.finished_deferred.addCallback(lambda _: self.handler_done())
        else:
            try:
                self.current_handler.handle_line(line)
            except Exception as e:
                self.current_handler = None
                import traceback
                self.sendline(traceback.format_exc())
                log.error(traceback.format_exc())
                self.show_prompt()
                return