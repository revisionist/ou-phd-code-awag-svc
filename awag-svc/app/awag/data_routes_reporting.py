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
import csv
import ast

from flask import Blueprint, current_app, g, jsonify, request, make_response

from datetime import datetime, timedelta
from collections import defaultdict
from io import StringIO

from domestique.logging import log_exception
from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.convert import str_to_bool

from authentication import require_api_auth

from .shared_resources import logger, init_route

from .client_mgmt_resources import get_awagdata_client


reporting_routes = Blueprint('reporting_routes', __name__)

awagdata_clients = {}


stats_table_base = "reporting_base"
stats_table_eval = "reporting_evaluation_feedback"


def init_db_tables(conn):

    conn.execute(f'''CREATE TABLE IF NOT EXISTS {stats_table_base}
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     classification_name TEXT not null,
                     tag_main TEXT not null,
                     classified_text TEXT not null,
                     available_classifications JSON not null,
                     classification_orig TEXT not null,
                     classification_manual TEXT,
                     classification_manual_agrees INTEGER,
                     tags_main JSON not null,
                     tags_actions JSON,
                     record_timestamp TEXT,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, classification_name, tag_main))''')

    conn.execute(f'''CREATE TABLE IF NOT EXISTS {stats_table_eval}
                     (agent_id TEXT not null,
                     item_id TEXT not null,
                     context_id TEXT not null,
                     persona_id TEXT not null,
                     perspective_id TEXT not null,
                     classification_name TEXT not null,
                     tag_main TEXT not null,
                     tag_eval TEXT not null,
                     classified_text TEXT not null,
                     available_classifications JSON not null,
                     classification_orig TEXT not null,
                     classification_manual TEXT,
                     classification_manual_agrees INTEGER,
                     item_url TEXT,
                     item_type TEXT,
                     evaluation_likert_val INTEGER,
                     evaluation_likert_text TEXT,
                     evaluation_likert_simple TEXT,
                     evaluation_agreement TEXT,
                     evaluation_agreement_int INTEGER,
                     evaluation_text INTEGER,
                     evaluated_selection TEXT,
                     evaluated_selection_agrees_with_orig INTEGER,
                     feedback_evaluation_likert_val INTEGER,
                     feedback_evaluation_likert_text TEXT,
                     feedback_evaluation_likert_simple TEXT,
                     feedback_evaluation_difference_int INTEGER,
                     feedback_evaluation_difference_text TEXT,
                     tags_main JSON not null,
                     tags_actions JSON,
                     tags_eval JSON,
                     mode TEXT,
                     record_timestamp TEXT,
                     eval_timestamp TEXT,
                     timestamp TEXT not null,
                     PRIMARY KEY (agent_id, item_id, context_id, persona_id, perspective_id, classification_name, tag_main, tag_eval))''')

    conn.commit()


def log_exception(agent_id, e):

    message = f"An error occurred for agent_id '{agent_id}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


def output_to_csv(response_data, filename="output.csv"):

    if not response_data:
        return ""

    output_stream = StringIO()
    csv_writer = csv.writer(output_stream)
    csv_writer.writerow(response_data[0].keys())
    for row in response_data:
        csv_writer.writerow(row.values())

    csv_content = output_stream.getvalue()
    output_stream.close()

    response = make_response(csv_content)
    cd = f"attachment; filename={filename}"
    response.headers['Content-Disposition'] = cd 
    response.headers['Content-Type'] = 'text/csv'

    return response


