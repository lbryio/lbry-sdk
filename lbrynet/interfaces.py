"""
Interfaces which are implemented by various classes within LBRYnet.
"""
from zope.interface import Interface


class IPeerFinder(Interface):
    """
    Used to find peers by sha384 hashes which they claim to be associated with.
    """
    def find_peers_for_blob(self, blob_hash):
        """
        Look for peers claiming to be associated with a sha384 hashsum.

        @param blob_hash: The sha384 hashsum to use to look up peers.
        @type blob_hash: string, hex encoded

        @return: a Deferred object which fires with a list of Peer objects
        @rtype: Deferred which fires with [Peer]
        """


class IRequestSender(Interface):
    """
    Used to connect to a peer, send requests to it, and return the responses to those requests.
    """
    def add_request(self, request):
        """
        Add a request to the next message that will be sent to the peer

        @param request: a request to be sent to the peer in the next message
        @type request: ClientRequest

        @return: Deferred object which will callback with the response to this request, a dict
        @rtype: Deferred which fires with dict
        """

    def add_blob_request(self, blob_request):
        """Add a request for a blob to the next message that will be sent to the peer.

        This will cause the protocol to call blob_request.write(data)
        for all incoming data, after the response message has been
        parsed out, until blob_request.finished_deferred fires.

        @param blob_request: the request for the blob
        @type blob_request: ClientBlobRequest

        @return: Deferred object which will callback with the response to this request
        @rtype: Deferred which fires with dict
        """


class IRequestCreator(Interface):
    """
    Send requests, via an IRequestSender, to peers.
    """

    def send_next_request(self, peer, protocol):
        """Create a Request object for the peer and then give the protocol that request.

        @param peer: the Peer object which the request will be sent to.
        @type peer: Peer

        @param protocol: the protocol to pass the request to.
        @type protocol: object which implements IRequestSender

        @return: Deferred object which will callback with True or
        False depending on whether a Request was sent
        @rtype: Deferred which fires with boolean
        """

    def get_new_peers(self):
        """
        Get some new peers which the request creator wants to send requests to.

        @return: Deferred object which will callback with [Peer]
        @rtype: Deferred which fires with [Peer]
        """


class IMetadataHandler(Interface):
    """
    Get metadata for the IDownloadManager.
    """
    def get_initial_blobs(self):
        """Return metadata about blobs that are known to be associated with
        the stream at the time that the stream is set up.

        @return: Deferred object which will call back with a list of BlobInfo objects
        @rtype: Deferred which fires with [BlobInfo]

        """

    def final_blob_num(self):
        """
        If the last blob in the stream is known, return its blob_num. Otherwise, return None.

        @return: integer representing the final blob num in the stream, or None
        @rtype: integer or None
        """


class IDownloadManager(Interface):
    """
    Manage the downloading of an associated group of blobs, referred to as a stream.

    These objects keep track of metadata about the stream, are responsible for starting and stopping
    other components, and handle communication between other components.
    """

    def start_downloading(self):
        """
        Load the initial metadata about the stream and then start the other components.

        @return: Deferred which fires when the other components have been started.
        @rtype: Deferred which fires with boolean
        """

    def resume_downloading(self):
        """
        Start the other components after they have been stopped.

        @return: Deferred which fires when the other components have been started.
        @rtype: Deferred which fires with boolean
        """

    def pause_downloading(self):
        """
        Stop the other components.

        @return: Deferred which fires when the other components have been stopped.
        @rtype: Deferred which fires with boolean
        """

    def add_blobs_to_download(self, blobs):
        """
        Add blobs to the list of blobs that should be downloaded

        @param blobs: list of BlobInfos that are associated with the stream being downloaded
        @type blobs: [BlobInfo]

        @return: DeferredList which fires with the result of adding each previously unknown BlobInfo
            to the list of known BlobInfos.
        @rtype: DeferredList which fires with [(boolean, Failure/None)]
        """

    def stream_position(self):
        """
        Returns the blob_num of the next blob needed in the stream.

        If the stream already has all of the blobs it needs, then this will return the blob_num
        of the last blob in the stream plus 1.

        @return: the blob_num of the next blob needed, or the last blob_num + 1.
        @rtype: integer
        """

    def needed_blobs(self):
        """Returns a list of BlobInfos representing all of the blobs that the
        stream still needs to download.

        @return: the list of BlobInfos representing blobs that the stream still needs to download.
        @rtype: [BlobInfo]

        """

    def final_blob_num(self):
        """
        If the last blob in the stream is known, return its blob_num. If not, return None.

        @return: The blob_num of the last blob in the stream, or None if it is unknown.
        @rtype: integer or None
        """

    def handle_blob(self, blob_num):
        """This function is called when the next blob in the stream is ready
        to be handled, whatever that may mean.

        @param blob_num: The blob_num of the blob that is ready to be handled.
        @type blob_num: integer

        @return: A Deferred which fires when the blob has been 'handled'
        @rtype: Deferred which can fire with anything

        """


