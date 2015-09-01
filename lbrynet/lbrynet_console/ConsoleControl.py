from twisted.protocols import basic
from twisted.internet import defer


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