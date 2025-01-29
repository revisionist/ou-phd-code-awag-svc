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
from copy import deepcopy

from openai import OpenAI

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.datetime import get_current_time_ms
from domestique.text import truncate_string
from domestique.convert import str_to_bool

from authentication import require_api_auth

from .shared_resources import logger, init_route, dict_from_openai_object
from .shared_resources import get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_prefix, get_dataset_meta_suffix, get_dataset_namespace_base_for_type
from .shared_resources import construct_pseudo_openai_training_entry, convert_pseudo_openai_training_entry
from .shared_resources import write_json_file, generate_timestamp_with_ms
from .shared_resources import get_mode_specific_content

from .client_mgmt_resources import get_objectstore_client, get_awagdata_client, get_openai_client_wrapper
from .openai_object_manager import OpenAIObjectManager, ObjectType
from .awag_evaluation_request_generator import AwAgEvaluationRequestGenerator
from .awag_evaluation_processor import AwAgEvaluationProcessor

gentraining_routes = Blueprint('gentraining_routes', __name__)

awagdata_clients = {}


@gentraining_routes.before_request
def before_request():
  
    g.objectstore_ft_namespace_prefix = current_app.config["OBJECTSTORE_FT_NAMESPACE_PREFIX"]
    g.evaluation_system_message_common = current_app.config["AWAG_SYSTEM_MESSAGE_COMMON"]
    g.evaluation_system_message_extra_mode1 = current_app.config["AWAG_SYSTEM_MESSAGE_EXTRA_MODE1"]
    g.evaluation_system_message_extra_mode2 = current_app.config["AWAG_SYSTEM_MESSAGE_EXTRA_MODE2"]
    g.evaluation_system_message_extra_mode3 = current_app.config["AWAG_SYSTEM_MESSAGE_EXTRA_MODE3"]
    g.training_item_user_message_premable_mode1 = current_app.config["EVALUATION_USER_MESSAGE_MODE1"]
    g.training_item_user_message_premable_mode2 = current_app.config["EVALUATION_USER_MESSAGE_MODE2"]
    g.training_item_user_message_premable_mode3 = current_app.config["EVALUATION_USER_MESSAGE_MODE3"]
    g.evaluation_request_schema = current_app.config["EVALUATION_REQUEST_SCHEMA"]
    g.evaluation_result_schema_mode1 = current_app.config["EVALUATION_RESULT_SCHEMA_MODE1"]
    g.evaluation_result_schema_mode2 = current_app.config["EVALUATION_RESULT_SCHEMA_MODE2"]
    g.evaluation_result_schema_mode3 = current_app.config["EVALUATION_RESULT_SCHEMA_MODE3"]
    g.evaluation_default_model = current_app.config["OPENAI_ENGINE"]

    g.training_item_user_message_example_mode2 = current_app.config["EVALUATION_USER_MESSAGE_EXAMPLE_MODE2"]
    g.training_item_user_message_example_mode3 = current_app.config["EVALUATION_USER_MESSAGE_EXAMPLE_MODE3"]

    g.trace_file_path = None
    awag_trace_file_path = current_app.config["AWAG_TRACE_FILE_PATH"]
    if awag_trace_file_path:
        if os.path.exists(awag_trace_file_path) and os.access(awag_trace_file_path, os.W_OK):
            gentrain_dir_path = os.path.join(awag_trace_file_path, "gentrain")
            os.makedirs(gentrain_dir_path, exist_ok=True)
            g.trace_file_path = gentrain_dir_path


def log_exception(CLIENT_ID, e):

    message = f"An error occurred for CLIENT_ID '{CLIENT_ID}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


def split_request(mode, evaluation_request, is_create_permutations=False):

    if mode == "mode1":
        # is_create_permutations is ignored for mode1
        return split_request_mode1(evaluation_request)
    elif mode in ["mode2", "mode3"]:
        split_requests = split_request_mode2(evaluation_request)
        if is_create_permutations:
            logger.debug(f"Will create permutations")
            split_requests_with_perm = create_request_permutations_mode2(split_requests)
            for req in split_requests_with_perm:
                logger.debug(f"Will create permutations")
                item0 = req["items"][0]
                ids = item0["id"]
                logger.debug(f"{ids['itemId']} permutation classification_name: {ids['classificationId']} classified_as: {item0['classification']['classifiedAs']}")
            return split_requests_with_perm
        else:
            return split_requests
    else:
        raise ValueError(f"Invalid mode: {mode}")


def split_request_mode1(evaluation_request):

    # Not currently splitting mode1

    return [deepcopy(evaluation_request)]


def split_request_mode2(evaluation_request):

    logger.debug(f"Splitting MODE2 evaluation_request: {evaluation_request}")

    split_requests = []
    template_request = deepcopy(evaluation_request)
    template_request["items"] = []

    for item in evaluation_request["items"]:
        split_request = deepcopy(template_request)
        split_request["items"] = [item]
        split_requests.append(split_request)
        logger.debug(f"Got split evaluation_request: {split_request}")

    return split_requests


