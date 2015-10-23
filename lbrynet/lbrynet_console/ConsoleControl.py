from twisted.protocols import basic
from twisted.internet import defer
import logging


log = logging.getLogger(__name__)


class ConsoleControl(basic.LineReceiver):
    from os import linesep as delimiter

    def __init__(self):
        self.connected = False
        self.buffer = []

    def start(self, command_handlers):
        self.command_handlers = {h.command: h for h in command_handlers}
        self.current_handler = None
        self.send_initial_prompt()
        return defer.succeed(True)

    def connectionMade(self):
        self.connected = True
        if self.buffer:
            self.send(self.buffer)
            self.buffer = []

    def send_initial_prompt(self):
        self.sendLine("")
        self.sendLine("Welcome to lbrynet-console!")
        self.sendLine("")
        self.sendLine("Enter a command. Try 'get wonderfullife' or 'help' to see more options.")
        self.show_prompt()

    def send(self, s):
        self.transport.write(s)

    def write(self, s):
        if self.connected is False:
            self.buffer.append(s)
        else:
            self.send(s)

    def flush(self):
        if self.connected is True and self.buffer:
            self.send(self.buffer)
            self.buffer = []

    def show_prompt(self):
        self.send("> ")

    def show_quick_help(self):
        self.sendLine("Available commands:")
        self.sendLine("")
        for command, handler in sorted(self.command_handlers.items(), key=lambda x: x[0]):
            if handler.is_main_command is True:
                self.sendLine(command + " - " + handler.short_help)
        self.sendLine("help-all - Show the full list of available commands")
        self.sendLine("")
        self.sendLine("For more information about any command type 'help <command>'")

    def show_full_help(self):
        self.sendLine("Available commands:")
        self.sendLine("")
        for command, handler in sorted(self.command_handlers.items(), key=lambda x: x[0]):
            self.sendLine(command + " - " + handler.short_help)
        self.sendLine("")
        self.sendLine("For more information about any command type 'help <command>'")

    def handler_done(self):
        self.current_handler = None
        self.show_prompt()

    def handler_failed(self, err):
        self.current_handler = None
        self.sendLine("An error occurred:")
        self.sendLine(err.getTraceback())
        self.show_prompt()

    def lineReceived(self, line):
        if self.current_handler is None:
            words = line.split()
            if len(words) == 0:
                self.show_prompt()
                return
            command, args = words[0], words[1:]
            if command == "help":
                if len(args) == 0:
                    self.show_quick_help()
                    self.show_prompt()
                    return
                if args[0] in self.command_handlers:
                    self.sendLine(self.command_handlers[args[0]].full_help)
                    self.show_prompt()
                    return
                if args[0] == "help-all":
                    self.sendLine("Show the full list of available commands!")
                    self.show_prompt()
                    return
                self.sendLine("Can't help you with '%s'. Sorry!" % args[0])
                self.show_prompt()
                return
            elif command == "help-all":
                self.show_full_help()
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
                self.current_handler = command_handler.get_handler(self)
            except:
                self.current_handler = None
                import traceback
                self.sendLine(traceback.format_exc())
                log.error(traceback.format_exc())
                self.show_prompt()
                return
            try:
                self.current_handler.start(*args)
            except TypeError:
                self.current_handler = None
                self.sendLine("Invalid arguments. Type 'help <command>' for the argument list.")
                import traceback
                log.error(traceback.format_exc())
                self.show_prompt()
                return
            except:
                self.current_handler = None
                import traceback
                self.sendLine(traceback.format_exc())
                log.error(traceback.format_exc())
                self.show_prompt()
                return
            self.current_handler.finished_deferred.addCallbacks(lambda _: self.handler_done(),
                                                                self.handler_failed)
        else:
            try:
                self.current_handler.handle_line(line)
            except Exception as e:
                self.current_handler = None
                import traceback
                self.sendLine(traceback.format_exc())
                log.error(traceback.format_exc())
                self.show_prompt()
                return