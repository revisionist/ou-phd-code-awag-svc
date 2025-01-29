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

import json
import requests

from domestique.validation import Validator, NoiseLevel
from domestique.json import get_json_str_from_dict_or_str, get_dict_from_dict_or_json_str
from domestique.flask.response import check_response_status
from domestique.text import truncate_string, tidy_and_truncate_string

from .shared_resources import logger


class AwagdataClient:

    def __init__(self, rest_base_url, client_id, client_token):

        logger.debug(f"Initialising new AwagdataClient with client_id '{client_id}' and URL: {rest_base_url}")

        if not rest_base_url:
            raise ValueError("rest_base_url required")
        if not client_id:
            raise ValueError("client_id required")
        if not client_token:
            raise ValueError("client_token required")

        self.rest_base_url = rest_base_url
        self.client_id = client_id
        self.client_token = client_token

        self.web_service_headers = {
            "Content-Type": "application/json",
            "x-client-id": client_id,
            "x-client-token": client_token,
        }


    def fetch_classification_actions(self, tag, page, count, item_id, classifications, last_n_hours, subset_tag, subset_percent):

        logger.debug(f"Doing /class/fetch-classification-actions with tag: {tag}")
        logger.debug(f"Passed page: {page}, count: {count}, item_id: {item_id}, classifications: {classifications}, last_n_hours: {last_n_hours}")

        if not tag:
            raise Exception("Method fetch_classification_actions requires a tag to be passed")

        params = {
            "tag": tag,
            "page": page,
            "count": count,
            }
        if item_id:
            params['itemId'] = item_id
        if classifications:
            params['classificationName'] = ",".join(classifications)
        if last_n_hours:
            params['lastNHours'] = last_n_hours
        if subset_tag:
            params['subsetTag'] = subset_tag
        if subset_percent:
            params['subsetPercent'] = subset_percent

        logger.debug(f'Built params: {params}')

        url = f"{self.rest_base_url}/class/fetch-classification-actions"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


    def fetch_training_items(self, tag, item_id=None, page=None, count=None, desc=None, classifications=None, last_n_hours=None, only_include_untrained=None):

        logger.debug(f"Doing /class/fetch-training-items with tag: {tag}")
        logger.debug(f"Passed page: {page}, count: {count}, desc: {desc}, item_id: {item_id}, classifications: {classifications}, last_n_hours: {last_n_hours}")

        if not tag:
            raise ValueError("Method fetch_training_items requires a tag to be passed")

        params = {
            "tag": tag
            }
        if page:
            params['page'] = page
        if count:
            params['count'] = count
        if item_id:
            params['itemId'] = item_id
        if desc:
            params['desc'] = desc
        if classifications:
            params['classificationName'] = ",".join(classifications)
        if last_n_hours:
            params['lastNHours'] = last_n_hours

        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/class/fetch-training-items"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


    def record_classification_action(self, record_request):

        logger.debug(f"Recording classification action:\n{record_request}")

        object_dict = get_dict_from_dict_or_json_str(record_request)

        params = {}

        url = f"{self.rest_base_url}/class/record-classification-action"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=object_dict, timeout=90)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Call to record_classification_action returning with message: {response_json.get('message')}")

        return response_json


    def gen_sim_text(self, category, topic, items, dramatis_personae=None, entities=None):

        logger.debug(f"Doing /sim/gen-sim-text with category '{category}', {items} items and topic: {tidy_and_truncate_string(topic, 50)}")
        logger.debug(f"Passed dramatis_personae:\n{dramatis_personae}")
        logger.debug(f"Passed entities:\n{entities}")

        if not category:
            raise ValueError("Method gen_sim_text requires a category to be passed")

        if not topic:
            raise ValueError("Method gen_sim_text requires a topic to be passed")

        if not items:
            raise ValueError("Method gen_sim_text requires an items parameter to be passed")

        params = {}

        request_json = {
            "category": category,
            "topic": topic,
            "items": items
        }
        if dramatis_personae:
            request_json["dramatis_personae"] = dramatis_personae
        if entities:
            request_json["entities"] = entities

        #logger.debug(f"Request JSON:\n{request_json}")
        
        url = f"{self.rest_base_url}/sim/gen-sim-text"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=request_json, timeout=180)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        usage = response_json.get('usage')
        logger.debug(f"Query complete with with {len(response_data)} items; usage: {usage}")

        return response_data, usage


    def add_sim_text(self, items):

        if not items:
            raise ValueError("Method add_sim_text requires items to be passed")

        if not isinstance(items, list):
            raise TypeError(f"items is not a valid array: {items}")

        logger.debug(f"Doing /sim/add-sim-text with {len(items)} items")

        params = {}

        url = f"{self.rest_base_url}/sim/add-sim-text"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=items, timeout=90)
            logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Update complete for {len(items)} items")

        return response_json


    def gen_and_add_sim_text(self, items):

        logger.debug(f"Doing /sim/gen-and-add-sim-text with category '{category}', {items} items and topic: {tidy_and_truncate_string(topic, 50)}")
        logger.debug(f"Passed dramatis_personae:\n{dramatis_personae}")
        logger.debug(f"Passed entities:\n{entities}")

        if not category:
            raise ValueError("Method gen_and_add_sim_text requires a category to be passed")

        if not topic:
            raise ValueError("Method gen_and_add_sim_text requires a topic to be passed")

        if not items:
            raise ValueError("Method gen_and_add_sim_text requires an items parameter to be passed")

        params = {}

        request_json = {
            "category": category,
            "topic": topic,
            "items": items
        }
        if dramatis_personae:
            request_json["dramatis_personae"] = dramatis_personae
        if entities:
            request_json["entities"] = entities

        #logger.debug(f"Request JSON:\n{request_json}")
        
        url = f"{self.rest_base_url}/sim/gen-and-add-sim-text"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=request_json, timeout=360)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        usage = response_json.get('usage')
        logger.debug(f"Generation complete with with {len(response_data)} items; usage: {usage}")

        return response_data, usage


    def get_sim_text(self, category, is_get_all=False):

        if not category:
            raise ValueError("Method get_sim_text requires category to be passed")

        logger.debug(f"Doing /sim/get-sim-text with category: {category}")

        params = {
            "category": category,
            "is_get_all": is_get_all
        }

        url = f"{self.rest_base_url}/sim/get-sim-text"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=20)
            logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        return response.json().get("data", None)


    def record_evaluation_items(self, evaluation_items):

        if not isinstance(evaluation_items, list):
            evaluation_items = [evaluation_items]

        #logger.debug(f"Recording evaluation_items:\n{evaluation_items}")
        logger.debug(f"Recording {len(evaluation_items)} evaluation_items...")
        req_dict = {
            "evaluationItems": evaluation_items
        }

        params = {}

        url = f"{self.rest_base_url}/eval/record-evaluation-items"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=req_dict, timeout=90)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Call to record_evaluation_items returning with message: {response_json.get('message')}")

        return response_json


    def record_evaluation_data(self, evaluation_data):

        #logger.debug(f"Recording evaluation_data:\n{evaluation_data}")

        params = {}

        url = f"{self.rest_base_url}/eval/record-evaluation-data"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=evaluation_data, timeout=90)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Call to record_evaluation_data returning with message: {response_json.get('message')}")

        return response_json


    def record_evaluation_failure(self, evaluation_failure_data):

        # Note that this method calls record-evaluation-failure-alt, as the data available
        # here in the Python application is not the same as the original Java

        logger.debug(f"Recording evaluation_failure_data:\n{evaluation_failure_data}")

        params = {}

        url = f"{self.rest_base_url}/eval/record-evaluation-failure-alt"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=evaluation_failure_data, timeout=90)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Call to record_evaluation_failure returning with message: {response_json.get('message')}")

        return response_json


    def record_evaluation_job(self, job_status):

        #logger.debug(f"Recording job_status:\n{job_status}")

        params = {}

        mode = job_status["mode"]

        url = f"{self.rest_base_url}/eval/record-evaluation-job/{mode}"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=job_status, timeout=90)
            #logger.debug(f"Awagdata response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        logger.debug(f"Call to record_evaluation_job returning with message: {response_json.get('message')}")

        return response_json


    def get_evaluation_data(self,
                    tag,
                    item_id=None,
                    page=None, count=None, desc=None,
                    persona_id=None,
                    context_id=None,
                    data_issue_flag=False,
                    classification_name=None,
                    evaluation_likert_val_min=None,
                    evaluation_likert_val_max=None,
                    is_detail=False,
                    last_n_hours=None,
                    exclude_items_with_feedback=None):

        logger.debug(f"Doing /eval/get-evaluation-data with tag: {tag}")
        logger.debug(f"Passed page: {page}, count: {count}, desc: {desc}, item_id: {item_id}, persona_id: {persona_id}, last_n_hours: {last_n_hours}")

        if not tag:
            raise ValueError("Method get_evaluation_data requires a tag to be passed")

        params = {
            "tag": tag
            }
        if page:
            params['page'] = page
        if count:
            params['count'] = count
        if item_id:
            params['itemId'] = item_id
        if desc:
            params['desc'] = desc
        if classifications:
            params['classificationName'] = ",".join(classifications)
        if last_n_hours:
            params['lastNHours'] = last_n_hours
        if persona_id:
            params['personaId'] = persona_id
        if is_detail:
            params['includeDetail'] = is_detail
        if context_id:
            params['contextId'] = context_id
        if data_issue_flag:
            params['dataIssueFlag'] = data_issue_flag
        if exclude_items_with_feedback:
            params['excludeItemsWithFeedback'] = exclude_items_with_feedback
        if evaluation_likert_val_min:
            params['evaluationLikertValMin'] = evaluation_likert_val_min
        if evaluation_likert_val_max:
            params['evaluationLikertValMax'] = evaluation_likert_val_max
        if classification_name:
            params['classificationName'] = classification_name

        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/eval/get-evaluation-data"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


    def get_base_data(self,
                    tag_main,
                    item_id=None,
                    page=None,
                    count=None,
                    desc=None,
                    last_n_hours=None,
                    classification_name=None,
                    is_only_with_manual=False):

        Validator().check(["tag_main"],
            tag_main=tag_main, item_id=item_id, last_n_hours=last_n_hours, classification_name=classification_name,
            is_only_with_manual=is_only_with_manual, page=page, count=count, desc=desc)

        logger.debug(f"Doing /reporting/get-base-data with tag_main: {tag_main}")
        logger.debug(f"Passed page: {page}, count: {count}, desc: {desc}, item_id: {item_id}, last_n_hours: {last_n_hours}")

        if not tag_main:
            raise ValueError("Method get_base_data requires a tag_main to be passed")

        params = {
            "tagMain": tag_main,
            "onlyIncludeWithManual": is_only_with_manual,
            "format": "json"
            }
        if page:
            params['page'] = page
        if count:
            params['count'] = count
        if desc:
            params['desc'] = desc
        if item_id:
            params['itemId'] = item_id
        if last_n_hours:
            params['lastNHours'] = last_n_hours
        if classification_name:
            params['classificationName'] = classification_name

        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/reporting/get-base-data"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response_json.get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


    def get_combined_evaluation_data(self,
                    tag_main,
                    tag_eval=None,
                    item_id=None,
                    page=None,
                    count=None,
                    desc=None,
                    evaluate_source_type=None,
                    persona_id=None,
                    context_id=None,
                    perspective_id=None,
                    last_n_hours=None,
                    classification_name=None,
                    is_only_with_manual=False,
                    is_only_with_eval=False,
                    is_only_with_feedback=False,
                    is_only_with_likert=False,
                    is_only_with_agreement=False
                    ):

        Validator().check(["tag_main"],
            tag_main=tag_main, tag_eval=tag_eval,
            item_id=item_id, evaluate_source_type=evaluate_source_type, persona_id=persona_id,
            perspective_id=perspective_id, context_id=context_id, last_n_hours=last_n_hours, classification_name=classification_name,
            is_only_with_manual=is_only_with_manual, is_only_with_eval=is_only_with_eval, is_only_with_feedback=is_only_with_feedback,
            is_only_with_likert=is_only_with_likert, is_only_with_agreement=is_only_with_agreement,
            page=page, count=count, desc=desc)

        logger.debug(f"Doing /reporting/get-combined-evaluation-data with tag_main: {tag_main}")
        logger.debug(f"Passed page: {page}, count: {count}, desc: {desc}, item_id: {item_id}, persona_id: {persona_id}, last_n_hours: {last_n_hours}")

        if not tag_main:
            raise ValueError("Method get_combined_evaluation_data requires a tag_main to be passed")

        params = {
            "tagMain": tag_main,
            "onlyIncludeWithManual": is_only_with_manual,
            "onlyIncludeWithEval": is_only_with_eval,
            "onlyIncludeWithFeedback": is_only_with_feedback,
            "onlyIncludeWithLikert": is_only_with_likert,
            "onlyIncludeWithAgreement": is_only_with_agreement,
            "format": "json"
            }
        if page:
            params['page'] = page
        if count:
            params['count'] = count
        if desc:
            params['desc'] = desc
        if tag_eval:
            params['tagEval'] = tag_eval
        if item_id:
            params['itemId'] = item_id
        if last_n_hours:
            params['lastNHours'] = last_n_hours
        if classification_name:
            params['classificationName'] = classification_name
        if persona_id:
            params['personaId'] = persona_id
        if context_id:
            params['contextId'] = context_id
        if perspective_id:
            params['perspectiveId'] = perspective_id
        if evaluate_source_type:
            params['evaluateSourceType'] = evaluate_source_type

        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/reporting/get-combined-evaluation-data"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response_json.get("data", [])
        response_remaining = response_json.get("remaining", -1)
        stats = response_json.get("stats", {})
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining, stats


    def fetch_classification_actions(self, tag, page, count, item_id, classifications, last_n_hours, subset_tag, subset_percent):

        logger.debug(f"Doing /class/fetch-classification-actions with tag: {tag}")
        logger.debug(f"Passed page: {page}, count: {count}, item_id: {item_id}, classifications: {classifications}, last_n_hours: {last_n_hours}")

        if not tag:
            raise Exception("Method fetch_classification_actions requires a tag to be passed")

        params = {
            "tag": tag,
            "page": page,
            "count": count,
            }
        if item_id:
            params["itemId"] = item_id
        if classifications:
            params["classificationName"] = ",".join(classifications)
        if last_n_hours:
            params["lastNHours"] = last_n_hours
        if subset_tag:
            params["subsetTag"] = subset_tag
        if subset_percent:
            params["subsetPercent"] = subset_percent

        logger.debug(f'Built params: {params}')

        url = f"{self.rest_base_url}/class/fetch-classification-actions"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


    def fetch_evaluation_items(self, tag, exclude_tag=None, last_n_hours=None, subset_tag=None, subset_percent=None, desc=None, by_uuid=None, page=None, count=None):

        logger.debug(f"Doing /eval/fetch-evaluation-items with tag: {tag}")
        logger.debug(f"Passed page: {page}, count: {count}, desc: {desc}")

        if not tag:
            raise ValueError("Method fetch_evaluation_items requires a tag to be passed")

        params = {
            "tag": tag
            }
        if exclude_tag:
            params["excludeExistingWithTag"] = exclude_tag
        if last_n_hours:
            params["lastNHours"] = last_n_hours
        if subset_tag:
            params["subsetTag"] = subset_tag
        if subset_percent:
            params["subsetPercent"] = subset_percent
        if desc:
            params["desc"] = desc
        if by_uuid:
            params["by_uuid"] = by_uuid
        if page:
            params["page"] = page
        if count:
            params["count"] = count

        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/eval/fetch-evaluation-items"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=90)
            #logger.debug(f"Data service response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_data = response.json().get("data", [])
        response_remaining = response_json.get("remaining", -1)
        logger.debug(f"Query complete with with {response_remaining} remaining: {len(response_data)} items")

        return response_data, response_remaining


