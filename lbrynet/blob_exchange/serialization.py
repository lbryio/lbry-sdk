import typing


class BlobMessage:
    key = ''

    def to_dict(self) -> typing.Dict:
        raise NotImplementedError()


class BlobPriceRequest(BlobMessage):
    key = 'blob_data_payment_rate'

    def __init__(self, blob_data_payment_rate: float):
        self.blob_data_payment_rate = blob_data_payment_rate

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.blob_data_payment_rate
        }


class BlobPriceResponse(BlobMessage):
    key = 'blob_data_payment_rate'

    def __init__(self, blob_data_payment_rate: str):
        assert blob_data_payment_rate in ('RATE_ACCEPTED', 'RATE_TOO_LOW')
        self.blob_data_payment_rate = blob_data_payment_rate

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.blob_data_payment_rate
        }


class BlobAvailabilityRequest(BlobMessage):
    key = 'requested_blobs'

    def __init__(self, requested_blobs: typing.List[str], lbrycrd_address: typing.Optional[bool] = True):
        assert len(requested_blobs)
        self.requested_blobs = requested_blobs
        self.lbrycrd_address = lbrycrd_address

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.requested_blobs,
            'lbrycrd_address': self.lbrycrd_address
        }


class BlobAvailabilityResponse(BlobMessage):
    key = 'available_blobs'

    def __init__(self, available_blobs: typing.List[str], lbrycrd_address: typing.Optional[str] = True):
        assert len(available_blobs)
        self.available_blobs = available_blobs
        self.lbrycrd_address = lbrycrd_address

    def to_dict(self) -> typing.Dict:
        d = {
            self.key: self.available_blobs
        }
        if self.lbrycrd_address:
            d['lbrycrd_address'] = self.lbrycrd_address
        return d


class BlobDownloadRequest(BlobMessage):
    key = 'requested_blob'

    def __init__(self, requested_blob: str):
        self.requested_blob = requested_blob

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.requested_blob
        }


class BlobDownloadResponse(BlobMessage):
    key = 'incoming_blob'

    def __init__(self, incoming_blob: typing.Dict):
        self.incoming_blob = incoming_blob
        assert set(incoming_blob.keys()) == {'blob_hash', 'length'}
        self.length = self.incoming_blob['length']
        self.blob_hash = self.incoming_blob['blob_hash']

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.incoming_blob,
        }


class BlobErrorResponse(BlobMessage):
    key = 'error'

    def __init__(self, error: str):
        self.error = error

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.error
        }


blob_request_types = typing.Union[BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest]
blob_response_types = typing.Union[BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse, BlobErrorResponse]


def decode_response(response: typing.Dict) -> blob_response_types:
    for response_type in (BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse, BlobErrorResponse):
        if response_type.key in response:
            return response_type(**response)
    raise ValueError("failed to decode response")


def decode_request(request: typing.Dict) -> blob_request_types:
    for request_type in (BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest):
        if request_type.key in request:
            return request_type(**request)
    raise ValueError("failed to decode response")
