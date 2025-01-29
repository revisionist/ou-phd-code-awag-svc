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

import os
import json
import mimetypes
import time
import threading

from datetime import datetime

from enum import Enum

from flask import current_app

from domestique.datetime import get_current_time_ms
from domestique.validation import Validator, NoiseLevel
from domestique.json import get_dict_from_dict_or_json_str
from domestique.text import truncate_string
from domestique.identifiers import generate_id, generate_shorter_id
from domestique.logging import log_exception
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn

from .shared_resources import logger

from .client_openai import OpenAIClientWrapper


class SimulationManager:

    def __init__(self, app_config, agent_id, awagdata_client, openai_auth_token=None, flask_app=None):

        if app_config is None:
            raise ValueError("No app_config (current_app.config from flask) passed to SimulationManager")

        self.app_config = app_config
        self.agent_id = agent_id

        self.openai_base_url = app_config.get("REST_BASE_URL_OPENAI", None)
        self.openai_engine = app_config.get("OPENAI_ENGINE", None)

        Validator().check_all(
            agent_id=agent_id,
            openai_base_url=self.openai_base_url,
            awagdata_client=awagdata_client,
            openai_engine=self.openai_engine)

        if not openai_auth_token:
            self.openai_auth_token = app_config.get("OPENAI_AUTH_TOKEN", None)
        else:
            self.openai_auth_token = openai_auth_token

        self.awagdata_client = awagdata_client

        self.get_simulated_messages_function = app_config.get("SIMULATION_MESSAGES_RESULT_SCHEMA", None)
        self.simulation_dramatis_personae_schema = app_config.get("SIMULATION_DRAMATIS_PERSONAE_SCHEMA", None)
        self.simulation_entities_schema = app_config.get("SIMULATION_ENTITIES_SCHEMA", None)

        Validator().check_all(noise_level=NoiseLevel.SILENT,
            get_simulated_messages_function=self.get_simulated_messages_function,
            simulation_dramatis_personae_schema=self.simulation_dramatis_personae_schema,
            simulation_entities_schema=self.simulation_entities_schema)

        #db_file_path = app.config['SQLITE_DATABASE_FILE']
        #sqlite.configure_db(db_file_path)

        self.flask_app = flask_app

        self.job_statuses = {}

        self.table_last_served = "last_served"
        self.table_items = "items"


    def get_agent_id(self):

        return self.agent_id


    def get_openai_auth_token(self):

        return self.openai_auth_token


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def get_job_statuses(self):

        return self.job_statuses


    def get_job_status(self, job_id):

        return self.job_statuses.get(job_id, None)


    def init_db_tables(self, conn):

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_items} (
                item_id INTEGER,
                item_category TEXT,
                item_userid TEXT,
                item_username TEXT,
                item_text TEXT,
                PRIMARY KEY (item_id, item_category)
            )
        """)

        # Create the last_served table if it doesn't exist
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_last_served} (
                agent_id INTEGER,
                item_id INTEGER,
                item_category TEXT,
                timestamp TEXT,
                PRIMARY KEY (agent_id, item_category, item_id)
            )
        """)
        conn.commit()


    def generate_response(self, status, message, code, data=None, info=None, usage=None):

        resp = {
            "status": status,
            "message": message,
            "code": code
        }
        if data is not None:
            resp["data"] = data
        if usage is not None:
            resp["usage"] = usage
        if info is not None:
            resp["info"] = info
        return resp


    def get_sim_text(self, item_category, item_id=None):

        agent_id = self.get_agent_id()

        Validator().check(["agent_id", "item_category"], agent_id=agent_id, item_category=item_category, item_id=item_id)

        # Check if item_id was passed that it is a valid integer
        if item_id is not None:
            logger.debug('Passed item_id' + str(item_id))
            try:
                item_id = int(item_id)
            except ValueError:
                raise ValueError(f"Invalid item_id: {item_id}")

        conn = get_db_conn()

        try:

            # Check if item_id is negative (i.e. reset requested)
            if item_id is not None and item_id < 0:
                c = conn.cursor()
                c.execute(f"DELETE FROM {self.table_last_served} WHERE agent_id=? AND item_category=?", (agent_id, item_category))
                conn.commit()
                conn.close()
                logger.debug(f"Deleted from {self.table_last_served} with item_category: '{item_category}', agent_id: '{agent_id}'")
                # Carry on as normal and fetch the next available item
                item_id = None

            # Fetch the next available item

            c = conn.cursor()
            if item_id is None:
                logger.debug(f"Fetching the next available item that hasn't been served to this agent yet for category '{item_category}', agent_id: '{agent_id}'")
                c.execute(f"""
                    SELECT item_id, item_userid, item_username, item_text FROM {self.table_items} 
                    WHERE item_category = ? AND item_id NOT IN (
                        SELECT item_id FROM {self.table_last_served} WHERE agent_id = ? AND item_category = ?
                    ) 
                    ORDER BY item_id ASC 
                    LIMIT 1
                """, (item_category, agent_id, item_category))
                result = c.fetchone()
                if result is None:
                    logger.debug("No items left to serve, cycle back to the beginning")
                    c.execute(f"DELETE FROM {self.table_last_served} WHERE agent_id=? AND item_category=?", (agent_id, item_category))
                    c.execute(f"SELECT item_id, item_userid, item_username, item_text FROM {self.table_items} WHERE item_category = ? ORDER BY item_id ASC LIMIT 1", (item_category,))
                    result = c.fetchone()
                    if result is None:
                        return self.generate_response("ERROR", f"Item not found for category: {item_category}", 404)
                    item_id = result[0]
                    logger.debug(f"New item_id: {item_id}")
            else:
                # Fetch the item with the given ID and category
                c.execute(f"SELECT item_id, item_userid, item_username, item_text FROM {self.table_items} WHERE item_category = ? AND item_id = ?", (item_category, item_id))
                result = c.fetchone()

            if result is None:
                response_message = f"Item not found for category: {item_category}"
                if item_id is not None:
                    response_message += f" with item_id: {item_id}"
                return self.generate_response("ERROR", response_message, 404)

            if item_id is None:
                item_id = result[0]

            # Update the last_served table with the new item for this agent and category
            c.execute(f"INSERT OR REPLACE INTO {self.table_last_served} (agent_id, item_category, item_id, timestamp) VALUES (?, ?, ?, datetime('now'))", (agent_id, item_category, result[0]))
            conn.commit()
            logger.debug(f"Updated {self.table_last_served}  with item_id: '{item_id}', item_category: '{item_category}', agent_id: '{agent_id}'")

            if result is None:
                return self.generate_response("ERROR", f"Item not found for category: {item_category}", 404)

            response_data = {
                    'agent': agent_id,
                    'item_category': item_category,
                    'item_id': result[0],
                    'item_userid': result[1],
                    'item_username': result[2],
                    'item_text': result[3]
                }

            return self.generate_response("OK", "OK", code=200, data=response_data)

        finally:

            conn_close(conn)


    def get_all_sim_texts(self, item_category, most_recent_count=None):

        agent_id = self.get_agent_id()

        Validator().check(["agent_id", "item_category"], agent_id=agent_id, item_category=item_category, most_recent_count=most_recent_count)

        conn = get_db_conn()

        try:

            c = conn.cursor()

            if most_recent_count is not None:
                sql = f"""
                    SELECT item_id, item_userid, item_username, item_text 
                    FROM (
                        SELECT item_id, item_userid, item_username, item_text 
                        FROM {self.table_items} 
                        WHERE item_category = ? 
                        ORDER BY item_id DESC 
                        LIMIT ?
                    ) AS subquery 
                    ORDER BY item_id ASC
                """
                c.execute(sql, (item_category, most_recent_count))
            else:
                sql = f"SELECT item_id, item_userid, item_username, item_text FROM {self.table_items} WHERE item_category = ? ORDER BY item_id ASC"
                c.execute(sql, (item_category,))

            rows = c.fetchall()

            response_data = []

            for row in rows:
                #logger.debug(f"Processing row: {row}")
                response_data.append({
                        'agent': agent_id,
                        'item_category': item_category,
                        'item_id': row["item_id"],
                        'item_userid': row["item_userid"],
                        'item_username': row["item_username"],
                        'item_text': row["item_text"]
                })

            if len(response_data) == 0:
                return self.generate_response("ERROR", f"No data for category: {item_category}", code=404, data=response_data)
            else:
                return self.generate_response("OK", "OK", code=200, data=response_data)

        finally:

            conn_close(conn)


    def insert_items(self, items):

        Validator().check(["items"], items=items)

        conn = get_db_conn()

        try:

            self.init_db_tables(conn)

            cursor = conn.cursor()

            counter = 0
            for item in items:
                if not item['text']:
                    logger.error(f"Items does not have text: {item}")
                    continue
                cursor.execute(f"SELECT MAX(item_id) FROM {self.table_items}  WHERE item_category = ?", (item['category'],))
                result = cursor.fetchone()
                item_id = result[0] if result[0] else 0
                cursor.execute(f"INSERT INTO {self.table_items}  (item_id, item_category, item_userid, item_username, item_text) VALUES (?, ?, ?, ?, ?)", (item_id+1, item['category'], item['userid'], item['username'], item['text']))
                counter += 1

            logger.info(f"Added items: {counter}")

            conn.commit()

            return self.generate_response("OK", "Items added successfully", code=201, data=counter)

        except Exception as e:

            conn_rollback(conn)
            log_exception(agent_id, e)
            raise e

        finally:

            conn_close(conn)


    def _extract_simulated_messages(self, openai_response, info_json=None):

        Validator().check(["openai_response"], openai_response=openai_response)

        resp_message = openai_response.message
        tool_calls = resp_message.tool_calls

        if not tool_calls:
            ex_msg = f"Did not get tool_calls from OpenAI API response: {openai_response}"
            logger.error(ex_msg)
            logger.error(f"info_json: {info_json}")
            raise Exception(ex_msg)

        function = tool_calls[0].function
        arguments_raw = function.arguments
        if not arguments_raw:
            raise ValueError("The expected function_call item is not present.")

        arguments_obj = get_dict_from_dict_or_json_str(arguments_raw)
        data = arguments_obj.get("data")
        logger.debug(f"Got simulated_messages: {data}")

        return data


    def _get_historical_messages(self, category, most_recent_count=None):

        get_all_result = self.get_all_sim_texts(category, most_recent_count)

        if get_all_result["code"] == 404:
            return []

        if get_all_result["status"] == "ERROR":
            raise Exception(f"Unable to get hostorical messages for '{category}': {get_all_result['message']}")

        historical_messages = []

        for message in get_all_result["data"]:
            historical_messages.append({
                "item_userid": message["item_userid"],
                "item_username": message["item_username"],
                "item_text": message["item_text"]
            })

        return historical_messages


    def generate_simulated_text(self, category, topic, item_count, prompt_template, dramatis_personae=None, entities=None, openai_params=None, openai_model=None, is_use_history=False):

        agent_id = self.get_agent_id()

        Validator().check(["agent_id", "category", "topic", "item_count"], agent_id=agent_id, category=category, topic=topic, item_count=item_count, is_use_history=is_use_history)
        Validator().check_all(noise_level=NoiseLevel.SILENT, prompt_template=prompt_template, openai_auth_token=self.openai_auth_token)

        openai_client = OpenAIClientWrapper(self.openai_auth_token)

        if not openai_params:
            openai_params = {
                        "max_tokens": 2048,
                        "temperature": 0.9,
                        "top_p": 0,
                        "frequency_penalty": 0.1,
                        "presence_penalty": 0.1
                    }

        if not all(isinstance(val, str) and val.strip() for val in [category, topic]):
            raise ValueError("Bad input data: category and topic must be non-empty strings")

        if item_count < 1:
            raise ValueError(f"Bad item_count: {item_count}")

        prompt = prompt_template.format(category=category, topic=topic, item_count=item_count)

        model = openai_model
        if not model:
            model = self.openai_engine

        messages = openai_client.append_system_message(f"This is the schema to use for identities:\n{json.dumps(self.simulation_dramatis_personae_schema)}")

        openai_client.append_system_message(f"This is the schema to use for entities:\n{json.dumps(self.simulation_entities_schema)}", messages)
        openai_client.append_system_message(prompt, messages)
        openai_client.append_user_message(f"This is the topic that I want you to generate content for: {topic}", messages)
        if dramatis_personae:
            openai_client.append_user_message(f"This is identities data (dramatis_personae):\n{json.dumps(dramatis_personae)}", messages)
        if entities:
            openai_client.append_user_message(f"This is entities data:\n{json.dumps(entities)}", messages)
        if is_use_history:
            historical_messages = self._get_historical_messages(category, 150)
            openai_client.append_user_message(f"This is a list of already existing messages for this topic.  Do not repeat any exact existing message in your content, but you can have your new messages make references to existing ones where appropriate:\n{json.dumps(historical_messages)}", messages)

        tools = [openai_client.get_tools_json_from_function_schema(self.get_simulated_messages_function)]
        tool_choice = openai_client.get_tool_choice_json("get_simulated_messages")

        logger.debug(f"Generated messages: {messages}")

        openai_response, info_json = openai_client.run_chat_completions(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            openai_params=openai_params
        )

        simulated_messages = self._extract_simulated_messages(openai_response, info_json)

        if len(simulated_messages) == 0:
            return self.generate_response("ERROR", f"No data generated", code=500, data=response_data)
        else:
            return self.generate_response("OK", "Items generated successfully", code=200, data=simulated_messages, info=info_json)


    def generate_simulated_texts(self, is_add, topics, item_count, prompt_template, dramatis_personae=None, entities=None, openai_params=None, openai_model=None, is_async=False, is_use_history=False):

        agent_id = self.get_agent_id()

        required = ["agent_id", "is_add", "topics", "item_count", "is_async"]

        Validator().check(required, agent_id=agent_id, is_add=is_add, topics=topics, item_count=item_count, is_async=is_async,is_use_history=is_use_history)
        Validator().check_all(noise_level=NoiseLevel.SILENT, prompt_template=prompt_template)

        #processed_items = []
        #error_items = []
        #error_flag = False

        job_id = generate_id()
        start_time = time.time()

        model = openai_model
        if not model:
            model = self.openai_engine

        job_status = {
            "job_id": job_id,
            "status": "INITIATED",
            "code": 202,
            "message": f"Initialised processing with job_id: {job_id}",
            "is_async": is_async,
            "is_add": is_add,
            "item_count": item_count,
            "openai_model": model,
            "openai_params": openai_params,
            "error_flag": False,
            "categories": [],
            "processed_count": 0,
            "generated_count": 0,
            "processed_ms": 0,
            "processed_tokens": 0,
            "processed_items": [],
            "error_items": [],
            "topics": []
        }
        self.job_statuses[job_id] = job_status

        def process_topics():

            nonlocal job_status

            with self.flask_app.app_context():  # So we can use context-dependent features such as logging

                topic_entry = None

                try:

                    categories_list = []
                    for topic_entry in topics:
                        is_topic_enabled = topic_entry.get('enabled', True)
                        if not is_topic_enabled:
                            continue
                        categories_list.append(topic_entry.get('category'))
                        job_status["topics"].append(topic_entry)

                    time.sleep(0.1) # Allow short time for calling function to return initial job_status
                    job_status["status"] = "PROCESSING"
                    job_status["categories"] = categories_list

                    logger.debug(f"Started process_topics for {len(topics)} topics...")

                    for topic_entry in topics:

                        logger.debug(f"Processing topic: {topic_entry}")

                        category = topic_entry.get('category')

                        job_status["message"] = f"Processing category '{category}' of {categories_list}"

                        topic = topic_entry.get('topic')

                        is_topic_enabled = topic_entry.get('enabled', True)
                        if not is_topic_enabled:
                            logger.debug(f"Skipping topic: {topic_entry}")
                            continue

                        items_multiplier = topic_entry.get('items_multiplier', 1)
                        adjusted_item_count = item_count * items_multiplier

                        Validator().check_all(noise_level=NoiseLevel.SILENT, category=category, topic=topic)

                        gen_resp = self.generate_simulated_text(category, topic, adjusted_item_count, prompt_template, dramatis_personae, entities, openai_params, model, is_use_history)

                        logger.debug(f"Got gen_resp: {gen_resp}")

                        if gen_resp["code"] != 200:
                            logger.error(f"Got non-success response from generate_simulated_text for category '{category}': {gen_resp}")
                            logger.error(f"Topic was: {topic}")
                            job_status["error_items"].append({
                                "category": category,
                                "topic": topic,
                                "gen_resp": gen_resp
                            })
                            job_status["error_flag"] = True
                            continue

                        simulated_messages = gen_resp["data"]

                        if is_add:
                            self.insert_items(simulated_messages)

                        info = gen_resp.get("info", {})
                        tokens_used = info.get("usage", {}).get("total_tokens", 0) if "usage" in info else 0

                        job_status["processed_items"].append({
                            "category": category,
                            "topic": topic,
                            "item_count": adjusted_item_count,
                            "content": simulated_messages,
                            "info": gen_resp.get("info", None)
                        })

                        job_status["processed_count"] += 1
                        job_status["generated_count"] += len(simulated_messages)
                        job_status["processed_tokens"] += tokens_used

                        current_time = time.time()
                        job_status["processed_ms"] = int((current_time - start_time) * 1000)

                    if job_status["error_flag"]:
                        job_status["status"] = "ERROR"
                        job_status["code"] = 500
                        job_status["message"] = "Errors encountered"
                    else:
                        job_status["status"] = "COMPLETE"
                        if is_add:
                            job_status["code"] = 201
                            job_status["message"] = f"Items generated & added successfully for {job_status['processed_count']} topics: {categories_list}"
                        else:
                            job_status["code"] = 200
                            job_status["message"] = f"Items generated successfully for {job_status['processed_count']} topics: {categories_list}"

                    logger.debug(f"Completed process_topics")

                except Exception as e:

                    msg = f"Error in process_topics for topic_entry: {topic_entry}: {e}"
                    job_status["status"] = "ERROR"
                    job_status["message"] = msg
                    logger.error(msg)
                    log_exception(self.agent_id, e, include_traceback=True)

                #self.job_statuses[job_id] = job_status

        if is_async:

            logger.debug(f"Started process_topics...")
            thread = threading.Thread(target=process_topics)
            thread.start()

        else:

            process_topics()

        return job_id, self.job_statuses.get(job_id)


