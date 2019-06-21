import typing
import json
import logging

log = logging.getLogger(__name__)


class BlobMessage:
    key = ''

    def to_dict(self) -> typing.Dict:
        raise NotImplementedError()


class BlobPriceRequest(BlobMessage):
    key = 'blob_data_payment_rate'

    def __init__(self, blob_data_payment_rate: float, **kwargs) -> None:
        self.blob_data_payment_rate = blob_data_payment_rate

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.blob_data_payment_rate
        }


class BlobPriceResponse(BlobMessage):
    key = 'blob_data_payment_rate'
    rate_accepted = 'RATE_ACCEPTED'
    rate_too_low = 'RATE_TOO_LOW'
    rate_unset = 'RATE_UNSET'

    def __init__(self, blob_data_payment_rate: str, **kwargs) -> None:
        if blob_data_payment_rate not in (self.rate_accepted, self.rate_too_low, self.rate_unset):
            raise ValueError(blob_data_payment_rate)
        self.blob_data_payment_rate = blob_data_payment_rate

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.blob_data_payment_rate
        }


class BlobAvailabilityRequest(BlobMessage):
    key = 'requested_blobs'

    def __init__(self, requested_blobs: typing.List[str], lbrycrd_address: typing.Optional[bool] = True,
                 **kwargs) -> None:
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

    def __init__(self, available_blobs: typing.List[str], lbrycrd_address: typing.Optional[str] = True,
                 **kwargs) -> None:
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

    def __init__(self, requested_blob: str, **kwargs) -> None:
        self.requested_blob = requested_blob

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.requested_blob
        }


class BlobDownloadResponse(BlobMessage):
    key = 'incoming_blob'

    def __init__(self, **response: typing.Dict) -> None:
        incoming_blob = response[self.key]
        self.error = None
        self.incoming_blob = None
        if 'error' in incoming_blob:
            self.error = incoming_blob['error']
        else:
            self.incoming_blob = {'blob_hash': incoming_blob['blob_hash'], 'length': incoming_blob['length']}
        self.length = None if not self.incoming_blob else self.incoming_blob['length']
        self.blob_hash = None if not self.incoming_blob else self.incoming_blob['blob_hash']

    def to_dict(self) -> typing.Dict:
        return {
            self.key if not self.error else 'error': self.incoming_blob or self.error,
        }


class BlobPaymentAddressRequest(BlobMessage):
    key = 'lbrycrd_address'

    def __init__(self, lbrycrd_address: str, **kwargs) -> None:
        self.lbrycrd_address = lbrycrd_address

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.lbrycrd_address
        }


class BlobPaymentAddressResponse(BlobPaymentAddressRequest):
    pass


class BlobErrorResponse(BlobMessage):
    key = 'error'

    def __init__(self, error: str, **kwargs) -> None:
        self.error = error

    def to_dict(self) -> typing.Dict:
        return {
            self.key: self.error
        }


blob_request_types = typing.Union[BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest,
                                  BlobPaymentAddressRequest]
blob_response_types = typing.Union[BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse,
                                   BlobErrorResponse, BlobPaymentAddressResponse]


def _parse_blob_response(response_msg: bytes) -> typing.Tuple[typing.Optional[typing.Dict], bytes]:
    # scenarios:
    #   <json>
    #   <blob bytes>
    #   <json><blob bytes>

    curr_pos = 0
    while True:
        next_close_paren = response_msg.find(b'}', curr_pos)
        if next_close_paren == -1:
            return None, response_msg
        curr_pos = next_close_paren + 1
        try:
            response = json.loads(response_msg[:curr_pos])
        except ValueError:
            continue
        possible_response_keys = {
                    BlobPaymentAddressResponse.key,
                    BlobAvailabilityResponse.key,
                    BlobPriceResponse.key,
                    BlobDownloadResponse.key
        }
        if isinstance(response, dict) and response.keys():
            if set(response.keys()).issubset(possible_response_keys):
                return response, response_msg[curr_pos:]
        return None, response_msg


class BlobRequest:
    def __init__(self, requests: typing.List[blob_request_types]) -> None:
        self.requests = requests

    def to_dict(self):
        d = {}
        for request in self.requests:
            d.update(request.to_dict())
        return d

    def _get_request(self, request_type: blob_request_types):
        request = tuple(filter(lambda r: type(r) == request_type, self.requests))
        if request:
            return request[0]

    def get_availability_request(self) -> typing.Optional[BlobAvailabilityRequest]:
        response = self._get_request(BlobAvailabilityRequest)
        if response:
            return response

    def get_price_request(self) -> typing.Optional[BlobPriceRequest]:
        response = self._get_request(BlobPriceRequest)
        if response:
            return response

    def get_blob_request(self) -> typing.Optional[BlobDownloadRequest]:
        response = self._get_request(BlobDownloadRequest)
        if response:
            return response

    def get_address_request(self) -> typing.Optional[BlobPaymentAddressRequest]:
        response = self._get_request(BlobPaymentAddressRequest)
        if response:
            return response

    def serialize(self) -> bytes:
        return json.dumps(self.to_dict()).encode()

    @classmethod
    def deserialize(cls, data: bytes) -> 'BlobRequest':
        request = json.loads(data)
        return cls([
            request_type(**request)
            for request_type in (BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest,
                                 BlobPaymentAddressRequest)
            if request_type.key in request
        ])

    @classmethod
    def make_request_for_blob_hash(cls, blob_hash: str) -> 'BlobRequest':
        return cls(
            [BlobAvailabilityRequest([blob_hash]), BlobPriceRequest(0.0), BlobDownloadRequest(blob_hash)]
        )


class BlobResponse:
    def __init__(self, responses: typing.List[blob_response_types], blob_data: typing.Optional[bytes] = None) -> None:
        self.responses = responses
        self.blob_data = blob_data

    def to_dict(self):
        d = {}
        for response in self.responses:
            d.update(response.to_dict())
        return d

    def _get_response(self, response_type: blob_response_types):
        response = tuple(filter(lambda r: type(r) == response_type, self.responses))
        if response:
            return response[0]

    def get_error_response(self) -> typing.Optional[BlobErrorResponse]:
        error = self._get_response(BlobErrorResponse)
        if error:
            log.error(error)
            return error

    def get_availability_response(self) -> typing.Optional[BlobAvailabilityResponse]:
        response = self._get_response(BlobAvailabilityResponse)
        if response:
            return response

    def get_price_response(self) -> typing.Optional[BlobPriceResponse]:
        response = self._get_response(BlobPriceResponse)
        if response:
            return response

    def get_blob_response(self) -> typing.Optional[BlobDownloadResponse]:
        response = self._get_response(BlobDownloadResponse)
        if response:
            return response

    def get_address_response(self) -> typing.Optional[BlobPaymentAddressResponse]:
        response = self._get_response(BlobPaymentAddressResponse)
        if response:
            return response

    def serialize(self) -> bytes:
        return json.dumps(self.to_dict()).encode()

    @classmethod
    def deserialize(cls, data: bytes) -> 'BlobResponse':
        response, extra = _parse_blob_response(data)
        requests = []
        if response:
            requests.extend([
                response_type(**response)
                for response_type in (BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse,
                                      BlobErrorResponse, BlobPaymentAddressResponse)
                if response_type.key in response
            ])
        return cls(requests, extra)