def create_request_permutations_mode2(evaluation_requests):

    logger.debug(f"Creating permutations for evaluation_requestS: {evaluation_requests}")

    output_requests = []

    for evaluation_request in evaluation_requests:

        logger.debug(f"Creating permutations for evaluation_request: {evaluation_request}")

        for item in evaluation_request["items"]:

            ids = item["id"]
            item_id = ids["itemId"]
            classification_name = ids["classificationId"]
            originally_classified_as = item["classification"]["classifiedAs"]
            logger.debug(f"Processing item: {item_id} {classification_name} {originally_classified_as}")

            if not originally_classified_as:
                raise ValueError(f"Did not get classifiedAs from item: {item}")
            available_classifications = item["classification"]["fromAvailableClassifications"]
            if not available_classifications:
                raise ValueError(f"Did not get fromAvailableClassifications from item: {item}")

            for this_available_classification in available_classifications:

                copy_request = deepcopy(evaluation_request)
                copy_item = deepcopy(item)

                if originally_classified_as == this_available_classification:
                    logger.debug("MATCH")
                    copy_request["items"] = [item]
                else:
                    logger.debug("NOT MATCH")
                    copy_item["classification"]["classifiedAs"] = this_available_classification
                    copy_request["items"] = [copy_item]

                logger.debug(f"Permutation classification_name: {classification_name} classified_as: {this_available_classification} (originally: {originally_classified_as})")
                #logger.debug(f"Appending output_request permutation:\n{copy_item}")

                output_requests.append(copy_request)

    logger.debug(f"Returning {len(output_requests)} output_requests")

    return output_requests


def process_eval_output(mode, evaluation_request, evaluation_results, is_save_output=False, output_path=None):

    return_items = []

    if mode == "mode1":
        training_item_tuples = process_eval_output_mode1(evaluation_request, evaluation_results)
    elif mode in ["mode2", "mode3"]:
        training_item_tuples = process_eval_output_mode2_mode3(mode, evaluation_request, evaluation_results)
    else:
        raise ValueError(f"Invalid mode: {mode}")

    for training_item_tuple in training_item_tuples:

        training_item_identifier, training_item = training_item_tuple
        return_items.append(training_item)

        if is_save_output:
            write_json_file(output_path, f"{training_item_identifier}.json", training_item)

    return return_items


def process_eval_output_mode1(evaluation_request, evaluation_results):

    logger.debug("Generating MODE1 output for item")

    # Not doing any clever processing with mode1, just output the results

    training_item_tuples = []

    for evaluation_result in evaluation_results:

        # We actually only expect one evaluation_result but in any case...
        #logger.debug(f"evaluation_result:\n{evaluation_result}")

        user_messages_trn_mode_1 = [
            g.training_item_user_message_premable_mode1,
            evaluation_request
        ]

        # generated_request should have exactly one item
        item_id = evaluation_request["items"][0]["itemId"]
        if not item_id:
            raise ValueError(f"Could not get item_id from evaluation_request: {evaluation_request}")

        training_item = construct_pseudo_openai_training_entry(g.evaluation_system_message_common, user_messages_trn_mode_1, evaluation_result)

        training_item_tuples.append((item_id, training_item))

        return training_item_tuples


def process_eval_output_mode2_mode3(mode, evaluation_request, evaluation_results):

    if mode == "mode2":
        logger.debug("Generating MODE2 output for item")
        training_item_user_message_premable = g.training_item_user_message_premable_mode2
    elif mode == "mode3":
        logger.debug("Generating MODE3 output for item")
        training_item_user_message_premable = g.training_item_user_message_premable_mode3
    else:
        raise ValueError(f"Invalid mode: {mode}")

    training_item_tuples = []

    for item in evaluation_request["items"]:

        ids = item["id"]
        item_id = ids["itemId"]
        logger.debug(f"Processing item '{item_id}': {item}")

        classification_name = ids["classificationId"]
        perspective_id = ids["perspectiveId"]

        classification = item["classification"]
        request_classified_as = classification["classifiedAs"]

        matched_item = None

        for evaluation_result in evaluation_results:

            result_ids = evaluation_result["id"]
            result_item_id = result_ids["itemId"]
            result_evaluated_selection = evaluation_result.get("evaluatedSelection", None)
            if not result_evaluated_selection:
                logger.debug(f"Result item did not contain evaluatedSelection! {item}")
                continue

            if result_item_id == item_id and perspective_id == result_ids["perspectiveId"] and classification_name == result_ids["classificationId"] and request_classified_as == result_evaluated_selection:
                matched_item = evaluation_result
                logger.debug(f"Got matching request item for result item with id '{result_item_id}': {matched_item}")

        if not matched_item:

            logger.error(f"Did not find matching request item for result item with id: {result_item_id}")
            logger.error(f"Value of evaluation_request: {evaluation_request}")
            logger.error(f"Value of evaluation_results: {evaluation_results}")

        else:
        
            matched_item_evaluated_selection = matched_item["evaluatedSelection"]
            
            if not request_classified_as == matched_item_evaluated_selection:
                logger.error(f"MISMATCH - request_classified_as != matched_item_evaluated_selection : {request_classified_as}/{matched_item_evaluated_selection}")
                logger.error(f"MISMATCH - item: {item}")
                logger.error(f"MISMATCH - matched_item: {matched_item}")
        
            user_message_part = deepcopy(evaluation_request)
            user_message_part["items"] = [item]
            user_messages_trn = [
                training_item_user_message_premable,
                user_message_part
            ]
            training_item = construct_pseudo_openai_training_entry(g.evaluation_system_message_common, user_messages_trn, matched_item)

            training_item_identifier = f"{item_id}~{mode}~{perspective_id}~{classification_name}-{matched_item_evaluated_selection}"

            logger.debug(f"Appending training item with identifier: {training_item_identifier}")
            training_item_tuples.append((training_item_identifier, training_item))

        return training_item_tuples


