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

import sys
import types
import re
import sqlite3
import json
import os

from datetime import datetime

from flask import current_app, make_response, g
from werkzeug.local import LocalProxy

from openai import OpenAI

# https://github.com/revisionist/python-utils/tree/main/domestique
from domestique.logging import log_exception
from domestique.flask.response import ResponseWrapper


logger = LocalProxy(lambda: current_app.logger)


VALID_NAME_REGEX = re.compile(r'^[a-zA-Z0-9:+\-_/~#]*$')


def init_route(request):

    client_id = g.client_id
    resp = None
    conn = None

    if not request:
        raise ValueError("Must pass a request to init_route!")

    logger.info(f"Route: {request.method} {request.path} from {request.remote_addr} as {client_id}")
    try:
        resp = ResponseWrapper(request, client_id)
    except Exception as e:
        log_exception(client_id, e)

    return client_id, resp, conn


def is_valid_name_string(val):

    return VALID_NAME_REGEX.match(val) is not None


def get_valid_list_from_string(raw_string):

    logger.debug(f'Method get_valid_list_from_string: {raw_string}')

    if not raw_string:
        return None

    parsed_strings = None

    if isinstance(raw_string, str):
        # Check if the string is JSON formatted
        if raw_string.startswith('[') and raw_string.endswith(']'):
            try:
                json_to_parse = raw_string.replace("'", '"')
                parsed_strings = json.loads(json_to_parse)
            except json.JSONDecodeError:
                raise ValueError(f'Unable to parse JSON string: {raw_string}')
        else:
            # Handle as a comma-separated string
            parsed_strings = [s.strip() for s in raw_string.split(',') if s.strip()]

    elif isinstance(raw_string, list):
        parsed_strings = raw_string

    # Validate each string in the parsed list
    if parsed_strings is not None:
        for string in parsed_strings:
            if not is_valid_name_string(string):
                logger.error(f'Got bad string: {string} in strings input: {raw_string}')
                raise ValueError(f'Invalid string found: {string}')

    return parsed_strings


def get_auth_token(client_id):

    #logger.debug(f"get_auth_token for client_id: {client_id}")
    api_auth = current_app.config['API_AUTH']
    auth_token = None
    if api_auth:
        auth_token = api_auth.get(client_id, None)
    return auth_token


def dict_from_openai_object(obj):

    # This method should not need to exist ಠ_ಠ

    if not obj:
        return None

    object_type = obj.object

    big_old_kludge = {
        "id": obj.id,
        "object": obj.object
    }

    if object_type == 'file':
        big_old_kludge["bytes"] = obj.bytes
        big_old_kludge["filename"] = obj.filename
        big_old_kludge["purpose"] = obj.purpose
        big_old_kludge["status"] = obj.status
        big_old_kludge["status_details"] = obj.status_details
        big_old_kludge["created_at"] = obj.created_at
    elif object_type == 'fine_tuning.job':
        big_old_kludge["model"] = obj.model
        big_old_kludge["finished_at"] = obj.finished_at
        big_old_kludge["fine_tuned_model"] = obj.fine_tuned_model
        big_old_kludge["organization_id"] = obj.organization_id
        big_old_kludge["result_files"] = obj.result_files
        big_old_kludge["status"] = obj.status
        big_old_kludge["validation_file"] = obj.validation_file
        big_old_kludge["training_file"] = obj.training_file
        big_old_kludge["hyperparameters"] = str(obj.hyperparameters)
        big_old_kludge["trained_tokens"] = obj.trained_tokens
        big_old_kludge["created_at"] = obj.created_at
    elif object_type == 'model':
        big_old_kludge["owned_by"] = obj.owned_by
        big_old_kludge["created"] = obj.created
    else:
        raise ValueError(f"Unsupported object: {object_type}")

    return big_old_kludge


def get_dataset_namespace_base_for_type(namespace_base, dataset_type):

    if not namespace_base:
        raise ValueError("Missing 'namespace_base'")

    if dataset_type == "from_actions":
        return namespace_base + "fa_"
    elif dataset_type == "from_files":
        return namespace_base + "ff_"
    else:
        raise ValueError(f"Invalid dataset_type: {dataset_type}")


