#!/usr/bin/env python3
"""
Basic class with file methods for the Daemon class (JSON-RPC server).
"""
import asyncio
import logging
import random

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_list
from lbry.extras.daemon.components import FILE_MANAGER_COMPONENT

log = logging.getLogger(__name__)


class Daemon_file(metaclass=JSONRPCServerType):
    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_list(self, sort=None, reverse=False, comparison=None, wallet_id=None, page=None,
                                page_size=None, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--added_on=<added_on>] [--claim_id=<claim_id>]
                      [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--blobs_in_stream=<blobs_in_stream>]
                      [--download_path=<download_path>] [--blobs_remaining=<blobs_remaining>]
                      [--uploading_to_reflector=<uploading_to_reflector>] [--is_fully_reflected=<is_fully_reflected>]
                      [--status=<status>] [--completed=<completed>] [--sort=<sort_by>] [--comparison=<comparison>]
                      [--full_status=<full_status>] [--reverse] [--page=<page>] [--page_size=<page_size>]
                      [--wallet_id=<wallet_id>]

        Options:
            --sd_hash=<sd_hash>                    : (str) get file with matching sd hash
            --file_name=<file_name>                : (str) get file with matching file name in the
                                                     downloads folder
            --stream_hash=<stream_hash>            : (str) get file with matching stream hash
            --rowid=<rowid>                        : (int) get file with matching row id
            --added_on=<added_on>                  : (int) get file with matching time of insertion
            --claim_id=<claim_id>                  : (str) get file with matching claim id(s)
            --outpoint=<outpoint>                  : (str) get file with matching claim outpoint(s)
            --txid=<txid>                          : (str) get file with matching claim txid
            --nout=<nout>                          : (int) get file with matching claim nout
            --channel_claim_id=<channel_claim_id>  : (str) get file with matching channel claim id(s)
            --channel_name=<channel_name>          : (str) get file with matching channel name
            --claim_name=<claim_name>              : (str) get file with matching claim name
            --blobs_in_stream<blobs_in_stream>     : (int) get file with matching blobs in stream
            --download_path=<download_path>        : (str) get file with matching download path
            --uploading_to_reflector=<uploading_to_reflector> : (bool) get files currently uploading to reflector
            --is_fully_reflected=<is_fully_reflected>         : (bool) get files that have been uploaded to reflector
            --status=<status>                      : (str) match by status, ( running | finished | stopped )
            --completed=<completed>                : (bool) match only completed
            --blobs_remaining=<blobs_remaining>    : (int) amount of remaining blobs to download
            --sort=<sort_by>                       : (str) field to sort by (one of the above filter fields)
            --comparison=<comparison>              : (str) logical comparison, (eq | ne | g | ge | l | le | in)
            --page=<page>                          : (int) page to return during paginating
            --page_size=<page_size>                : (int) number of items on page during pagination
            --wallet_id=<wallet_id>                : (str) add purchase receipts from this wallet

        Returns: {Paginated[File]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        sort = sort or 'rowid'
        comparison = comparison or 'eq'

        paginated = paginate_list(
            self.file_manager.get_filtered(sort, reverse, comparison, **kwargs), page, page_size
        )
        if paginated['items']:
            receipts = {
                txo.purchased_claim_id: txo for txo in
                await self.ledger.db.get_purchases(
                    accounts=wallet.accounts,
                    purchased_claim_id__in=[s.claim_id for s in paginated['items']]
                )
            }
            for stream in paginated['items']:
                stream.purchase_receipt = receipts.get(stream.claim_id)
        return paginated

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_set_status(self, status, **kwargs):
        """
        Start or stop downloading a file

        Usage:
            file_set_status (<status> | --status=<status>) [--sd_hash=<sd_hash>]
                      [--file_name=<file_name>] [--stream_hash=<stream_hash>] [--rowid=<rowid>]

        Options:
            --status=<status>            : (str) one of "start" or "stop"
            --sd_hash=<sd_hash>          : (str) set status of file with matching sd hash
            --file_name=<file_name>      : (str) set status of file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) set status of file with matching stream hash
            --rowid=<rowid>              : (int) set status of file with matching row id

        Returns:
            (str) Confirmation message
        """

        if status not in ['start', 'stop']:
            raise Exception('Status must be "start" or "stop".')

        streams = self.file_manager.get_filtered(**kwargs)
        if not streams:
            raise Exception(f'Unable to find a file for {kwargs}')
        stream = streams[0]
        if status == 'start' and not stream.running:
            if not hasattr(stream, 'bt_infohash') and 'dht' not in self.conf.components_to_skip:
                stream.downloader.node = self.dht_node
            await stream.save_file()
            msg = "Resumed download"
        elif status == 'stop' and stream.running:
            await stream.stop()
            msg = "Stopped download"
        else:
            msg = (
                "File was already being downloaded" if status == 'start'
                else "File was already stopped"
            )
        return msg

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_delete(self, delete_from_download_dir=False, delete_all=False, **kwargs):
        """
        Delete a LBRY file

        Usage:
            file_delete [--delete_from_download_dir] [--delete_all] [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                        [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--claim_id=<claim_id>] [--txid=<txid>]
                        [--nout=<nout>] [--claim_name=<claim_name>] [--channel_claim_id=<channel_claim_id>]
                        [--channel_name=<channel_name>]

        Options:
            --delete_from_download_dir             : (bool) delete file from download directory,
                                                    instead of just deleting blobs
            --delete_all                           : (bool) if there are multiple matching files,
                                                     allow the deletion of multiple files.
                                                     Otherwise do not delete anything.
            --sd_hash=<sd_hash>                    : (str) delete by file sd hash
            --file_name=<file_name>                 : (str) delete by file name in downloads folder
            --stream_hash=<stream_hash>            : (str) delete by file stream hash
            --rowid=<rowid>                        : (int) delete by file row id
            --claim_id=<claim_id>                  : (str) delete by file claim id
            --txid=<txid>                          : (str) delete by file claim txid
            --nout=<nout>                          : (int) delete by file claim nout
            --claim_name=<claim_name>              : (str) delete by file claim name
            --channel_claim_id=<channel_claim_id>  : (str) delete by file channel claim id
            --channel_name=<channel_name>                 : (str) delete by file channel claim name

        Returns:
            (bool) true if deletion was successful
        """

        streams = self.file_manager.get_filtered(**kwargs)

        if len(streams) > 1:
            if not delete_all:
                log.warning("There are %i files to delete, use narrower filters to select one",
                            len(streams))
                return False
            else:
                log.warning("Deleting %i files",
                            len(streams))

        if not streams:
            log.warning("There is no file to delete")
            return False
        else:
            for stream in streams:
                message = f"Deleted file {stream.file_name}"
                await self.file_manager.delete(stream, delete_file=delete_from_download_dir)
                log.info(message)
            result = True
        return result

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_save(self, file_name=None, download_directory=None, **kwargs):
        """
        Start saving a file to disk.

        Usage:
            file_save [--file_name=<file_name>] [--download_directory=<download_directory>] [--sd_hash=<sd_hash>]
                      [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--claim_id=<claim_id>] [--txid=<txid>]
                      [--nout=<nout>] [--claim_name=<claim_name>] [--channel_claim_id=<channel_claim_id>]
                      [--channel_name=<channel_name>]

        Options:
            --file_name=<file_name>                      : (str) file name to save to
            --download_directory=<download_directory>    : (str) directory to save into
            --sd_hash=<sd_hash>                          : (str) save file with matching sd hash
            --stream_hash=<stream_hash>                  : (str) save file with matching stream hash
            --rowid=<rowid>                              : (int) save file with matching row id
            --claim_id=<claim_id>                        : (str) save file with matching claim id
            --txid=<txid>                                : (str) save file with matching claim txid
            --nout=<nout>                                : (int) save file with matching claim nout
            --claim_name=<claim_name>                    : (str) save file with matching claim name
            --channel_claim_id=<channel_claim_id>        : (str) save file with matching channel claim id
            --channel_name=<channel_name>                : (str) save file with matching channel claim name

        Returns: {File}
        """

        streams = self.file_manager.get_filtered(**kwargs)

        if len(streams) > 1:
            log.warning("There are %i matching files, use narrower filters to select one", len(streams))
            return False
        if not streams:
            log.warning("There is no file to save")
            return False
        stream = streams[0]
        if not hasattr(stream, 'bt_infohash') and 'dht' not in self.conf.components_to_skip:
            stream.downloader.node = self.dht_node
        await stream.save_file(file_name, download_directory)
        return stream

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_reflect(self, **kwargs):
        """
        Reflect all the blobs in a file matching the filter criteria

        Usage:
            file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                         [--stream_hash=<stream_hash>] [--rowid=<rowid>]
                         [--reflector=<reflector>]

        Options:
            --sd_hash=<sd_hash>          : (str) get file with matching sd hash
            --file_name=<file_name>      : (str) get file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) get file with matching stream hash
            --rowid=<rowid>              : (int) get file with matching row id
            --reflector=<reflector>      : (str) reflector server, ip address or url
                                           by default choose a server from the config

        Returns:
            (list) list of blobs reflected
        """

        server, port = kwargs.get('server'), kwargs.get('port')
        if server and port:
            port = int(port)
        else:
            server, port = random.choice(self.conf.reflector_servers)
        reflected = await asyncio.gather(*[
            self.file_manager['stream'].reflect_stream(stream, server, port)
            for stream in self.file_manager.get_filtered_streams(**kwargs)
        ])
        total = []
        for reflected_for_stream in reflected:
            total.extend(reflected_for_stream)
        return total
