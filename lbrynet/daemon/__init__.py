from lbrynet import custom_logger
import Components  # register Component classes
from lbrynet.daemon.auth.client import LBRYAPIClient
get_client = LBRYAPIClient.get_client