def get_dataset_namespace_prefix(namespace_base):

    if not namespace_base:
        raise ValueError("Missing 'namespace_base'")

    return namespace_base + "dataset_"


def get_dataset_namespace(namespace_base, dataset):

    if not dataset:
        raise ValueError("Missing 'dataset'")

    return get_dataset_namespace_prefix(namespace_base) + dataset


def get_dataset_meta_suffix():

    return "_meta"


def get_dataset_meta_namespace(namespace_base, dataset):

    return get_dataset_namespace(namespace_base, dataset) + get_dataset_meta_suffix()


def append_openai_message(role, content, messages=[]):
    
        if not messages:
            messages = []

        if not role:
            raise ValueError("Missing required value: role")

        if not content:
            raise ValueError("Missing required value: content")

        messages.append({
            "role": role,
            "content": content
        })

        return messages;


def construct_pseudo_openai_training_entry(system_message, user_messages, assistant_message):

    # This does not necessarily generate a valid openai_training_entry because any
    # messages passed as objects are not converted to strings as would be requried
    # by openai.  We use this for generating human-readable/editable content

    messages = append_openai_message("system", system_message)

    if isinstance(user_messages, list):  # Check if user_messages is a list
        #concat_user_message = ""
        for user_message in user_messages:
            #if not concat_user_message:
            #    concat_user_message += "\n\n"
            #concat_user_message += f"{user_message}"
            messages = append_openai_message("user", user_message, messages)
        #messages = append_openai_message("user", concat_user_message, messages)
    else:
        messages = append_openai_message("user", user_messages, messages)

    messages = append_openai_message("assistant", assistant_message, messages)

    return {"messages": messages}


def construct_openai_training_entry(system_message, user_messages, assistant_message):

    # chat-completion format, compatible with gpt-3.5-turbo and newer

    return construct_pseudo_openai_training_entry(str(system_message), str(user_messages), str(assistant_message))


def convert_pseudo_openai_training_entry(messages):

    converted_messages = []
    for message in messages:
        if 'content' in message:
            converted_message = {
                "role": message["role"],
                "content": str(message["content"])
            }
            converted_messages.append(converted_message)
        else:
            converted_messages.append(message)
    
    return converted_messages


def validate_subset_percent(subset_percent):

    if subset_percent is None:
        raise ValueError("Subset percent must not be None")

    try:
        subset_percent = int(subset_percent)
    except ValueError:
        raise ValueError("Subset percent must be an integer")

    if not (1 <= subset_percent <= 100):
        raise ValueError("Subset percent must be between 1 and 100")

    return subset_percent


def write_json_file(path, filename, content_json):

    if not os.access(path, os.W_OK):
        raise ValueError(f"Server path is not writable: {path}")
    file_path = os.path.join(path, filename)
    with open(file_path, 'w') as file:
        json.dump(content_json, file, indent=4)
    logger.debug(f"Item written to file: {file_path}")


