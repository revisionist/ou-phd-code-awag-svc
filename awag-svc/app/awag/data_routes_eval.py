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

from flask import Blueprint, current_app, g, jsonify, request

from datetime import datetime, timedelta
from collections import defaultdict

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.convert import str_to_bool, extract_object_by_property, get_value_from_dict

from authentication import require_api_auth

from .client_mgmt_resources import get_awagdata_client, get_openai_client_wrapper
from .awag_evaluation_processor import AwAgEvaluationProcessor

from .shared_resources import *

evaluation_routes = Blueprint('evaluation_routes', __name__)


awagdata_clients = {}
evaluation_processors  = {}


def store_evaluation_processor(mode, job_id, evaluation_processor):

    global evaluation_processors

    if job_id:
        evaluation_processors[(mode, job_id)] = evaluation_processor

    return evaluation_processor


def get_evaluation_processor(client_id, mode, openai_auth_token=None, job_id=None, reqjson=None):

    global evaluation_processors

    if job_id:
        if (mode, job_id) in evaluation_processors:
            return evaluation_processors[(mode, job_id)]
        else:
            return None

    awagdata_client = get_awagdata_client(awagdata_clients, client_id)
    openai_client = get_openai_client_wrapper(openai_auth_token)

    evaluation_system_message_common = g.evaluation_system_message_common
    evaluation_request_schema = g.evaluation_request_schema

    evaluation_system_message_extra, evaluation_result_schema, evaluation_user_messages = get_mode_specific_content(mode, reqjson)

    evaluation_processor = AwAgEvaluationProcessor(
                            client_id=client_id,
                            openai_client=openai_client,
                            awagdata_client=awagdata_client,
                            mode=mode,
                            evaluation_system_message_common=evaluation_system_message_common,
                            evaluation_system_message_extra=evaluation_system_message_extra,
                            evaluation_request_schema=evaluation_request_schema,
                            evaluation_result_schema=evaluation_result_schema,
                            evaluation_user_messages=evaluation_user_messages,
                            default_model=g.evaluation_default_model,
                            trace_file_path=g.trace_file_path,
                            flask_app=current_app._get_current_object())

    if job_id:
        evaluation_processors[(mode, job_id)] = evaluation_processor

    return evaluation_processor