def create_response_item(row_record, extend=False):

    response_item = {
        'agent_id': row_record['agent_id'],
        'item_id': row_record['item_id'],
        'classification_name': row_record['classification_name'],
        'classified_text': row_record['body_text'],
        'available_classifications': row_record['available_classifications'],
        'classification_orig': row_record['classification'],
        'classification_manual': row_record['classification_new'],
        'classification_manual_agrees': row_record['classification_new'] == row_record['classification'] if row_record['classification_new'] is not None else None,
        'tag_main': row_record['tag_main'],
        'tags_main': row_record['tags_main'],
        'tags_actions': row_record['tags_actions']
    }

    if extend:
        for field in ['context_id', 'item_url', 'item_type', 'persona_id', 'perspective_id', 'evaluation_likert_val', 'evaluation_likert_text',
        'evaluation_likert_simple', 'evaluation_agreement', 'evaluation_agreement_int', 'evaluation_text', 'evaluated_selection', 'evaluated_selection_agrees_with_orig',
        'feedback_evaluation_likert_val', 'feedback_evaluation_likert_text', 'feedback_evaluation_likert_simple', 'feedback_evaluation_difference_int',
        'feedback_evaluation_difference_text', 'tag_eval', 'tags_eval', 'eval_timestamp']:
            response_item[field] = None

    response_item['tag_main'] = row_record["tag_main"]
    response_item['tags_main'] = row_record["tags_main"]
    response_item['tags_actions'] = row_record["tags_actions"]

    if extend:
        for field in ['tag_eval', 'tags_eval', 'eval_timestamp']:
            response_item[field] = None

    response_item['record_timestamp'] = row_record["record_timestamp"]

    return response_item


def get_query_base():

    return """SELECT r.agent_id,
            r.item_id,
            rt.tag AS tag_main,
            r.classification_name,
            r.body_text,
            r.classification,
            r.available_classifications,
            a.classification_new,
            r.tags AS tags_main,
            a.tags AS tags_actions,
            r.timestamp AS record_timestamp
        FROM classification_record r
        INNER JOIN classification_record_tags rt
            ON r.agent_id = rt.agent_id
            AND r.item_id = rt.item_id
            AND r.classification_name = rt.classification_name
        LEFT OUTER JOIN classification_actions a
            ON r.agent_id = a.agent_id
            AND r.item_id = a.item_id
            AND r.classification_name = a.classification_name
    """


def prepare_query_and_params(agent_id, request, query_base, additional_conditions=None):

    tag_main = get_required_arg(request, "tagMain")

    item_id = get_arg(request, "itemId", None)
    last_n_hours = get_arg(request, "lastNHours", None)
    classification_name = get_arg(request, "classificationName", None)
    response_format = get_arg(request, "format", "json")

    is_only_with_manual = request.args.get('onlyIncludeWithManual', type=str_to_bool, default=False)
    logger.debug(f"Using is_only_with_manual: {is_only_with_manual}")

    # Pagination parameters
    page = request.args.get('page', type=int, default=1)
    count = request.args.get('count', type=int, default=10)
    desc = request.args.get('desc', False)

    logger.debug('Page: ' + str(page))
    logger.debug('Count: ' + str(count))

    if page < 1:
        raise ValueError(f"Invalid page number: {page}")

    if count < 1:
        raise ValueError(f"Invalid count number: {count}")

    query = query_base
    query += " WHERE r.agent_id = ?"
    query += " AND rt.tag = ?"
    query_params = [agent_id, tag_main]

    if item_id is not None:
        query += " AND r.item_id = ?"
        query_params.append(item_id)

    if classification_name is not None:
        query += " AND r.classification_name = ?"
        query_params.append(classification_name)

    if is_only_with_manual:
        query += " AND a.classification_new is not null"

    if last_n_hours:
        current_time_ms = int(time.time() * 1000)
        n_hours_ago_ms = current_time_ms - (int(last_n_hours) * 3600 * 1000)
        query += " AND r.timestamp >= ?"
        query_params.append(n_hours_ago_ms)

    if additional_conditions:
        for condition, params in additional_conditions:
            query += condition
            query_params.extend(params)

    total_count_query = f"SELECT COUNT(*) FROM ({query})"
    total_count_query_params = query_params.copy()

    offset = (page - 1) * count

    if desc:
        query += " ORDER BY r.timestamp, r.item_id DESC"
    else:
        query += " ORDER BY r.timestamp, r.item_id ASC"

    query += " LIMIT ? OFFSET ?"
    query_params.extend([count, offset])

    #logger.debug('Query (main): ' + query)
    #logger.debug('Query params (main): ' + str(query_params))
    #logger.debug('Query (total_count): ' + total_count_query)
    #logger.debug('Query params (total_count): ' + str(total_count_query_params))

    return tag_main, page, count, response_format, query, query_params, total_count_query, total_count_query_params


def append_base_data_record(response_data, row_record):

    logger.debug(f"append_base_data_record {row_record['agent_id']} - {row_record['item_id']} - {row_record['classification_name']}")
    
    response_item = create_response_item(row_record, extend=False)

    #logger.debug(f"Appending: {response_item}")

    response_data.append(response_item)


