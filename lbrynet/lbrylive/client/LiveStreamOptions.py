# pylint: skip-file
from lbrynet.lbrylive.StreamDescriptor import LiveStreamType, LiveStreamDescriptorValidator
from lbrynet.core.DownloadOption import DownloadOption, DownloadOptionChoice


def add_live_stream_to_sd_identifier(sd_identifier, base_live_stream_payment_rate_manager):
    sd_identifier.add_stream_type(LiveStreamType, LiveStreamDescriptorValidator,
                                  LiveStreamOptions(base_live_stream_payment_rate_manager))


class LiveStreamOptions(object):
    def __init__(self, base_live_stream_payment_rate_manager):
        self.base_live_stream_prm = base_live_stream_payment_rate_manager

    def get_downloader_options(self, sd_validator, payment_rate_manager):
        prm = payment_rate_manager

        def get_default_data_rate_description():
            if prm.min_blob_data_payment_rate is None:
                return "Application default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate)
            else:
                return "%f LBC/MB" % prm.min_blob_data_payment_rate

        options = [
            DownloadOption(
                [
                    DownloadOptionChoice(None,
                                         "No change",
                                         "No change"),
                    DownloadOptionChoice(None,
                                         "Application default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate),
                                         "Default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate)),
                    DownloadOptionChoice(float,
                                         "Rate in LBC/MB",
                                         "Rate in LBC/MB")
                ],
                "rate which will be paid for data",
                "data payment rate",
                prm.min_blob_data_payment_rate,
                get_default_data_rate_description()
            ),
            DownloadOption(
                [
                    DownloadOptionChoice(None,
                                         "No change",
                                         "No change"),
                    DownloadOptionChoice(None,
                                         "Application default (%s LBC/MB)" % str(self.base_live_stream_prm.min_live_blob_info_payment_rate),
                                         "Default (%s LBC/MB)" % str(self.base_live_stream_prm.min_live_blob_info_payment_rate)),
                    DownloadOptionChoice(float,
                                         "Rate in LBC/MB",
                                         "Rate in LBC/MB")
                ],
                "rate which will be paid for metadata",
                "metadata payment rate",
                None,
                "Application default (%s LBC/MB)" % str(self.base_live_stream_prm.min_live_blob_info_payment_rate)
            ),
            DownloadOption(
                [
                    DownloadOptionChoice(True,
                                         "Allow reuploading data downloaded for this file",
                                         "Allow reuploading"),
                    DownloadOptionChoice(False,
                                         "Disallow reuploading data downloaded for this file",
                                         "Disallow reuploading")
                ],
                "allow reuploading data downloaded for this file",
                "allow upload",
                True,
                "Allow"
            ),
        ]
        return options