class IConnectionManager(Interface):
    """
    Connects to peers so that IRequestCreators can send their requests.
    """
    def get_next_request(self, peer, protocol):
        """Ask all IRequestCreators belonging to this object to create a
        Request for peer and give it to protocol

        @param peer: the peer which the request will be sent to.
        @type peer: Peer

        @param protocol: the protocol which the request should be sent to by the IRequestCreator.
        @type protocol: IRequestSender

        @return: Deferred object which will callback with True or
            False depending on whether the IRequestSender should send
            the request or hang up
        @rtype: Deferred which fires with boolean

        """

    def protocol_disconnected(self, peer, protocol):
        """
        Inform the IConnectionManager that the protocol has been disconnected

        @param peer: The peer which the connection was to.
        @type peer: Peer

        @param protocol: The protocol which was disconnected.
        @type protocol: Protocol

        @return: None
        """


class IProgressManager(Interface):
    """Responsible for keeping track of the progress of the download.

    Specifically, it is their responsibility to decide which blobs
    need to be downloaded and keep track of the progress of the
    download

    """
    def stream_position(self):
        """
        Returns the blob_num of the next blob needed in the stream.

        If the stream already has all of the blobs it needs, then this will return the blob_num
        of the last blob in the stream plus 1.

        @return: the blob_num of the next blob needed, or the last blob_num + 1.
        @rtype: integer
        """

    def needed_blobs(self):
        """Returns a list of BlobInfos representing all of the blobs that the
        stream still needs to download.

        @return: the list of BlobInfos representing blobs that the stream still needs to download.
        @rtype: [BlobInfo]

        """

    def blob_downloaded(self, blob, blob_info):
        """
        Mark that a blob has been downloaded and does not need to be downloaded again

        @param blob: the blob that has been downloaded.
        @type blob: Blob

        @param blob_info: the metadata of the blob that has been downloaded.
        @type blob_info: BlobInfo

        @return: None
        """


class IBlobHandler(Interface):
    """
    Responsible for doing whatever should be done with blobs that have been downloaded.
    """
    def blob_downloaded(self, blob, blob_info):
        """
        Do whatever the downloader is supposed to do when a blob has been downloaded

        @param blob: The downloaded blob
        @type blob: Blob

        @param blob_info: The metadata of the downloaded blob
        @type blob_info: BlobInfo

        @return: A Deferred which fires when the blob has been handled.
        @rtype: Deferred which can fire with anything
        """


class IRateLimited(Interface):
    """
    Have the ability to be throttled (temporarily stopped).
    """
    def throttle_upload(self):
        """
        Stop uploading data until unthrottle_upload is called.

        @return: None
        """

    def throttle_download(self):
        """
        Stop downloading data until unthrottle_upload is called.

        @return: None
        """

    def unthrottle_upload(self):
        """
        Resume uploading data at will until throttle_upload is called.

        @return: None
        """

    def unthrottle_downlad(self):
        """
        Resume downloading data at will until throttle_download is called.

        @return: None
        """


