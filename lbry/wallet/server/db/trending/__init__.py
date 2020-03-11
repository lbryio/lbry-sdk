from . import zscore
from . import ar
from . import variable_decay

TRENDING_ALGORITHMS = {
    'zscore': zscore,
    'ar': ar,
    'variable_decay': variable_decay
}
