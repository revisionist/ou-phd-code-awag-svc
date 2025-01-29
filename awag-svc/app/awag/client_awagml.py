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
from domestique.text import tidy_and_truncate_string

from .shared_resources import logger


class AwagMLClient:

    def __init__(self, rest_base_url, client_id, client_token):

        logger.debug(f"Initialising new AwagMLClient with client_id '{client_id}' and URL: {rest_base_url}")

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


    def trim_response(self, resp_text):
        '''
        This method exists because responses from the awagml web service are just text that needs some tidying
        '''
        
        resp_text = resp_text.rstrip('\n')
        if resp_text.startswith('"'):
            resp_text = resp_text[1:-1]
        return resp_text


    def get_model_desc(self, model):

        logger.debug(f"Doing /getmodeldesc with model: {model}")

        if not model:
            raise ValueError("Method get_model_desc requires a model to be passed")

        params = {
            'agent': self.client_id,
            'model': model
            }
        logger.debug(f'Built params: {params}')
        
        url = f"{self.rest_base_url}/getmodeldesc"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.get(url, headers=self.web_service_headers, params=params, timeout=30)
            #logger.debug(f"Awagml response: \n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        model_desc = self.trim_response(response.text)
        logger.debug(f"Got desc for model '{model}': {model_desc}")

        return model_desc


    def perform_model_training(self, originator, model, text_to_train_with, text_classification):

        logger.debug(f"Recording model training for model '{model}' with new classification '{text_classification}' - text is: {tidy_and_truncate_string(text_to_train_with, 80)}")

        if not model:
            raise ValueError("Method perform_model_training requires a model to be passed")
        if not text_to_train_with:
            raise ValueError("Method perform_model_training requires a text_to_train_with to be passed")
        if not text_classification:
            raise ValueError("Method perform_model_training requires a text_classification to be passed")

        training_request = {
            'agent': self.client_id,
            'model': model,
            'originator': originator,
            'items': [ {
                'data': text_to_train_with,
                'target': text_classification
            }]
        }

        params = {}

        url = f"{self.rest_base_url}/addrows"

        logger.debug(f"Calling: {url}")
        try:
            response = requests.post(url, headers=self.web_service_headers, params=params, json=training_request, timeout=60)
            #logger.debug(f"Awagml response:\n{response.text}")
        except requests.exceptions.Timeout:
            raise Exception("Request timed out calling: " + url)
        check_response_status(response, url)

        resp_text = self.trim_response(response.text)

        logger.debug(f"Call to perform_model_training returning: {resp_text}")

        return resp_text
