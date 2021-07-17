#!/usr/bin/env python3
"""
Basic class with downloading methods for the Daemon class (JSON-RPC server).
"""
import os
import logging

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.components import WALLET_COMPONENT, DATABASE_COMPONENT, BLOB_COMPONENT
from lbry.extras.daemon.components import FILE_MANAGER_COMPONENT
from lbry.extras.daemon.components import EXCHANGE_RATE_MANAGER_COMPONENT
from lbry.error import DownloadSDTimeoutError

log = logging.getLogger(__name__)


class Daemon_get(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              FILE_MANAGER_COMPONENT)
    async def jsonrpc_get(
            self, uri, file_name=None, download_directory=None, timeout=None, save_file=None, wallet_id=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>]
             [<download_directory> | --download_directory=<download_directory>] [<timeout> | --timeout=<timeout>]
             [--save_file=<save_file>] [--wallet_id=<wallet_id>]


        Options:
            --uri=<uri>              : (str) uri of the content to download
            --file_name=<file_name>  : (str) specified name for the downloaded file, overrides the stream file name
            --download_directory=<download_directory>  : (str) full path to the directory to download into
            --timeout=<timeout>      : (int) download timeout in number of seconds
            --save_file=<save_file>  : (bool) save the file to the downloads directory
            --wallet_id=<wallet_id>  : (str) wallet to check for claim purchase receipts

        Returns: {File}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if download_directory and not os.path.isdir(download_directory):
            return {"error": f"specified download directory \"{download_directory}\" does not exist"}
        try:
            stream = await self.file_manager.download_from_uri(
                uri, self.exchange_rate_manager, timeout, file_name, download_directory,
                save_file=save_file, wallet=wallet
            )
            if not stream:
                raise DownloadSDTimeoutError(uri)
        except Exception as e:
            log.warning("Error downloading %s: %s", uri, str(e))
            return {"error": str(e)}
        return stream