def ensure_dir_exists(path):

    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def is_writable(path):

    return os.access(path, os.W_OK)


def check_and_prepare_path(base_path, client_id, mode):

    if base_path:
        if not is_writable(base_path):
            raise ValueError(f"Path is not writable: {base_path}")
        path = os.path.join(base_path, client_id, mode)
        ensure_dir_exists(path)
        return path, True
    return None, False


@gentraining_routes.route('/eval', methods=['POST'])
@require_api_auth
def generate_eval_training_data():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        mode = get_reqjson_val(reqjson, "mode", "mode2")

        server_path = get_reqjson_val(reqjson, "server_path", None)
        quantity = get_reqjson_val(reqjson, "quantity", 10)
        sim_text_category = get_reqjson_val(reqjson, "category", None)

        persona = get_reqjson_val(reqjson, "persona", None)
        perspectives = get_reqjson_val(reqjson, "perspectives", None)
        classifications = get_reqjson_val(reqjson, "classifications", None)
        originator_text = get_reqjson_val(reqjson, "originator_text", None)
        model = get_reqjson_val(reqjson, "model", None)
        openai_params = get_reqjson_val(reqjson, "openai_params", {})

        logger.debug(f"server_path: {server_path}; quantity: {quantity}; sim_text_category: {sim_text_category}; originator_text: {originator_text}; mode: {mode}")

        evaluation_system_message_extra, evaluation_result_schema, evaluation_user_messages = get_mode_specific_content(mode, reqjson)

        if quantity < 1:
            return resp.generate_response_with_data(f"No content - request was for {quantity} items", 204)

        output_path, is_save_output = check_and_prepare_path(server_path, CLIENT_ID, mode)
        trace_path, is_save_trace = check_and_prepare_path(g.trace_file_path, CLIENT_ID, mode)

        openai_auth_token = request.headers.get('OpenAI-Auth-Token', current_app.config['OPENAI_AUTH_TOKEN'])
        openai_client = get_openai_client_wrapper(openai_auth_token)
        awagdata_client = get_awagdata_client(awagdata_clients, CLIENT_ID)

        request_generator = AwAgEvaluationRequestGenerator(
                                openai_client=openai_client,
                                awagdata_client=awagdata_client,
                                flask_app=current_app._get_current_object())

        evaluation_processor = AwAgEvaluationProcessor(
                                client_id=CLIENT_ID,
                                openai_client=openai_client,
                                mode=mode,
                                evaluation_system_message_common=g.evaluation_system_message_common,
                                evaluation_system_message_extra=evaluation_system_message_extra,
                                evaluation_request_schema=g.evaluation_request_schema,
                                evaluation_result_schema=evaluation_result_schema,
                                evaluation_user_messages=evaluation_user_messages,
                                default_model=g.evaluation_default_model,
                                flask_app=current_app._get_current_object())

        training_items = []

        for i in range(quantity):

            logger.debug(f"Item {i+1} of {quantity}")

            generated_request = request_generator.generate_request_with_random_classifications(
                        sim_text_category=sim_text_category,
                        persona=persona,
                        perspectives=perspectives,
                        classifications=classifications,
                        source_originator=originator_text,
                        mode=mode)

            logger.debug(f"GENERATED REQUEST: {generated_request}")

            split_requests = split_request(mode, generated_request, is_create_permutations=True)

            info = []

            for eval_request in split_requests:

                logger.debug(f"Processing split request: {eval_request}")

                evaluation_results, info_json = evaluation_processor.get_evaluation(
                        eval_request=eval_request,
                        model=model,
                        openai_params=openai_params)
                #logger.debug(f"evaluation_results:\n{evaluation_results}")

                if is_save_trace:
                    file_prefix = f"gentrain_{mode}_{generate_timestamp_with_ms()}"
                    write_json_file(trace_path, f"{file_prefix}_request.json", eval_request)
                    write_json_file(trace_path, f"{file_prefix}_response.json", evaluation_results)
                    write_json_file(trace_path, f"{file_prefix}_info.json", info_json)

                info.append(info_json)

                training_items_from_request = process_eval_output(mode, eval_request, evaluation_results, is_save_output, output_path)
                logger.debug(f"Got {len(training_items_from_request)} training items from request: {eval_request}")
                training_items.append(training_items_from_request)

        response_json = {
            "status": "OK",
            "message": "Items generated successfully",
            "info": info 
            }

        if not is_save_output:
            response_json["data"] = training_items

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

