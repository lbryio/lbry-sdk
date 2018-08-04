from unittest import TestCase
from torba.basedatabase import constraints_to_sql


class TestConstraintBuilder(TestCase):

    def test_any(self):
        constraints = {
            'ages__any': {
                'age__gt': 18,
                'age__lt': 38
            }
        }
        self.assertEqual(
            constraints_to_sql(constraints, prepend_sql=''),
            '(age > :ages__any_age__gt OR age < :ages__any_age__lt)'
        )
        self.assertEqual(
            constraints, {
                'ages__any_age__gt': 18,
                'ages__any_age__lt': 38
            }
        )