@reporting_routes.route('/get-base-data', methods=['GET'])
@require_api_auth
def get_base_data():

    agent_id, resp, conn = init_route(request)

    try:

        query_base = get_query_base()

        tag_main, page, count, response_format, query, query_params, total_count_query, total_count_query_params = prepare_query_and_params(agent_id, request, query_base, additional_conditions=None)

        conn = get_db_conn()

        c = conn.cursor()
        c.execute(query, query_params)

        rows_record = c.fetchall()

        if len(rows_record) == 0:
            logger.debug('Query (main) returned no records!')

        response_data = []

        for row_record in rows_record:

            row_item_id = row_record["item_id"]
            row_classification_name = row_record["classification_name"]

            logger.debug(f"Processing row: {row_item_id} - {row_record['classification_name']} - {row_record['tag_main']} - {row_record['classification']} - {row_record['classification_new']}")

            append_base_data_record(response_data, row_record)

        c.execute(total_count_query, total_count_query_params)
        total_items = c.fetchone()[0]
        remaining = max(total_items - page * count, 0)
        #logger.debug(f"total_items: {total_items}; page: {page}; count: {count}; remaining: {remaining};")

        if response_format.lower() == 'csv':

            return output_to_csv(response_data, "base-data.csv")

        else:

            response_json = {
                'status': 'OK',
                'message': 'OK',
                'data': response_data,
                'page': page,
                'count': count,
                'remaining': remaining
            }

            return resp.generate_response_with_data(response_json, 200)

    except Exception as err:

        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)
        time.sleep(1/100)


def append_combined_evaluation_data_record(response_data, row_record, row_eval):

    logger.debug(f"append_combined_evaluation_data_record {row_record['agent_id']} - {row_record['item_id']} - {row_record['classification_name']} - {row_eval}")
    
    response_item = create_response_item(row_record, extend=True)

    def get_likert_text_simple(likert_val):
        if likert_val is None:
            return None
        elif likert_val in [1, 2]:
            return 'DISAGREE'
        elif likert_val == 3:
            return 'NEUTRAL'
        elif likert_val in [4, 5]:
            return 'AGREE'
        else:
            return None

    def get_likert_text_full(likert_val):
        if likert_val == 1:
            return 'STRONGLY_DISAGREE'
        elif likert_val == 2:
            return 'DISAGREE'
        elif likert_val == 3:
            return 'NEUTRAL'
        elif likert_val == 4:
            return 'AGREE'
        elif likert_val == 5:
            return 'STRONGLY_AGREE'
        else:
            return None

    def compare_likert_values_int(val1, val2):
    
        if val1 is None or val2 is None:
            return None

        return val2 - val1

    def compare_likert_values_text(val1, val2):
    
        if val1 is None or val2 is None:
            return None

        difference_abs = abs(val2 - val1)
    
        if difference_abs == 0:
            return 'SAME'
        elif difference_abs in [1]:
            return 'SIMILAR'
        elif difference_abs in [2,3]:
            return 'DIFFERENT'
        elif difference_abs > 3:
            return 'VERY_DIFFERENT'
        else:
            return None

    if row_eval is not None:

        logger.debug(f"row_eval {row_eval['item_id']} - {row_eval['context_id']}")

        #row_dict = dict(row_eval)
        #for column_name, value in row_dict.items():
        #    logger.debug(f"{column_name}: {value}")

        evaluated_selection = row_eval["evaluated_selection"]
        evaluated_selection_agrees_with_orig = None
        # This calculation also appears in data_routes_eval
        if evaluated_selection is not None:
            if evaluated_selection == response_item["classification_orig"]:
                evaluated_selection_agrees_with_orig = True
            else:
                evaluated_selection_agrees_with_orig = False

        response_item['context_id'] = row_eval['context_id']
        response_item['item_url'] = row_eval['item_url']
        response_item['item_type'] = row_eval['item_type']
        response_item['persona_id'] = row_eval['persona_id']
        response_item['perspective_id'] = row_eval['perspective_id']

        evaluation_likert_val = row_eval["evaluation_likert_val"]

        feedback_evaluation_likert_val = None
        if evaluation_likert_val is not None:
            feedback_evaluation_likert_val = row_eval['new_evaluation_likert_val']
            response_item['evaluation_likert_val'] = evaluation_likert_val
            response_item['evaluation_likert_text'] = get_likert_text_full(evaluation_likert_val)
            response_item['evaluation_likert_simple'] = get_likert_text_simple(evaluation_likert_val)

        response_item['evaluation_text'] = row_eval['evaluation_text']
        response_item['evaluated_selection'] = evaluated_selection
        response_item['evaluated_selection_agrees_with_orig'] = evaluated_selection_agrees_with_orig

        if feedback_evaluation_likert_val:
            response_item['feedback_evaluation_likert_val'] = feedback_evaluation_likert_val
            response_item['feedback_evaluation_likert_text'] = get_likert_text_full(feedback_evaluation_likert_val)
            response_item['feedback_evaluation_likert_simple'] = get_likert_text_simple(feedback_evaluation_likert_val)
            response_item['feedback_evaluation_difference_int'] = compare_likert_values_int(evaluation_likert_val, feedback_evaluation_likert_val)
            response_item['feedback_evaluation_difference_text'] = compare_likert_values_text(evaluation_likert_val, feedback_evaluation_likert_val)

        #logger.debug(f"row_eval['evaluation_agreement'] {row_eval['evaluation_agreement']}")

        evaluation_agreement = row_eval['evaluation_agreement']
        if evaluation_agreement:
            response_item['evaluation_agreement'] = evaluation_agreement
            if evaluation_agreement.lower() in ['agree', 'yes', 'y', '1']:
                response_item['evaluation_agreement_int'] = 1
            else:
                response_item['evaluation_agreement_int'] = 0

        response_item['tag_eval'] = row_eval['eval_tag']
        response_item['tags_eval'] = row_eval['eval_tags']
        response_item['eval_timestamp'] = row_eval['eval_timestamp']

    #logger.debug(f"Appending: {response_item}")

    response_data.append(response_item)


