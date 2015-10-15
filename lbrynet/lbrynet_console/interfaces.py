from zope.interface import Interface


class IControlHandlerFactory(Interface):
    def get_prompt_description(self):
        pass

    def get_handler(self):
        pass


class IControlHandler(Interface):
    def handle_line(self, line):
        pass


class ICommandHandlerFactory(Interface):
    def get_handler(self):
        pass


class ICommandHandler(Interface):
    def handle_line(self, line):
        pass