def init_db_tables(conn):

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_main
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     context_id TEXT not null,
                     evaluate_source_type TEXT not null,
                     evaluate_source_originator TEXT not null,
                     evaluate_source_channel TEXT not null,
                     evaluate_time_ms INTEGER not null,
                     evaluate_time_text TEXT not null,
                     evaluate_title TEXT,
                     evaluate_text TEXT not null,
                     evaluate_classifications JSON not null,
                     evaluate_perspectives JSON not null,
                     data_issue_flag INTEGER not null,
                     tags JSON,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, persona_id, persona_version, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_tags
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     context_id TEXT not null,
                     tag TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, persona_id, persona_version, context_id, tag))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_item_classifications
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     context_id TEXT not null,
                     classification_name TEXT not null,
                     classification_value TEXT not null,
                     classification_options JSON not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, persona_id, persona_version, context_id, classification_name))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_item_info
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     context_id TEXT not null,
                     originator TEXT not null,
                     item_url TEXT not null,
                     provider_description TEXT not null,
                     provider_name TEXT not null,
                     provider_url TEXT not null,
                     item_type TEXT not null,
                     item_type_desc TEXT not null,
                     item_from JSON not null,
                     item_to JSON not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, persona_id, persona_version, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_persona
                     (agent_id TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     persona_name TEXT not null,
                     persona_json JSON not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, persona_id, persona_version))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_perspective
                     (agent_id TEXT not null,
                     perspective_id TEXT not null,
                     perspective_version INTEGER not null,
                     perspective_name TEXT not null,
                     perspective_text TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, perspective_id, perspective_version))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_results
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     classification_name TEXT not null,
                     persona_id TEXT not null,
                     persona_version INTEGER not null,
                     perspective_id TEXT not null,
                     perspective_version INTEGER not null,
                     context_id TEXT not null,
                     evaluation_likert_val INTEGER,
                     evaluation_likert_text TEXT,
                     evaluation_agreement TEXT,
                     evaluation_text TEXT not null,
                     evaluated_selection TEXT,
                     mode TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name, persona_id, persona_version, perspective_id, perspective_version, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_context
                     (agent_id TEXT not null,
                     context_id TEXT not null,
                     evaluation_items JSON not null,
                     openai_api_completions_query_info JSON not null,
                     query_state JSON not null,
                     total_tokens INTEGER not null,
                     items_in_batch INTEGER not null,
                     finish_reason TEXT not null,
                     batch_data_issue_flag INTEGER not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_failures
                     (agent_id TEXT not null,
                     context_id TEXT not null,
                     query_state JSON not null,
                     response_text TEXT,
                     prompt_query_json JSON,
                     prompt_text TEXT,
                     max_tokens INTEGER not null,
                     model TEXT,
                     item_ids JSON,
                     item_count INTEGER not null,
                     evaluation_persona JSON,
                     evaluation_perspectives JSON,
                     finish_reason TEXT,
                     timestamp_ms INTEGER not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_failures_alt
                     (agent_id TEXT not null,
                     context_id TEXT not null,
                     query_info JSON not null,
                     query_state JSON not null,
                     additional_query_info JSON not null,
                     mode TEXT,
                     model TEXT,
                     evaluation_item JSON,
                     evaluation_persona JSON,
                     evaluation_perspectives JSON,
                     evaluation_request JSON,
                     finish_reason TEXT,
                     timestamp_ms INTEGER not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_requests_log
                     (agent_id TEXT not null,
                     context_id TEXT not null,
                     evaluation_request JSON not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, context_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_raw_items
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     item JSON,
                     tags JSON,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_raw_tags
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     tag TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, tag))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_feedback_items
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     context_id TEXT not null,
                     persona_id TEXT not null,
                     perspective_id TEXT not null,
                     classification_name TEXT not null,
                     old_evaluation_likert_val INTEGER not null,
                     new_evaluation_likert_val INTEGER not null,
                     text_likert_mismatch INTEGER,
                     additional_details JSON not null,
                     tags JSON,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, context_id, persona_id, perspective_id, classification_name))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_feedback_tags
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     context_id TEXT not null,
                     persona_id TEXT not null,
                     perspective_id TEXT not null,
                     classification_name TEXT not null,
                     tag TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, context_id, persona_id, perspective_id, classification_name, tag))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS evaluation_jobs
                     (agent_id TEXT not null,
                     job_id TEXT not null,
                     mode TEXT not null,
                     eval_info JSON not null,
                     status TEXT not null,
                     is_error INTEGER not null,
                     processed_items INTEGER not null,
                     completion_tokens INTEGER not null,
                     prompt_tokens INTEGER not null,
                     total_tokens INTEGER not null,
                     tag_source TEXT not null,
                     tags_dest JSON not null,
                     first_tag_dest TEXT not null,
                     openai_model TEXT not null,
                     job_status JSON not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, job_id))''')
    conn.commit()


@evaluation_routes.before_request
def before_request():
  
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
            gentrain_dir_path = os.path.join(awag_trace_file_path, "eval")
            os.makedirs(gentrain_dir_path, exist_ok=True)
            g.trace_file_path = gentrain_dir_path


@evaluation_routes.route('/record-evaluation-data', methods=['POST'])
@require_api_auth
def record_evaluation_data():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        evaluation_persona_json = reqjson["evaluationPersona"]
        if not isinstance(evaluation_persona_json, dict):
            raise TypeError(f"evaluation_persona_json is not a valid dict:: {evaluation_persona_json}")

        items = reqjson["items"]
        if not isinstance(items, list):
            raise TypeError(f"items is not a valid array:: {items}")

        evaluation_perspectives = reqjson["evaluationPerspectives"]
        if not isinstance(evaluation_perspectives, list):
            raise TypeError(f"evaluation_perspectives is not a valid array:: {evaluation_perspectives}")

        context = reqjson["context"]
        if not isinstance(context, dict):
            raise TypeError(f"context is not a valid dict:: {context}")

        context_id = context["contextId"]
        logger.debug(f"Got contextId: {context_id}")

        context_evaluation_items = json.dumps(context["evaluationItems"])
        context_openai_api_completions_query_info = json.dumps(context["openaiApiCompletionsQueryInfo"])
        context_query_state_x = context["queryState"]
        context_query_state = json.dumps(context["queryState"])

        logger.debug(f"context_query_state_x: {context_query_state_x}")

        logger.debug(f"context_evaluation_items: {context_evaluation_items}")
        logger.debug(f"context_openai_api_completions_query_info: {context_openai_api_completions_query_info}")

        context_finish_reason = context_query_state_x["finish_reason"]
        context_total_tokens = context_query_state_x["usage"]["total_tokens"]

        evaluation_request = reqjson.get("evaluationRequest", None)

        conn = get_db_conn()
        init_db_tables(conn)
        timestamp = str(datetime.now())

        # Used to track store the correct version for each perspective
        perspective_versions = {}

        cursor = conn.cursor()

        #  Update perspectives table if necessary...
        for perspective in evaluation_perspectives:
            evaluation_perspective_id, evaluation_perspective_name, evaluation_perspective_text, evaluation_perspective_version \
                = process_record_evaluation_data_perspective(conn, agent_id, perspective, perspective_versions, timestamp)

        #  Update personas table if necessary...
        evaluation_persona_version, evaluation_persona_id, evaluation_persona_name \
            = process_record_evaluation_data_persona(conn, agent_id, evaluation_persona_json, timestamp)

        # Now process the evaluated items...

        data_issue_flag = 0
        item_count = 0

        for item in items:

            logger.debug('Processing item: ' + str(item))

            item_count, data_issue_flag = process_record_evaluation_data_item(item, item_count, agent_id, evaluation_persona_id, conn, timestamp, evaluation_perspectives, perspective_versions, context_id, evaluation_persona_version, data_issue_flag)

        # Insert context rows...

        conn.execute("INSERT INTO evaluation_context \
        (agent_id, context_id, evaluation_items, openai_api_completions_query_info, query_state, total_tokens, items_in_batch, finish_reason, batch_data_issue_flag, timestamp) \
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
        (agent_id, context_id, context_evaluation_items, context_openai_api_completions_query_info, context_query_state, context_total_tokens, item_count, context_finish_reason, data_issue_flag, timestamp))

        # If we were passed an evaluation_request, record this

        if evaluation_request:

            conn.execute("INSERT INTO evaluation_requests_log \
            (agent_id, context_id, evaluation_request, timestamp) \
            VALUES (?, ?, ?, ?)", \
            (agent_id, context_id, json.dumps(evaluation_request), timestamp))

        # Commit the changes to the database
        conn.commit()

        return resp.generate_response_with_data(f"Record added successfully for context_id: {context_id}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


def process_record_evaluation_data_persona(conn, agent_id, persona, timestamp):

    logger.debug(f"process_record_evaluation_data_persona: {persona}")

    if not persona or 'id' not in persona or 'name' not in persona:
        raise ValueError('Invalid persona object.')

    if not persona['id'] or not persona['name']:
        raise ValueError('Persona id or name is empty.')

    persona_id = persona['id']
    persona_name = persona['name']

    insert_persona_record = False  # Flag to determine whether we need to insert a new persona record
    persona_version = 1

    cursor = conn.cursor()

    cursor.execute("SELECT persona_name, persona_json, persona_version FROM evaluation_persona WHERE agent_id = ? AND persona_id = ? ORDER BY timestamp DESC LIMIT 1", (agent_id, persona_id,))
    result = cursor.fetchone()

    if result is not None:
        old_persona_name, old_persona_json, old_persona_version = result
        if old_persona_name == persona_name and json.dumps(persona, sort_keys=True) == json.dumps(json.loads(old_persona_json), sort_keys=True):
            persona_version = old_persona_version
        else:
            logger.debug('Persona details have changed - incrementing persona_version')
            persona_version = old_persona_version + 1
            insert_persona_record = True
    else:
        # If no record exists for this persona_id, start at version 1
        insert_persona_record = True

    logger.debug(f"Using persona_version: {persona_version}")

    if insert_persona_record:
        conn.execute("INSERT INTO evaluation_persona \
            (agent_id, persona_id, persona_version, persona_name, persona_json, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?)", \
            (agent_id, persona_id, persona_version, persona_name, json.dumps(persona), timestamp))

    return persona_version, persona_id, persona_name


def process_record_evaluation_data_perspective(conn, agent_id, perspective, perspective_versions, timestamp):

    logger.debug(f"proecess_record_evaluation_data_perspective: {perspective}")

    insert_perspective_record = False

    logger.debug('Processing perspective (for perspective updates): ' + str(perspective))

    if not perspective or 'perspectiveId' not in perspective or 'perspectiveName' not in perspective or 'perspectiveText' not in perspective:
        raise ValueError('Invalid perspective object.')

    if not perspective['perspectiveId'] or not perspective['perspectiveName'] or not perspective['perspectiveText']:
        raise ValueError('Persona id, name or text  is empty.')

    perspective_id = perspective['perspectiveId'];
    perspective_name = perspective['perspectiveName'];
    perspective_text = perspective['perspectiveText'];

    perspective_version = 1;

    cursor = conn.cursor()
    cursor.execute("SELECT perspective_name, perspective_text, perspective_version FROM evaluation_perspective WHERE agent_id = ? AND perspective_id = ? ORDER BY timestamp DESC LIMIT 1", (agent_id, perspective_id,))
    result = cursor.fetchone()

    if result is not None:
        old_perspective_name, old_perspective_text, old_perspective_version = result
        if old_perspective_name == perspective_name and old_perspective_text == perspective_text:
            perspective_version = old_perspective_version
        else:
            logger.debug('Perspective details have changed - incrementing perspective_version')
            perspective_version = old_perspective_version + 1
            insert_perspective_record = True
    else:
        # If no record exists for this perspective_id, start at version 1
        insert_perspective_record = True

    logger.debug('Using evaluation_perspective_version: ' + str(perspective_version))

    if insert_perspective_record:
        conn.execute("INSERT INTO evaluation_perspective \
            (agent_id, perspective_id, perspective_version, perspective_name, perspective_text, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?)", \
            (agent_id, perspective_id, perspective_version, perspective_name, perspective_text, timestamp))

    perspective_versions[perspective_id] = perspective_version

    logger.debug(f"Updated perspective_versions: {perspective_versions}")

    return perspective_id, perspective_name, perspective_text, perspective_version


def process_record_evaluation_data_item(item, item_count, agent_id, evaluation_persona_id, conn, timestamp, evaluation_perspectives, perspective_versions, context_id, evaluation_persona_version, data_issue_flag):

    logger.debug(f"Processing item: {item}")

    item_data_issue_flag = 0
    item_count += 1

    item_id = item['itemId']
    tags = item['tags']
    logger.debug('Tags: ' + str(tags))

    evaluate_source_type = item['evaluateSourceType']
    evaluate_source_originator = item['evaluateSourceOriginator']
    evaluate_source_channel = item['evaluateSourceChannel']
    evaluate_time_text = item['evaluateTimeText']
    evaluate_time_ms = item['evaluateTimeMs']
    evaluate_title = item['evaluateTitle']
    evaluate_text = item['evaluateText']

    evaluate_classifications = item['classifications']
    if not isinstance(evaluate_classifications, list):
        raise TypeError(f"classifications is not a valid array: {evaluate_classifications}")

    evaluation_responses = item['evaluationResponses']
    if not isinstance(evaluation_responses, list):
        raise TypeError(f"evaluation_responses is not a valid array: {evaluation_responses}")

    logger.debug(f"Item: {agent_id} - {item_id} - {evaluation_persona_id}")

    content_item_summary = None
    if 'contentItemSummary' in item:
        content_item_summary = item['contentItemSummary']

    evaluate_classifications_list = []
    evaluate_perspectives_list = []

    for classification in evaluate_classifications:

        classification_name = classification['classificationName']
        classification_value = classification['classificationValue']

        classification_options = json.dumps(classification['classificationOptions'])

        evaluate_classifications_list.append(classification_name)

        logger.debug(f"Item classification: {agent_id} - {item_id} - {classification_name}")

        classification_response = extract_object_by_property(evaluation_responses, 'classificationName', classification_name)

        if classification_response is None:
            # Really should not happen
            logger.error(f"Did not find classification_response in item {item_id} for: {classification_name}")
            item_data_issue_flag = 1
            data_issue_flag = 1
            continue

        classification_perspectives = classification_response['perspectives']

        for perspective in evaluation_perspectives:

            logger.debug(f"Processing perspective (for results updates): {perspective}")

            evaluation_perspective_id = perspective['perspectiveId'];
            evaluation_perspective_name = perspective['perspectiveName'];
            evaluation_perspective_text = perspective['perspectiveText'];
            evaluation_perspective_version = perspective_versions[evaluation_perspective_id]

            if evaluation_perspective_id not in evaluate_perspectives_list:
                evaluate_perspectives_list.append(evaluation_perspective_id)

            if evaluation_perspective_version is None:
                # Really should not happen
                logger.error(f"Did not find evaluation_perspective_version in item {item_id} for: {evaluation_perspective_id}")
                item_data_issue_flag = 1
                data_issue_flag = 1
                continue

            evaluation_response = extract_object_by_property(classification_perspectives, 'perspectiveId', evaluation_perspective_id)

            if evaluation_response is None:

                logger.error(f"Unable to find an evaluation_response with perspective_id: {evaluation_perspective_id}")
                logger.error(f"Item was: {item_id}")
                logger.error(f"Looked in evaluation_responses: {evaluation_responses}")
                item_data_issue_flag = 1
                data_issue_flag = 1
                continue

            logger.debug(f"Processing evaluation_response: {evaluation_response}")

            evaluation_likert_val = evaluation_response.get('evaluationLikertVal', None)
            evaluation_likert_text = evaluation_response.get('evaluationLikertText', None)
            evaluation_agreement = evaluation_response.get('evaluationAgreement', None)

            logger.debug(f"Got evaluation_likert_val: {evaluation_likert_val}")
            logger.debug(f"Got evaluation_likert_text: {evaluation_likert_text}")
            logger.debug(f"Got evaluation_agreement: {evaluation_agreement}")

            if not evaluation_likert_val and not evaluation_agreement:
                raise ValueError("Both evaluation_likert_val and evaluation_agreement can not be empty")

            if 'mode' in evaluation_response:
                evaluation_mode = evaluation_response['mode'].lower()
                logger.debug(f"Got evaluation_mode: {evaluation_mode}")
                if evaluation_mode not in ['mode1', 'mode2', 'mode3']:
                    raise ValueError("Mode must be one of 'mode1', 'mode2', or 'mode3'")
            else:
                raise ValueError(f"Evaluation response does not have a 'mode' value: {agent_id} - {item_id} - {evaluation_response}")

            if evaluation_likert_val is None and (evaluation_mode == "mode1" or evaluation_mode == "mode2"): 
                raise ValueError(f"Cannot have empty evaluation_likert_val for mode: {evaluation_mode}")

            if not evaluation_agreement and evaluation_mode == "mode3": 
                raise ValueError(f"Cannot have empty evaluation_agreement for mode: {evaluation_mode}")

            evaluation_text = evaluation_response['evaluationText']
            evaluated_selection = evaluation_response['evaluatedSelection']

            logger.debug(f"Insert into evaluation_results: {agent_id}  - {item_id} - {classification_name} - {evaluation_persona_id}- {evaluation_persona_version} - {evaluation_perspective_id} - {evaluation_perspective_version} - {evaluated_selection} - {evaluation_mode}")

            conn.execute("INSERT INTO evaluation_results \
                (agent_id, item_id, classification_name, persona_id, persona_version, perspective_id, perspective_version, context_id, evaluation_likert_val, evaluation_likert_text, evaluation_agreement, evaluation_text, evaluated_selection, mode, timestamp) \
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
                (agent_id, item_id, classification_name, evaluation_persona_id, evaluation_persona_version, evaluation_perspective_id, evaluation_perspective_version, context_id, evaluation_likert_val, evaluation_likert_text, evaluation_agreement, evaluation_text, evaluated_selection, evaluation_mode, timestamp))

        conn.execute("INSERT INTO evaluation_item_classifications \
            (agent_id, item_id, persona_id, persona_version, context_id, classification_name, classification_value, classification_options, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, item_id, evaluation_persona_id, evaluation_persona_version, context_id, classification_name, classification_value, classification_options, timestamp))

    # Insert tags...

    tags_json = '[]';

    if tags is not None:
        tags_json = json.dumps(tags)
        for tag in tags:
            conn.execute("INSERT INTO evaluation_tags \
                (agent_id, item_id, persona_id, persona_version, context_id, tag, timestamp) \
                VALUES (?, ?, ?, ?, ?, ?, ?)", \
                (agent_id, item_id, evaluation_persona_id, evaluation_persona_version, context_id, tag, timestamp))

    # Insert main...

    conn.execute("INSERT INTO evaluation_main \
        (agent_id, item_id, persona_id, persona_version, context_id, evaluate_source_type, evaluate_source_originator, evaluate_source_channel, evaluate_time_ms, evaluate_time_text, evaluate_title, evaluate_text, evaluate_classifications, evaluate_perspectives, data_issue_flag, tags, timestamp) \
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
        (agent_id, item_id, evaluation_persona_id, evaluation_persona_version, context_id, evaluate_source_type, evaluate_source_originator, evaluate_source_channel, evaluate_time_ms, evaluate_time_text, evaluate_title, evaluate_text, json.dumps(evaluate_classifications_list), json.dumps(evaluate_perspectives_list), item_data_issue_flag, tags_json, timestamp))

    if  content_item_summary is not None:

        conn.execute("INSERT INTO evaluation_item_info \
            (agent_id, item_id, persona_id, persona_version, context_id, originator, item_url, provider_name, provider_description, provider_url, item_type, item_type_desc, item_from, item_to, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, item_id, evaluation_persona_id, evaluation_persona_version, context_id, content_item_summary['originator'], content_item_summary['itemUrl'], content_item_summary['providerName'], content_item_summary['providerDescription'], content_item_summary['providerUrl'], content_item_summary['type'], content_item_summary['typeDescription'], json.dumps(content_item_summary['from']), json.dumps(content_item_summary['to']),timestamp))

    # Return both modified values
    return item_count, data_issue_flag  


@evaluation_routes.route('/delete-evaluation-data', methods=['DELETE'])
@require_api_auth
def delete_evaluation_data():

    agent_id, resp, conn = init_route(request)

    try:

        tag = get_required_arg(request, "tag")
        is_confirm = request.args.get('confirm', type=str_to_bool, default=False)

        if not is_confirm:
            return resp.generate_response_with_data(f"Missing required parameter confirm=true", 400)

        conn = get_db_conn()
        timestamp = str(datetime.now())

        cursor = conn.execute("SELECT agent_id, item_id, persona_id, persona_version, context_id FROM evaluation_tags WHERE tag = ? AND agent_id = ?", (tag, agent_id))
        records_to_delete = cursor.fetchall()

        if not records_to_delete:
            return resp.generate_response_with_data(f"No items found for tag: {tag}", 404)

        # Delete corresponding records from all tables
        for agent_id, item_id, persona_id, persona_version, context_id in records_to_delete:
            conn.execute("DELETE FROM evaluation_main WHERE agent_id = ? AND item_id = ? AND persona_id = ? AND persona_version = ? AND context_id = ?", (agent_id, item_id, persona_id, persona_version, context_id))
            conn.execute("DELETE FROM evaluation_tags WHERE agent_id = ? AND item_id = ? AND persona_id = ? AND persona_version = ? AND context_id = ?", (agent_id, item_id, persona_id, persona_version, context_id))
            conn.execute("DELETE FROM evaluation_item_classifications WHERE agent_id = ? AND item_id = ? AND persona_id = ? AND persona_version = ? AND context_id = ?", (agent_id, item_id, persona_id, persona_version, context_id))
            conn.execute("DELETE FROM evaluation_item_info WHERE agent_id = ? AND item_id = ? AND persona_id = ? AND persona_version = ? AND context_id = ?", (agent_id, item_id, persona_id, persona_version, context_id))
            conn.execute("DELETE FROM evaluation_results WHERE agent_id = ? AND item_id = ? AND persona_id = ? AND persona_version = ? AND context_id = ?", (agent_id, item_id, persona_id, persona_version, context_id))

        # Commit the changes to the database
        conn.commit()

        return resp.generate_response_with_data(f"Items deleted successfully for tag: {tag}", 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


def get_evaluation_data_class_persp(cursor, agent_id, item_id, persona_id, persona_version, context_id, perspective_id, evaluation_likert_val_min, evaluation_likert_val_max, classification_name, exclude_items_with_feedback):

    def is_non_partial_feedback(row_persp):
    
        if not row_persp:
            return False
        elif row_persp["old_evaluation_likert_val"]:
            if row_persp["old_evaluation_likert_val"] >= 0:
                return True
            else:
                return False
        else:
            return False

    perspectives_query = """
        SELECT results.agent_id, 
            results.item_id, 
            results.classification_name,
            classifications.classification_value,
            classifications.classification_options,
            results.persona_id,
            results.persona_version,
            results.perspective_id,
            results.perspective_version,
            results.context_id,
            perspective.perspective_name,
            perspective.perspective_text,
            results.evaluation_likert_val,
            results.evaluation_likert_text,
            results.evaluation_agreement,
            results.evaluation_text,
            results.evaluated_selection,
            results.mode,
            feedback.old_evaluation_likert_val,
            feedback.new_evaluation_likert_val,
            feedback.text_likert_mismatch,
            feedback.timestamp as feedback_timestamp,
            results.timestamp
        FROM evaluation_results AS results
        INNER JOIN evaluation_perspective AS perspective 
            ON results.agent_id = perspective.agent_id 
            AND results.perspective_id = perspective.perspective_id 
            AND results.perspective_version = perspective.perspective_version
        LEFT JOIN evaluation_item_classifications AS classifications 
            ON results.agent_id = classifications.agent_id 
            AND results.item_id = classifications.item_id
            AND results.context_id = classifications.context_id
            AND results.persona_id  = classifications.persona_id
            AND results.classification_name = classifications.classification_name 
        LEFT JOIN evaluation_feedback_items AS feedback
            ON results.agent_id = feedback.agent_id
            AND results.item_id = feedback.item_id
            AND results.persona_id = feedback.persona_id
            AND results.context_id = feedback.context_id
            AND results.perspective_id = feedback.perspective_id
            AND results.classification_name = feedback.classification_name
        WHERE results.agent_id = ?
          AND results.item_id = ?
          AND results.persona_id = ?
          AND results.persona_version = ?
          AND results.context_id = ?
        """

    perspectives_params = [agent_id, item_id, persona_id, persona_version, context_id]

    if perspective_id is not None:
        perspectives_query += " AND results.perspective_id = ?"
        perspectives_params.append(perspective_id)

    if evaluation_likert_val_min is not None:
        perspectives_query += " AND (results.evaluation_likert_val IS NULL OR results.evaluation_likert_val >= ?)"
        perspectives_params.append(evaluation_likert_val_min)

    if evaluation_likert_val_max is not None:
        perspectives_query += " AND (results.evaluation_likert_val IS NULL OR results.evaluation_likert_val <= ?)"
        perspectives_params.append(evaluation_likert_val_max)

    if classification_name is not None:
        perspectives_query += " AND results.classification_name = ?"
        perspectives_params.append(classification_name)

    perspectives_query += " ORDER BY results.perspective_id ASC"

    cursor.execute(perspectives_query, perspectives_params)
    rows_persp = cursor.fetchall()

    classification_dict = {}

    for row_persp in rows_persp:

        classification_name = row_persp["classification_name"]
        perspective_id = row_persp["perspective_id"]

        if exclude_items_with_feedback and is_non_partial_feedback(row_persp):
            logger.debug(f"Ignoring row_persp with non-partial feedback: {item_id} / {classification_name} / {perspective_id}")
            continue

        feedback = None

        old_evaluation_likert_val = row_persp["old_evaluation_likert_val"]

        if old_evaluation_likert_val:
            text_likert_mismatch = row_persp["text_likert_mismatch"] == 1
            feedback = {
                "old_evaluation_likert_val": old_evaluation_likert_val,
                "new_evaluation_likert_val": row_persp["new_evaluation_likert_val"],
                "text_likert_mismatch": text_likert_mismatch,
                "feedback_timestamp": row_persp["feedback_timestamp"],
                "is_partial": old_evaluation_likert_val < 0
            }

        classification_options = json.loads(row_persp["classification_options"]) if row_persp["classification_options"] else None
        actual_classification_value = row_persp["classification_value"]

        evaluated_selection = row_persp["evaluated_selection"]
        evaluated_selection_agrees_with_orig = None
        if evaluated_selection is not None:
            if not actual_classification_value:
                # Integrity check - actual_classification_value should never be null
                raise Exception(f"No actual_classification_value for {item_id} / {perspective_id}!")
            evaluated_selection_agrees_with_orig = evaluated_selection == actual_classification_value

        perspective_item = {
            "perspective_id": perspective_id,
            "perspective_version": row_persp["perspective_version"],
            "perspective_name": row_persp["perspective_name"],
            "perspective_text": row_persp["perspective_text"],
            "evaluation_likert_val": row_persp["evaluation_likert_val"],
            "evaluation_likert_text": row_persp["evaluation_likert_text"],
            "evaluation_agreement": row_persp["evaluation_agreement"],
            "evaluation_text": row_persp["evaluation_text"],
            "evaluated_selection": evaluated_selection,
            "evaluated_selection_agrees_with_orig": evaluated_selection_agrees_with_orig,
            "mode": row_persp["mode"],
            "feedback": feedback
        }

        # We are merging data here. Probably a better approach is to change this to
        # use nested queries for classification -> perspective

        if classification_name not in classification_dict:
            classification_dict[classification_name] = {
                "classification_name": classification_name,
                "classification_value": actual_classification_value,
                "classification_options": classification_options,
                "perspectives": []
            }

        classification_dict[classification_name]["perspectives"].append(perspective_item)

    results_data_classifications = list(classification_dict.values())

    return results_data_classifications if results_data_classifications else None


def dict_from_row(row):

    return {key: row[key] for key in row.keys()}


@evaluation_routes.route('/get-evaluation-data', methods=['GET'])
@require_api_auth
def get_evaluation_data():

    agent_id, resp, conn = init_route(request)

    try:

        item_id = request.args.get("itemId")
        evaluate_source_type = request.args.get("evaluateSourceType")
        persona_id = request.args.get("personaId")
        context_id = request.args.get("contextId")
        perspective_id = request.args.get("perspectiveId")
        last_n_hours = request.args.get("lastNHours")
        data_issue_flag = request.args.get("dataIssueFlag")
        tag = request.args.get("tag")

        classification_name = request.args.get("classificationName")
        evaluation_likert_val_min = request.args.get("evaluationLikertValMin", type=int)
        evaluation_likert_val_max = request.args.get("evaluationLikertValMax", type=int)

        is_detail = request.args.get("includeDetail", type=str_to_bool, default=False)
        exclude_items_with_feedback = request.args.get("excludeItemsWithFeedback", type=str_to_bool, default=False)
        include_partial_evaluations = request.args.get("includePartialEvaluations", type=str_to_bool, default=True)

        subset_tag = request.args.get("subsetTag", default=tag)
        subset_percent = request.args.get("subsetPercent", type=int, default=None)
        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        # To filter on evaluations that also have manual classification
        is_only_with_manual = request.args.get('onlyIncludeWithManual', type=str_to_bool, default=False)
        logger.debug(f"Using is_only_with_manual: {is_only_with_manual}")

        page = request.args.get("page", type=int, default=1)
        count = request.args.get("count", type=int, default=10)
        desc = request.args.get("desc", type=str_to_bool, default=False)
        by_uuid = request.args.get("by_uuid", type=str_to_bool, default=False)

        logger.debug(f"Agent: {agent_id}")
        logger.debug(f"Item ID: {item_id}")
        logger.debug(f"Evaluate Source Type: {evaluate_source_type}")
        logger.debug(f"Persona ID: {persona_id}")
        logger.debug(f"Last N hours: {last_n_hours}")
        logger.debug(f"Include detail: {is_detail}")
        logger.debug(f"Data issue flag: {data_issue_flag}")
        logger.debug(f"Subset percent: {subset_percent}")
        logger.debug(f"Tag: {tag}")
        logger.debug(f"Page: {page}")
        logger.debug(f"Count: {count}")

        if page < 1:
            raise ValueError(f"Invalid page number: {page}")

        conn = get_db_conn()
        init_db_tables(conn)
        c = conn.cursor()

        query_select = """SELECT main.agent_id, 
            main.item_id, 
            main.evaluate_source_type,
            main.evaluate_source_originator,
            main.evaluate_source_channel,
            main.evaluate_time_ms,
            main.evaluate_time_text,
            main.evaluate_title,
            main.evaluate_text,
            main.evaluate_classifications,
            main.evaluate_perspectives,
            main.context_id,
            personas.persona_id, 
            personas.persona_version, 
            personas.persona_name,
            context.evaluation_items,
            context.openai_api_completions_query_info,
            context.total_tokens,
            context.items_in_batch,
            context.finish_reason,
            main.data_issue_flag,
            context.batch_data_issue_flag,
            info.originator,
            info.item_url,
            info.provider_description,
            info.provider_name,
            info.provider_url,
            info.item_type,
            info.item_type_desc,
            info.item_from,
            info.item_to,
            main.tags, 
            main.timestamp 
        """

        query_from = """FROM evaluation_main AS main
        INNER JOIN evaluation_persona AS personas
            ON main.agent_id = personas.agent_id
            AND main.persona_id = personas.persona_id
            AND main.persona_version = personas.persona_version
        INNER JOIN evaluation_context AS context
            ON main.agent_id = context.agent_id
            AND main.context_id = context.context_id
        LEFT OUTER JOIN evaluation_item_info AS info
            ON main.agent_id = info.agent_id
            AND main.item_id = info.item_id
            AND main.persona_id = info.persona_id
            AND main.persona_version = info.persona_version
            AND main.context_id = info.context_id
        """

        query_where = "WHERE main.agent_id = ?"
        query_params = [agent_id]

        if subset_percent is not None:
            query_from += """
            LEFT OUTER JOIN classification_id_subsets s
                ON main.agent_id = s.agent_id
                AND main.item_id = s.item_id
            """
            query_where += " AND s.tag = ? AND s.subset_percent = ?"
            query_params.extend([subset_tag, subset_percent])

        if tag is not None:
            query_from += """
            INNER JOIN evaluation_tags AS tags
                ON main.agent_id = tags.agent_id
                AND main.persona_id = tags.persona_id
                AND main.persona_version = tags.persona_version
                AND main.context_id = tags.context_id
                AND main.item_id = tags.item_id
            """
            query_where += " AND tags.tag = ?"
            query_params.append(tag)

        if item_id is not None:
            query_where += " AND main.item_id = ?"
            query_params.append(item_id)

        if evaluate_source_type is not None:
            query_where += " AND main.evaluate_source_type = ?"
            query_params.append(evaluate_source_type)

        if persona_id is not None:
            query_where += " AND main.persona_id = ?"
            query_params.append(persona_id)

        if context_id is not None:
            query_where += " AND main.context_id = ?"
            query_params.append(context_id)

        if last_n_hours:
            current_time_ms = int(time.time() * 1000)
            n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
            query_where += " AND main.evaluate_time_ms >= ?"
            query_params.append(n_hours_ago_ms)

        if data_issue_flag is not None:
            query_where += " AND context.batch_data_issue_flag = ?"
            query_params.append(data_issue_flag)

        offset = (page - 1) * count

        query_order = ""
        if by_uuid or desc:
            query_order += "ORDER BY "
            if by_uuid:
                query_order += "main.item_id, main.evaluate_time_ms"
            else:
                query_order += "main.evaluate_time_ms, main.item_id"
            if desc:
                query_order += " DESC"

        # Total count is currently not accurate if exclude_items_with_feedback is True,
        # because it does not account for items later excluded
        total_count_query_select = "SELECT COUNT(DISTINCT main.item_id)"
        total_count_query = concat_sql([total_count_query_select, query_from, query_where])

        #logger.debug(f"Executing total_count_query: {total_count_query}")
        #logger.debug(f"Original query_from: {query_from}")
        #logger.debug(f"Using query_params: {query_params}")
        total_cursor = conn.execute(total_count_query, query_params)
        total_items = total_cursor.fetchone()[0]
        logger.debug(f"Got total_items from total_count_query: {total_items}")

        if count < 1:
            logger.debug("Not paging (count < 1)")
            return_count = total_items
            return_page = 1
            remaining_items = 0
            query_limit = ""
        else:
            return_count = count
            return_page = page
            remaining_items = max(total_items - (page * count), 0)
            query_limit = "LIMIT ? OFFSET ?"
            query_params.extend([count, offset])

        logger.debug(f"Page: {page}; count: {count}; offset: {offset}; total_items: {total_items}; remaining_items: {remaining_items}")

        real_count = 0
        items_to_fetch = count
        actual_offset = offset
        found_items = []
        found_enough = False
        loop_count = 0

        query_combined = concat_sql([query_select, query_from, query_where, query_order, query_limit])

        while real_count < count and not found_enough:

            loop_count += 1
            query_params[-2] = items_to_fetch
            query_params[-1] = actual_offset

            logger.debug(f"Executing items query, loop: {loop_count}")
            logger.debug(f"Params: {query_params}")

            c.execute(query_combined, query_params)
            temp_items = c.fetchall()

            if not temp_items:
                break

            if exclude_items_with_feedback:

                logger.debug(f"Filtering for exclude_items_with_feedback - initial temp_items size: {len(temp_items)}")

                filtered_items = []

                for item in temp_items:

                    item_dict = dict_from_row(item) 

                    feedback_check_query = """
                        SELECT COUNT(*) as feedback_count
                        FROM evaluation_feedback_items
                        WHERE agent_id = ?
                          AND item_id = ?
                          AND context_id = ?
                          AND persona_id = ?
                          AND old_evaluation_likert_val > -1
                    """
                    feedback_check_params = [
                        item_dict["agent_id"],
                        item_dict["item_id"],
                        item_dict["context_id"],
                        item_dict["persona_id"]
                    ]
                    c.execute(feedback_check_query, feedback_check_params)
                    feedback_result = c.fetchone()

                    if feedback_result["feedback_count"] == 0:
                        filtered_items.append(item)
                    else:
                        item_dict["filtered_perspectives"] = get_evaluation_data_class_persp(c, agent_id, item_dict["item_id"], item_dict["persona_id"], item_dict["persona_version"], item_dict["context_id"], perspective_id, evaluation_likert_val_min, evaluation_likert_val_max, classification_name, exclude_items_with_feedback)
                        if item_dict["filtered_perspectives"]:
                            filtered_items.append(item_dict)

                temp_items = filtered_items

                logger.debug(f"Filtered for exclude_items_with_feedback - processed temp_items size: {len(temp_items)}")

            if is_only_with_manual:

                logger.debug(f"Filtering for is_only_with_manual - initial temp_items size: {len(temp_items)}")

                manual_check_query = """
                    SELECT distinct item_id
                    FROM classification_actions
                    WHERE agent_id = ?
                      AND classification_new is not null
                """
                manual_check_params = [
                    agent_id
                ]
                c.execute(manual_check_query, manual_check_params)

                manual_item_ids = {row["item_id"] for row in c.fetchall()}

                temp_items = [item for item in temp_items if dict_from_row(item)["item_id"] in manual_item_ids]

                logger.debug(f"Filtered for is_only_with_manual - processed temp_items size: {len(temp_items)}")

            real_count += len(temp_items)
            found_items.extend(temp_items[:count - len(found_items)])

            if len(found_items) < count:
                actual_offset += items_to_fetch
                items_to_fetch = count - len(found_items)
            else:
                found_enough = True

        remaining_items = max(total_items - (return_page * len(found_items)), 0)

        responseData = []

        for row_item in found_items:

            item_id = row_item["item_id"]
            logger.debug(f"Processing row_item with item_id: {item_id}")

            resultsDataClassifications = []
            if "filtered_perspectives" in row_item:
                resultsDataClassifications = row_item["filtered_perspectives"]
            else:
                resultsDataClassifications = get_evaluation_data_class_persp(c, agent_id, item_id, row_item["persona_id"], row_item["persona_version"], row_item["context_id"], perspective_id, evaluation_likert_val_min, evaluation_likert_val_max, classification_name, exclude_items_with_feedback)

            evaluate_classifications = json.loads(row_item["evaluate_classifications"]) if row_item["evaluate_classifications"] else None
            evaluate_perspectives = json.loads(row_item["evaluate_perspectives"]) if row_item["evaluate_perspectives"] else None

            context = {}
            context["context_id"] = row_item["context_id"]
            context["total_tokens"] = row_item["total_tokens"]
            context["items_in_batch"] = row_item["items_in_batch"]
            context["finish_reason"] = row_item["finish_reason"]
            context["evaluate_classifications"] = evaluate_classifications
            context["evaluate_perspectives"] = evaluate_perspectives
            context["data_issue_flag"] = row_item["batch_data_issue_flag"] > 0

            tags_obj = json.loads(row_item["tags"]) if row_item["tags"] else []

            if row_item["item_url"] is None:
                item_info = {}
            else:
                item_info = {
                    "originator": row_item["originator"],
                    "provider_description": row_item["provider_description"],
                    "provider_name": row_item["provider_name"],
                    "provider_url": row_item["provider_url"],
                    "item_url": row_item["item_url"],
                    "item_type": row_item["item_type"],
                    "item_type_desc": row_item["item_type_desc"],
                    "item_from": json.loads(row_item["item_from"]),
                    "item_to": json.loads(row_item["item_to"])
                }

            responseItem = {
                "agent_id": agent_id,
                "item_id": item_id,
                "tags": tags_obj,
                "evaluate_source_type": row_item["evaluate_source_type"],
                "evaluate_source_originator": row_item["evaluate_source_originator"],
                "evaluate_source_channel": row_item["evaluate_source_channel"],
                "evaluate_time_ms": row_item["evaluate_time_ms"],
                "evaluate_time": row_item["evaluate_time_text"],
                "evaluate_title": row_item["evaluate_title"],
                "evaluate_text": row_item["evaluate_text"],
                "persona_id": row_item["persona_id"],
                "persona_version": row_item["persona_version"],
                "persona_name": row_item["persona_name"],
                "data_issue_flag": row_item["data_issue_flag"] > 0,
                "context": context,
                "info": item_info,
                "timestamp": row_item["timestamp"]
            }

            if resultsDataClassifications:

                responseItem["results"] = resultsDataClassifications

                if is_detail:
                    context_openai_api_completions_query_info = json.loads(row_item["openai_api_completions_query_info"])
                    context["openai_query_info"] = context_openai_api_completions_query_info
                    if context_openai_api_completions_query_info and "promptQueryJson" in context_openai_api_completions_query_info:
                        context["prompt_query_json"] = context_openai_api_completions_query_info["promptQueryJson"]
                        del context_openai_api_completions_query_info["promptQueryJson"]
                    evaluation_items = json.loads(row_item["evaluation_items"]) if row_item["evaluation_items"] else None
                    context["evaluation_items"] = evaluation_items

                responseItem["context"] = context
                responseData.append(responseItem)

            else:

                logger.debug(f"Will not append responseItem as has no resultsDataClassifications: {responseItem}")

        response_json = {
            "status": "OK",
            "message": "OK",
            "data": responseData,
            "page": return_page,
            "count": return_count,
            "remaining": remaining_items
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/get-evaluation-persona', methods=['GET'])
@require_api_auth
def get_evaluation_persona():

    agent_id, resp, conn = init_route(request)

    try:

        persona_id = request.args.get('persona')
        persona_version = request.args.get('version')

        logger.debug('Agent: ' + str(agent_id))
        logger.debug('Persona ID: ' + str(persona_id))
        logger.debug('Persona version: ' + str(persona_version))

        if persona_id == '':
            persona_id = None

        if persona_version == '':
            persona_version = None
        else:
            if persona_version is not None:
                try:
                    persona_version = int(persona_version)
                except ValueError:
                    raise ValueError(f"Version parameter must be a valid integer: {persona_version}")

        conn = get_db_conn()

        c = conn.cursor()

        query = """
            SELECT agent_id, 
                persona_id, 
                persona_version, 
                persona_name, 
                persona_json, 
                timestamp 
            FROM evaluation_persona 
            WHERE agent_id = ? 
        """

        params = [agent_id]

        if persona_id is not None:
            query += " AND persona_id = ? "
            params.append(persona_id)

        if persona_version is not None:
            if persona_version < 0:
                if persona_id is None:
                    # Filter for the highest persona_version for each persona_id
                    query += """
                        AND persona_version IN (
                            SELECT MAX(persona_version) 
                            FROM evaluation_persona 
                            WHERE agent_id = ?
                            GROUP BY persona_id
                        )
                    """
                    params.append(agent_id)
                else:
                    # Filter for the highest persona_version for the specified persona_id
                    query += """
                        AND persona_version = (
                            SELECT MAX(persona_version) 
                            FROM evaluation_persona 
                            WHERE agent_id = ? AND persona_id = ?
                        )
                    """
                    params.append(agent_id)
                    params.append(persona_id)
            else:
                query += " AND persona_version = ? "
                params.append(persona_version)

        query += "ORDER BY persona_id, persona_version DESC"

        c.execute(query, tuple(params))

        rows = c.fetchall()

        response_data = []

        for row in rows:

            try:
                persona_json = json.loads(row["persona_json"])
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in database for agent_id {row['agent_id']}, persona_id {row['persona_id']}, version {row['persona_version']}")
                continue

            # Check for mismatch between persona_id, persona_name and their counterparts in persona_json
            if str(persona_json.get('id', '')) != str(row["persona_id"]) or persona_json.get('name', '') != row["persona_name"]:
                logger.error(f"Mismatch in database for agent_id {row['agent_id']}, persona_id {row['persona_id']}, version {row['persona_version']}: persona_json id/name does not match database columns")

            response_data.append({
                'agent_id': row["agent_id"],
                'persona_id': row["persona_id"],
                'persona_version': row["persona_version"],
                'persona_name': row["persona_name"],
                'persona_json': persona_json,
                'timestamp': row["timestamp"]
            })

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'data': response_data
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/get-evaluation-perspective', methods=['GET'])
@require_api_auth
def get_evaluation_perspective():

    agent_id, resp, conn = init_route(request)

    try:
 
        perspective_id = request.args.get('perspective')
        perspective_version = request.args.get('version')

        logger.debug('Persona ID: ' + str(perspective_id))
        logger.debug('Persona version: ' + str(perspective_version))

        if perspective_id == '':
            perspective_id = None

        if perspective_version == '':
            perspective_version = None
        else:
            if perspective_version is not None:
                try:
                    persona_version = int(perspective_version)
                except ValueError:
                    raise ValueError(f"Version parameter must be a valid integer: {perspective_version}")

        conn = get_db_conn()

        c = conn.cursor()

        query = """
            SELECT agent_id, 
                perspective_id, 
                perspective_version, 
                perspective_name, 
                perspective_text, 
                timestamp 
            FROM evaluation_perspective 
            WHERE agent_id = ? 
        """

        params = [agent_id]

        if perspective_id is not None:
            query += " AND perspective_id = ? "
            params.append(perspective_id)

        if perspective_version is not None:
            if perspective_version < 0:
                if perspective_id is None:
                    # Filter for the highest perspective_version for each perspective_id
                    query += """
                        AND perspective_version IN (
                            SELECT MAX(perspective_version) 
                            FROM evaluation_perspective 
                            WHERE agent_id = ?
                            GROUP BY perspective_id
                        )
                    """
                    params.append(agent_id)
                else:
                    # Filter for the highest perspective_version for the specified perspective_id
                    query += """
                        AND perspective_version = (
                            SELECT MAX(perspective_version) 
                            FROM evaluation_perspective 
                            WHERE agent_id = ? AND perspective_id = ?
                        )
                    """
                    params.append(agent_id)
                    params.append(perspective_id)
            else:
                query += " AND perspective_version = ? "
                params.append(perspective_version)

        query += "ORDER BY perspective_id, perspective_version DESC"

        c.execute(query, tuple(params))

        rows = c.fetchall()

        response_data = []

        for row in rows:
            response_data.append({
                'agent_id': row["agent_id"],
                'perspective_id': row["perspective_id"],
                'perspective_version': row["perspective_version"],
                'perspective_name': row["perspective_name"],
                'perspective_text': row["perspective_text"],
                'timestamp': row["timestamp"]
            })

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'data': response_data
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/record-evaluation-failure', methods=['POST'])
@require_api_auth
def record_evaluation_failure():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        context_id = reqjson['contextIdentifier']
        logger.debug(f"contextIdentifier: {context_id}")

        query_state = reqjson['queryState']
        response_text = reqjson['responseText']
        prompt_query_json = reqjson['promptQueryJson']
        prompt_text = reqjson['promptText']
        max_tokens = reqjson['maxTokens']
        model = reqjson['model']
        item_ids = reqjson['items']
        item_count = reqjson['itemCount']
        evaluation_persona = reqjson['evaluationPersona']
        evaluation_perspectives = reqjson['evaluationPerspectives']
        finish_reason = get_value_from_dict(query_state, "finish_reason")

        now = datetime.now()
        timestamp = str(now)
        timestamp_ms = now.timestamp() * 1000

        conn = get_db_conn()
        init_db_tables(conn)

        # Used to track store the correct version for each perspective
        perspective_versions = {}

        cursor = conn.cursor()

        conn.execute("INSERT INTO evaluation_failures \
            (agent_id, context_id, query_state, response_text, prompt_query_json, prompt_text, max_tokens, model, item_ids, item_count, evaluation_persona, evaluation_perspectives, finish_reason, timestamp_ms, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, context_id, json.dumps(query_state), response_text, json.dumps(prompt_query_json), prompt_text, max_tokens, model, json.dumps(item_ids), item_count, json.dumps(evaluation_persona), json.dumps(evaluation_perspectives), finish_reason, timestamp_ms, timestamp))

        # Commit the changes to the database
        conn.commit()

        return resp.generate_response_with_data(f"Record added successfully for context_id: {context_id}", 201)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/record-evaluation-failure-alt', methods=['POST'])
@require_api_auth
def record_evaluation_failure_alt():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        context_id = reqjson["contextIdentifier"]
        logger.debug(f"contextIdentifier: {context_id}")

        query_info = reqjson["queryInfo"]
        additional_query_info = reqjson["additionalQueryInfo"]
        query_state = reqjson["queryState"]
        mode = reqjson["mode"]
        model = reqjson["model"]
        evaluation_item = reqjson["evaluationItem"]
        evaluation_persona = reqjson["evaluationPersona"]
        evaluation_perspectives = reqjson["evaluationPerspectives"]
        finish_reason = reqjson["finishReason"]
        evaluation_request = ["evaluationRequest"]

        now = datetime.now()
        timestamp = str(now)
        timestamp_ms = now.timestamp() * 1000

        conn = get_db_conn()
        init_db_tables(conn)

        # Used to track store the correct version for each perspective
        perspective_versions = {}

        cursor = conn.cursor()

        conn.execute("INSERT INTO evaluation_failures_alt \
            (agent_id, context_id, query_info, additional_query_info, query_state, mode, model, evaluation_item, evaluation_persona, evaluation_perspectives, evaluation_request, finish_reason, timestamp_ms, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, context_id, json.dumps(query_info), json.dumps(additional_query_info), json.dumps(query_state), mode, model, json.dumps(evaluation_item), json.dumps(evaluation_persona), json.dumps(evaluation_perspectives), json.dumps(evaluation_request), finish_reason, timestamp_ms, timestamp))

        # Commit the changes to the database
        conn.commit()

        return resp.generate_response_with_data(f"Record added successfully for context_id: {context_id}", 201)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/get-evaluation-failures', methods=['GET'])
@require_api_auth
def get_evaluation_failures():

    agent_id, resp, _ = init_route(request)

    try:

        item_id = request.args.get('itemId')
        context_id = request.args.get('contextId')
        last_n_hours = request.args.get('lastNHours')
        last_n_minutes = request.args.get('lastNMinutes')

        logger.debug('Item ID: ' + str(item_id))

        conn = get_db_conn()

        cursor = conn.cursor()

        query = "SELECT * FROM evaluation_failures WHERE agent_id=?"
        parameters = [agent_id]

        current_time_ms = int(time.time() * 1000)

        if item_id:
            query += " AND item_id=?"
            parameters.append(item_id)
        if context_id:
            query += " AND context_id=?"
            parameters.append(context_id)
        if last_n_hours:
            n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
            query += " AND timestamp_ms >= ?"
            parameters.append(n_hours_ago_ms)
        elif last_n_minutes:
            n_minutes_ago_ms = current_time_ms - (int(last_n_minutes) * 60 * 1000)
            query += " AND timestamp_ms >= ?"
            parameters.append(n_minutes_ago_ms)

        query += " ORDER BY timestamp_ms DESC"

        cursor.execute(query, parameters)

        rows = cursor.fetchall()

        results = []
        for row in rows:
            result = {
                'agent': row["agent_id"],
                'contextId': row["context_id"],
                'queryState': json.loads(row["query_state"]),
                'responseText': row["response_text"],
                'promptQueryJson': json.loads(row["prompt_query_json"]),
                'promptText': row["prompt_text"],
                'maxTokens': row["max_tokens"],
                'model': row["model"],
                'itemCount': row["item_count"],
                'itemIds': json.loads(row["item_ids"]),
                'evaluationPersona': json.loads(row["evaluation_persona"]),
                'evaluationPerspectives': json.loads(row["evaluation_perspectives"]),
                'finishReason': row["finish_reason"],
                'timestampMs': row["timestamp_ms"],
                'timestamp': row["timestamp"],
                'currentTimeMs': current_time_ms
            }
            results.append(result)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'data': results
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/record-evaluation-items', methods=['POST'])
@require_api_auth
def record_evaluation_items():

    agent_id, resp, conn = init_route(request)

    items_list = []

    try:

        reqjson = get_reqjson(request)

        evaluation_items = reqjson['evaluationItems']
        if not isinstance(evaluation_items, list):
            raise TypeError(f"evaluation_items is not a valid array: {evaluation_items}")

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        item_count = 0

        for evaluation_item in evaluation_items:

            logger.debug(f"Processing evaluation_item: {evaluation_item}")

            item_count += 1

            content_item_summary = evaluation_item['contentItemSummary']

            if not isinstance(content_item_summary, dict):
                raise TypeError(f"content_item_summary is not a valid dict: {content_item_summary}")

            item_id = content_item_summary['itemId']
            tags = evaluation_item.get('tags', [])

            items_list.append(item_id)

            tags_json = json.dumps(tags)
            evaluation_item_json = json.dumps(evaluation_item)

            conn.execute("DELETE FROM evaluation_raw_tags WHERE agent_id = ? AND item_id = ?", (agent_id, item_id))

            conn.execute("INSERT OR REPLACE INTO evaluation_raw_items (agent_id, item_id, item, tags, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (agent_id, item_id, evaluation_item_json, tags_json, timestamp))

            tags_data = [(agent_id, item_id, tag, timestamp) for tag in tags]
            conn.executemany("INSERT INTO evaluation_raw_tags (agent_id, item_id, tag, timestamp) VALUES (?, ?, ?, ?)", tags_data)

        conn.commit()

        return resp.generate_response_with_data(f"Records added successfully for item: {item_count} items: {items_list}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/fetch-evaluation-items', methods=['GET'])
@require_api_auth
def fetch_evaluation_items():

    agent_id, resp, conn = init_route(request)

    try:

        tag_filter = request.args.get('tag', None)
        desc = request.args.get('desc', type=str_to_bool, default=False)
        by_uuid = request.args.get('by_uuid', type=str_to_bool, default=True)

        # If specified, the fetch will exclude any items that have evaluation records matching
        # the passed tag; this allows us to split an eval process into multiple runs
        exclude_tag = request.args.get('excludeExistingWithTag', None)

        last_n_hours = request.args.get('lastNHours', None)

        time_filter = None
        if last_n_hours:
            time_filter = datetime.now() - timedelta(hours=int(last_n_hours))

        subset_tag = request.args.get('subsetTag', default=tag_filter)
        subset_percent = request.args.get('subsetPercent', type=int, default=None)

        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        page = int(request.args.get('page', 1))
        count = int(request.args.get('count', 10))
        offset = (page - 1) * count

        conn = get_db_conn()

        query_select = "SELECT e.item"
        query_from = "FROM evaluation_raw_items e"

        query_order = ""
        if by_uuid or desc:
            query_order += "ORDER BY "
            if by_uuid:
                query_order += "e.item_id, e.timestamp"
            else:
                query_order += "e.timestamp, e.item_id"
            if desc:
                query_order += " DESC"

        where_conditions = ["e.agent_id = ?"]
        query_params = [agent_id]

        if tag_filter:
            query_from += " INNER JOIN evaluation_raw_tags t ON e.item_id = t.item_id"
            where_conditions.append("t.tag = ?")
            query_params.append(tag_filter)

        if time_filter:
            where_conditions.append("e.timestamp >= ?")
            query_params.append(time_filter)

        if exclude_tag:
            logger.debug(f"Using exclude_tag: {exclude_tag}")
            where_conditions.append("NOT EXISTS (SELECT 1 FROM evaluation_tags et WHERE et.item_id = e.item_id AND et.tag = ?)")
            query_params.append(exclude_tag)

        if subset_percent is not None:
            query_from += """ LEFT OUTER JOIN classification_id_subsets s
                  ON e.agent_id = s.agent_id
                  AND e.item_id = s.item_id
                  """
            where_conditions.append("s.tag = ? AND s.subset_percent = ?")
            query_params.extend([subset_tag, subset_percent])

        query_where = "WHERE " + " AND ".join(where_conditions)
        logger.debug(f"Got query_where: {query_where}")

        total_count_query = concat_sql(["SELECT COUNT(DISTINCT e.item_id)", query_from, query_where])
        logger.debug(f"Executing total_count_query: {total_count_query}")
        logger.debug(f"Using query_params: {query_params}")
        total_cursor = conn.execute(total_count_query, query_params)
        total_items = total_cursor.fetchone()[0]
        logger.debug(f"Got total_items from total_count_query: {total_items}")

        if count < 1:
            logger.debug('Not paging (count < 1)')
            return_count = total_items
            return_page = 1
            remaining_items = 0
            query_limit = ""
        else:
            return_count = count
            return_page = page
            remaining_items = max(total_items - (page * count), 0)
            query_limit = "LIMIT ? OFFSET ?"
            query_params.extend([count, offset])

        logger.debug(f"Page: {page}; count: {count}; offset: {offset}; total_items: {total_items}; remaining_items: {remaining_items}")

        query_combined = concat_sql([query_select, query_from, query_where, query_order, query_limit])

        logger.debug(f"Query: {query_combined}")
        logger.debug(f"Params: {query_params}")

        data_cursor = conn.execute(query_combined, query_params)
        
        response_data = []
        
        for row in data_cursor:
            item = json.loads(row[0])
            response_data.append(item)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'page': return_page,
            'count': return_count,
            'remaining': remaining_items,
            'data': response_data
        }
        
        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:
    
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/record-evaluation-feedback', methods=['POST'])
@evaluation_routes.route('/record-evaluation-feedback-partial', methods=['POST'])
@require_api_auth
def record_evaluation_feedback():

    agent_id, resp, conn = init_route(request)

    items_list = []

    try:

        is_partial = False
        if request.path.endswith("/record-evaluation-feedback-partial"):
            is_partial = True

        reqjson = get_reqjson(request)

        item_id = get_required_reqjson_val(reqjson, "itemId")
        logger.debug(f"Item: {item_id}")
        persona_id = get_required_reqjson_val(reqjson, "personaId")
        context_id = get_required_reqjson_val(reqjson, "contextId")
        perspective_id = get_required_reqjson_val(reqjson, "perspectiveId")
        classification_name = get_required_reqjson_val(reqjson, "classificationName")

        additional_details = get_reqjson_val(reqjson, "additionalDetails", {})

        #  Possible this may be missing from reqjson
        if "textLikertMismatch" in reqjson:
            text_likert_mismatch = 1 if reqjson["textLikertMismatch"] else 0
        else:
            text_likert_mismatch = None

        tags = reqjson["tags"]

        if not isinstance(tags, list):
            raise TypeError(f"tags is not a valid array: {tags}")
        tags_json = json.dumps(tags)

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        def insert_evaluation_feedback(old_evaluation_likert_val, new_evaluation_likert_val):

            logger.debug(f"insert_evaluation_feedback: {old_evaluation_likert_val}, {new_evaluation_likert_val}, {tags}")

            conn.execute("REPLACE INTO evaluation_feedback_items \
                (agent_id, item_id, context_id, persona_id, perspective_id, classification_name, \
                old_evaluation_likert_val, new_evaluation_likert_val, text_likert_mismatch, additional_details, tags, timestamp) \
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                (agent_id, item_id, context_id, persona_id, perspective_id, classification_name,
                old_evaluation_likert_val, new_evaluation_likert_val, text_likert_mismatch, json.dumps(additional_details), tags_json, timestamp))

            for tag in tags:
                conn.execute("REPLACE INTO evaluation_feedback_tags \
                    (agent_id, item_id, context_id, persona_id, perspective_id, classification_name, tag, timestamp) \
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                    (agent_id, item_id, context_id, persona_id, perspective_id, classification_name, tag, timestamp))

        if is_partial:

            # Note that a partial update will intentionally do nothing (silently) if there is no existing record 
            logger.debug(f"Recording PARTIAL feedback for text_likert_mismatch: {text_likert_mismatch}")

            update_result = conn.execute(
                "UPDATE evaluation_feedback_items SET text_likert_mismatch = ? \
                WHERE agent_id = ? AND item_id = ? AND context_id = ? AND persona_id = ? AND perspective_id = ? AND classification_name = ?", 
                (text_likert_mismatch, agent_id, item_id, context_id, persona_id, perspective_id, classification_name))
            conn.commit()

            if update_result.rowcount == 0:

                logger.debug("No existing record found, creating a new record with default values.")

                old_evaluation_likert_val = -1
                new_evaluation_likert_val = -1

                insert_evaluation_feedback(old_evaluation_likert_val, new_evaluation_likert_val)
                conn.commit()

                return resp.generate_response_with_data("New record created with default values", 200)

            else:

                return resp.generate_response_with_data(f"Record updated successfully for item_id: {item_id}", 200)

        else:

            old_evaluation_likert_val = reqjson['oldLikertValue']
            new_evaluation_likert_val = reqjson['newLikertValue']

            logger.debug(f"Recording FULL feedback for: {old_evaluation_likert_val} -> {new_evaluation_likert_val}")

            if new_evaluation_likert_val is None:
                logger.debug('Got null newLikertValue - setting to oldLikertValue')
                new_evaluation_likert_val = old_evaluation_likert_val

            insert_evaluation_feedback(old_evaluation_likert_val, new_evaluation_likert_val)
            conn.commit()

            return resp.generate_response_with_data(f"Record added successfully for item_id: {item_id}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/fetch-evaluation-feedback', methods=['GET'])
@require_api_auth
def fetch_evaluation_feedback():

    agent_id, resp, conn = init_route(request)

    try:

        tag_filter = request.args.get('tag', None)

        item_id_filter = request.args.get('itemId', None)
        
        desc = request.args.get('desc', type=str_to_bool, default=False)
        by_uuid = request.args.get('by_uuid', type=str_to_bool, default=True)

        values_same = request.args.get('valuesSame', type=str_to_bool, default=False)
        is_detail = request.args.get('includeDetail', type=str_to_bool, default=False)
        
        last_n_hours = request.args.get('lastNHours', None)
       
        time_filter = None
        if last_n_hours:
            time_filter = datetime.now() - timedelta(hours=int(last_n_hours))
        
        page = int(request.args.get('page', 1))
        count = int(request.args.get('count', 20))
        offset = (page - 1) * count

        conn = get_db_conn()

        base_query = " FROM evaluation_feedback_items e"
        if tag_filter:
            base_query += " INNER JOIN evaluation_feedback_tags t ON e.agent_id = t.agent_id AND e.item_id = t.item_id AND e.context_id = t.context_id AND e.persona_id = t.persona_id AND e.perspective_id = t.perspective_id AND e.classification_name = t.classification_name AND t.tag = ?"
        
        where_conditions = ["e.agent_id = ?"]
        params = []

        if tag_filter:
            params.append(tag_filter)

        params.append(agent_id)

        if item_id_filter:
            where_conditions.append("e.item_id = ?")
            params.append(item_id_filter)

        if time_filter:
            where_conditions.append("e.timestamp >= ?")
            params.append(time_filter)

        if values_same is not None:
            if values_same:
                where_conditions.append("e.old_evaluation_likert_val = e.new_evaluation_likert_val")
            else:
                where_conditions.append("e.old_evaluation_likert_val != e.new_evaluation_likert_val")

        where_clause = " WHERE " + " AND ".join(where_conditions)
        
        total_cursor = conn.execute("SELECT COUNT(*) " + base_query + where_clause, params)
        total_items = total_cursor.fetchone()[0]
        remaining_items = max(total_items - (page * count), 0)

        data_query = "SELECT e.agent_id, e.item_id, e.context_id, e.persona_id, e.perspective_id, e.classification_name,"
        data_query += " e.old_evaluation_likert_val, e.new_evaluation_likert_val, e.tags, e.additional_details, e.timestamp"
        data_query += base_query
        data_query += where_clause

        if by_uuid or desc:
            data_query += " ORDER BY "
            if by_uuid:
                 data_query += "e.item_id, e.timestamp"
            else:
                data_query += "e.timestamp, e.item_id"
            if desc:
                data_query += " DESC"

        data_query += " LIMIT ? OFFSET ?"
        
        params.extend([count, offset])

        logger.debug(f"base_query: {base_query}")
        logger.debug(f"data_query: {data_query}")
        logger.debug(f"params: {params}")

        data_cursor = conn.execute(data_query, params)
        
        response_data = []
        
        for row in data_cursor:

            logger.debug("Processing row...")

            tags_json = []
            if row['tags']:
                tags_json = json.loads(row['tags']) 

            responseItem = {
                'agentId': row['agent_id'],
                'itemId': row['item_id'],
                'contextId': row['context_id'],
                'personaId': row['persona_id'],
                'perspectiveId': row['perspective_id'],
                'classificationName': row['classification_name'],
                'oldEvaluationVikertVal': row['old_evaluation_likert_val'],
                'newEvaluationVikertVal': row['new_evaluation_likert_val'],
                'tags': tags_json,
                'tagFilter': tag_filter,
                'timestamp': row['timestamp']
            }
            
            if is_detail:
                additional_details = {}
                if row['additional_details']:
                    additional_details = json.loads(row['additional_details']) 
                responseItem['additionalDetails'] = additional_details
            
            response_data.append(responseItem)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'page': page,
            'count': count,
            'remaining': remaining_items,
            'data': response_data
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/do-eval/<mode>', methods=['POST'])
@require_api_auth
def do_evaluation(mode):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        content = get_required_reqjson_val(reqjson, "content")
        model = get_reqjson_val(reqjson, "model", None)
        lightweight_mode = get_reqjson_val(reqjson, "lightweight_mode", True)
        openai_params = get_reqjson_val(reqjson, "openai_params", {})

        openai_params = get_reqjson_val(reqjson, "openai_params", {})

        logger.debug(f"content: {content}; model: {model}; openai_params: {openai_params}")

        evaluation_system_message_common = g.evaluation_system_message_common
        evaluation_request_schema = g.evaluation_request_schema

        openai_auth_token = request.headers.get('OpenAI-Auth-Token', current_app.config['OPENAI_AUTH_TOKEN'])

        evaluation_processor = get_evaluation_processor(CLIENT_ID, mode, openai_auth_token)

        if lightweight_mode:
            is_use_request_schema = False
        else:
            is_use_request_schema = True

        evaluation_results, info_json  = evaluation_processor.get_evaluation(
                    eval_request=content,
                    model=model,
                    is_use_request_schema=is_use_request_schema,
                    openai_params=openai_params)
        #logger.debug(f"evaluation_results:\n{evaluation_results}")

        response_json = {
            "status": "OK",
            "message": "Evaluation complete",
            "result": evaluation_results,
            "info": info_json 
            }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@evaluation_routes.route('/process-evals/<mode>', methods=['POST'])
@require_api_auth
def process_evaluations(mode):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        tag_source = get_required_reqjson_val(reqjson, "tag_source")
        tags_dest = get_required_reqjson_val(reqjson, "tags_dest")
        openai_model = get_required_reqjson_val(reqjson, "model")

        persona_json = get_required_reqjson_val(reqjson, "persona")
        perspectives = get_required_reqjson_val(reqjson, "perspectives")

        lightweight_mode = get_reqjson_val(reqjson, "lightweight_mode", True)
        openai_params = get_reqjson_val(reqjson, "openai_params", {})

        is_exclude_existing = get_reqjson_val(reqjson, "exclude_existing", True)

        subset_tag = get_reqjson_val(reqjson, "subset_tag", None)
        subset_percent = get_reqjson_val(reqjson, "subset_percent", None)
        is_most_recent = get_reqjson_val(reqjson, "is_most_recent", False)
        last_n_hours = get_reqjson_val(reqjson, "last_n_hours", None)
        
        by_uuid = get_reqjson_val(reqjson, "by_uuid", True)

        items_to_process = int(get_arg(request, "items_to_process", 1))

        is_async = request.args.get("async", type=str_to_bool, default=False)
        is_dry_run = request.args.get("dry_run", type=str_to_bool, default=False)

        openai_auth_token = request.headers.get('OpenAI-Auth-Token', current_app.config['OPENAI_AUTH_TOKEN'])

        evaluation_processor = get_evaluation_processor(CLIENT_ID, mode, openai_auth_token, job_id=None)

        job_status = evaluation_processor.run_evaluations(
                            tag_source=tag_source,
                            tags_dest=tags_dest,
                            openai_model=openai_model,
                            persona=persona_json,
                            perspectives=perspectives,
                            items_to_process=items_to_process,
                            lightweight_mode=lightweight_mode,
                            openai_params=openai_params,
                            is_exclude_existing=is_exclude_existing,
                            subset_tag=subset_tag,
                            subset_percent=subset_percent,
                            is_most_recent=is_most_recent,
                            last_n_hours=last_n_hours,
                            by_uuid=by_uuid,
                            is_async=is_async,
                            is_dry_run=is_dry_run)

        job_id = job_status["job_id"]

        store_evaluation_processor(mode, job_id, evaluation_processor)

        return resp.generate_response_with_data(job_status, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@evaluation_routes.route('/process-evals/<mode>/<job_id>', methods=['GET'])
@require_api_auth
def query_evaluations(mode, job_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        evaluation_processor = get_evaluation_processor(CLIENT_ID, mode, job_id=job_id)
        if not evaluation_processor:
            return resp.generate_response_with_data(f"Evaluation processor not found for job: {mode}/{job_id}", 404)

        job_status = evaluation_processor.job_statuses.get(job_id, {})
        if not job_status:
            return resp.generate_response_with_data(f"Job not found: {mode}/{job_id}", 404)

        return resp.generate_response_with_data(job_status, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@evaluation_routes.route('/record-evaluation-job/<mode>', methods=['POST'])
@require_api_auth
def record_evaluation_job(mode):

    agent_id, resp, conn = init_route(request)

    items_list = []

    try:

        job_status = get_reqjson(request)

        job_id = job_status["job_id"]
        eval_info = job_status["eval_info"]

        processed_items = job_status["processed_items"]

        usage = job_status["usage"]
        completion_tokens = usage["completion_tokens"]
        prompt_tokens = usage["prompt_tokens"]
        total_tokens = usage["total_tokens"]

        tag_source = job_status["tag_source"]
        tags_dest = job_status["tags_dest"]
        first_tag_dest = tags_dest[0]

        status = job_status["status"]

        if job_status["is_error"]:
            is_error = 1
        else:
            is_error = 0

        openai_model = job_status["openai_model"]

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        conn.execute("INSERT OR REPLACE INTO evaluation_jobs \
            (agent_id, job_id, mode, eval_info, status, is_error, processed_items, completion_tokens, prompt_tokens, total_tokens, tag_source, tags_dest, first_tag_dest, openai_model, job_status, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, job_id, mode, json.dumps(eval_info), status, is_error, processed_items, completion_tokens, prompt_tokens, total_tokens, tag_source, json.dumps(tags_dest), first_tag_dest, openai_model, json.dumps(job_status), timestamp))

        conn.commit()

        return resp.generate_response_with_data(f"Record added successfully for job_id: {job_id}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@evaluation_routes.route('/get-evaluation-jobs', methods=['GET'])
@require_api_auth
def get_evaluation_jobs():

    agent_id, resp, conn = init_route(request)

    try:

        page = int(get_arg(request, "page", 1))
        count = int(get_arg(request, "count", 5))
        offset = (page - 1) * count

        job_id = get_arg(request, "job_id", None)
        mode = get_arg(request, "mode", None)
        status = get_arg(request, "status", None)
        is_error = get_arg(request, "is_error", None)
        tag_source = get_arg(request, "tag_source", None)
        first_tag_dest = get_arg(request, "first_tag_dest", None)
        openai_model = get_arg(request, "openai_model", None)
        last_n_hours = get_arg(request, "last_n_hours", None)

        is_show_info = request.args.get("show_info", type=str_to_bool, default=True)
        is_show_detail = request.args.get("show_detail", type=str_to_bool, default=False)
        desc = request.args.get("desc", type=str_to_bool, default=True)

        conn = get_db_conn()
        init_db_tables(conn)
        c = conn.cursor()

        # Base query
        select_columns = """
            agent_id, job_id, mode, eval_info, status, 
            is_error, processed_items, completion_tokens, prompt_tokens, 
            total_tokens, tag_source, tags_dest, first_tag_dest, openai_model,
            job_status, timestamp
        """

        query = f"SELECT {select_columns} FROM evaluation_jobs WHERE agent_id = ?"
        count_query = "SELECT COUNT(*) FROM evaluation_jobs WHERE agent_id = ?"
        summary_query = """
            SELECT SUM(processed_items) as total_processed_items,
                   SUM(completion_tokens) as total_completion_tokens,
                   SUM(prompt_tokens) as total_prompt_tokens,
                   SUM(total_tokens) as total_total_tokens
            FROM evaluation_jobs WHERE agent_id = ?
        """

        def append_query_part(param_name, value):

            nonlocal query, count_query, summary_query

            if value is not None:
                query += f" AND {param_name} = ?"
                count_query += f" AND {param_name} = ?"
                summary_query += f" AND {param_name} = ?"
                return True
            return False

        applied_filters = {}

        params = [agent_id]
        count_params = [agent_id]
        summary_params = [agent_id]

        if is_error is not None:
            if is_error:
                is_error_val = 1
            else:
                is_error_val = 0
        else:
            is_error_val = None

        for param, value in [("job_id", job_id), ("mode", mode), ("status", status), ("is_error", is_error_val),
                             ("tag_source", tag_source), ("first_tag_dest", first_tag_dest), ("openai_model", openai_model)]:
            if append_query_part(param, value):
                params.append(value)
                count_params.append(value)
                summary_params.append(value)
                applied_filters[param] = value

        if last_n_hours:
            last_n_hours = int(last_n_hours)
            query += " AND timestamp >= ?"
            count_query += " AND timestamp >= ?"
            summary_query += " AND timestamp >= ?"
            time_threshold = datetime.now() - timedelta(hours=last_n_hours)
            time_threshold_str = time_threshold.strftime("%Y-%m-%d %H:%M:%S")
            params.append(time_threshold_str)
            count_params.append(time_threshold_str)
            summary_params.append(time_threshold_str)

        order_direction = "DESC" if desc else "ASC"
        query += f" ORDER BY timestamp {order_direction} LIMIT ? OFFSET ?"
        params.extend([count, offset])

        c.execute(query, tuple(params))
        rows = c.fetchall()

        c.execute(count_query, tuple(count_params))
        total_records = c.fetchone()[0]

        remaining_records = max(total_records - (page * count), 0)

        c.execute(summary_query, tuple(summary_params))
        summary = c.fetchone()

        response_data = []

        for row in rows:
            job_status = json.loads(row["job_status"])
            if "init_remaining" in job_status:
                init_remaining = job_status["init_remaining"]
            else:
                init_remaining = None
            job_data = {
                "agent_id": row["agent_id"],
                "job_id": row["job_id"],
                "status": row["status"],
                "first_tag_dest": row["first_tag_dest"],
                "processed_items": row["processed_items"],
                "init_remaining": init_remaining,       # From job_status
                "remaining": job_status["remaining"],   # From job_status
                "is_error": row["is_error"],
                "eval_info": None,
                "mode": row["mode"],
                "completion_tokens": row["completion_tokens"],
                "prompt_tokens": row["prompt_tokens"],
                "total_tokens": row["total_tokens"],
                "tag_source": row["tag_source"],
                "tags_dest": row["tags_dest"],
                "openai_model": row["openai_model"],
                "job_status": None,
                "timestamp": row["timestamp"]
            }
            if is_show_info:
                job_data["eval_info"] = json.loads(row["eval_info"])
            if is_show_detail:
                job_data["job_status"] = job_status
            response_data.append(job_data)

        response_json = {
            "status": "OK",
            "message": "OK",
            "summary": {
                "total_processed_items": summary["total_processed_items"] if summary["total_processed_items"] is not None else 0,
                "total_completion_tokens": summary["total_completion_tokens"] if summary["total_completion_tokens"] is not None else 0,
                "total_prompt_tokens": summary["total_prompt_tokens"] if summary["total_prompt_tokens"] is not None else 0,
                "total_total_tokens": summary["total_total_tokens"] if summary["total_total_tokens"] is not None else 0,
                "applied_filters": applied_filters
            },
            "data": response_data,
            "page": page,
            "count": count,
            "remaining": remaining_records,
            "total_records": total_records
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)