@reporting_routes.route('/get-combined-evaluation-data', methods=['GET'])
@require_api_auth
def get_combined_evaluation_data():

    agent_id, resp, conn = init_route(request)

    try:

        tag_eval = get_required_arg(request, "tagEval")

        query_base = get_query_base()

        is_only_with_eval = request.args.get('onlyIncludeWithEval', type=str_to_bool, default=False)
        is_only_with_feedback = request.args.get('onlyIncludeWithFeedback', type=str_to_bool, default=False)

        is_only_with_likert = request.args.get('onlyIncludeWithLikert', type=str_to_bool, default=False)
        is_only_with_agreement = request.args.get('onlyIncludeWithAgreement', type=str_to_bool, default=False)

        logger.debug(f"Using is_only_with_eval: {is_only_with_eval}")
        logger.debug(f"Using is_only_with_feedback: {is_only_with_feedback}")
        logger.debug(f"Using is_only_with_likert: {is_only_with_likert}")
        logger.debug(f"Using is_only_with_agreement: {is_only_with_agreement}")

        additional_conditions = []

        if is_only_with_eval:
            additional_conditions.append((" AND r.item_id IN (SELECT DISTINCT item_id FROM evaluation_tags WHERE agent_id = ? AND tag = ?)", [agent_id, tag_eval]))

        if is_only_with_feedback:
            additional_conditions.append((" AND r.item_id IN (SELECT DISTINCT item_id FROM evaluation_feedback_tags WHERE agent_id = ? AND tag = ?)", [agent_id, tag_eval]))

        tag_main, page, count, response_format, query, query_params, total_count_query, total_count_query_params = prepare_query_and_params(agent_id, request, query_base, additional_conditions=additional_conditions)

        evaluate_source_type = get_arg(request, "evaluateSourceType", None)
        persona_id = get_arg(request, "personaId", None)
        context_id = get_arg(request, "contextId", None)
        perspective_id = get_arg(request, "perspectiveId", None)

        conn = get_db_conn()

        c = conn.cursor()
        c.execute(query, query_params)

        rows_record = c.fetchall()

        if len(rows_record) == 0:
            logger.debug('Query (main) returned no records!')

        response_data = []

        items_with_eval = 0
        items_without_eval = 0

        for row_record in rows_record:

            row_item_id = row_record["item_id"]
            row_classification_name = row_record["classification_name"]

            logger.debug(f"Processing row: {row_item_id} - {row_record['classification_name']} - {row_record['tag_main']} - {row_record['classification']} - {row_record['classification_new']}")

            query_eval = """
                SELECT
                    evalm.item_id, 
                    evalm.context_id,
                    info.item_url,
                    info.item_type,
                    evalres.classification_name,
                    evalm.tags AS eval_tags,
                    evalm.persona_id,
                    evalres.perspective_id,
                    evalres.evaluation_likert_val,
                    evalres.evaluation_agreement,
                    evalres.evaluation_text,
                    evalres.evaluated_selection,
                    evalres.mode,
                    evalfi.old_evaluation_likert_val,
                    evalfi.new_evaluation_likert_val,
                    tags.tag as eval_tag,
                    evalm.timestamp as eval_timestamp
                FROM evaluation_main AS evalm
                INNER JOIN evaluation_tags AS tags 
                    ON evalm.agent_id = tags.agent_id 
                    AND evalm.persona_id = tags.persona_id 
                    AND evalm.persona_version = tags.persona_version
                    AND evalm.context_id = tags.context_id
                    AND evalm.item_id = tags.item_id
                INNER JOIN evaluation_item_info AS info 
                    ON evalm.agent_id = info.agent_id 
                    AND evalm.item_id = info.item_id 
                    AND evalm.persona_id = info.persona_id 
                    AND evalm.persona_version = info.persona_version
                    AND evalm.context_id = info.context_id
                INNER JOIN evaluation_results AS evalres
                    ON evalm.agent_id = evalres.agent_id 
                    AND evalm.item_id = evalres.item_id 
                    AND evalm.persona_id = evalres.persona_id 
                    AND evalm.persona_version = evalres.persona_version
                    AND evalm.context_id = evalres.context_id
                LEFT OUTER JOIN evaluation_feedback_items AS evalfi
                    ON evalres.agent_id = evalfi.agent_id 
                    AND evalres.item_id = evalfi.item_id 
                    AND evalres.persona_id = evalfi.persona_id 
                    AND evalres.context_id = evalfi.context_id
                    AND evalres.classification_name = evalfi.classification_name
                    AND evalres.perspective_id = evalfi.perspective_id
            """
            query_eval += " WHERE evalm.agent_id = ?"
            query_eval_params = [agent_id]

            query_eval += " AND evalm.item_id = ?"
            query_eval_params.append(row_item_id)

            query_eval += " AND evalres.classification_name = ?"
            query_eval_params.append(row_classification_name)

            if is_only_with_likert:
                query_eval += " AND evalres.evaluation_likert_val is not null"

            if is_only_with_agreement:
                query_eval += " AND evalres.evaluation_agreement is not null"

            if persona_id is not None:
                query_eval += " AND evalm.persona_id = ?"
                query_eval_params.append(persona_id)

            if context_id is not None:
                query_eval += " AND evalm.context_id = ?"
                query_eval_params.append(context_id)

            if perspective_id is not None:
                query_eval += " AND evalres.perspective_id = ?"
                query_eval_params.append(perspective_id)

            if tag_eval is not None:
                query_eval += " AND tags.tag = ? "
                query_eval_params.append(tag_eval)

            query_eval += " ORDER BY evalres.classification_name, evalm.persona_id, evalres.perspective_id, eval_tag ASC"

            #logger.debug(f"Query (eval): {query_eval}")
            logger.debug(f"Query params (eval): {query_eval_params}")

            c.execute(query_eval, query_eval_params)

            rows_eval = c.fetchall()

            if len(rows_eval) == 0:
                items_without_eval += 1
                logger.debug("Got empty rows_eval!")
                # Write row with nulls for eval
                append_combined_evaluation_data_record(response_data, row_record, None)
            else:
                logger.debug(f"Got eval data for item_id: {row_item_id}")
                items_with_eval += 1
                for row_eval in rows_eval:
                    # Write row with eval data
                    append_combined_evaluation_data_record(response_data, row_record, row_eval)

        c.execute(total_count_query, total_count_query_params)
        total_items = c.fetchone()[0]
        remaining = max(total_items - page * count, 0)
        #logger.debug(f"total_items: {total_items}; page: {page}; count: {count}; remaining: {remaining};")

        if response_format.lower() == 'csv':

            return output_to_csv(response_data, "combined-evaluation-data.csv")

        else:

            response_json = {
                "status": "OK",
                "message": "OK",
                "data": response_data,
                "stats": {
                    "items_with_eval": items_with_eval,
                    "items_without_eval": items_without_eval
                },
                "page": page,
                "count": count,
                "remaining": remaining
            }

            return resp.generate_response_with_data(response_json, 200)

    except Exception as err:

        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)
        time.sleep(1/100)


