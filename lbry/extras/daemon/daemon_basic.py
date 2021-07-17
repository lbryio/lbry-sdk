#!/usr/bin/env python3
"""
Basic class with basic methods for the Daemon class (JSON-RPC server).
"""
from aiohttp import web
import asyncio
from binascii import hexlify
import logging
import typing

from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.components import WALLET_COMPONENT, DHT_COMPONENT
from lbry.schema.url import URL

log = logging.getLogger(__name__)


class Daemon_base(metaclass=JSONRPCServerType):
    def jsonrpc_stop(self):  # pylint: disable=no-self-use
        """
        Stop lbrynet API server.

        Usage:
            stop

        Options:
            None

        Returns:
            (string) Shutdown message
        """

        def shutdown():
            raise web.GracefulExit()

        log.info("Shutting down lbrynet daemon")
        asyncio.get_event_loop().call_later(0, shutdown)
        return "Shutting down"

    async def jsonrpc_ffmpeg_find(self):
        """
        Get ffmpeg installation information

        Usage:
            ffmpeg_find

        Options:
            None

        Returns:
            (dict) Dictionary of ffmpeg information
            {
                'available': (bool) found ffmpeg,
                'which': (str) path to ffmpeg,
                'analyze_audio_volume': (bool) should ffmpeg analyze audio
            }
        """
        return await self._video_file_analyzer.status(reset=True, recheck=True)

    async def jsonrpc_status(self):
        """
        Get daemon status

        Usage:
            status

        Options:
            None

        Returns:
            (dict) lbrynet-daemon status
            {
                'installation_id': (str) installation id - base58,
                'is_running': (bool),
                'skipped_components': (list) [names of skipped components (str)],
                'startup_status': { Does not include components which have been skipped
                    'blob_manager': (bool),
                    'blockchain_headers': (bool),
                    'database': (bool),
                    'dht': (bool),
                    'exchange_rate_manager': (bool),
                    'hash_announcer': (bool),
                    'peer_protocol_server': (bool),
                    'file_manager': (bool),
                    'libtorrent_component': (bool),
                    'upnp': (bool),
                    'wallet': (bool),
                },
                'connection_status': {
                    'code': (str) connection status code,
                    'message': (str) connection status message
                },
                'blockchain_headers': {
                    'downloading_headers': (bool),
                    'download_progress': (float) 0-100.0
                },
                'wallet': {
                    'connected': (str) host and port of the connected spv server,
                    'blocks': (int) local blockchain height,
                    'blocks_behind': (int) remote_height - local_height,
                    'best_blockhash': (str) block hash of most recent block,
                    'is_encrypted': (bool),
                    'is_locked': (bool),
                    'connected_servers': (list) [
                        {
                            'host': (str) server hostname,
                            'port': (int) server port,
                            'latency': (int) milliseconds
                        }
                    ],
                },
                'libtorrent_component': {
                    'running': (bool) libtorrent was detected and started successfully,
                },
                'dht': {
                    'node_id': (str) lbry dht node id - hex encoded,
                    'peers_in_routing_table': (int) the number of peers in the routing table,
                },
                'blob_manager': {
                    'finished_blobs': (int) number of finished blobs in the blob manager,
                    'connections': {
                        'incoming_bps': {
                            <source ip and tcp port>: (int) bytes per second received,
                        },
                        'outgoing_bps': {
                            <destination ip and tcp port>: (int) bytes per second sent,
                        },
                        'total_outgoing_mps': (float) megabytes per second sent,
                        'total_incoming_mps': (float) megabytes per second received,
                        'time': (float) timestamp
                    }
                },
                'hash_announcer': {
                    'announce_queue_size': (int) number of blobs currently queued to be announced
                },
                'file_manager': {
                    'managed_files': (int) count of files in the stream manager,
                },
                'upnp': {
                    'aioupnp_version': (str),
                    'redirects': {
                        <TCP | UDP>: (int) external_port,
                    },
                    'gateway': (str) manufacturer and model,
                    'dht_redirect_set': (bool),
                    'peer_redirect_set': (bool),
                    'external_ip': (str) external ip address,
                }
            }
        """
        ffmpeg_status = await self._video_file_analyzer.status()
        running_components = self.component_manager.get_components_status()
        response = {
            'installation_id': self.installation_id,
            'is_running': all(running_components.values()),
            'skipped_components': self.component_manager.skip_components,
            'startup_status': running_components,
            'ffmpeg_status': ffmpeg_status
        }
        for component in self.component_manager.components:
            status = await component.get_status()
            if status:
                response[component.component_name] = status
        return response

    def jsonrpc_version(self):  # pylint: disable=no-self-use
        """
        Get lbrynet API server version information

        Usage:
            version

        Options:
            None

        Returns:
            (dict) Dictionary of lbry version information
            {
                'processor': (str) processor type,
                'python_version': (str) python version,
                'platform': (str) platform string,
                'os_release': (str) os release string,
                'os_system': (str) os name,
                'version': (str) lbrynet version,
                'build': (str) "dev" | "qa" | "rc" | "release",
            }
        """
        return self.platform_info

    @requires(WALLET_COMPONENT)
    async def jsonrpc_resolve(self, urls: typing.Union[str, list], wallet_id=None, **kwargs):
        """
        Get the claim that a URL refers to.

        Usage:
            resolve <urls>... [--wallet_id=<wallet_id>]
                    [--include_purchase_receipt]
                    [--include_is_my_output]
                    [--include_sent_supports]
                    [--include_sent_tips]
                    [--include_received_tips]
                    [--new_sdk_server=<new_sdk_server>]

        Options:
            --urls=<urls>              : (str, list) one or more urls to resolve
            --wallet_id=<wallet_id>    : (str) wallet to check for claim purchase receipts
           --new_sdk_server=<new_sdk_server> : (str) URL of the new SDK server (EXPERIMENTAL)
           --include_purchase_receipt  : (bool) lookup and include a receipt if this wallet
                                                has purchased the claim being resolved
            --include_is_my_output     : (bool) lookup and include a boolean indicating
                                                if claim being resolved is yours
            --include_sent_supports    : (bool) lookup and sum the total amount
                                                of supports you've made to this claim
            --include_sent_tips        : (bool) lookup and sum the total amount
                                                of tips you've made to this claim
                                                (only makes sense when claim is not yours)
            --include_received_tips    : (bool) lookup and sum the total amount
                                                of tips you've received to this claim
                                                (only makes sense when claim is yours)

        Returns:
            Dictionary of results, keyed by url
            '<url>': {
                    If a resolution error occurs:
                    'error': Error message

                    If the url resolves to a channel or a claim in a channel:
                    'certificate': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number (or -1 if unknown),
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'confirmations': (int) claim depth,
                        'timestamp': (int) timestamp of the block that included this claim tx,
                        'has_signature': (bool) included if decoded_claim
                        'name': (str) claim name,
                        'permanent_url': (str) permanent url of the certificate claim,
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}],
                        'txid': (str) claim txid,
                        'nout': (str) claim nout,
                        'signature_is_valid': (bool), included if has_signature,
                        'value': ClaimDict if decoded, otherwise hex string
                    }

                    If the url resolves to a channel:
                    'claims_in_channel': (int) number of claims in the channel,

                    If the url resolves to a claim:
                    'claim': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number (or -1 if unknown),
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'depth': (int) claim depth,
                        'has_signature': (bool) included if decoded_claim
                        'name': (str) claim name,
                        'permanent_url': (str) permanent url of the claim,
                        'channel_name': (str) channel name if claim is in a channel
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}]
                        'txid': (str) claim txid,
                        'nout': (str) claim nout,
                        'signature_is_valid': (bool), included if has_signature,
                        'value': ClaimDict if decoded, otherwise hex string
                    }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        if isinstance(urls, str):
            urls = [urls]

        results = {}

        valid_urls = set()
        for url in urls:
            try:
                URL.parse(url)
                valid_urls.add(url)
            except ValueError:
                results[url] = {"error": f"{url} is not a valid url"}

        resolved = await self.resolve(wallet.accounts, list(valid_urls), **kwargs)

        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri] if resolved[resolved_uri] is not None else \
                {"error": f"{resolved_uri} did not resolve to a claim"}

        return results

    @requires(DHT_COMPONENT)
    def jsonrpc_routing_table_get(self):
        """
        Get DHT routing information

        Usage:
            routing_table_get

        Options:
            None

        Returns:
            (dict) dictionary containing routing and peer information
            {
                "buckets": {
                    <bucket index>: [
                        {
                            "address": (str) peer address,
                            "udp_port": (int) peer udp port,
                            "tcp_port": (int) peer tcp port,
                            "node_id": (str) peer node id,
                        }
                    ]
                },
                "node_id": (str) the local dht node id
            }
        """
        result = {
            'buckets': {}
        }

        for i in range(len(self.dht_node.protocol.routing_table.buckets)):
            result['buckets'][i] = []
            for peer in self.dht_node.protocol.routing_table.buckets[i].peers:
                host = {
                    "address": peer.address,
                    "udp_port": peer.udp_port,
                    "tcp_port": peer.tcp_port,
                    "node_id": hexlify(peer.node_id).decode(),
                }
                result['buckets'][i].append(host)

        result['node_id'] = hexlify(self.dht_node.protocol.node_id).decode()
        return result
