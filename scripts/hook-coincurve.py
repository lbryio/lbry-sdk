"""
Hook for coincurve.
"""

import os.path
from PyInstaller.utils.hooks import get_module_file_attribute

coincurve_dir = os.path.dirname(get_module_file_attribute('coincurve'))
binaries = [(os.path.join(coincurve_dir, 'libsecp256k1.dll'), 'coincurve')]
