import unittest
from unittest.mock import patch
from mcpywrap.builders.project_builder import _replace_with_retry


def locked(code=5):
    error=PermissionError('Windows directory temporarily locked')
    error.winerror=code
    return error


class ReplaceRetry(unittest.TestCase):
    def test_recovers_from_transient_windows_lock(self):
        with patch('mcpywrap.builders.project_builder.os.replace',side_effect=[locked(),locked(32),None]) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
            _replace_with_retry('source','target')
        self.assertEqual(replace.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[.05,.1])
        self.assertTrue(all(c.args==('source','target') for c in replace.call_args_list))

    def test_persistent_lock_is_bounded_and_propagated(self):
        error=locked(33)
        with patch('mcpywrap.builders.project_builder.os.replace',side_effect=error) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
            with self.assertRaises(PermissionError) as caught:_replace_with_retry('source','target')
        self.assertIs(caught.exception,error)
        self.assertEqual(replace.call_count,7)
        self.assertLess(sum(c.args[0] for c in sleep.call_args_list),4)

    def test_non_windows_or_non_lock_errors_are_not_retried(self):
        for error in (PermissionError('permissions'),FileNotFoundError('missing')):
            with patch('mcpywrap.builders.project_builder.os.replace',side_effect=error) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
                with self.assertRaises(type(error)):_replace_with_retry('source','target')
                self.assertEqual(replace.call_count,1);sleep.assert_not_called()


if __name__=='__main__':unittest.main()
