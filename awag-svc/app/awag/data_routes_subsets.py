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
import random

from flask import Blueprint, current_app, g, jsonify, request, make_response

from datetime import datetime, timedelta
from collections import defaultdict

from domestique.logging import log_exception
from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.flask.response import ResponseWrapper
from domestique.convert import str_to_bool
from domestique.rfc2822 import parse_rfc_address
from domestique.text import tidy_and_truncate_string

from authentication import require_api_auth

from .shared_resources import *

subsets_routes = Blueprint('subsets_routes', __name__)


def init_db_tables(conn):

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_id_subsets
                    (agent_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    subset_percent INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (agent_id, item_id, subset_percent, tag))''')
    conn.commit()


@subsets_routes.route('/subset/<tag>/<subset_percent>', methods=['POST'])
@require_api_auth
def update_subset(tag, subset_percent):

    agent_id, resp, conn = init_route(request)

    try:

        output_tag = get_arg(request, "output_tag", tag)

        is_incremental = request.args.get('incremental', type=str_to_bool, default=False)

        logger.debug(f"tag: {tag}; output_tag: {output_tag}; subset_percent: {subset_percent}; is_incremental: {is_incremental}")

        subset_percent = validate_subset_percent(subset_percent)

        timestamp = str(datetime.now())
        conn = get_db_conn()
        init_db_tables(conn)

        item_ids_x = conn.execute('''SELECT distinct item_id FROM classification_record_tags WHERE tag = ?''', (tag,)).fetchall()
        all_item_ids = [row[0] for row in item_ids_x]

        all_item_ids_count = len(all_item_ids)
        logger.debug(f"There are: {all_item_ids_count} item_ids for tag: {tag}")

        if all_item_ids_count == 0:
            return resp.generate_response_with_data(f"No items for tag: {tag}", 404)

        subset_size = max(1, int(all_item_ids_count * (subset_percent / 100)))

        existing_item_ids = set()
        if is_incremental:
            existing_items = conn.execute('''SELECT item_id FROM classification_id_subsets WHERE agent_id = ? AND tag = ? AND subset_percent = ?''', (agent_id, output_tag, subset_percent)).fetchall()
            existing_item_ids = {item[0] for item in existing_items}

        existing_item_ids_count = len(existing_item_ids)
        additional_items_needed = max(0, subset_size - existing_item_ids_count)
        remaining_items = [item_id for item_id in all_item_ids if item_id not in existing_item_ids]
        new_random_subset = random.sample(remaining_items, additional_items_needed)

        if additional_items_needed != len(new_random_subset):
            raise ValueError(f"Mismatch between additional_items_needed {additional_items_needed} and len(new_random_subset) {len(new_random_subset)}!")

        final_subset = list(existing_item_ids) + new_random_subset

        logger.debug(f"Built subset of length: {len(final_subset)}")

        if subset_size != len(final_subset):
            raise ValueError(f"Mismatch between subset_size {subset_size} and len(final_subset) {len(final_subset)}!")

        conn.execute('''DELETE FROM classification_id_subsets
                    WHERE agent_id = ? AND tag = ? AND subset_percent = ?''', 
                    (agent_id, output_tag, subset_percent))

        for item_id in final_subset:
            logger.debug(f"Writing: agent_id: {agent_id}; item_id: {item_id}; subset_percent: {subset_percent}; tag: {tag}")
            conn.execute('''INSERT INTO classification_id_subsets
                        (agent_id, item_id, subset_percent, tag, timestamp)
                        VALUES (?, ?, ?, ?, ?)''', 
                        (agent_id, item_id, subset_percent, output_tag, timestamp))

        conn.commit()

        message = f"Generated {subset_percent}% subset of {subset_size}/{all_item_ids_count} items from source tag '{tag}' using output_tag '{output_tag}'."
        if is_incremental:
            message += f"This was an INCREMENTAL update from an existing subset of size {existing_item_ids_count}"

        response_json = {
            "status": "OK",
            "message": message,
            "subset_size": subset_size,
            "all_item_ids_count": all_item_ids_count,
        }

        if is_incremental:
            response_json["existing_item_ids_count"] = existing_item_ids_count
            response_json["additional_items_needed"] = additional_items_needed
            response_json["final_subset_size"] = len(final_subset)

        return resp.generate_response_with_data(response_json, 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@subsets_routes.route('/subset', methods=['GET'])
@require_api_auth
def get_subset_tags():

    agent_id, resp, conn = init_route(request)

    try:

        response_json = {
            "status": "OK",
            "message": "OK",
            "data": []
        }

        conn = get_db_conn()

        logger.debug(f"agent_id: {agent_id}")

        tags_x = conn.execute("SELECT distinct tag FROM classification_id_subsets WHERE agent_id = ? ORDER BY 1",
                    (agent_id,)).fetchall()
        response_json["data"] = [row[0] for row in tags_x]

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@subsets_routes.route('/subset/<tag>', methods=['GET'])
@subsets_routes.route('/subset/<tag>/<subset_percent>', methods=['GET'])
@require_api_auth
def get_subset(tag, subset_percent=None):

    agent_id, resp, conn = init_route(request)

    try:

        logger.debug(f"tag: {tag}; subset_percent: {subset_percent}")

        response_json = {
            "status": "OK",
            "message": "OK",
            "data": []
        }

        conn = get_db_conn()

        if subset_percent is None:

            percents_x = conn.execute('''SELECT distinct subset_percent FROM classification_id_subsets
                        WHERE agent_id = ? AND tag = ? ORDER BY 1 ASC''',
                        (agent_id, tag)).fetchall()
            response_json["data"] = [row[0] for row in percents_x]

        else:

            subset_percent = validate_subset_percent(subset_percent)

            item_ids_x = conn.execute('''SELECT item_id FROM classification_id_subsets
                        WHERE agent_id = ? AND tag = ? AND subset_percent = ?''', 
                        (agent_id, tag, subset_percent)).fetchall()
            response_json["data"] = [row[0] for row in item_ids_x]

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@subsets_routes.route('/subset/<tag>/<subset_percent>', methods=['DELETE'])
@require_api_auth
def delete_subset():

    agent_id, resp, conn = init_route(request)

    try:

        logger.debug(f"tag: {tag}; subset_percent: {subset_percent}")

        validate_subset_percent(subset_percent)

        conn = get_db_conn()
        init_db_tables(conn)

        conn.execute('''DELETE FROM classification_id_subsets
                    WHERE agent_id = ? AND tag = ? AND subset_percent = ?''', 
                    (agent_id, tag, subset_percent))

        conn.commit()

        response_json = {
            "status": "OK",
            "message": f"Deleted {subset_percent}% subset with tag: {tag}"
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)
