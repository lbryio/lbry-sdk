"""
Download LBRY Files from LBRYnet and save them to disk.
"""
import logging
import time
import urllib
from zope.interface import implements
from twisted.internet import defer

from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.core.Error import NoSuchSDHash, NoSuchStreamHash
from lbrynet.core.utils import short_hash
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaver
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileDownloader
from lbrynet.lbryfilemanager.EncryptedFileStatusReport import EncryptedFileStatusReport
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import save_sd_info
from lbrynet.core.Wallet import ClaimOutpoint
from lbrynet.interfaces import IStreamDownloaderFactory, IStreamDownloader
log = logging.getLogger(__name__)



class HttpDownloader(object):
    implements(IStreamDownloader)


    def __init__(self, download_directory, link):
 
        self.download_directory = download_directory
        self.link = link 
        
    @defer.inlineCallbacks
    def start(self):
        log.info("downloading from %s to %s", self.link, self.download_directory)
        testfile = urllib.URLopener()
        testfile.retrieve(self.link, self.download_directory + "/" + self.link.split("/")[-1])
        log.info("downloaded from http")
        
    def insufficient_funds(self, err):
        pass
    def stop(self):
        pass
