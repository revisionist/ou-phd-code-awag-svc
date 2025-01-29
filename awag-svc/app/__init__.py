# BSD 3-Clause Clear License
#
# Copyright (c) 2023-2025, David Goddard. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions, and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions, and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY
# THIS LICENSE. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER
# OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# This file includes code based on boilerplate from Idris Rampurawala,
# originally under the MIT License. Original boilerplate code Copyright 2020
# by Idris Rampurawala. The full text of the MIT License for the original
# boilerplate code can be found in the accompanying file named
# 'LICENSE-MIT' or at https://opensource.org/licenses/MIT.

import logging.config
from os import environ

#import sys
#import pkg_resources
#print(sys.path)
#print(list(pkg_resources.working_set))
#print(sys.modules.keys())

from celery import Celery
from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

# https://github.com/revisionist/python-utils/tree/main/domestique
from domestique.db import sqlite


from .config import config as app_config

celery = Celery(__name__)


def create_app():

    load_dotenv()
    APPLICATION_ENV = get_environment()

    logging.config.dictConfig(app_config[APPLICATION_ENV].LOGGING)

    app = Flask(app_config[APPLICATION_ENV].APP_NAME)

    app.config.from_object(app_config[APPLICATION_ENV])

    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    db_file_path = app.config['SQLITE_DATABASE_FILE']
    sqlite.configure_db(db_file_path)

    CORS(app, resources={r'/api/*': {'origins': '*'}})

    celery.config_from_object(app.config, force=True)
    # celery is not able to pick result_backend and hence using update
    celery.conf.update(result_backend=app.config['RESULT_BACKEND'])

    from .awag.views import awag_ml as awag_ml_blueprint
    app.register_blueprint(
        awag_ml_blueprint,
        url_prefix='/api/v1/awag/ml'
    )

    from .awag.data import awag_data as awag_data_blueprint
    app.register_blueprint(
        awag_data_blueprint,
        url_prefix='/api/v1/awag/data'
    )

    return app


def get_environment():
    return environ.get('APPLICATION_ENV') or 'development'
