#!/usr/bin/env python3
"""Tests for the slack_emoji_uploader module"""
import os.path
import tempfile
import unittest

import slack_emoji_uploader


class LoadSettingsTest(unittest.TestCase):
    """Test Case for slack_emoji_uploader.load_settings()"""

    def setUp(self):
        """Sets up function arguments"""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.temporary_directory.name, 'config')

    def tearDown(self):
        """Tears down function arguments"""
        self.temporary_directory.cleanup()

    def test_default_section(self):
        """Tests that a config with the default section loads"""
        with open(self.config, 'w') as config_file:
            config_file.writelines((
                '[DEFAULT]\n',
                'section.name=DEFAULT\n',
            ))

        settings = slack_emoji_uploader.load_settings(self.config, 'default')

        self.assertEqual('DEFAULT', settings.get('section.name'))

    def test_profile_section(self):
        """Tests that a config with the chosen profile section loads"""
        with open(self.config, 'w') as config_file:
            config_file.writelines((
                '[other]\n',
                'section.name=other\n',
            ))

        settings = slack_emoji_uploader.load_settings(self.config, 'other')

        self.assertEqual('other', settings.get('section.name'))
