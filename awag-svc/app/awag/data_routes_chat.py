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
import time
import types
import requests
import tempfile
import os

from flask import Blueprint, current_app, g, jsonify, request, make_response

from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.datetime import get_current_time_ms
from domestique.text import truncate_string
from domestique.convert import str_to_bool
from domestique.identifiers import generate_id

from authentication import require_api_auth

from .shared_resources import logger, init_route
from .client_mgmt_resources import get_objectstore_client, get_awagdata_client, get_openai_client_wrapper
from .chat_handler import OpenAIChatHandler

chat_routes = Blueprint('chat_routes', __name__)

chat_handlers = {}
objectstore_clients = {}
awagdata_clients = {}


@chat_routes.before_request
def before_request():

    g.objectstore_ft_namespace_prefix = current_app.config["OBJECTSTORE_FT_NAMESPACE_PREFIX"]
    g.chat_system_message = current_app.config["CHAT_SYSTEM_MESSAGE"]
    g.chat_history_limit = current_app.config["CHAT_HISTORY_LIMIT"]
    g.defalt_model = current_app.config["CHAT_OPENAI_MODEL"]


def log_exception(CLIENT_ID, e):

    message = f"An error occurred for CLIENT_ID '{CLIENT_ID}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


def get_chat_handler(client_id, conversation_id):

    if conversation_id in chat_handlers:

        return chat_handlers[conversation_id]

    else:

        objectstore_client = get_objectstore_client(objectstore_clients, client_id)
        openai_client_wrapper = get_openai_client_wrapper()
        chat_handler = OpenAIChatHandler(
                g.objectstore_ft_namespace_prefix,
                objectstore_client,
                openai_client_wrapper,
                g.chat_system_message,
                g.chat_history_limit
                )
        chat_handlers[conversation_id] = chat_handler

        return chat_handler


@chat_routes.route('/ask', methods=['POST'])
@require_api_auth
def do_chat():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        chat_request = get_required_reqjson_val(reqjson, "chat_request")
        conversation_id = get_reqjson_val(reqjson, "conversation_id", None)
        model_id = get_reqjson_val(reqjson, "model", g.defalt_model)
        is_reset_conversation = request.args.get('reset_conversation', type=str_to_bool, default=False)

        if is_reset_conversation and conversation_id:
            chat_handlers.pop(conversation_id, None)
            conversation_id = generate_id()

        if not conversation_id:
            conversation_id = generate_id()

        chat_handler = get_chat_handler(CLIENT_ID, conversation_id)

        chat_response, info_json = chat_handler.get_chat_reponse(chat_request, model_id)

        message = f"Got chat response for conversation: {conversation_id}"

        response_json = {
            "status": "OK",
            "message": message,
            "chat_request": chat_request,
            "chat_response": chat_response,
            "conversation_id": conversation_id,
            "info_json": info_json,
            "current_time_ms": get_current_time_ms(),
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