def generate_timestamp_with_ms():

    now = datetime.now()
    timestamp_str = now.strftime('%Y%m%d%H%M%S') + '{:03d}'.format(now.microsecond // 1000)
    return timestamp_str


def validate_persona(persona):

    if not persona:
        raise ValueError("Persona must not be empty")

    required_keys = ['id', 'name', 'definition']
    for key in required_keys:
        if key not in persona:
            raise ValueError(f"Missing required key in Persona JSON: {key}")

    if not isinstance(persona['id'], str) or not persona['id']:
        raise ValueError("The 'id' must be a non-empty string")
    if not isinstance(persona['name'], str) or not persona['name']:
        raise ValueError("The 'name' must be a non-empty string")

    required_definition_keys = [
        'age', 'does', 'feelThinkBelieve', 'gender', 'technologyExperience', 
        'problems', 'needs', 'existingSolutions'
    ]

    if not isinstance(persona['definition'], dict):
        raise ValueError("'definition' must be a dictionary")

    for key in required_definition_keys:
        if key not in persona['definition']:
            raise ValueError(f"Missing required key in Persona JSON 'definition': {key}")

    return persona['id'], persona['name']


def get_mode_specific_content(mode, reqjson):

    evaluation_user_messages = []
    if mode == "mode1":
        evaluation_result_schema = g.evaluation_result_schema_mode1
        evaluation_system_message_extra = g.evaluation_system_message_extra_mode1
        if reqjson is not None:
            evaluation_user_messages.append(get_reqjson_val(reqjson, "evaluation_user_message", g.training_item_user_message_premable_mode1)) 
        else:
            evaluation_user_messages.append(g.training_item_user_message_premable_mode1) 
    elif mode == "mode2":
        evaluation_result_schema = g.evaluation_result_schema_mode2
        evaluation_system_message_extra = g.evaluation_system_message_extra_mode2
        if reqjson is not None:
            evaluation_user_messages.append(get_reqjson_val(reqjson, "evaluation_user_message", g.training_item_user_message_premable_mode2)) 
            evaluation_user_messages.append(get_reqjson_val(reqjson, "evaluation_user_message_example", g.training_item_user_message_example_mode2)) 
        else:
            evaluation_user_messages.append(g.training_item_user_message_premable_mode2) 
            evaluation_user_messages.append(g.training_item_user_message_example_mode2) 
    elif mode == "mode3":
        evaluation_result_schema = g.evaluation_result_schema_mode3
        evaluation_system_message_extra = g.evaluation_system_message_extra_mode3
        if reqjson is not None:
            evaluation_user_messages.append(get_reqjson_val(reqjson, "evaluation_user_message", g.training_item_user_message_premable_mode3)) 
            evaluation_user_messages.append(get_reqjson_val(reqjson, "evaluation_user_message_example", g.training_item_user_message_example_mode3)) 
        else:
            evaluation_user_messages.append(g.training_item_user_message_premable_mode3) 
            evaluation_user_messages.append(g.training_item_user_message_example_mode3) 
    else:
        raise ValueError(f"Invalid mode: {mode}")

    return evaluation_system_message_extra, evaluation_result_schema, evaluation_user_messages


def validate_mode1_evaluation_result(evaluation_result):

    if "itemId" not in evaluation_result or not evaluation_result["itemId"]:
        return False
    if "evaluations" not in evaluation_result or not isinstance(evaluation_result["evaluations"], list):
        return False

    for evaluation in evaluation_result["evaluations"]:
        if "classificationName" not in evaluation or not evaluation["classificationName"]:
            return False
        if "perspectives" not in evaluation or not isinstance(evaluation["perspectives"], list):
            return False

        for perspective in evaluation["perspectives"]:
            required_perspective_fields = ["perspectiveId", "evaluatedSelection", "evaluationLikert", "evaluationText"]
            if not all(field in perspective for field in required_perspective_fields):
                return False
            if not isinstance(perspective["perspectiveId"], str) or not perspective["perspectiveId"]:
                return False
            if not isinstance(perspective["evaluatedSelection"], str) or not perspective["evaluatedSelection"]:
                return False
            if not isinstance(perspective["evaluationLikert"], int):
                return False
            if not isinstance(perspective["evaluationText"], str) or not perspective["evaluationText"]:
                return False

    return True


def validate_mode2_mode3_evaluation_result(evaluation_result, mode):

    required_fields = ["id", "evaluationText", "evaluatedSelection"]
    is_valid = all(field in evaluation_result for field in required_fields)
    if not is_valid:
        return False

    id_fields = ["itemId", "perspectiveId", "classificationId"]
    if not all(key in evaluation_result["id"] for key in id_fields):
        return False

    if mode == "mode2":
        if "evaluationLikert" not in evaluation_result:
            return False
    elif mode == "mode3":
        if "evaluationAgreement" not in evaluation_result:
            return False
    else:
        return False  # Invalid mode passed

    return True


def get_likert_label(value):

    if value is None:
        raise ValueError("Value must not be None")

    try:
        value = int(value)
    except ValueError:
        raise ValueError("Value must be an integer")

    label = None

    match value:
        case 1:
            label = "Strongly Disagree"
        case 2:
            label = "Disagree"
        case 3:
            label = "Neutral"
        case 4:
            label = "Agree"
        case 5:
            label = "Strongly Agree"
        case _:
            raise ValueError(f"Invalid value {value}")

    return label


def get_agent_name_from_id(agent_lookup_dict, agent_id):

    if not agent_id:
        return None

    if not agent_lookup_dict:
        return agent_id

    return agent_lookup_dict.get(agent_id, agent_id)

