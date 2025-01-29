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

import json

from os import environ, path
from dotenv import load_dotenv
from .resource_loader import ResourceLoader


basedir = path.abspath(path.join(path.dirname(__file__), '..'))

load_dotenv()


class BaseConfig(object):

    resource_dir = path.join(path.dirname(__file__), 'resources')
    resource_loader = ResourceLoader(resource_dir=resource_dir)

    # General config

    APP_NAME = environ.get('APP_NAME') or 'awag-svc'

    api_auth_str = environ.get('API_AUTH', '{}')
    API_AUTH = json.loads(api_auth_str)

    ORIGINS = ['*']
    EMAIL_CHARSET = 'UTF-8'
    API_KEY = environ.get('API_KEY')
    BROKER_URL = environ.get('BROKER_URL')
    RESULT_BACKEND = environ.get('RESULT_BACKEND')

    # Logging and tracing

    LOG_INFO_FILE = environ.get('AWAG_LOG') or path.join(basedir, 'log', 'awag-svc-info.log')
    LOG_CELERY_FILE = environ.get('AWAG_CELERY_LOG') or path.join(basedir, 'log', 'awag-svc-celery.log')

    AWAG_TRACE_FILE_PATH = environ.get('AWAG_TRACE_FILE_PATH') or '/data/awag/trace'

    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '[%(asctime)s] - %(levelname)s - %(module)s - %(funcName)s - '
                '%(message)s',
                'datefmt': '%b %d %Y %H:%M:%S'
            },
            'aligned': {
                'format': '[%(asctime)s] [%(module)18s] [%(funcName)10s:%(lineno)s] --- %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'simple': {
                'format': '%(module)s - %(funcName)s - %(message)s'
            },
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'simple'
            },
            'log_info_file': {
                'level': 'DEBUG',
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': LOG_INFO_FILE,
                'maxBytes': 16777216,  # 16megabytes
                'formatter': 'aligned',
                'backupCount': 5
            },
        },
        'loggers': {
            '': {  # This is the root logger
                'handlers': ['console'],
                'level': 'WARN',
                'propagate': True
            },
            APP_NAME: {
                'level': 'DEBUG',
                'handlers': ['log_info_file'],
                'propagate': False
            },
            'domestique': {
                'handlers': ['log_info_file'],
                'level': 'DEBUG',
                'propagate': False
            },
        }
    }

    CELERY_LOGGING = {
        'format': '[%(asctime)s] - %(name)s - %(levelname)s - '
        '%(message)s',
        'datefmt': '%b %d %Y %H:%M:%S',
        'filename': LOG_CELERY_FILE,
        'maxBytes': 10000000,  # 10megabytes
        'backupCount': 5
    }

    DEFAULT_DATA_ID = environ.get('DEFAULT_DATA_ID') or 'default'

    # Namespace prefix in Objexct Store to use for OpenAI fine-tuning related data
    OBJECTSTORE_FT_NAMESPACE_PREFIX = environ.get('OBJECTSTORE_FT_NAMESPACE_PREFIX') or 'openai_ft_'

    # Common URLs

    # Note that parts of this application make REST calls back to other parts to obtain data etc.
    # These do not need to be externally resolvable and it's likely more efficient if these are local

    REST_BASE_URL_AWAGDATA = environ.get('REST_BASE_URL_AWAGDATA') or 'http://LOCALHOST:5000/api/v1/awag/data'
    REST_BASE_URL_AWAGML = environ.get('REST_BASE_URL_AWAGML') or 'http://LOCALHOST:5000/api/v1/awag/ml'
    REST_BASE_URL_OBJECTSTORE = environ.get('REST_BASE_URL_OBJECTSTORE') or 'http://LOCALHOST:5000/svc/v1/objectstore'


    # OpenAI configuration

    REST_BASE_URL_OPENAI = environ.get('REST_BASE_URL_OPENAI') or 'https://api.openai.com/v1'

    OPENAI_AUTH_TOKEN = environ.get('OPENAI_AUTH_TOKEN') or environ.get('OPENAI_API_KEY') or None
    OPENAI_ENGINE_LEGACY = environ.get('OPENAI_ENGINE_LEGACY') or 'text-davinci-003'
    OPENAI_ENGINE = environ.get('OPENAI_ENGINE') or 'gpt-4o'


    # Items for awagml

    CONTAINER_PATH_ROOT = environ.get('CONTAINER_PATH_ROOT') or '/data/awag/ml/sklearn/live/'
    CONTAINER_SUBDIR_MODELS = environ.get('CONTAINER_SUBDIR_MODELS') or 'models'
    CONTAINER_SUBDIR_TRAIN = environ.get('CONTAINER_SUBDIR_TRAIN') or 'train'
    CONTAINER_SUBDIR_TEST = environ.get('CONTAINER_SUBDIR_TEST') or 'test'

    MODELS_METADATA_FILENAME = environ.get('MODELS_METADATA_FILENAME') or 'models_metadata.json'

    CONTAINER_PATH_DELETED = environ.get('CONTAINER_PATH_DELETED') or '/data/awag/ml/sklearn/deleted/'

    SQLITE_DATABASE_FILE = environ.get('SQLITE_DATABASE_FILE') or '/data/awag/db/awag_sqlite.db'


    # Items for Evaluation

    AWAG_SYSTEM_MESSAGE_COMMON = resource_loader.load_text('AWAG_SYSTEM_MESSAGE_COMMON')

    AWAG_SYSTEM_MESSAGE_EXTRA_MODE1 = resource_loader.load_text('AWAG_SYSTEM_MESSAGE_EXTRA_MODE1')
    AWAG_SYSTEM_MESSAGE_EXTRA_MODE2 = resource_loader.load_text('AWAG_SYSTEM_MESSAGE_EXTRA_MODE2')

    AWAG_SYSTEM_MESSAGE_EXTRA_MODE3 = environ.get('AWAG_SYSTEM_MESSAGE_EXTRA_MODE3') or AWAG_SYSTEM_MESSAGE_EXTRA_MODE2

    EVALUATION_USER_MESSAGE_COMMON_LIKERT = resource_loader.load_text('EVALUATION_USER_MESSAGE_COMMON_LIKERT')

    EVALUATION_USER_MESSAGE_BASE_MODE1 = resource_loader.load_text('EVALUATION_USER_MESSAGE_BASE_MODE1')
    EVALUATION_USER_MESSAGE_MODE1 = f"{EVALUATION_USER_MESSAGE_BASE_MODE1}\n{EVALUATION_USER_MESSAGE_COMMON_LIKERT}"

    EVALUATION_USER_MESSAGE_BASE_MODE2 = resource_loader.load_text('EVALUATION_USER_MESSAGE_BASE_MODE2')
    EVALUATION_USER_MESSAGE_MODE2 = f"{EVALUATION_USER_MESSAGE_BASE_MODE2}\n{EVALUATION_USER_MESSAGE_COMMON_LIKERT}"

    EVALUATION_USER_MESSAGE_MODE3 = resource_loader.load_text('EVALUATION_USER_MESSAGE_MODE3')

    EVALUATION_USER_MESSAGE_EXAMPLE_MODE2 = resource_loader.load_text('EVALUATION_USER_MESSAGE_EXAMPLE_MODE2')
    EVALUATION_USER_MESSAGE_EXAMPLE_MODE3 = resource_loader.load_text('EVALUATION_USER_MESSAGE_EXAMPLE_MODE3')

    # Mode 1 schema
    EVALUATION_REQUEST_SCHEMA = resource_loader.load_json('classification-evaluation-request.schema')

    # Mode 2/3 schema (not used, for reference only)
    EVALUATION_REQUEST_ALT_SCHEMA = resource_loader.load_json('classification-evaluation-request.alt.schema')

    EVALUATION_RESULT_SCHEMA_MODE1 = resource_loader.load_json('classification-evaluation-result.mode1.schema')
    EVALUATION_RESULT_SCHEMA_MODE2 = resource_loader.load_json('classification-evaluation-result.mode2.schema')
    EVALUATION_RESULT_SCHEMA_MODE3 = resource_loader.load_json('classification-evaluation-result.mode3.schema')


    # Items for Evaluation (fine-tuning)

    # Used with DatasetManager.process_classification_actions() [as called from data_routes_train.populate_dataset_from_actions()] where we currently use only process a subset of an eval item to create each training entry in the dataset
    EVALUATION_USER_MESSAGE_ALT_1 = resource_loader.load_text('EVALUATION_USER_MESSAGE_ALT_1')


    # Items for simulation (synthetic content)

    CHAT_SYSTEM_MESSAGE = AWAG_SYSTEM_MESSAGE_COMMON
    CHAT_HISTORY_LIMIT = environ.get('CHAT_HISTORY_LIMIT') or 50
    CHAT_OPENAI_MODEL = environ.get('CHAT_OPENAI_MODEL') or 'gpt-3.5-turbo'


    # Items for simulation (synthetic content)

    SIMULATION_MESSAGES_PROMPT_TEMPLATE = resource_loader.load_text('SIMULATION_MESSAGES_PROMPT_TEMPLATE')

    SIMULATION_MESSAGES_RESULT_SCHEMA = resource_loader.load_json('simulation-messages-result.schema')
    SIMULATION_DRAMATIS_PERSONAE_SCHEMA = resource_loader.load_json('simulation-dramatis-personae.schema')
    SIMULATION_ENTITIES_SCHEMA = resource_loader.load_json('simulation-entities.schema')


    # Items for reporting/stats
    
    agent_lookup_str = environ.get('AGENT_LOOKUP', '{}')
    AGENT_LOOKUP = json.loads(agent_lookup_str)
    #AGENT_LOOKUP={"example-agent-uuid":"example"}

    STATS_NOTES = resource_loader.load_json('STATS_NOTES')


class Development(BaseConfig):
    ''' Development config. '''

    DEBUG = True
    ENV = 'dev'


class Staging(BaseConfig):
    ''' Staging config. '''

    DEBUG = True
    ENV = 'staging'


class Production(BaseConfig):
    ''' Production config '''

    DEBUG = False
    ENV = 'production'


config = {
    'development': Development,
    'staging': Staging,
    'production': Production,
}
