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
from flask import Blueprint, current_app, jsonify, request

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close
from domestique.db.sqlite import get_db_conn
from domestique.flask.response import ResponseWrapper

from authentication import require_api_auth

from .shared_resources import *
from .client_mgmt_resources import get_awagdata_client, get_awagml_client


fixit_routes = Blueprint('fixit_routes', __name__)

awagdata_clients = {}
awagml_clients = {}

model_descriptions_cache = {}


def init_db_tables(conn):

    pass


def find_classification_by_name(classifications, name):

    for classification in classifications:
        if classification["classificationName"] == name:
            return classification
    return None


def get_model_desc(awagml_client, model):

    agent_id = awagml_client.client_id
    cache_key = (agent_id, model)

    if cache_key not in model_descriptions_cache:
        model_desc = awagml_client.get_model_desc(model)
        if not model_desc:
            raise ValueError(f"Unable to get model_desc for: {model}")
        model_descriptions_cache[cache_key] = model_desc

    return model_descriptions_cache[cache_key]


@fixit_routes.route('/construct-eval-items', methods=['POST'])
@require_api_auth
def construct_eval_items():

    agent_id, resp, conn = init_route(request)

    try:
 
        reqjson = get_reqjson(request)

        #timestamp = str(datetime.now())

        tag_source = get_required_reqjson_val(reqjson, "tagSource")
        tags_add = get_reqjson_val(reqjson, "tagsAdd", [])
        combined_tags = list(set([tag_source] + tags_add))
        logger.debug(f"Tag (source): {tag_source}")
        logger.debug(f"Tags (add): {tag_source}")
        logger.debug(f"Tags (combined): {combined_tags}")

        max_items_count = get_reqjson_val(reqjson, "max_items", -1)

        awagdata_client = get_awagdata_client(awagdata_clients, agent_id)
        awagml_client = get_awagml_client(awagml_clients, agent_id)

        page = 1
        remaining = 1

        total_processed = 0
        processed_ids = []

        while remaining and (max_items_count < 1 or total_processed < max_items_count):
 
            fetched_items, remaining = awagdata_client.fetch_training_items(tag=tag_source, only_include_untrained=False, page=page, count=20)
            if not fetched_items:
                raise Exception("Response from fetch_training_items does not contain data:")

            evaluation_items = []

            for fetched_item in fetched_items:

                if max_items_count >= 1 and total_processed >= max_items_count:
                    break

                #logger.debug(f"Fetched item:\n{fetched_item}")
                item_id = fetched_item["itemId"]
                logger.debug(f"Fetched item: {item_id}")
 
                summary_info = fetched_item.get("summaryInfo")
                if not summary_info:
                    raise Exception(f"fetched_item does not contain summary_info:\n{fetched_item}")

                evaluation_item = build_evaluation_item(fetched_item, summary_info, awagml_client, None, combined_tags)
                evaluation_items.append(evaluation_item)
                total_processed += 1
                processed_ids.append(item_id)
                logger.debug(f"Appended evaluation_item:\n{evaluation_item}")

            awagdata_client.record_evaluation_items(evaluation_items)

            page += 1

        response_json = {
            "status": "OK",
            'message': f"Evaluation construction complete for tag '{tag_source}' - processed {total_processed} items",
            "processed_ids": processed_ids,
            "tags": combined_tags,
            "max_items_count": max_items_count
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)


def build_evaluation_item(fetched_item, summary_info, awagml_client, timestamp, tags):

    if timestamp:
        timestamp_use = timestamp
    else:
        timestamp_use = summary_info["date"]

    evaluation_item = {
        "contentItemSummary": summary_info,
        "evaluateSourceType": summary_info["typeDescription"],
        "evaluateSourceOriginator": summary_info["originator"],
        "evaluateSourceChannel": summary_info["channel"],
        "evaluateClassifications": [],
        "evaluateTitle": summary_info.get("subject", ""),
        "evaluateText": summary_info.get("body", ""),
        "tags": tags,
        "evaluateTime": timestamp_use
    }

    classifications = fetched_item.get("classifications", [])

    for classification in classifications:

        classification_name = classification["classificationName"]
        classification_desc = get_model_desc(awagml_client, classification_name)

        evaluation_classification_info = {
            "classificationName": classification_name,
            "classificationDesc": classification_desc,
            "classificationValue": classification.get("classificationOrig", None),
            "classificationOptions": classification.get("availableClassifications", None)
        }

        evaluation_item["evaluateClassifications"].append(evaluation_classification_info)

    return evaluation_item