@reporting_routes.route('/update-base-data', methods=['POST'])
@require_api_auth
def update_base_data():

    agent_id, resp, conn = init_route(request)

    try:

        tag_main = get_required_arg(request, "tagMain")

        item_id = get_arg(request, "itemId", None)
        last_n_hours = get_arg(request, "lastNHours", None)
        classification_name = get_arg(request, "classificationName", None)

        is_only_with_manual = request.args.get('onlyIncludeWithManual', type=str_to_bool, default=False)

        items_per_pass = int(get_arg(request, "itemsPerPass", 50))
        is_clear_first = request.args.get('clearFirst', type=bool, default=False)

        logger.debug(f"Using is_clear_first: {is_clear_first}")

        page = 0
        count = items_per_pass
        desc = False

        if items_per_pass < -1:
            raise ValueError(f"Invalid items_per_pass number: {items_per_pass}")

        if items_per_pass < 0:
            count = 0

        conn = get_db_conn()
        init_db_tables(conn)

        timestamp = str(datetime.now())

        operation_summary = {
            "records_deleted": 0,
            "records_inserted_or_updated": 0
        }

        if is_clear_first:

            sql_prefix = "INSERT INTO"

            base_delete_query = f"DELETE FROM {stats_table_base} WHERE agent_id = ?"
            query_params_delete = [agent_id]
            conditions = []

            for param, value in [('item_id', item_id), ('classification_name', classification_name)]:
                if value is not None:
                    conditions.append(f"{param} = ?")
                    query_params_delete.append(value)

            conditions.append("tag_main = ?")
            query_params_delete.append(tag_main)

            delete_query = f"{base_delete_query} AND {' AND '.join(conditions)}"

            logger.debug(f"Delete query: {delete_query}")
            logger.debug(f"Delete params: {query_params_delete}")

            cursor = conn.execute(delete_query, query_params_delete)
            operation_summary["records_deleted"] = cursor.rowcount

            conn.commit()

        else:
            
            sql_prefix = "INSERT OR REPLACE INTO"

        awagdata_client = get_awagdata_client(awagdata_clients, agent_id)

        insert_query = f'''
             {sql_prefix} {stats_table_base} (
                agent_id, 
                item_id, 
                classification_name, 
                tag_main, 
                classified_text, 
                available_classifications, 
                classification_orig, 
                classification_manual,
                classification_manual_agrees,
                tags_main,
                tags_actions,
                record_timestamp,
                timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''

        page = 0
        remaining = 1
        
        fetched = 0
        written = 0

        while remaining > 0:

            page += 1

            fetched_items, remaining = awagdata_client.get_base_data(
                tag_main=tag_main,
                item_id=item_id,
                last_n_hours=last_n_hours,
                classification_name=classification_name,
                is_only_with_manual=is_only_with_manual,
                page=page,
                count=count,
                desc=desc
            )

            fetched += len(fetched_items)
            logger.debug(f"Fetched {len(fetched_items)} items (running total: {fetched}) - {remaining} remaining")

            for item in fetched_items:

                values = (
                    item['agent_id'],
                    item['item_id'],
                    item['classification_name'],
                    item['tag_main'],
                    item['classified_text'],
                    item['available_classifications'],
                    item['classification_orig'],
                    item['classification_manual'],
                    item['classification_manual_agrees'],
                    item['tags_main'],
                    item['tags_actions'],
                    item['record_timestamp'],
                    timestamp
                    )

                written += 1

                cursor = conn.execute(insert_query, values)
                operation_summary["records_inserted_or_updated"] += cursor.rowcount

            conn.commit()

        logger.debug(f"Fetched TOTAL of {fetched} items; written: {written}")

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'operation_summary': operation_summary
        }

        return resp.generate_response_with_data(response_json, 201)

    except Exception as err:

        conn_rollback(conn)
        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)


@reporting_routes.route('/update-combined-evaluation-data', methods=['POST'])
@require_api_auth
def update_combined_evaluation_data():

    agent_id, resp, conn = init_route(request)

    try:

        tag_main = get_required_arg(request, "tagMain")

        tags_eval_raw = get_arg(request, "tagsEval", None)
        tag_eval_raw = get_arg(request, "tagEval", None)
        if tags_eval_raw:
            tags_lit = ast.literal_eval(tags_eval_raw)
            if isinstance(tags_lit, list):
                tags_eval = tags_lit
            else:
                tags_eval = [tags_eval_raw]
        else:
            tags_eval = [tag_eval_raw] if tag_eval_raw else None
        if not tags_eval:
            raise ValueError(f"Must pass one or more evaluation tags in tagEval or tagsEval")

        item_id = get_arg(request, "itemId", None)
        evaluate_source_type = get_arg(request, "evaluateSourceType", None)
        persona_id = get_arg(request, "personaId", None)
        context_id = get_arg(request, "contextId", None)
        perspective_id = get_arg(request, "perspectiveId", None)
        last_n_hours = get_arg(request, "lastNHours", None)
        classification_name = get_arg(request, "classificationName", None)

        is_only_with_manual = request.args.get("onlyIncludeWithManual", type=str_to_bool, default=False)
        is_only_with_eval = request.args.get("onlyIncludeWithEval", type=str_to_bool, default=False)
        is_only_with_feedback = request.args.get("onlyIncludeWithFeedback", type=str_to_bool, default=False)

        is_only_with_likert = request.args.get("onlyIncludeWithLikert", type=str_to_bool, default=False)
        is_only_with_agreement = request.args.get("onlyIncludeWithAgreement", type=str_to_bool, default=False)

        items_per_pass = int(get_arg(request, "itemsPerPass", 50))

        is_clear_first = request.args.get("clearFirst", type=bool, default=False)

        logger.debug(f"Using is_clear_first: {is_clear_first}")

        page = 0
        count = items_per_pass
        desc = False

        if items_per_pass < -1:
            raise ValueError(f"Invalid items_per_pass number: {items_per_pass}")

        if items_per_pass < 0:
            count = 0

        conn = get_db_conn()
        init_db_tables(conn)

        timestamp = str(datetime.now())

        overall_operation_summary = []

        awagdata_client = get_awagdata_client(awagdata_clients, agent_id)

        for tag_eval in tags_eval:

            logger.debug(f"Updating for tag: {tag_eval}")

            operation_summary = {
                "tag_eval": tag_eval,
                "records_deleted": 0,
                "records_inserted_or_updated": 0,
                "items_with_eval": 0,
                "items_without_eval": 0
            }

            if is_clear_first:

                sql_prefix = "INSERT INTO"

                base_delete_query = f"DELETE FROM {stats_table_eval} WHERE agent_id = ?"
                query_params_delete = [agent_id]
                conditions = []

                for param, value in [("item_id", item_id), ("context_id", context_id), ("persona_id", persona_id), 
                                    ("perspective_id", perspective_id), ("classification_name", classification_name)]:
                    if value is not None:
                        conditions.append(f"{param} = ?")
                        query_params_delete.append(value)

                conditions.append("tag_main = ?")
                conditions.append("tag_eval = ?")
                query_params_delete.extend([tag_main, tag_eval])

                delete_query = f"{base_delete_query} AND {' AND '.join(conditions)}"

                logger.debug(f"Delete query: {delete_query}")
                logger.debug(f"Delete params: {query_params_delete}")

                cursor = conn.execute(delete_query, query_params_delete)
                operation_summary["records_deleted"] = cursor.rowcount

                logger.debug(f"Committing (delete)....")
                conn.commit()
                logger.debug(f"Committing (delete) done")

            else:

                sql_prefix = "INSERT OR REPLACE INTO"

            insert_query = f'''
                {sql_prefix} {stats_table_eval} (
                    agent_id, 
                    item_id, 
                    context_id, 
                    persona_id, 
                    perspective_id, 
                    classification_name, 
                    tag_main, 
                    tag_eval, 
                    classified_text, 
                    available_classifications, 
                    classification_orig, 
                    classification_manual,
                    classification_manual_agrees,
                    item_url,
                    item_type,
                    evaluation_likert_val,
                    evaluation_likert_text,
                    evaluation_likert_simple,
                    evaluation_agreement,
                    evaluation_agreement_int,
                    evaluation_text,
                    evaluated_selection,
                    evaluated_selection_agrees_with_orig,
                    feedback_evaluation_likert_val,
                    feedback_evaluation_likert_text,
                    feedback_evaluation_likert_simple,
                    feedback_evaluation_difference_int,
                    feedback_evaluation_difference_text,
                    tags_main,
                    tags_actions,
                    tags_eval,
                    mode,
                    record_timestamp,
                    eval_timestamp,
                    timestamp
                    )
                    VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                    )
                    '''

            page = 0
            remaining = 1

            fetched = 0
            written = 0

            while remaining > 0:

                page += 1

                fetched_items, remaining, stats = awagdata_client.get_combined_evaluation_data(
                    tag_main=tag_main,
                    tag_eval=tag_eval,
                    item_id=item_id,
                    evaluate_source_type=evaluate_source_type,
                    persona_id=persona_id,
                    context_id=context_id,
                    perspective_id=perspective_id,
                    last_n_hours=last_n_hours,
                    classification_name=classification_name,
                    is_only_with_eval=is_only_with_eval,
                    is_only_with_feedback=is_only_with_feedback,
                    is_only_with_likert=is_only_with_likert,
                    is_only_with_agreement=is_only_with_agreement,
                    page=page,
                    count=count,
                    desc=False
                )

                fetched += len(fetched_items)
                logger.debug(f"Fetched {len(fetched_items)} items (running total: {fetched}) - {remaining} remaining")

                operation_summary["items_with_eval"] += stats.get("items_with_eval", 0)
                operation_summary["items_without_eval"] += stats.get("items_without_eval", 0)

                for item in fetched_items:

                    # These items form part of the table PK, but they can be null if there are no evaluations
                    # Therefore replace with text
                    this_context_id = item["context_id"] if item["context_id"] is not None else "NONE"
                    this_persona_id = item["persona_id"] if item["persona_id"] is not None else "NONE"
                    this_perspective_id = item["perspective_id"] if item["perspective_id"] is not None else "NONE"

                    values = (
                        item["agent_id"],
                        item["item_id"],
                        this_context_id,
                        this_persona_id,
                        this_perspective_id,
                        item["classification_name"],
                        item["tag_main"],
                        tag_eval,
                        item["classified_text"],
                        item["available_classifications"],
                        item["classification_orig"],
                        item["classification_manual"],
                        item["classification_manual_agrees"],
                        item["item_url"],
                        item["item_type"],
                        item.get("evaluation_likert_val", None),
                        item.get("evaluation_likert_text", None),
                        item.get("evaluation_likert_simple", None),
                        item.get("evaluation_agreement", None),
                        item.get("evaluation_agreement_int", None),
                        item["evaluation_text"],
                        item["evaluated_selection"],
                        item["evaluated_selection_agrees_with_orig"],
                        item.get("feedback_evaluation_likert_val", None),
                        item.get("feedback_evaluation_likert_text", None),
                        item.get("feedback_evaluation_likert_simple", None),
                        item.get("feedback_evaluation_difference_int", None),
                        item.get("feedback_evaluation_difference_text", None),
                        item["tags_main"],
                        item["tags_actions"],
                        item["tags_eval"],
                        item.get("mode", "modeX"),
                        item["record_timestamp"],
                        item["eval_timestamp"],
                        timestamp
                    )

                    written += 1

                    cursor = conn.execute(insert_query, values)
                    operation_summary["records_inserted_or_updated"] += cursor.rowcount

                conn.commit()

            logger.debug(f"Fetched TOTAL of {fetched} items for '{tag_eval}'; written: {written}")
            overall_operation_summary.append(operation_summary)

        response_json = {
            "status": "OK",
            "message": "OK",
            "operation_summary": overall_operation_summary
        }

        return resp.generate_response_with_data(response_json, 201)

    except Exception as err:

        conn_rollback(conn)
        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)
