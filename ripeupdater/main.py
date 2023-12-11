#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
This module contains HTTP-Service based on Flask, which update RIPE Inetnum &
Inet6num automatically.
It catches webhooks from NetBox and initializes HTTP queries also to NetBox, to build at the end
a valid RIPE Object.
"""
import os

from flask import Flask, abort, request, render_template
from flask.logging import default_handler

from .backup_manager import BackupManager
from .log_manager import LogManager
from .netbox import ObjectBuilder
from .ripe import RipeObjectManager
from .exceptions import (RipeUpdaterException, NotRoutedNetwork, ErrorSmallPrefix)
from .configuration import *

logmgr = LogManager()
logger = logmgr.logger

# Initialize Flask and giving the application a name 'app'
logger.info('Initialize App')

app = Flask(__name__)
app.logger.removeHandler(default_handler)
app.logger.addHandler(logger)
backup = BackupManager()


@app.route('/health')
def check_health():
    logger.debug('calling /health')
    return 'Ok'


@app.route('/backups')
def list_backups():
    logger.info('list backups')
    return render_template('backups.html', backups=backup.list())


@app.route('/backup/<name>')
def get_backup(name):
    logger.info('get backup')
    return backup.get(name)


@app.route('/update', methods=['POST'])
def update():
    """
    /update is a route which accepts JSON HTTP requests and returns 200
    if the incoming webhook is prefix.
    """
    if request.headers.get('Authorisation') != UPDATE_TOKEN:
        logger.error('token missmatch')
        abort(401)

    logger.info('Update route is runnning and waiting to catch prefixes...')

    # Content-Type: application/json
    webhook = request.json
    if webhook is None:
        msg = 'request payload must be application/json'
        logger.error(msg)
        return msg, 400

    # ensure valid netbox request
    try:
        if webhook['model'] != 'prefix':
            msg = 'only prefixes are supported'
            logger.error(msg)
            return msg, 400
    except KeyError as e:
        msg = f'not a valid netbox request. Key not found: {e}'
        logger.error(msg)
        return msg, 400

    # ensure presence of custom fields
    try:
        data = webhook['data']
        custom_fields = data['custom_fields']
        ripe_report = custom_fields['ripe_report']
    except (KeyError, TypeError) as e:
        msg = f'missing custom fields. {type(e)}: {e}'
        logger.error(msg)
        return msg, 400

    try:
        # If the webhook event is deleted or ripe_report is DELETE,
        # delete the object
        if webhook['event'] == 'deleted' or ripe_report == "DELETE":
            logger.info(f"prefix deleted in NetBox, deleting prefix {webhook['data']['prefix']} in RIPE DB")
            netbox_object = ObjectBuilder(webhook)
            ripe = RipeObjectManager(netbox_object, backup)
            ripe.delete_object()
            return '', 204
        # If ripe_report is No, do nothing
        if ripe_report == "NO" or ripe_report is None:
            logger.info(f"ripe_report is NO or not defined, doing nothing!")
        elif ripe_report == "YES":
            logger.info(f"updating prefix {webhook['data']['prefix']}")
            netbox_object = ObjectBuilder(webhook)
            ripe = RipeObjectManager(netbox_object, backup)
            ripe.push_object()
        else:
            logger.info("No match, something went wrong!")
    except NotRoutedNetwork:
        return 'NotRoutedNetwork, skipping request', 200
    except ErrorSmallPrefix:
        return 'ErrorSmallPrefix, skipping request', 200
    except RipeUpdaterException as err:
        return f'{err=}', 500

    return '', 204
