from lbrynet.conf import BLOB_SIZE


class ClientRequest(object):
    def __init__(self, request_dict, response_identifier=None):
        self.request_dict = request_dict
        self.response_identifier = response_identifier


class ClientPaidRequest(ClientRequest):
    def __init__(self, request_dict, response_identifier, max_pay_units):
        ClientRequest.__init__(self, request_dict, response_identifier)
        self.max_pay_units = max_pay_units


class ClientBlobRequest(ClientPaidRequest):
    def __init__(self, request_dict, response_identifier, write_func, finished_deferred,
                 cancel_func, blob):
        if blob.length is None:
            max_pay_units = BLOB_SIZE
        else:
            max_pay_units = blob.length
        ClientPaidRequest.__init__(self, request_dict, response_identifier, max_pay_units)
        self.write = write_func
        self.finished_deferred = finished_deferred
        self.cancel = cancel_func
        self.blob = blob