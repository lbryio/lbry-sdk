from lbrynet.blob.blob_file import MAX_BLOB_SIZE


class ClientRequest:
    def __init__(self, request_dict, response_identifier=None):
        self.request_dict = request_dict
        self.response_identifier = response_identifier


class ClientPaidRequest(ClientRequest):
    def __init__(self, request_dict, response_identifier, max_pay_units):
        super().__init__(request_dict, response_identifier)
        self.max_pay_units = max_pay_units


class ClientBlobRequest(ClientPaidRequest):
    def __init__(self, request_dict, response_identifier, write_func, finished_deferred,
                 cancel_func, blob):
        if blob.length is None:
            max_pay_units = MAX_BLOB_SIZE
        else:
            max_pay_units = blob.length
        super().__init__(request_dict, response_identifier, max_pay_units)
        self.write = write_func
        self.finished_deferred = finished_deferred
        self.cancel = cancel_func
        self.blob = blob
