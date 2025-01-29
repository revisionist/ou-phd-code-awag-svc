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
from collections import defaultdict

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn

from authentication import require_api_auth

from .shared_resources import *

flow_monitor_routes = Blueprint('flow_monitor_routes', __name__)


def init_db_tables(conn):

    conn.execute('''CREATE TABLE IF NOT EXISTS flow_record
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     event_time_ms INTEGER not null,
                     event_time_text TEXT not null,
                     item_secondary_id TEXT,
                     item_category TEXT not null,
                     item_type INTEGER not null,
                     item_extra TEXT,
                     event_type_id INTEGER not null,
                     event_type_label TEXT not null,
                     event_text TEXT,
                     source_class_canonical TEXT not null,
                     source_class TEXT not null,
                     queue_class_canonical TEXT,
                     queue_class TEXT,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, event_time_ms, event_type_id, source_class))''')
    conn.commit()


@flow_monitor_routes.route('/flow-monitor-record', methods=['POST'])
@require_api_auth
def flow_monitor_record():

    agent_id, resp, conn = init_route(request)

    try:

        reqjson = get_reqjson(request)

        item_id = get_required_reqjson_val(reqjson, "itemId")
        event_time_ms = get_required_reqjson_val(reqjson, "eventDateTimeMs")
        event_time_text = get_required_reqjson_val(reqjson, "eventDateTimeText")
        item_category = get_required_reqjson_val(reqjson, "itemCategory")
        item_type = get_required_reqjson_val(reqjson, "itemType")
        event_type_id = get_required_reqjson_val(reqjson, "eventTypeId")
        event_type_label = get_required_reqjson_val(reqjson, "eventTypeLabel")
        source_class_canonical = get_required_reqjson_val(reqjson, "sourceClassCanonical")
        source_class = get_required_reqjson_val(reqjson, "sourceClass")

        item_secondary_id = get_reqjson_val(reqjson, "itemSecondaryId", None)
        item_extra = get_reqjson_val(reqjson, "itemExtra", None)
        event_text = get_reqjson_val(reqjson, "eventText", None)
        queue_class_canonical = get_reqjson_val(reqjson, "queueClassCanonical", None)
        queue_class = get_reqjson_val(reqjson, "queueClass", None)

        logger.debug(f"Item: {agent_id} - {item_id} - {item_type} - {event_type_label} - {source_class}")

        conn = get_db_conn()
        init_db_tables(conn)

        cursor = conn.cursor()

        timestamp = str(datetime.now())

        conn.execute("INSERT INTO flow_record \
            (agent_id, item_id, event_time_ms, event_time_text, item_secondary_id, item_category, item_type, item_extra, event_type_id, event_type_label, event_text, source_class_canonical, source_class, queue_class_canonical, queue_class, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
                     (agent_id, item_id, event_time_ms, event_time_text, item_secondary_id, item_category, item_type,
                      item_extra, event_type_id, event_type_label, event_text, source_class_canonical, source_class,
                      queue_class_canonical, queue_class, timestamp))

        conn.commit()

        return resp.generate_response_with_data(f"Flow record added successfully for item: {item_id}", 201)

    except Exception as err:

        conn_rollback(conn)
        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)


@flow_monitor_routes.route('/get-flow-monitor-records', methods=['GET'])
@require_api_auth
def get_flow_monitor_records():

    agent_id, resp, conn = init_route(request)

    try:

        item_id = get_arg(request, "itemId", None)
        event_type_id = get_arg(request, "eventTypeId", None)
        item_category = get_arg(request, "itemCategory", None)
        item_secondary_id = get_arg(request, "itemSecondaryId", None)
        last_n_hours = get_arg(request, "lastNHours", None)
        last_n_minutes = get_arg(request, "lastNMinutes", None)

        conn = get_db_conn()

        cursor = conn.cursor()

        query = "SELECT * FROM flow_record WHERE agent_id=?"
        parameters = [agent_id]

        if item_id:
            query += " AND item_id=?"
            parameters.append(item_id)
        if event_type_id:
            query += " AND event_type_id=?"
            parameters.append(event_type_id)
        if item_category:
            query += " AND item_category=?"
            parameters.append(item_category)
        if item_secondary_id:
            query += " AND item_secondary_id=?"
            parameters.append(item_secondary_id)
        if last_n_hours:
            current_time_ms = int(time.time() * 1000)
            n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
            query += " AND event_time_ms >= ?"
            parameters.append(n_hours_ago_ms)
        elif last_n_minutes:
            current_time_ms = int(time.time() * 1000)
            n_minutes_ago_ms = current_time_ms - (int(last_n_minutes) * 60 * 1000)
            query += " AND event_time_ms >= ?"
            parameters.append(n_minutes_ago_ms)

        query += " ORDER BY event_time_ms DESC"

        # Select rows based on the filters
        cursor.execute(query, parameters)

        # Fetch all rows as a list of dictionaries
        rows = cursor.fetchall()

        # Convert each row to a dictionary
        results = []
        for row in rows:
            result = {
                'agent': row["agent_id"],
                'eventDateTime': row["event_time_text"],
                'itemId': row["item_id"],
                'itemSecondaryId': row["item_secondary_id"],
                'eventTypeId': row["event_type_id"],
                'eventTypeLabel': row["event_type_label"],
                'itemCategory': row["item_category"],
                'itemType': row["item_type"],
                'sourceClass': row["source_class"],
                'queueClass': row["queue_class"],
                'itemExtra': row["item_extra"],
                'eventText': row["event_text"],
                'timestamp': row["timestamp"]
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

