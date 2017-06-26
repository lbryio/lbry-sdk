from lbrynet.lbry_file.StreamDescriptor import EncryptedFileStreamType
from lbrynet.lbry_file.StreamDescriptor import EncryptedFileStreamDescriptorValidator
from lbrynet.core.DownloadOption import DownloadOption, DownloadOptionChoice


def add_lbry_file_to_sd_identifier(sd_identifier):
    sd_identifier.add_stream_type(
        EncryptedFileStreamType, EncryptedFileStreamDescriptorValidator, EncryptedFileOptions())


class EncryptedFileOptions(object):
    def __init__(self):
        pass

    def get_downloader_options(self, sd_validator, payment_rate_manager):
        prm = payment_rate_manager

        def get_default_data_rate_description():
            if prm.base.min_blob_data_payment_rate is None:
                return "Application default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate)
            else:
                return "%f LBC/MB" % prm.base.min_blob_data_payment_rate

        rate_choices = []
        rate_choices.append(DownloadOptionChoice(
            prm.base.min_blob_data_payment_rate,
            "No change - %s" % get_default_data_rate_description(),
            "No change - %s" % get_default_data_rate_description()))
        if prm.base.min_blob_data_payment_rate is not None:
            rate_choices.append(DownloadOptionChoice(
                None,
                "Application default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate),
                "Application default (%s LBC/MB)" % str(prm.base.min_blob_data_payment_rate)))
        rate_choices.append(DownloadOptionChoice(float,
                                                 "Enter rate in LBC/MB",
                                                 "Enter rate in LBC/MB"))

        options = [
            DownloadOption(
                rate_choices,
                "Rate which will be paid for data",
                "data payment rate",
                prm.base.min_blob_data_payment_rate,
                get_default_data_rate_description()
            ),
        ]
        return options
