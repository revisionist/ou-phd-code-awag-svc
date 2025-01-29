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

from functools import wraps

from flask import g, request, abort, current_app
from werkzeug.local import LocalProxy

logger = LocalProxy(lambda: current_app.logger)


def require_appkey(view_function):
    @wraps(view_function)
    # the new, post-decoration function. Note *args and **kwargs here.
    def decorated_function(*args, **kwargs):
        if request.headers.get('x-api-key') and request.headers.get(
                'x-api-key') == current_app.config['API_KEY']:
            return view_function(*args, **kwargs)
        else:
            abort(401)
    return decorated_function


def require_agent_in_json(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        reqjson = request.json
        if 'agent' not in reqjson:
            abort(400)
        elif not reqjson['agent']:
            abort(400)
        else:
            return view_function(*args, **kwargs)
    return decorated_function


def require_agent_as_param(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        if not request.args.get('agent'):
            abort(400)
        else:
            return view_function(*args, **kwargs)
    return decorated_function


def get_is_auth(client_id, client_token):

    api_auth = current_app.config['API_AUTH']
    #logger.debug(f"Auth data: {api_auth}")
    #logger.debug(f"Client ID: {client_id}")
    auth_val = api_auth.get(client_id)
    logger.debug(f"Auth val: {auth_val}")
    return auth_val == client_token


def require_api_auth(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):

        client_id = request.args.get('client_id') or request.headers.get('x-client-id')
        client_token = request.args.get('client_token') or request.headers.get('x-client-token')

        if client_id and client_token and get_is_auth(client_id, client_token):
            #logger.debug(f"Authenticated client for URL {request.url} : {client_id}")
            g.client_id = client_id  # Store the validated client_id in Flask's g object
            return view_function(*args, **kwargs)
        else:
            logger.debug(f"Client not authenticated for URL {request.url} : {repr(client_id)} / {repr(client_token)}")
            #logger.debug(f"Request URL: {request.url}")
            #logger.debug(f"Request Headers: {request.headers}")
            abort(401)
    
    return decorated_function
