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

from openai import OpenAI

from domestique.json import get_json_str_from_dict_or_str
from domestique.flask.response import check_response_status
from domestique.text import truncate_string, tidy_and_truncate_string

from .shared_resources import logger, dict_from_openai_object

OPENAI = None


class OpenAIClientWrapper:

    def __init__(self, openai_api_key):

        logger.debug(f"Initialising new OpenAIClientWrapper with openai_api_key: {openai_api_key}")

        self.OPENAI = OpenAI(
            api_key = openai_api_key
        )

        logger.debug(f"Got OpenAI: {self.OPENAI}")


    def get_client(self):

        return self.OPENAI


    def append_message(self, role, content, messages=[]):
    
        if not messages:
            messages = []

        if not role:
            raise ValueError("Missing required value: content")

        if not content:
            raise ValueError("Missing required value: content")

        messages.append({
            "role": role,
            "content": content
        })

        return messages;


    def append_user_message(self, content, messages=[]):

        return self.append_message(role="user", content=content, messages=messages)


    def append_system_message(self, content, messages=[]):

        return self.append_message(role="system", content=content, messages=messages)


    def xx_create_message(self, role, content):
    
        '''
        TODO: consider implementing later
        See https://github.com/openai/openai-python/blob/main/examples/assistant.py
        '''


    def get_tools_json_from_function_schema(self, schema):

        # This method updates the structure to soemthing that works with the newer 'tools' syntax

        return {
            "type": "function",
            "function": schema
        }


    def get_tool_choice_json(self, function_name):

        return {
            "type": "function",
            "function": {
                "name": function_name
            }
        }


    def run_chat_completions(self,
        messages,
        model='gpt-3.5-turbo',
        openai_params={},
        tools=None,
        tool_choice=None
        ):

        #if tools is None:
        #    tools = []

        if not isinstance(messages, list):
            raise TypeError(f"Messages must be a valid list: {messages}")

        logger.debug(f"Call to run_chat_completions using model '{model}'; messages has size: {len(messages)}")

        if tools:
            logger.debug(f"Passed tools: {tools}")
        if tool_choice:
            logger.debug(f"Passed tool_choice: {tool_choice}")

        try:

            completion = self.get_client().chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                stream=False,
                **openai_params
            )

            logger.debug(f"Response (completion):\n{completion}")

            logger.debug(f"Completion ID: {completion.id}")

            choices = completion.choices
            if len(choices) < 1:
                raise Exception(f"Completion result has no choices!:\n{completion}")
            elif len(choices) > 1:
                logger.warn(f"Completion result has {len(choices)} choices!")

            info_json_usage = {}
            if completion.usage:
                usg = completion.usage
                info_json_usage["completion_tokens"] = usg.completion_tokens
                info_json_usage["prompt_tokens"] = usg.prompt_tokens
                info_json_usage["total_tokens"] = usg.total_tokens

            info_json = {
                "engine": "awag_python",
                "query_info": {
                    "model": model,
                    "tool_choice": tool_choice,
                    **openai_params
                },
                "query_state": {
                    "id": completion.id,
                    "created": completion.created,
                    "model": completion.model,
                    "object": completion.object,
                    "system_fingerprint": completion.system_fingerprint
                },
                "usage": info_json_usage
            }

            return_choice = choices[0]
            logger.debug(f"Returning choice: {truncate_string(str(return_choice), 150)}")
            logger.debug(f"Returning info_json: {info_json}")

            return return_choice, info_json

        except Exception as e:

            logger.exception(f"An error occurred in run_chat_completions: {e}")
            logger.error(f"Passed messages: {messages}")
            raise e


    def get_file(self, file_id):

        logger.debug(f"Call to get_file using file_id: {file_id}")

        file = None
        file_as_dict = None
        try:
            file = self.get_client().files.retrieve(file_id=file_id)
            logger.debug(f"Got openai_files_response: {file}")
            file_as_dict = dict_from_openai_object(file)
        except Exception as e:
            logger.debug(f"Got Exception from OpenAI: {e}")
            if hasattr(e, "status_code") and e.status_code == 404:
                logger.debug(f"Got 404 response from OpenAI: {e}")
            else:
                logger.error(f"Got exception from OpenAI: {e}")
                raise e

        return file, file_as_dict


    def delete_file(self, file_id):

        logger.debug(f"Call to delete_file using file_id: {file_id}")

        try:
            deletion_status = self.get_client().files.delete(file_id=file_id)
            logger.debug(f"Got openai response: {deletion_status}")
        except Exception as e:
            logger.error(f"Got Exception from OpenAI in delete_file: {e}")
            raise e

        return deletion_status


    def get_fine_tuning_job(self, job_id):

        logger.debug(f"Call to get_fine_tuning_job using job_id: {job_id}")

        job = None
        job_as_dict = None
        try:
            job = self.get_client().fine_tuning.jobs.retrieve(fine_tuning_job_id=job_id)
            logger.debug(f"Got job: {job}")
            job_as_dict = dict_from_openai_object(job)
        except Exception as e:
            logger.debug(f"Got Exception from OpenAI: {e}")
            if hasattr(e, "status_code") and e.status_code == 404:
                logger.debug(f"Got 404 response from OpenAI: {e}")
            else:
                logger.error(f"Got exception from OpenAI: {e}")
                raise e

        return job, job_as_dict


    def delete_fine_tuning_job(self, job_id):

        logger.debug(f"Call to delete_fine_tuning_job using file_id: {job_id}")

        try:
            deletion_status = self.get_client().fine_tuning.jobs.delete(fine_tuning_job_id=job_id)
            logger.debug(f"Got openai response: {deletion_status}")
        except Exception as e:
            logger.error(f"Got Exception from OpenAI in delete_fine_tuning_job: {e}")
            raise e

        return deletion_status


    def get_model(self, model_id):

        logger.debug(f"Call to get_model using model_id: {model_id}")

        model = None
        model_as_dict = None
        try:
            model = self.get_client().models.retrieve(model=model_id)
            logger.debug(f"Got model: {model}")
            model_as_dict = dict_from_openai_object(model)
        except Exception as e:
            logger.debug(f"Got Exception from OpenAI: {e}")
            if hasattr(e, "status_code") and e.status_code == 404:
                logger.debug(f"Got 404 response from OpenAI: {e}")
            else:
                logger.error(f"Got exception from OpenAI: {e}")
                raise e

        return model, model_as_dict


    def delete_model(self, model_id):

        logger.debug(f"Call to delete_model using model_id: {model_id}")

        try:
            deletion_status = self.get_client().models.delete(model=model_id)
            logger.debug(f"Got openai response: {deletion_status}")
        except Exception as e:
            logger.error(f"Got Exception from OpenAI in delete_model: {e}")
            raise e

        return deletion_status

