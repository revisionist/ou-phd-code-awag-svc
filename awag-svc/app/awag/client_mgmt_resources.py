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

from flask import current_app, make_response

from .shared_resources import get_auth_token

from .client_objectstore import ObjectstoreClient
from .client_awagdata import AwagdataClient
from .client_awagml import AwagMLClient
from .client_openai import OpenAIClientWrapper


def get_objectstore_client(objectstore_clients, client_id):

    if client_id in objectstore_clients:
        return objectstore_clients.get(client_id)
    else:
        rest_base_url = current_app.config['REST_BASE_URL_OBJECTSTORE']
        client_token = get_auth_token(client_id)
        if not client_token:
            raise Exception(f"Unable to get client_token for client_id: {client_id}!")
        objectstore_client = ObjectstoreClient(rest_base_url, client_id, client_token)
        objectstore_clients[client_id] = objectstore_client
        return objectstore_client


def get_awagdata_client(awagdata_clients, client_id):

    if client_id in awagdata_clients:
        return awagdata_clients.get(client_id)
    else:
        rest_base_url = current_app.config['REST_BASE_URL_AWAGDATA']
        client_token = get_auth_token(client_id)
        if not client_token:
            raise Exception(f"Unable to get client_token for client_id: {client_id}!")
        awagdata_client = AwagdataClient(rest_base_url, client_id, client_token)
        awagdata_clients[client_id] = awagdata_client
        return awagdata_client


def get_awagml_client(awagml_clients, client_id):

    if client_id in awagml_clients:
        return awagml_clients.get(client_id)
    else:
        rest_base_url = current_app.config['REST_BASE_URL_AWAGML']
        client_token = get_auth_token(client_id)
        if not client_token:
            raise Exception(f"Unable to get client_token for client_id: {client_id}!")
        awagml_client = AwagMLClient(rest_base_url, client_id, client_token)
        awagml_clients[client_id] = awagml_client
        return awagml_client


def get_openai_client_wrapper(api_key=None):

    api_key = api_key or current_app.config['OPENAI_AUTH_TOKEN'] or os.environ.get("OPENAI_API_KEY")
    client = OpenAIClientWrapper(api_key)
    return client