class IRateLimiter(Interface):
    """
    Can keep track of download and upload rates and can throttle objects which implement the
    IRateLimited interface.
    """
    def report_dl_bytes(self, num_bytes):
        """
        Inform the IRateLimiter that num_bytes have been downloaded.

        @param num_bytes: the number of bytes that have been downloaded
        @type num_bytes: integer

        @return: None
        """

    def report_ul_bytes(self, num_bytes):
        """
        Inform the IRateLimiter that num_bytes have been uploaded.

        @param num_bytes: the number of bytes that have been uploaded
        @type num_bytes: integer

        @return: None
        """

    def register_protocol(self, protocol):
        """Register an IRateLimited object with the IRateLimiter so that the
        IRateLimiter can throttle it

        @param protocol: An object implementing the interface IRateLimited
        @type protocol: Object implementing IRateLimited

        @return: None

        """

    def unregister_protocol(self, protocol):
        """Unregister an IRateLimited object so that it won't be throttled any more.

        @param protocol: An object implementing the interface
            IRateLimited, which was previously registered with this
            IRateLimiter via "register_protocol"
        @type protocol: Object implementing IRateLimited

        @return: None

        """


class IRequestHandler(Interface):
    """
    Pass client queries on to IQueryHandlers
    """
    def register_query_handler(self, query_handler, query_identifiers):
        """Register a query handler, which will be passed any queries that
        match any of the identifiers in query_identifiers

        @param query_handler: the object which will handle queries
        matching the given query_identifiers
        @type query_handler: Object implementing IQueryHandler

        @param query_identifiers: A list of strings representing the query identifiers
            for queries that should be passed to this handler
        @type query_identifiers: [string]

        @return: None

        """

    def register_blob_sender(self, blob_sender):
        """
        Register a blob sender which will be called after the response has
        finished to see if it wants to send a blob

        @param blob_sender: the object which will upload the blob to the client.
        @type blob_sender: IBlobSender

        @return: None
        """


class IBlobSender(Interface):
    """
    Upload blobs to clients.
    """
    def send_blob_if_requested(self, consumer):
        """
        If a blob has been requested, write it to 'write' func of the consumer and then
        callback the returned deferred when it has all been written

        @param consumer: the object implementing IConsumer which the file will be written to
        @type consumer: object which implements IConsumer

        @return: Deferred which will fire when the blob sender is done, which will be
            immediately if no blob should be sent.
        @rtype: Deferred which fires with anything
        """


class IQueryHandler(Interface):
    """
    Respond to requests from clients.
    """
    def register_with_request_handler(self, request_handler, peer):
        """
        Register with the request handler to receive queries

        @param request_handler: the object implementing IRequestHandler to register with
        @type request_handler: object implementing IRequestHandler

        @param peer: the Peer which this query handler will be answering requests from
        @type peer: Peer

        @return: None
        """

    def handle_queries(self, queries):
        """
        Return responses to queries from the client.

        @param queries: a dict representing the query_identifiers:queries that should be handled
        @type queries: {string: dict}

        @return: a Deferred object which will callback with a dict of query responses
        @rtype: Deferred which fires with {string: dict}
        """


class IQueryHandlerFactory(Interface):
    """
    Construct IQueryHandlers to handle queries from each new client that connects.
    """
    def build_query_handler(self):
        """
        Create an object that implements the IQueryHandler interface

        @return: object that implements IQueryHandler
        """


class IStreamDownloaderOptions(Interface):
    def get_downloader_options(self, sd_validator, payment_rate_manager):
        """
        Return the list of options that can be used to modify IStreamDownloader behavior

        @param sd_validator: object containing stream metadata, which the options may depend on
        @type sd_validator: object which implements IStreamDescriptorValidator interface

        @param payment_rate_manager: The payment rate manager currently in effect for the downloader
        @type payment_rate_manager: PaymentRateManager

        @return: [DownloadOption]
        @rtype: [DownloadOption]
        """


