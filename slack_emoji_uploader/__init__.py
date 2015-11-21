#!/usr/bin/env python3
"""Automatic uploader for slack emoji images with threading"""
import argparse
import collections
import concurrent.futures
import configparser
import getpass
import http.client
import io
import logging
import os.path
import socket
import urllib.error
import urllib.parse
import urllib.request

import lxml.html
import reliable_executor
import requests

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s [%(module)s:%(lineno)s] %(message)s',
    level=logging.CRITICAL,
)

Image = collections.namedtuple('Image', (
    'id',
    'filename',
    'remove_form',
))
Slack = collections.namedtuple('Slack', (
    'url',
    'cookie',
))
Settings = collections.namedtuple('Settings', (
    'slack',
    'headers',
    'upload_folder',
))


def load_settings(config_path, profile, log=logging.getLogger(__name__)):
    """Loads settings and returns a configparser.SectionProxy object"""
    settings = configparser.ConfigParser()
    settings_paths = (
        '{}.settings'.format(__file__),
        '/etc/slack_emoji_uploader/config',
        config_path,
    )
    log.debug(
        'Loading settings from "%s"',
        '", "'.join(settings_paths),
    )
    settings.read(settings_paths)

    if settings.has_section(profile):
        log.debug('Loading "%s" profile from settings', profile)
        settings = settings[profile]
    else:
        log.debug('Profile "%s" was not found in settings', profile)
        settings.add_section(profile)
        settings = settings[profile]

    return settings


def process_cookies(url, headers=None, data=None):
    """Processes cookies in a request/response chain and returns it with the response"""
    class RedirHandler(urllib.request.HTTPRedirectHandler):
        """Handler for redirects in urllib requests"""

        def http_error_302(self, req, fp, code, msg, headers):
            """Handler for redirects with HTTP 302"""
            return urllib.request.HTTPRedirectHandler.http_error_302(
                self,
                req,
                fp,
                code,
                msg,
                headers,
            )

        http_error_301 = http_error_303 = http_error_307 = http_error_302

    cookie_jar = urllib.request.HTTPCookieProcessor()

    urllib.request.install_opener(urllib.request.build_opener(RedirHandler, cookie_jar))

    response = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers))
    cookies = '{};'.format('; '.join(
        '{}={}'.format(cookie.name, cookie.value)
        for cookie in cookie_jar.cookiejar
    ))

    return (response, cookies)


def log_in_to_slack(slack_team, headers=None, log=logging.getLogger(__name__)):
    """Logs in to Slack and returns the session cookie"""
    log_in_url = 'https://{}.slack.com/'.format(slack_team)

    log.debug('Requesting user name')
    email_address = input('Email Address: ')
    log.debug('Requesting password for "%s"', email_address)
    password = getpass.getpass()

    response = process_cookies(log_in_url, headers=headers)[0]
    sign_in_form = lxml.html.parse(response).xpath(
        '/child::html'
        '/child::body'
        '//child::form[attribute::id="signin_form"]'
    )[0]
    form_data = dict(
        (item.attrib['name'], item.attrib['value'])
        for item in sign_in_form.xpath('child::input[attribute::type="hidden"]')
    )
    form_data['email'] = email_address
    form_data['password'] = password
    form_data = urllib.parse.urlencode(form_data)
    form_data = form_data.encode('utf-8')

    response, cookies = process_cookies(log_in_url, headers=headers, data=form_data)

    if cookies == ';':
        mfa_form = lxml.html.parse(response).xpath(
            '/child::html'
            '/child::body'
            '//child::form'
        )[0]
        form_data = dict(
            (item.attrib['name'], item.attrib['value'])
            for item in mfa_form.xpath('child::input[attribute::type="hidden"]')
        )
        form_data['2fa_code'] = input('Two Factor Authentication Code: ')
        form_data = urllib.parse.urlencode(form_data)
        form_data = form_data.encode('utf-8')

        cookies = process_cookies(log_in_url, headers=headers, data=form_data)[1]

    return cookies


def upload(
        image,
        settings,
        log=logging.getLogger(__name__),
):
    """Uploads an image"""
    upload_form = lxml.html.parse(urllib.request.urlopen(urllib.request.Request(
        settings.slack.url,
        headers=settings.headers,
    ))).xpath(
        '/child::html'
        '/child::body'
        '//child::form[attribute::id="addemoji"]'
    )[0]
    form_data = dict(
        (item.attrib['name'], item.attrib['value'])
        for item in upload_form.xpath('child::input[attribute::type="hidden"]')
    )
    form_data['name'] = image.id
    form_data['mode'] = 'data'

    image_path = os.path.normpath(os.path.join(
        settings.upload_folder,
        image.filename,
    ))
    log.debug(
        'Opening "%s" for uploading',
        image_path,
    )
    with io.open(image_path, 'rb') as image_file:
        requests.post(
            settings.slack.url,
            headers=settings.headers,
            data=form_data,
            files={
                'img': image_file,
            },
        )

    return image.id


def reliably_upload(
        image,
        settings,
        log=logging.getLogger(__name__),
):
    """Reliably uploads an image"""
    log.debug('Attempting to upload "%s"', image.id)
    try:
        log.info(
            'Uploaded "%s" as "%s" successfully',
            image.filename,
            reliable_executor.reliably_execute(
                upload,
                image,
                settings,
                log=log,
            ),
        )
    except RuntimeError as runtime_error:
        log.error(
            'Uploading "%s" failed because of "%s"',
            image.id,
            runtime_error,
        )


