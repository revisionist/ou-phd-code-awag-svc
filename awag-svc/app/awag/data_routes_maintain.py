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

import sqlite3

from datetime import datetime
from flask import Blueprint, request

from domestique.db import conn_rollback, conn_close
from domestique.db.sqlite import get_db_conn

from authentication import require_api_auth

from .shared_resources import *

maintenance_routes = Blueprint('maintenance_routes', __name__)


def get_purge_tables_list():

    tables_list = [
        "evaluation_main",
        "evaluation_tags",
        "evaluation_item_classifications",
        "evaluation_item_info",
        "evaluation_persona",
        "evaluation_perspective",
        "evaluation_results",
        "evaluation_context",
        "evaluation_failures",
        "evaluation_raw_items",
        "evaluation_raw_tags",
        "evaluation_feedback_items",
        "evaluation_feedback_tags",
        "classification_record",
        "classification_record_tags",
        "classification_actions",
        "classification_actions_tags",
        "classification_item_ignore",
        "flow_record",
        "reporting_base",
        "reporting_evaluation_feedback",
        "classification_id_subsets",
        "summarisation_request_record",
        "summarisation_feedback_record"
    ]

    # Include for information so we can see what we intentionally do not want to purge
    do_not_purge_list = [
        "items",           # Do not purge
        "last_served",     # Do not purge
    ]

    return tables_list


@maintenance_routes.before_request
def before_request():
  
    pass


@maintenance_routes.route('/purge-agent-data', methods=['DELETE'])
@require_api_auth
def purge_agent_data():

    agent_id, resp, conn = init_route(request)

    try:

        is_confirm = request.args.get('confirm', type=bool, default=False)

        if not is_confirm:
            return resp.generate_response_with_data(f"Missing required parameter confirm=true", 400)

        conn = get_db_conn()

        timestamp = datetime.now().strftime("%Y%m%d")
        prefix = f"purged_archive_{timestamp}"
        purged_archive_tables = []

        tables_list = get_purge_tables_list()

        for table in tables_list:

            purged_table_name = f"{prefix}_{table}"

            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (purged_table_name,))
            table_exists = cur.fetchone()

            archive_sql = None
            if table_exists:
                logger.debug(f"Table EXISTS: {purged_table_name}")
                archive_sql = f"INSERT OR REPLACE INTO {purged_table_name} SELECT * FROM {table} WHERE agent_id=?"
            else:
                logger.debug(f"Table DOES NOT EXIST: {purged_table_name}")
                archive_sql = f"CREATE TABLE {purged_table_name} AS SELECT * FROM {table} WHERE agent_id=?"

            logger.debug(f"Executing SQL to archive purged data: {archive_sql}")
            cur.execute(archive_sql, (agent_id,))

            delete_sql = f"DELETE FROM {table} WHERE agent_id=?"
            logger.debug(f"Executing SQL to delete data: {delete_sql}")
            cur.execute(delete_sql, (agent_id,))

            purged_archive_tables.append(purged_table_name)

        conn.commit()

        response_json = {
            'status': f"Data purged successfully for agent_id: {agent_id}",
            'message': 'OK',
            'purged_tables': tables_list,
            'prefix': prefix,
            'purged_archive_tables': purged_archive_tables
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        conn_rollback(conn)
        return resp.generate_response_with_exception(e)

    finally:

        conn_close(conn)

