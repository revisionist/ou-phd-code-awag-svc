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
import sqlite3
import requests

from flask import Blueprint, current_app, g, jsonify, request, make_response

from datetime import datetime, timedelta

from domestique.logging import log_exception
from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.json import get_dict_from_dict_or_json_str
from domestique.convert import str_to_bool

from authentication import require_api_auth

from .shared_resources import logger, init_route
from .client_mgmt_resources import get_openai_client_wrapper, get_awagdata_client

from .simulation_manager import SimulationManager


simulation_routes = Blueprint('simulation_routes', __name__)

simulation_managers = {}
awagdata_clients = {}


def init_db_tables():

    # Note that init_db_tables is performed in SimulationManager!

    pass


def store_simulation_manager(job_id, simulation_manager):

    global simulation_managers

    if job_id:
        simulation_managers[job_id] = simulation_manager

    return simulation_manager


def get_simulation_manager(agent_id, openai_auth_token=None, job_id=None):

    global simulation_managers

    if job_id:
        if job_id in simulation_managers:
            logger.debug(f"Returning EXISTING simulation manager for job_id: {job_id}")
            return simulation_managers[job_id]
        else:
            logger.debug(f"Got NO simulation manager for job_id: {job_id}")
            return None

    logger.debug(f"Creating NEW simulation manager for job_id: {job_id}")

    awagdata_client = get_awagdata_client(awagdata_clients, agent_id)

    manager = SimulationManager(
                    current_app.config,
                    agent_id,
                    awagdata_client,
                    openai_auth_token=openai_auth_token,
                    flask_app=current_app._get_current_object())

    if job_id:
        logger.debug(f"Storing simulation manager for job_id: {job_id}")
        store_simulation_manager(job_id, manager)

    return manager


@simulation_routes.route('/get-dummy-text', methods=['GET'])
@simulation_routes.route('/get-sim-text', methods=['GET'])
@simulation_routes.route('/get-all-sim-texts', methods=['GET'])
@require_api_auth
def get_sim_text():

    agent_id, resp, _ = init_route(request)

    try:

        item_category = get_required_arg(request, "category")
        item_id = get_arg(request, "item_id", None)

        is_get_all = False
        if request.path.endswith('/get-all-sim-texts'):
            is_get_all = True
            if item_id:
                raise ValueError("Must not pass item_id to /get-all-sim-texts")
        else:
            is_get_all = request.args.get("is_get_all", type=str_to_bool, default=False)

        simulation_manager = get_simulation_manager(agent_id)

        if is_get_all:
            response_json = simulation_manager.get_all_sim_texts(item_category)
        else:
            response_json = simulation_manager.get_sim_text(item_category, item_id)

        return resp.generate_response_with_data(response_json, response_json.get("code", 500))

    except Exception as e:

        return resp.generate_response_with_exception(e)


@simulation_routes.route('/add-sim-text', methods=['POST'])
@require_api_auth
def add_sim_text():

    agent_id, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        if isinstance(reqjson, list):
            items = reqjson
        else:
            items = [reqjson]
        
        logger.debug(f"Items: {items}")

        simulation_manager = get_simulation_manager(agent_id)
        response_json = simulation_manager.insert_items(items)

        return resp.generate_response_with_data(response_json, response_json.get("code", 500))

    except Exception as e:

        return resp.generate_response_with_exception(e)


@simulation_routes.route('/gen-sim-text', methods=['POST'])
@simulation_routes.route('/gen-and-add-sim-text', methods=['POST'])
@require_api_auth
def generate_sim_text():

    agent_id, resp, _ = init_route(request)

    openai_request_json = None

    try:

        reqjson = get_reqjson(request)

        is_add = False
        if request.path.endswith('/gen-and-add-sim-text'):
            is_add = True
        else:
            is_add = request.args.get("is_add", type=str_to_bool, default=False)

        is_async = request.args.get("is_async", type=str_to_bool, default=False)

        item_count = int(get_arg(request, "item_count", 1))

        topics = get_required_reqjson_val(reqjson, "topics")

        is_use_history = get_reqjson_val(reqjson, "use_history", False)

        dramatis_personae = get_reqjson_val(reqjson, "dramatis_personae", None)
        entities = get_reqjson_val(reqjson, "entities", None)
        openai_params = get_reqjson_val(reqjson, "openai_params", None)
        openai_model = get_reqjson_val(reqjson, "openai_model", None)

        openai_auth_token = request.headers.get('OpenAI-Auth-Token', current_app.config['OPENAI_AUTH_TOKEN'])

        simulation_manager = get_simulation_manager(agent_id, openai_auth_token=openai_auth_token, job_id=None)

        prompt_template = current_app.config['SIMULATION_MESSAGES_PROMPT_TEMPLATE']

        job_id, response_json = simulation_manager.generate_simulated_texts(is_add, topics, item_count, prompt_template, dramatis_personae=dramatis_personae, entities=entities, openai_params=openai_params, openai_model=openai_model, is_async=is_async, is_use_history=is_use_history)

        store_simulation_manager(job_id, simulation_manager)

        return resp.generate_response_with_data(response_json, response_json.get("code", 500))

    except Exception as e:

        return resp.generate_response_with_exception(e)


@simulation_routes.route('/jobs/<job_id>', methods=['GET'])
@require_api_auth
def job_query(job_id):

    agent_id, resp, _ = init_route(request)

    try:
 
        manager = get_simulation_manager(agent_id, openai_auth_token=None, job_id=job_id)

        job_status = None
        if manager is not None:
            job_status = manager.get_job_status(job_id)

        if job_status:
            return resp.generate_response_with_data(job_status, 200)
        else:
            return resp.generate_response_with_data(f"Job not found with id: {job_id}", 404)

    except Exception as e:

        return resp.generate_response_with_exception(e)
