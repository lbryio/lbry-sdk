import os
import logging
import requests

# from twisted.internet import defer

from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from tqdm import tqdm, trange

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024

session = requests.Session()
# Max retries and back-off strategy so all requests to http:// sleep
# before retrying
retries = Retry(total=7,
                backoff_factor=0.1,
                status_forcelist=[429, 500, 502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))

class HttpDownloader(object):

    def __init__(self, download_directory, url):
        self.download_directory = download_directory
        self.url = url


    def download(self, url, directory, no_redirects):

        file_name = url.split('/')[-1]
        file_address = directory + '/' + file_name
        is_redirects = not no_redirects

        response = session.get(url, stream=True, allow_redirects=is_redirects)

        if not response.status_code == 200:
            # ignore this file since server returns invalid response
            log.info("Cannot download file as server returned invalid response: %d"%response.status_code)
            return

        try:
            total_size = int(response.headers['content-length'])
        except KeyError:
            total_size = len(response.content)

        total_chunks = total_size / CHUNK_SIZE

        file_iterable = response.iter_content(chunk_size=CHUNK_SIZE)

        tqdm_iter = tqdm(iterable=file_iterable, total=total_chunks,
                         unit='KB', desc=file_name, leave=False)

        with open(file_address, 'wb') as f:
            for data in tqdm_iter:
                f.write(data)

        return file_address


    def start(self, no_redirects=False):

        # Create directory to save files
        if not os.path.exists(self.download_directory):
            os.makedirs(self.download_directory)

        file_address = self.download(self.url, self.download_directory, no_redirects)
        
        return file_address