class IStreamDownloaderFactory(Interface):
    """Construct IStreamDownloaders and provide options that will be
    passed to those IStreamDownloaders.

    """

    def can_download(self, sd_validator, payment_rate_manager):
        """Decide whether the downloaders created by this factory can
        download the stream described by sd_validator

        @param sd_validator: object containing stream metadata
        @type sd_validator: object which implements IStreamDescriptorValidator interface

        @param payment_rate_manager: The payment rate manager currently in effect for the downloader
        @type payment_rate_manager: PaymentRateManager

        @return: True if the downloaders can download the stream, False otherwise
        @rtype: bool

        """

    def make_downloader(self, sd_validator, options, payment_rate_manager):
        """Create an object that implements the IStreamDownloader interface

        @param sd_validator: object containing stream metadata which
            will be given to the IStreamDownloader
        @type sd_validator: object which implements IStreamDescriptorValidator interface

        @param options: a list of values that will be used by the IStreamDownloaderFactory to
            construct the IStreamDownloader. the options are in the same order as they were given
            by get_downloader_options.
        @type options: [Object]

        @param payment_rate_manager: the PaymentRateManager which the IStreamDownloader should use.
        @type payment_rate_manager: PaymentRateManager

        @return: a Deferred which fires with the downloader object
        @rtype: Deferred which fires with IStreamDownloader

        """

    def get_description(self):
        """
        Return a string detailing what this downloader does with streams

        @return: short description of what the IStreamDownloader does.
        @rtype: string
        """


class IStreamDownloader(Interface):
    """
    Use metadata and data from the network for some useful purpose.
    """
    def start(self):
        """start downloading the stream

        @return: a Deferred which fires when the stream is finished
            downloading, or errbacks when the stream is cancelled.
        @rtype: Deferred which fires with anything

        """

    def insufficient_funds(self, err):
        """
        this function informs the stream downloader that funds are too low to finish downloading.

        @return: None
        """


class IStreamDescriptorValidator(Interface):
    """
    Pull metadata out of Stream Descriptor Files and perform some
    validation on the metadata.
    """
    def validate(self):
        """
        @return: whether the stream descriptor passes validation checks
        @rtype: boolean
        """

    def info_to_show(self):
        """

        @return: A list of tuples representing metadata that should be
            presented to the user before starting the download
        @rtype: [(string, string)]
        """


class IWallet(Interface):
    """Send and receive payments.

    To send a payment, a payment reservation must be obtained
    first. This guarantees that a payment isn't promised if it can't
    be paid. When the service in question is rendered, the payment
    reservation must be given to the IWallet along with the final
    price. The reservation can also be canceled.
    """
    def stop(self):
        """Send out any unsent payments, close any connections, and stop
        checking for incoming payments.

        @return: None

        """

    def start(self):
        """
        Set up any connections and start checking for incoming payments

        @return: None
        """
    def get_info_exchanger(self):
        """
        Get the object that will be used to find the payment addresses of peers.

        @return: The object that will be used to find the payment addresses of peers.
        @rtype: An object implementing IRequestCreator
        """

    def get_wallet_info_query_handler_factory(self):
        """
        Get the object that will be used to give our payment address to peers.

        This must return an object implementing IQueryHandlerFactory. It will be used to
        create IQueryHandler objects that will be registered with an IRequestHandler.

        @return: The object that will be used to give our payment address to peers.
        @rtype: An object implementing IQueryHandlerFactory
        """

    def reserve_points(self, peer, amount):
        """Ensure a certain amount of points are available to be sent as
        payment, before the service is rendered

        @param peer: The peer to which the payment will ultimately be sent
        @type peer: Peer

        @param amount: The amount of points to reserve
        @type amount: float

        @return: A ReservedPoints object which is given to send_points
        once the service has been rendered
        @rtype: ReservedPoints

        """

    def cancel_point_reservation(self, reserved_points):
        """
        Return all of the points that were reserved previously for some ReservedPoints object

        @param reserved_points: ReservedPoints previously returned by reserve_points
        @type reserved_points: ReservedPoints

        @return: None
        """

    def send_points(self, reserved_points, amount):
        """
        Schedule a payment to be sent to a peer

        @param reserved_points: ReservedPoints object previously returned by reserve_points.
        @type reserved_points: ReservedPoints

        @param amount: amount of points to actually send, must be less than or equal to the
            amount reserved in reserved_points
        @type amount: float

        @return: Deferred which fires when the payment has been scheduled
        @rtype: Deferred which fires with anything
        """

    def get_balance(self):
        """
        Return the balance of this wallet

        @return: Deferred which fires with the balance of the wallet
        @rtype: Deferred which fires with float
        """

    def add_expected_payment(self, peer, amount):
        """
        Increase the number of points expected to be paid by a peer

        @param peer: the peer which is expected to pay the points
        @type peer: Peer

        @param amount: the amount of points expected to be paid
        @type amount: float

        @return: None
        """


