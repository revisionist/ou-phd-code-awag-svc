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

misc_routes = Blueprint('misc_routes', __name__)


def init_db_tables(conn):

    pass


@misc_routes.route('/get-tags', methods=['GET'])
@require_api_auth
def get_tags():

    agent_id, resp, conn = init_route(request)

    responseData = []

    try:

        last_n_hours = get_arg(request, "lastNHours", None)
        type = get_arg(request, "type", "evaluation")

        time_filter = None
        if last_n_hours and int(last_n_hours) > 0:
            time_filter = datetime.now() - timedelta(hours=int(last_n_hours))
        
        conn = get_db_conn()

        if (type == 'classification'):
            base_query = "select distinct agent_id, tag FROM classification_record_tags t"
        else:
            base_query = "select distinct agent_id, tag FROM evaluation_tags t"

        where_conditions = ["t.agent_id = ?"]
        params = [agent_id]

        if time_filter:
            where_conditions.append("t.timestamp >= ?")
            params.append(time_filter)

        where_clause = " WHERE " + " AND ".join(where_conditions)
        
        data_query = base_query + where_clause
        data_query += " ORDER BY t.tag ASC"
        
        data_cursor = conn.execute(data_query, params)
        
        for row in data_cursor:
            responseData.append(row["tag"])

        response_json = {
            'status': 'OK',
            'message': 'OK',
            'data': responseData
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:
    
        return resp.generate_response_with_exception(e)

    finally:
        conn_close(conn)

