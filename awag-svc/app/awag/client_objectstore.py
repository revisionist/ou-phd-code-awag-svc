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

from domestique.json import get_json_str_from_dict_or_str
from domestique.flask.response import check_response_status
from domestique.text import truncate_string, tidy_and_truncate_string


from .shared_resources import logger


class ObjectstoreClient:

    def __init__(self, rest_base_url, client_id, client_token):

        logger.debug(f"Initialising new ObjectstoreClient with client_id '{client_id}' and URL: {rest_base_url}")

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


    def get_ws_url_objectstore_namespace(self, namespace):

        return f"{self.rest_base_url}/{namespace}"


    def get_ws_url_objectstore_obj(self, namespace, object_id):

        return f"{self.get_ws_url_objectstore_namespace(namespace)}/{object_id}"


    def get_ws_url_objectstore_tags(self, namespace, object):

        return f"{self.rest_base_url}/tags/{namespace}/{object}"


    def get_ws_url_objectstore_mappings(self):

        return f"{self.rest_base_url}/mappings"


    def query_namespace(self, namespace_id, tag):

        logger.debug(f"Querying namespace '{namespace_id}' with tag: {tag}")

        if not namespace_id:
            raise Exception("Bad namespace passed to query_namespace")

        params = {}
        if (tag):
            params["tag"] = tag
        url = f"{self.get_ws_url_objectstore_namespace(namespace_id)}"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_namespace_id = response_json.get("namespace_id")
        response_object_ids = response_json.get("object_ids", [])
        logger.debug(f"Queried namespace '{namespace_id}' with tag '{tag}' and got objects: {response_object_ids}")

        return response_object_ids


    def clear_namespace(self, namespace_id):

        logger.debug(f"Clearing namespace: {namespace_id}")

        if not namespace_id:
            raise Exception("Bad namespace passed to clear_namespace")

        params = {
            "confirm": True
        }
        url = f"{self.get_ws_url_objectstore_namespace(namespace_id)}"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.delete(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_message = response_json.get("message")
        logger.debug(f"Cleared namespace '{namespace_id}' and got message: {response_message}")

        return response_message


    def store_object(self, namespace_id, object_id, tags, object_to_store):

        if object_id:
            logger.debug(f"Storing object in namespace '{namespace_id}' using object_id: {object_id}")
        else:
            logger.debug(f"Storing object in namespace '{namespace_id}' - no object_id")
        #logger.debug(f"Object is:\n{object_dict}")

        object_json = get_json_str_from_dict_or_str(object_to_store)

        params = {}
        if tags:
            params['tags'] = tags

        url = self.get_ws_url_objectstore_obj(namespace_id, object_id)

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=object_json, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_object_id = response_json.get("object_id")
        response_revision_id = response_json.get("revision_id")
        response_new_version = response_json.get("new_version")
        response_object_timestamp = response_json.get("object_timestamp")
        if response_new_version:
            log_prefix = "Stored NEW/UPDATED object"
        else:
            log_prefix = "Found EXISTING object"
        logger.debug(f"{log_prefix} '{namespace_id}/{response_object_id}' with revision_id '{response_revision_id}' and timestamp: {response_object_timestamp}")

        return response_object_id


    def delete_object(self, namespace_id, object_id):

        if not namespace_id:
            raise Exception("Bad namespace passed to delete_object")

        if not object_id:
            raise Exception("Bad object_id passed to delete_object")

        logger.debug(f"Deleting object from namespace '{namespace_id}': {object_id}")

        url = self.get_ws_url_objectstore_obj(namespace_id, object_id)
        params = {}

        logger.debug(f"Calling: {url}")
        try:
            response = requests.delete(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        deleted_object_id = None
        if response.status_code == 404:
            logger.warn(f"Attempted to delete object that does not exist: '{namespace_id}/{object_id}'")
        else:
            check_response_status(response, url)
            deleted_object_id = object_id

        logger.debug(f"Deleted object: {deleted_object_id}")

        return deleted_object_id


    def retrieve_object(self, namespace_id, object_id):

        response_object, _, _ = self.retrieve_object_with_details(namespace_id, object_id)

        return response_object


    def retrieve_object_with_details(self, namespace_id, object_id):

        logger.debug(f"Retrieving object '{object_id}' from namespace: {namespace_id}")

        if not namespace_id or not object_id:
            raise Exception("Bad namespace or object_id passed to retrieve_openai_file_obj")

        params = {}
        url = f"{self.get_ws_url_objectstore_obj(namespace_id, object_id)}"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        response_json = response.json()
        response_object_id = response_json.get("object_id")
        response_revision_id = response_json.get("revision_id")
        response_object_timestamp = response_json.get("object_timestamp")
        response_object = response_json.get("object")
        logger.debug(f"Retrieved object '{namespace_id}/{response_object_id}' with revision_id '{response_revision_id}' and timestamp: {response_object_timestamp}")
        #logger.debug(f"Object: \n{response_object}")

        return response_object, response_object_id, response_revision_id


    def object_exists(self, namespace_id, object_id):

        logger.debug(f"Checking that object '{object_id}' exists in namespace: {namespace_id}")

        if not namespace_id or not object_id:
            raise Exception("Bad namespace or object_id passed to retrieve_openai_file_obj")

        params = {}
        url = self.get_ws_url_objectstore_obj(namespace_id, object_id)

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)

        object_exists = False
        if response.status_code == 404:
            logger.debug(f"Query for '{namespace_id}/{object_id}' got a 404 status")
            object_exists = False
        elif 200 <= response.status_code <= 299:
            logger.debug(f"Query for '{namespace_id}/{object_id}' got status: {response.status_code}")
            object_exists = True
        else:
            # Use check_response_status to handle what is probably an error
            logger.debug(f"Query for '{namespace_id}/{object_id}' got OTHER status: {response.status_code}")
            check_response_status(response, url)

        return object_exists


    def get_object_tags(self, namespace_id, object_id):

        logger.debug(f"Getting tags for object '{object_id}' in namespace: {namespace_id}")

        if not namespace_id or not object_id:
            raise Exception("Bad namespace or object_id passed to get_object_tags")

        params = {}
        url = self.get_ws_url_objectstore_tags(namespace_id, object_id)

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)

        check_response_status(response, url)

        response_json = response.json()

        return response_json.get("tags")


    def set_object_tags(self, namespace_id, object_id, tags):

        logger.debug(f"Setting tags for object '{object_id}' in namespace: {namespace_id}")

        if not namespace_id or not object_id:
            raise Exception("Bad namespace or object_id passed to get_object_tags")

        if tags == None:
            tags = []

        params_remove = {}
        params_add = { "tags": tags }
        url_remove = self.get_ws_url_objectstore_tags(namespace_id, object_id)
        url_add = self.get_ws_url_objectstore_tags(namespace_id, object_id)

        logger.debug(f"Calling: {url_remove}")
        try:
            response = requests.put(url_remove, headers=self.web_service_headers, params=url_remove, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url_remove)

        check_response_status(response, url_remove)

        logger.debug(f"Calling: {url_add}")
        try:
            response = requests.get(url_add, headers=self.web_service_headers, params=params_add, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + params_add)

        check_response_status(response, params_add)

        return response.tags


    def tags_match(self, namespace_id1, object_id1, namespace_id2, object_id2):

        try:

            tags1 = self.get_object_tags(namespace_id1, object_id1)
            tags2 = self.get_object_tags(namespace_id2, object_id2)
            return set(tags1) == set(tags2)

        except Exception as e:

            logger.error(f"Error in tags_match: {str(e)}")
            raise e


    def get_mappings(self):

        logger.debug(f"Getting mapping data")

        params = {}
        url = self.get_ws_url_objectstore_mappings()

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Object store response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)

        check_response_status(response, url)

        response_json = response.json()

        return response_json.get("data")