class IBlobPriceModel(Interface):
    """
    A blob price model

    Used by INegotiationStrategy classes
    """

    def calculate_price(self, blob):
        """
        Calculate the price for a blob

        @param blob: a blob hash
        @type blob: str

        @return: blob price target
        @type: Decimal
        """


class INegotiationStrategy(Interface):
    """
    Strategy to negotiate download payment rates
    """

    def make_offer(self, peer, blobs):
        """
        Make a rate offer for the given peer and blobs

        @param peer: peer to make an offer to
        @type: str

        @param blobs: blob hashes to make an offer for
        @type: list

        @return: rate offer
        @rtype: Offer
        """

    def respond_to_offer(self, offer, peer, blobs):
        """
        Respond to a rate offer given by a peer

        @param offer: offer to reply to
        @type: Offer

        @param peer: peer to make an offer to
        @type: str

        @param blobs: blob hashes to make an offer for
        @type: list

        @return: accepted, rejected, or unset offer
        @rtype: Offer
        """

class IEncryptedFileMetadataManager(Interface):
    """
    Store and provide access to LBRY file metadata
    """

    def setup(self):
        pass

    def stop(self):
        pass

    def get_all_streams(self):
        pass

    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        pass

    def get_stream_info(self, stream_hash):
        pass

    def check_if_stream_exists(self, stream_hash):
        pass

    def delete_stream(self, stream_hash):
        pass

    def add_blobs_to_stream(self, stream_hash, blobs):
        pass

    def get_blobs_for_stream(self, stream_hash, start_blob=None,
                             end_blob=None, count=None, reverse=False):
        pass

    def get_stream_of_blob(self, blob_hash):
        pass

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        pass

    def get_sd_blob_hashes_for_stream(self, stream_hash):
        pass


class IBlobManager(Interface):
    """
    This class stores blobs and manages their announcement
    """

    def setup(self):
        pass

    def stop(self):
        pass

    def get_blob(self, blob_hash, length=None):
        """
        Return a blob identified by blob_hash, which may be a new blob or a
        blob that is already on the hard disk

        @param blob_hash: blob hash
        @type: str

        @param length: blob length
        @type: int

        @return: existing or new blob
        @rtype: HashBlob
        """

    def get_blob_creator(self):
        pass

    def blob_completed(self, blob, next_announce_time=None):
        pass

    def completed_blobs(self, blob_hashes_to_check):
        """
        Get completed blobs out of the blob hashes to check
        """


    def get_all_verified_blobs(self):
        pass

    def hashes_to_announce(self):
        pass

    def creator_finished(self, blob_creator):
        pass

    def delete_blob(self, blob_hash):
        pass

    def delete_blobs(self, blob_hashes):
        pass

    def add_blob_to_download_history(self, blob_hash, host, rate):
        pass

    def add_blob_to_upload_history(self, blob_hash, host, rate):
        pass

    def immediate_announce_all_blobs(self, blob_hashes):
        pass
