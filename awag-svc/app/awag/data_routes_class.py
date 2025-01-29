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
from .client_mgmt_resources import get_awagdata_client, get_awagml_client

classification_routes = Blueprint('classification_routes', __name__)

ACTION_USER_ID = "awagui"

awagdata_clients = {}
awagml_clients = {}


def init_db_tables(conn):

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_record
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     classification_name TEXT not null,
                     classification TEXT not null,
                     available_classifications JSON not null,
                     body_text TEXT not null,
                     additional_details JSON not null,
                     tags JSON,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_record_tags
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     classification_name TEXT not null,
                     tag string,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name, tag))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_actions
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     action_user_id TEXT not null,
                     classification_name TEXT not null,
                     classification_orig TEXT not null,
                     classification_new TEXT not null,
                     body_text TEXT not null,
                     additional_details JSON not null,
                     tags JSON,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_actions_tags
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     classification_name TEXT not null,
                     tag string,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name, tag))''')
    conn.commit()

    conn.execute('''CREATE TABLE IF NOT EXISTS classification_item_ignore
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id))''')
    conn.commit()


@classification_routes.route('/record-classification', methods=['POST'])
@require_api_auth
def record_classification():

    agent_id, resp, conn = init_route(request)

    items_list = []

    try:

        reqjson = get_reqjson(request)

        item_id = reqjson['itemId']
        logger.debug('Item: ' + str(item_id))
        classification_name = reqjson['classificationName']
        classification = reqjson['classification']
        available_classifications = json.dumps(reqjson['availableClassifications'])
        body_text = reqjson['bodyText']

        additional_details = json.dumps(reqjson['additionalDetails'])
        #logger.debug('additional_details: ' + str(additional_details))

        tags = reqjson['tags']
        if not isinstance(tags, list):
            raise TypeError(f"tags is not a valid array: {tags}")
        tags_json = json.dumps(tags)

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        additional_details = json.dumps(reqjson['additionalDetails'])
        logger.debug('additional_details: ' + tidy_and_truncate_string(additional_details, 100))

        for tag in tags:
            logger.debug('Processing tag: ' + str(tag))
            conn.execute("REPLACE INTO classification_record_tags \
                (agent_id, item_id, classification_name, tag, timestamp) \
                VALUES (?, ?, ?, ?, ?)", \
                (agent_id, item_id, classification_name, tag, timestamp))

        conn.execute("REPLACE INTO classification_record \
            (agent_id, item_id, classification_name, classification, available_classifications, body_text, additional_details, tags, timestamp) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", \
            (agent_id, item_id, classification_name, classification, available_classifications, body_text, additional_details, tags_json, timestamp))

        conn.commit()

        return resp.generate_response_with_data(f"Record added successfully for item_id: {item_id}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@classification_routes.route('/record-classification-action', methods=['POST'])
@require_api_auth
def record_classification_action():

    agent_id, resp, conn = init_route(request)

    items_list = []

    try:

        reqjson = get_reqjson(request)

        item_id = reqjson['itemId']
        logger.debug('Item: ' + str(item_id))
        action_user_id = reqjson['actionUserId']
        classification_name = reqjson['classificationName']
        classification_orig = reqjson['classificationOrig']
        classification_new = reqjson['classificationNew']
        body_text = reqjson['bodyText']
        
        additional_details = json.dumps(reqjson['additionalDetails'])
        #logger.debug('additional_details: ' + str(additional_details))

        tags = reqjson['tags']
        if not isinstance(tags, list):
            message = f"Invalid tags array: {tags}"
            logger.error(message)
            return resp.generate_response_with_data(message, 400)
        tags_json = json.dumps(tags)

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        # Check if a record already exists
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM classification_actions WHERE agent_id = ? AND item_id = ? AND classification_name = ?", (agent_id, item_id, classification_name))

        if cur.fetchone()[0] > 0:
            # Log and prepare response for existing record

            message = f"Record already exists for item_id: {item_id} and classification_name: {classification_name}"
            logger.info(message)
            return resp.generate_response_with_data(message, 200)

        else:
            # Insert new records
            
            for tag in tags:
                logger.debug('Processing tag: ' + str(tag))
                conn.execute("REPLACE INTO classification_actions_tags \
                    (agent_id, item_id, classification_name, tag, timestamp) \
                    VALUES (?, ?, ?, ?, ?)", \
                    (agent_id, item_id, classification_name, tag, timestamp))

            conn.execute("INSERT INTO classification_actions \
                (agent_id, item_id, action_user_id, classification_name, classification_orig, classification_new, body_text, additional_details, tags, timestamp) \
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", \
                (agent_id, item_id, action_user_id, classification_name, classification_orig, classification_new, body_text, additional_details, tags_json, timestamp))

            conn.commit()

            message = f"Record added successfully item_id: {item_id} and classification_name: {classification_name}"
            logger.debug(message)

            return resp.generate_response_with_data(message, 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


def get_training_paginated_item_ids(conn, query_from, query_where, query_params, count, offset):

    responseData = []

    query_item_ids_params = query_params.copy()

    query_parts = ["SELECT DISTINCT r.item_id"]
    query_parts.append(query_from)
    query_parts.append(query_where)
    query_parts.append("ORDER BY r.item_id")
    query_parts.append("LIMIT ? OFFSET ?")
    query_item_ids_params.extend([count, offset])

    query_item_ids = concat_sql(query_parts)
    #logger.debug(f'SQL in get_training_paginated_item_ids: {str(query_item_ids)}')

    item_ids_cursor = conn.execute(query_item_ids, query_item_ids_params)
    item_ids = [row['item_id'] for row in item_ids_cursor]

    logger.debug(f"Built item_id list: {item_ids}")

    return item_ids


@classification_routes.route('/fetch-training-items', methods=['GET'])
@require_api_auth
def fetch_training_items():

    agent_id, resp, conn = init_route(request)

    responseData = []

    try:

        item_id = request.args.get('itemId')
        tag = request.args.get('tag', None)
        desc = request.args.get('desc', type=str_to_bool, default=False)
        
        last_n_hours = request.args.get('lastNHours', None)

        is_only_untrained = request.args.get('onlyIncludeUntrained', type=str_to_bool, default=False)
        is_include_ignored = request.args.get('includeIgnored', type=str_to_bool, default=False)

        classification_names = get_valid_list_from_string(request.args.get('classificationName'))
        type = request.args.get('type')

        subset_percent = request.args.get('subsetPercent', type=int, default=None)
        subset_tag = request.args.get('subsetTag', default=tag)
        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        logger.debug(f'Passed: tag[{tag}], desc[{desc}], item_id[{item_id}], last_n_hours[{last_n_hours}], is_only_untrained[{is_only_untrained}], classification_names[{classification_names}], type[{type}], subset_percent[{subset_percent}]')

        # Calculate the timestamp for filtering if lastNHours is provided
        time_filter = None
        if last_n_hours:
            time_filter = datetime.now() - timedelta(hours=int(last_n_hours))
        
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        count = int(request.args.get('count', 10))
        offset = (page - 1) * count

        logger.debug(f'Passed: page[{page}], count[{count}]')

        if page < 1:
            raise ValueError(f"Invalid page number: {page}")

        if tag is None:
            raise ValueError("Missing tag parameter")

        conn = get_db_conn()

        query_select = """SELECT r.agent_id,
                r.item_id,
                rt.tag AS tag_main,
                r.body_text,
                r.available_classifications,
                r.classification_name,
                r.classification,
                a.classification_new,
                r.tags AS tags_main,
                a.tags AS tags_actions,
                r.additional_details,
                r.timestamp AS record_timestamp
                """

        query_from = """FROM classification_record r
            INNER JOIN classification_record_tags rt
                ON r.agent_id = rt.agent_id
                AND r.item_id = rt.item_id
                AND r.classification_name = rt.classification_name
            LEFT OUTER JOIN classification_item_ignore i
                ON r.agent_id = i.agent_id
                AND r.item_id = i.item_id
            LEFT OUTER JOIN classification_actions a
                ON r.agent_id = a.agent_id
                AND r.item_id = a.item_id
                AND r.classification_name = a.classification_name
        """

        query_where = "WHERE r.agent_id = ?"
        query_params = [agent_id]

        query_where += " AND rt.tag = ?"
        query_params.append(tag)

        if subset_percent is not None:
            query_from += """ LEFT OUTER JOIN classification_id_subsets s
                  ON r.agent_id = s.agent_id
                  AND r.item_id = s.item_id
                  """
            query_where += " AND s.tag = ? AND s.subset_percent = ?"
            query_params.extend([subset_tag, subset_percent])

        if item_id is not None:
            query_where += " AND r.item_id = ?"
            query_params.append(item_id)

        if classification_names is not None and classification_names:
            placeholders = ', '.join(['?' for _ in classification_names])
            query_where += " AND r.classification_name IN ({})".format(placeholders)
            query_params.extend(classification_names)

        if is_only_untrained:
            query_where += " AND a.classification_new is null"

        if not is_include_ignored:
            query_where += " AND i.item_id is null"

        if last_n_hours:
            current_time_ms = int(time.time() * 1000)
            n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
            query_where += " AND r.timestamp >= ?"
            query_params.append(n_hours_ago_ms)

        query_order = ""
        if desc:
            query_order += " ORDER BY r.timestamp DESC"
        else:
            query_order += " ORDER BY r.timestamp ASC"

        total_count_query = concat_sql(["SELECT COUNT(DISTINCT r.item_id)", query_from, query_where])
        #logger.debug(f"Executing total_count_query: {total_count_query}")
        #logger.debug(f"Using query_params: {query_params}")
        total_cursor = conn.execute(total_count_query, query_params)
        total_items = total_cursor.fetchone()[0]
        #logger.debug(f"Got total_items from total_count_query: {total_items}")

        if count < 1:
            logger.debug('Not paging (count < 1)')
            return_count = total_items
            return_page = 1
            remaining_items = 0
        else:
            item_ids = get_training_paginated_item_ids(conn, query_from, query_where, query_params, count, offset)
            query_where += " AND r.item_id IN ({})".format(','.join(['?' for _ in item_ids]))
            query_params.extend(item_ids)
            return_count = count
            return_page = page
            remaining_items = max(total_items - (page * count), 0)

        logger.debug(f'Page: {page}; count: {count}; offset: {offset}; total_items: {total_items}; remaining_items: {remaining_items}')

        query_combined = query_select + query_from + query_where + query_order

        query_combined = concat_sql([query_select, query_from, query_where, query_order])

        #logger.debug(f"Query:\n{query_combined}")
        #logger.debug(f"Query params: {query_params}")

        data_cursor = conn.execute(query_combined, query_params)

        item_data = defaultdict(lambda: {
                    'agentId': None,
                    'itemId': None,
                    'bodyText': None,
                    'summaryText': None,
                    'subject': None,
                    'channel': None,
                    'date': None,
                    'from': None,
                    'to': None,
                    'itemUrl': None,
                    'originator': None,
                    'providerName': None,
                    'providerUrl': None,
                    'type': None,
                    'typeDescription': None,
                    'summaryInfo': None,
                    'tagsMain': [],
                    'classifications': []
        })

        for row in data_cursor:

            tags_main_obj = []
            if row['tags_main']:
                tags_main_obj = json.loads(row['tags_main']) 

            tags_actions_obj = []
            if row['tags_actions']:
                tags_actions_obj = json.loads(row['tags_actions']) 

            item = item_data[row['item_id']]
            if not item['agentId']:
                item.update({
                    'agentId': row['agent_id'],
                    'itemId': row['item_id'],
                    'bodyText': row['body_text'],
                    'tagsMain': tags_main_obj,
                    'timestamp': row['record_timestamp']
                })
            
                additional_details = {}

                if row['additional_details']:
                    additional_details = json.loads(row['additional_details'])
                    if additional_details.get('summaryInfo', None):
                        summary_info = additional_details['summaryInfo']
                        if summary_info['augmentations']:
                            item.update( {'summaryText': summary_info['augmentations'].get('summaryText')})
                        del summary_info['augmentations']   # Not applicable at this level
                        summary_info_type = summary_info['type']
                        if type is not None and summary_info_type != type:
                            pass
                        else:
                            item.update({
                                'summaryInfo': summary_info,
                                'subject': summary_info.get('subject', None),
                                'channel': summary_info.get('channel', None),
                                'date': summary_info.get('date', None),
                                'from': parse_rfc_address(summary_info.get('from', None)),
                                'to': parse_rfc_address(summary_info.get('to', None)),
                                'itemUrl': summary_info.get('itemUrl', None),
                                'originator': summary_info.get('originator', None),
                                'providerName': summary_info.get('providerName', None),
                                'providerUrl': summary_info.get('providerUrl', None),
                                'type': summary_info.get('type', None),
                                'typeDescription': summary_info.get('typeDescription', None)
                            })
            
            item['classifications'].append({
                'classificationName': row['classification_name'],
                'classificationOrig': row['classification'],
                'classificationNew': row['classification_new'],
                'availableClassifications': json.loads(row['available_classifications']),
                'tagAction': tags_actions_obj,
                'timestamp': row['record_timestamp']
            })

        # Convert the defaultdict to a list
        response_data = list(item_data.values())

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

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


def find_classification_by_name(classifications, name):

    for classification in classifications:
        if classification["classificationName"] == name:
            return classification
    return None


@classification_routes.route('/process-classification-feedback', methods=['POST'])
@require_api_auth
def process_classification_feedback():

    agent_id, resp, conn = init_route(request)

    try:
 
        reqjson = get_reqjson(request)

        item_id = reqjson['itemId']
        logger.debug('Item ID: ' + str(item_id))

        additional_details = json.dumps(reqjson['additionalDetails'])

        tag = reqjson['tag']
        logger.debug('Tag: ' + str(tag))

        awagdata_client = get_awagdata_client(awagdata_clients, agent_id)
        awagml_client = get_awagml_client(awagml_clients, agent_id)

        fetched_items, remaining = awagdata_client.fetch_training_items(tag, item_id)
        #logger.debug('Fetched items:\n' + repr(fetched_items))
        
        if not fetched_items:
            raise Exception("Response from fetch_training_items does not contain data:")

        fetched_item = fetched_items[0];
        #logger.debug('Fetched item:\n' + repr(fetched_item))

        classify_text = fetched_item['bodyText']

        for classification in reqjson['classifications']:

            classification_name = classification['classificationName']
            classification_new = classification['classificationNew']
            classification_obj = find_classification_by_name(fetched_item["classifications"], classification_name)
            if not classification_obj:
                logger.debug(f'Classification: {classification_name} not found in {str(fetched_item)}')
                raise Exception(f"Unable to find a classification for item {item_id} with name: {classification_name}")

            classification_orig = classification_obj['classificationOrig']

            awagml_client.perform_model_training(ACTION_USER_ID, classification_name, classify_text, classification_new)

            record_request = {
                'agent': agent_id,
                'itemId': item_id,
                'classificationName': classification_name,
                'classificationOrig': classification_orig,
                'classificationNew': classification_new,
                'bodyText': classify_text,
                'actionUserId': ACTION_USER_ID,
                'tags': [tag],
                'additionalDetails': additional_details
            }

            awagdata_client.record_classification_action(record_request)

        return resp.generate_response_with_data(f"Classification feedback processed for item_id: {item_id}", 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@classification_routes.route('/fetch-classification-actions', methods=['GET'])
@require_api_auth
def fetch_classification_actions():

    agent_id, resp, conn = init_route(request)

    responseData = []

    try:

        item_id = request.args.get('itemId')
        tag = request.args.get('tag', None)
        desc = request.args.get('desc', type=str_to_bool, default=False)

        last_n_hours = request.args.get('lastNHours', None)
        classification_names = get_valid_list_from_string(request.args.get('classificationName'))

        subset_percent = request.args.get('subsetPercent', type=int, default=None)
        subset_tag = request.args.get('subsetTag', default=tag)
        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        logger.debug(f'Passed: tag[{tag}], desc[{desc}], item_id[{item_id}], last_n_hours[{last_n_hours}], classification_names[{classification_names}], type[{type}], subset_percent[{subset_percent}]')

        # Calculate the timestamp for filtering if lastNHours is provided
        time_filter = None
        if last_n_hours:
            time_filter = datetime.now() - timedelta(hours=int(last_n_hours))
        
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        count = int(request.args.get('count', 10))
        offset = (page - 1) * count

        logger.debug(f'Passed: page[{page}], count[{count}]')

        if page < 1:
            raise ValueError(f"Invalid page number: {page}")

        if tag is None:
            raise ValueError("Missing tag parameter")

        conn = get_db_conn()

        query_select = """SELECT a.agent_id,
                a.item_id,
                t.tag,
                a.action_user_id,
                a.body_text,
                r.available_classifications,
                a.classification_name,
                a.classification_orig,
                a.classification_new,
                a.tags,
                a.additional_details,
                a.timestamp AS record_timestamp
                """

        query_from = """FROM classification_actions a
            INNER JOIN classification_actions_tags t
                ON a.agent_id = t.agent_id
                AND a.item_id = t.item_id
                AND a.classification_name = t.classification_name
            INNER JOIN classification_record r
                ON a.agent_id = r.agent_id
                AND a.item_id = r.item_id
                AND a.classification_name = r.classification_name
        """

        query_where = "WHERE a.agent_id = ?"
        query_params = [agent_id]

        query_where += " AND t.tag = ?"
        query_params.append(tag)

        if item_id is not None:
            query_where += " AND a.item_id = ?"
            query_params.append(item_id)

        if classification_names is not None and classification_names:
            placeholders = ', '.join(['?' for _ in classification_names])
            query_where += " AND a.classification_name IN ({})".format(placeholders)
            query_params.extend(classification_names)

        if subset_percent is not None:
            query_from += """ LEFT OUTER JOIN classification_id_subsets s
                  ON a.agent_id = s.agent_id
                  AND a.item_id = s.item_id
                  """
            query_where += " AND s.tag = ? AND s.subset_percent = ?"
            query_params.extend([subset_tag, subset_percent])

        if last_n_hours:
            current_time_ms = int(time.time() * 1000)
            n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
            query_where += " AND a.timestamp >= ?"
            query_params.append(n_hours_ago_ms)

        query_order = ""
        if desc:
            query_order += " ORDER BY a.timestamp DESC"
        else:
            query_order += " ORDER BY a.timestamp ASC"

        total_count_query = concat_sql(["SELECT COUNT(*)", query_from, query_where])
        total_cursor = conn.execute(total_count_query, query_params)
        total_items = total_cursor.fetchone()[0]

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

        logger.debug(f'Page: {page}; count: {count}; offset: {offset}; total_items: {total_items}; remaining_items: {remaining_items}')

        query_combined = concat_sql([query_select, query_from, query_where, query_order, query_limit])

        #logger.debug('Query: \n' + query_combined)
        #logger.debug('Query params: ' + str(query_params))

        data_cursor = conn.execute(query_combined, query_params)

        response_data = []
        classification_descs = {}
        
        awagml_client = get_awagml_client(awagml_clients, agent_id)

        for row in data_cursor:

            tags_obj = []
            if row['tags']:
                tags_obj = json.loads(row['tags']) 

            available_classifications_obj = []
            if row['available_classifications']:
                available_classifications_obj = json.loads(row['available_classifications']) 

            additional_details_obj = {}
            if row['additional_details']:
                additional_details_obj = json.loads(row['additional_details']) 

            classification_name = row["classification_name"]
            if not classification_name in classification_descs:
                classification_descs[classification_name] = awagml_client.get_model_desc(classification_name)

            response_item = {
                'agentId': row["agent_id"],
                'itemId': row["item_id"],
                'bodyText': row["body_text"],
                'classificationName': classification_name,
                'classificationOrig': row["classification_orig"],
                'classificationNew': row["classification_new"],
                'classificationDesc': classification_descs.get(classification_name, None),
                'availableClassifications': available_classifications_obj,
                'actionUserId': row["action_user_id"],
                'tag': row["tag"],
                'tags': tags_obj,
                'subsetTag': subset_tag,
                'subsetPercent': subset_percent,
                'additionalDetails': additional_details_obj,
                'record_timestamp': row["record_timestamp"],
            }

            logger.debug(f"/fetch-classification-actions adding item {item_id}; classification_name: {classification_name}; tag: {tag}")

            response_data.append(response_item)

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'page': return_page,
            'count': return_count,
            'remaining': remaining_items,
            'data': response_data
        }

        logger.debug(f"/fetch-classification-actions returning {len(response_data)} items")

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:
    
        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


@classification_routes.route('/ignore-classification-item', methods=['POST'])
@require_api_auth
def ignore_classification_item():

    agent_id, resp, conn = init_route(request)

    try:
 
        reqjson = get_reqjson(request)

        item_id = reqjson['itemId']
        logger.debug('Item ID: ' + str(item_id))

        conn = get_db_conn()
        timestamp = str(datetime.now())
        init_db_tables(conn)

        conn.execute("REPLACE INTO classification_item_ignore \
            (agent_id, item_id, timestamp) \
            VALUES (?, ?, ?)", \
            (agent_id, item_id, timestamp))

        conn.commit()

        message = f"Record added successfully item_id: {item_id}"
        logger.debug(message)

        return resp.generate_response_with_data(message, 201)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)