def remove(
        images,
        settings,
        log=logging.getLogger(__name__),
):
    """Removes images contained in the list provided"""
    log.info('Removing: "%s"', ', '.join(sorted(image.id for image in images)))
    for image in images:
        requests.post(
            settings.slack.url,
            headers=settings.headers,
            data=dict(
                (item.attrib['name'], item.attrib['value'])
                for item in image.remove_form.xpath('child::input[attribute::type="hidden"]')
            ),
        )


def get_current_state(settings):
    """Gets the current state to know what to delete or what is missing"""
    image_rows = lxml.html.parse(urllib.request.urlopen(urllib.request.Request(
        settings.slack.url,
        headers=settings.headers,
    ))).xpath(
        '/child::html'
        '/child::body'
        '//child::table[attribute::id="custom_emoji"]'
        '/child::tr[attribute::class="emoji_row"]'
    )
    images = []
    for image in image_rows:
        images.append(Image(
            image.xpath('child::td[position()=2]')[0].text.strip().strip(':'),
            None,
            image.xpath('child::td[position()=4]/form')[0],
        ))
    return images


def main():
    """Main function"""
    args = argparse.ArgumentParser(
        description='Automatic slack emoji manager',
    )
    args.add_argument(
        '-s',
        '--start',
        type=int,
        default=0,
        help='ID number to start with for uploading images',
    )
    args.add_argument(
        '-f',
        '--finish',
        type=int,
        default=0,
        help='ID number to finish with for uploading images',
    )
    args.add_argument(
        '-p',
        '--profile',
        default='default',
        help='Settings profile to load [default: default]',
    )
    args.add_argument(
        '-u',
        '--upload',
        action='store_true',
        help='Enable uploading images',
    )
    args.add_argument(
        '-r',
        '--remove',
        action='store_true',
        help='Enable removing images',
    )
    args.add_argument(
        '-c',
        '--config',
        default=os.path.expanduser('~/.slack_emoji_uploader/config'),
        help='Configuration file to use when uploading [default: ~/.slack_emoji_uploader/config]',
    )
    args.add_argument(
        '-z',
        '--dry-run',
        action='store_true',
        help='Enable Dry Run mode',
    )
    args.add_argument(
        '-t',
        '--threads',
        type=int,
        default=4,
        help='Number of threads to use for uploading [default: 4]',
    )
    args.add_argument(
        '--upload-folder',
        default=os.path.dirname(__file__),
        help='Base folder for relative image paths [default: script location]',
    )
    args.add_argument(
        '-d',
        '--debug',
        action='store_const',
        default=logging.INFO,
        const=logging.DEBUG,
        help='Output debug information while running',
    )
    args = args.parse_args()

    log = logging.getLogger(__name__)
    log.level = args.debug

    settings = load_settings(args.config, args.profile, log=log)
    initial_headers = {}
    if 'browser.user_agent' in settings:
        initial_headers['User-Agent'] = settings['browser.user_agent']
    configurations = Settings(
        Slack(
            'https://{}.slack.com/customize/emoji'.format(settings['slack.team']),
            settings.get('slack.cookie') or log_in_to_slack(
                settings['slack.team'],
                initial_headers,
                log=log,
            ),
        ),
        initial_headers,
        args.upload_folder,
    )
    configurations.headers['Cookie'] = configurations.slack.cookie
    existing_images = get_current_state(configurations)

    if args.remove:
        images_to_remove = tuple(
            image
            for image in existing_images
            for image_id in range(args.start, args.finish+1)
            if '{}.id'.format(image_id) in settings.keys()
            and image.id in settings['{}.id'.format(image_id)].split('|')
        )

        if args.dry_run:
            log.info(
                'Would remove "%s"',
                ', '.join(sorted(image.id for image in images_to_remove)),
            )
        else:
            remove(images_to_remove, configurations, log=log)

        for image_to_remove in images_to_remove:
            existing_images.remove(image_to_remove)

    if args.upload:
        with concurrent.futures.ThreadPoolExecutor(args.threads) as executor:
            uploading = set()
            for image_id in range(args.start, args.finish+1):
                if '{}.id'.format(image_id) in settings.keys():
                    images = tuple(
                        Image(identifier, filename, None)
                        for identifier, filename in dict(zip(
                            settings['{}.id'.format(image_id)].split('|'),
                            (settings.get('{}.filename'.format(image_id)) or '').split('|'),
                        )).items()
                    )
                    for image in images:
                        if image.id in (image.id for image in existing_images):
                            continue
                        if len(uploading) >= args.threads:
                            uploading = concurrent.futures.wait(
                                uploading,
                                return_when=concurrent.futures.FIRST_COMPLETED
                            ).not_done
                        if args.dry_run:
                            log.info('Would upload "%s"', image.id)
                        else:
                            uploading.add(executor.submit(
                                reliably_upload,
                                image,
                                configurations,
                                log=log,
                            ))
                else:
                    log.warning(
                        'ID "%s.id" was not found in settings',
                        image_id,
                    )
            concurrent.futures.wait(uploading)

if __name__ == '__main__':
    __name__ = 'slack_emoji_uploader'
    main()
