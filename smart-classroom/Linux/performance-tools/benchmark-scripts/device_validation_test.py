"""
Unit tests for benchmark target device validation.
"""

import argparse
import os
import unittest
from unittest import mock

from device_validation import validate_target_device, resolve_target_device_default


class TestDeviceValidation(unittest.TestCase):

    def test_valid_target_devices(self):
        test_cases = {
            'CPU': 'CPU',
            'GPU': 'GPU',
            'GPU.0': 'GPU.0',
            'GPU.1': 'GPU.1',
            'GPU.2': 'GPU.2',
            'NPU': 'NPU',
        }

        for user_value, expected in test_cases.items():
            with self.subTest(user_value=user_value):
                self.assertEqual(validate_target_device(user_value), expected)

    def test_invalid_target_devices(self):
        invalid_values = ['GPU.', 'GPU.A', 'GPU.-1', 'GPU.abc']

        for user_value in invalid_values:
            with self.subTest(user_value=user_value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    validate_target_device(user_value)

    def test_env_target_device_valid(self):
        with mock.patch.dict(os.environ, {'TARGET_DEVICE': 'gpu.2'}, clear=False):
            self.assertEqual(resolve_target_device_default('CPU'), 'GPU.2')

    def test_env_target_device_invalid(self):
        with mock.patch.dict(os.environ, {'TARGET_DEVICE': 'GPU.-1'}, clear=False):
            with self.assertRaises(argparse.ArgumentTypeError):
                resolve_target_device_default('CPU')

    def test_env_target_device_fallback_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_target_device_default('CPU'), 'CPU')

    def test_env_target_device_fallback_when_empty(self):
        with mock.patch.dict(os.environ, {'TARGET_DEVICE': '   '}, clear=False):
            self.assertEqual(resolve_target_device_default('GPU'), 'GPU')


if __name__ == '__main__':
    unittest.main()
