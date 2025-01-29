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

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.convert import extract_object_by_property

from authentication import require_api_auth

from .shared_resources import logger, init_route

summarisation_routes = Blueprint('summarisation_routes', __name__)


def init_db_tables(conn):

    conn.execute('''CREATE TABLE IF NOT EXISTS summarisation_request_record
                    (agent_id TEXT not null,
                    item_id TEXT not null,
                    summary_input TEXT not null,
                    summary_output TEXT not null,
                    source_type TEXT not null,
                    additional_details JSON not null,
                    timestamp TEXT not null,
                    PRIMARY KEY (agent_id, item_id))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS summarisation_feedback_record
                    (agent_id TEXT not null,
                    item_id TEXT not null,
                    feedback_value int not null,
                    additional_details JSON not null,
                    timestamp TEXT not null,
                    PRIMARY KEY (agent_id, item_id))''')
    conn.commit()


def log_exception(agent_id, e):

    message = f"An error occurred for agent_id '{agent_id}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


@summarisation_routes.route('/record-summarisation-request', methods=['POST'])
@require_api_auth
def record_summarisation_request():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        item_id = get_required_reqjson_val(reqjson, "itemId")
        summary_input = get_required_reqjson_val(reqjson, "summaryInput")
        summary_output = get_required_reqjson_val(reqjson, "summaryOutput")
        source_type = get_required_reqjson_val(reqjson, "sourceType")
        additional_details = get_reqjson_val(reqjson, "additionalDetails", {})

        conn = get_db_conn()
        init_db_tables(conn)

        cursor = conn.cursor()

        cursor.execute("SELECT * FROM summarisation_request_record WHERE agent_id=? AND item_id=?", (agent_id, item_id))
        result = cursor.fetchone()

        if result:
            return resp.generate_response_with_data(f"Record with agent_id {agent_id} and item_id {item_id} already exists", 409)

        timestamp = str(datetime.now())

        conn.execute("INSERT INTO summarisation_request_record (agent_id, item_id, summary_input, summary_output, source_type, additional_details, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?)", (agent_id, item_id, summary_input, summary_output, source_type, json.dumps(additional_details), timestamp))

        conn.commit()

        return resp.generate_response_with_data(f"Record with agent_id {agent_id} and item_id {item_id} added successfully", 201)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@summarisation_routes.route('/get-summarisation-requests', methods=['GET'])
@require_api_auth
def get_summarisation_requests():

    agent_id, resp, conn = init_route(request)

    try:

        limit = get_arg(request, "limit", None)

        conn = get_db_conn()
        cursor = conn.cursor()

        # Construct the SQL query with an optional limit
        query = "SELECT * FROM summarisation_request_record WHERE agent_id=?"
        if limit is not None:
            query += " ORDER BY timestamp DESC LIMIT ?"

        # Execute the query with optional limit parameter
        if limit is not None:
            cursor.execute(query, (agent_id, limit))
        else:
            cursor.execute(query, (agent_id,))

        # Fetch all rows as a list of tuples
        rows = cursor.fetchall()

        # Convert each row to a dictionary
        results = []
        for row in rows:
            result = {
                'agent': row[0],
                'itemId': row[1],
                'summaryInput': row[2],
                'summaryOutput': row[3],
                'sourceType': row[4],
                'additionalDetails': json.loads(row[5]),
                'timestamp': row[6]
            }
            results.append(result)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'limit': limit,
            'data': results
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@summarisation_routes.route('/record-summarisation-feedback', methods=['POST'])
@require_api_auth
def record_summarisation_feedback():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        item_id = get_required_reqjson_val(reqjson, "itemId")
        feedback_value = get_required_reqjson_val(reqjson, "feedbackValue")
        additional_details = get_reqjson_val(reqjson, "additionalDetails", {})

        logger.debug(f"Item: {agent_id} - {item_id}  - {feedback_value}")

        conn = get_db_conn()
        init_db_tables(conn)

        cursor = conn.cursor()

        cursor.execute("SELECT * FROM summarisation_feedback_record WHERE agent_id=? AND item_id=?", (agent_id, item_id))
        result = cursor.fetchone()

        if result:
            logger.debug('Deleting existing record: ' + str(agent_id) + ' - ' + str(item_id) + ' - ' + str(feedback_value))
            cursor.execute("delete FROM summarisation_feedback_record WHERE agent_id=? AND item_id=?", (agent_id, item_id))

        timestamp = str(datetime.now())

        conn.execute("INSERT INTO summarisation_feedback_record (agent_id, item_id, feedback_value, additional_details, timestamp) \
            VALUES (?, ?, ?, ?, ?)", (agent_id, item_id, feedback_value, additional_details, timestamp))

        conn.commit()

        return resp.generate_response_with_data(f"Record with agent_id {agent_id} and item_id {item_id} added successfully for feedback value: {feedback_value}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@summarisation_routes.route('/get-summarisation-feedback', methods=['GET'])
@require_api_auth
def get_summarisation_feedback():

    agent_id, resp, conn = init_route(request)

    try:

        limit = get_arg(request, "limit", None)

        conn = get_db_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM summarisation_feedback_record WHERE agent_id=?"
        if limit is not None:
            query += " ORDER BY timestamp DESC LIMIT ?"

        if limit is not None:
            cursor.execute(query, (agent_id, limit))
        else:
            cursor.execute(query, (agent_id,))

        rows = cursor.fetchall()

        results = []
        for row in rows:
            result = {
                'agent': row[0],
                'itemId': row[1],
                'feedbackValue': row[2],
                'additionalDetails': json.loads(row[3]),
                'timestamp': row[4]
            }
            results.append(result)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'limit': limit,
            'data': results
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@summarisation_routes.route('/get-summarisation-feedback-completed', methods=['GET'])
@require_api_auth
def get_summarisation_feedback_completed():

    agent_id, resp, conn = init_route(request)

    try:

        conn = get_db_conn()
        cursor = conn.cursor()

        cursor.execute(
            "select s.agent_id, f.item_id, s.summary_input, s.summary_output, f.feedback_value, s.additional_details sad, f.additional_details fad, f.timestamp from summarisation_request_record s inner join summarisation_feedback_record f on s.agent_id = f.agent_id and s.item_id = f.item_id  WHERE s.agent_id=?",
            (agent_id,))

        rows = cursor.fetchall()

        results = []
        for row in rows:
            adS = json.loads(row[5])
            adF = json.loads(row[6])

            result = {
                'agent': row[0],
                'itemId': row[1],
                'summaryInput': row[2],
                'summaryOutput': row[3],
                'feedbackValue': row[4],
                'itemUrl': adS['itemUrl'],
                'providerName': adS['providerName'],
                'providerUrl': adS['providerUrl'],
                'channelName': adF['channel']['name'],
                'userName': adF['user']['name'],
                'timestamp': row[7]
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
