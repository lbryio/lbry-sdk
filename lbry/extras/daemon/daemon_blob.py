#!/usr/bin/env python3
"""
Basic class with blob methods for the Daemon class (JSON-RPC server).
"""
import asyncio
import logging

from lbry import utils
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_list
from lbry.extras.daemon.components import (WALLET_COMPONENT,
                                           DHT_COMPONENT,
                                           DATABASE_COMPONENT,
                                           BLOB_COMPONENT)
from lbry.blob.blob_file import is_valid_blobhash, BlobBuffer
from lbry.blob_exchange.downloader import download_blob

log = logging.getLogger(__name__)


class Daemon_blob(metaclass=JSONRPCServerType):
    @requires(DATABASE_COMPONENT)
    async def jsonrpc_blob_announce(self, blob_hash=None, stream_hash=None, sd_hash=None):
        """
        Announce blobs to the DHT

        Usage:
            blob_announce (<blob_hash> | --blob_hash=<blob_hash>
                          | --stream_hash=<stream_hash> | --sd_hash=<sd_hash>)

        Options:
            --blob_hash=<blob_hash>        : (str) announce a blob, specified by blob_hash
            --stream_hash=<stream_hash>    : (str) announce all blobs associated with
                                             stream_hash
            --sd_hash=<sd_hash>            : (str) announce all blobs associated with
                                             sd_hash and the sd_hash itself

        Returns:
            (bool) true if successful
        """
        blob_hashes = []
        if blob_hash:
            blob_hashes.append(blob_hash)
        elif stream_hash or sd_hash:
            if sd_hash and stream_hash:
                raise Exception("either the sd hash or the stream hash should be provided, not both")
            if sd_hash:
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
            blobs = await self.storage.get_blobs_for_stream(stream_hash, only_completed=True)
            blob_hashes.extend(blob.blob_hash for blob in blobs if blob.blob_hash is not None)
        else:
            raise Exception('single argument must be specified')
        await self.storage.should_single_announce_blobs(blob_hashes, immediate=True)
        return True

    @requires(BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_blob_delete(self, blob_hash):
        """
        Delete a blob

        Usage:
            blob_delete (<blob_hash> | --blob_hash=<blob_hash>)

        Options:
            --blob_hash=<blob_hash>  : (str) blob hash of the blob to delete

        Returns:
            (str) Success/fail message
        """
        if not blob_hash or not is_valid_blobhash(blob_hash):
            return f"Invalid blob hash to delete '{blob_hash}'"
        streams = self.file_manager.get_filtered(sd_hash=blob_hash)
        if streams:
            await self.file_manager.delete(streams[0])
        else:
            await self.blob_manager.delete_blobs([blob_hash])
        return "Deleted %s" % blob_hash

    @requires(WALLET_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT)
    async def jsonrpc_blob_get(self, blob_hash, timeout=None, read=False):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>] [--read]

        Options:
        --blob_hash=<blob_hash>                        : (str) blob hash of the blob to get
        --timeout=<timeout>                            : (int) timeout in number of seconds

        Returns:
            (str) Success/Fail message or (dict) decoded data
        """

        blob = await download_blob(asyncio.get_event_loop(), self.conf, self.blob_manager, self.dht_node, blob_hash)
        if read:
            with blob.reader_context() as handle:
                return handle.read().decode()
        elif isinstance(blob, BlobBuffer):
            log.warning("manually downloaded blob buffer could have missed garbage collection, clearing it")
            blob.delete()
        return "Downloaded blob %s" % blob_hash

    @requires(BLOB_COMPONENT, WALLET_COMPONENT)
    async def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
                                finished=None, page=None, page_size=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob_list [--needed] [--finished] [<uri> | --uri=<uri>]
                      [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>]
                      [--page=<page>] [--page_size=<page_size>]

        Options:
            --needed                     : (bool) only return needed blobs
            --finished                   : (bool) only return finished blobs
            --uri=<uri>                  : (str) filter blobs by stream in a uri
            --stream_hash=<stream_hash>  : (str) filter blobs by stream hash
            --sd_hash=<sd_hash>          : (str) filter blobs by sd hash
            --page=<page>                : (int) page to return during paginating
            --page_size=<page_size>      : (int) number of items on page during pagination

        Returns:
            (list) List of blob hashes
        """

        if uri or stream_hash or sd_hash:
            if uri:
                metadata = (await self.resolve([], uri))[uri]
                sd_hash = utils.get_sd_hash(metadata)
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
            elif stream_hash:
                sd_hash = await self.storage.get_sd_blob_hash_for_stream(stream_hash)
            elif sd_hash:
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
                sd_hash = await self.storage.get_sd_blob_hash_for_stream(stream_hash)
            if sd_hash:
                blobs = [sd_hash]
            else:
                blobs = []
            if stream_hash:
                blobs.extend([b.blob_hash for b in (await self.storage.get_blobs_for_stream(stream_hash))[:-1]])
        else:
            blobs = list(self.blob_manager.completed_blob_hashes)
        if needed:
            blobs = [blob_hash for blob_hash in blobs if not self.blob_manager.is_blob_verified(blob_hash)]
        if finished:
            blobs = [blob_hash for blob_hash in blobs if self.blob_manager.is_blob_verified(blob_hash)]
        return paginate_list(blobs, page, page_size)

    @requires(BLOB_COMPONENT)
    async def jsonrpc_blob_reflect(self, blob_hashes, reflector_server=None):
        """
        Reflects specified blobs

        Usage:
            blob_reflect (<blob_hashes>...) [--reflector_server=<reflector_server>]

        Options:
            --reflector_server=<reflector_server>          : (str) reflector address

        Returns:
            (list) reflected blob hashes
        """

        raise NotImplementedError()

    @requires(BLOB_COMPONENT)
    async def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Usage:
            blob_reflect_all

        Options:
            None

        Returns:
            (bool) true if successful
        """

        raise NotImplementedError()
