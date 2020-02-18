from . import zscore
from . import ar
from . import delayed_ar

TRENDING_ALGORITHMS = {
    'zscore': zscore,
    'ar': ar,
    'delayed_ar': delayed_ar
}
