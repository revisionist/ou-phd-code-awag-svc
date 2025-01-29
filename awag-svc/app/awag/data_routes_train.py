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
import requests
import tempfile
import os

from flask import Blueprint, current_app, g, jsonify, request, make_response

from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.datetime import get_current_time_ms
from domestique.text import truncate_string
from domestique.convert import str_to_bool

from authentication import require_api_auth

from .shared_resources import logger, init_route, dict_from_openai_object
from .shared_resources import get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_prefix, get_dataset_meta_suffix, get_dataset_namespace_base_for_type
from .shared_resources import validate_subset_percent
from .shared_resources import convert_pseudo_openai_training_entry
from .client_mgmt_resources import get_objectstore_client, get_awagdata_client, get_openai_client_wrapper
from .openai_object_manager import OpenAIObjectManager, ObjectType
from .dataset_manager import DatasetManager

training_routes = Blueprint('training_routes', __name__)

objectstore_clients = {}
awagdata_clients = {}
dataset_managers  = {}


@training_routes.before_request
def before_request():
  
    g.objectstore_ft_namespace_prefix = current_app.config["OBJECTSTORE_FT_NAMESPACE_PREFIX"]
    g.evaluation_system_message_common = current_app.config["AWAG_SYSTEM_MESSAGE_COMMON"]
    g.evaluation_system_message_extra_mode2 = current_app.config["AWAG_SYSTEM_MESSAGE_EXTRA_MODE2"]
    g.evaluation_system_message_extra_mode3 = current_app.config["AWAG_SYSTEM_MESSAGE_EXTRA_MODE3"]
    g.training_item_user_message_premable_mode2 = current_app.config["EVALUATION_USER_MESSAGE_MODE2"]
    g.training_item_user_message_premable_mode3 = current_app.config["EVALUATION_USER_MESSAGE_MODE3"]
    g.training_item_user_message_example_mode2 = current_app.config["EVALUATION_USER_MESSAGE_EXAMPLE_MODE2"]
    g.training_item_user_message_example_mode3 = current_app.config["EVALUATION_USER_MESSAGE_EXAMPLE_MODE3"]


def log_exception(CLIENT_ID, e):

    message = f"An error occurred for CLIENT_ID '{CLIENT_ID}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


def store_dataset_manager(job_id, dataset_manager):

    global dataset_managers

    if job_id:
        dataset_managers[job_id] = dataset_manager

    return dataset_manager


def get_dataset_manager(client_id, job_id=None):

    global dataset_managers

    if job_id:
        if job_id in dataset_managers:
            return dataset_managers[job_id]
        else:
            return None

    objectstore_client = get_objectstore_client(objectstore_clients, client_id)
    awagdata_client = get_awagdata_client(awagdata_clients, client_id)
    #openai_client_wrapper = get_openai_client_wrapper()
    manager = DatasetManager(
        namespace_base=g.objectstore_ft_namespace_prefix,
        objectstore_client=objectstore_client,
        awagdata_client=awagdata_client,
        flask_app=current_app._get_current_object())

    if job_id:
        dataset_managers[job_id] = manager

    return manager


def get_object_manager(client_id, object_type):

    objectstore_client = get_objectstore_client(objectstore_clients, client_id)
    openai_client_wrapper = get_openai_client_wrapper()

    manager =  OpenAIObjectManager(g.objectstore_ft_namespace_prefix, objectstore_client, openai_client_wrapper, object_type)
    return manager


def get_object_manager_for_files(client_id):

    return get_object_manager(client_id, ObjectType.FINE_TUNING_FILE)


def get_object_manager_for_jobs(client_id):

    return get_object_manager(client_id, ObjectType.FINE_TUNING_JOB)


def get_object_manager_for_models(client_id):

    return get_object_manager(client_id, ObjectType.MODEL)


@training_routes.route('/datasets/from_actions/<dataset_id>', methods=['POST'])
@require_api_auth
def populate_dataset_from_actions(dataset_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        tag_source = get_required_reqjson_val(reqjson, "tag_source")
        item_id = get_reqjson_val(reqjson, "itemId", None)
        classifications = get_reqjson_val(reqjson, "classifications", [])
        last_n_hours = get_arg(request, "lastNHours", None)

        subset_percent = get_reqjson_val(reqjson, 'subset_percent', None)
        subset_tag = get_reqjson_val(reqjson, 'subset_tag', None)
        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        is_exclude_agree = get_reqjson_val(reqjson, "exclude_agree", False)
        is_exclude_disagree = get_reqjson_val(reqjson, "exclude_disagree", False)

        is_async = request.args.get("async", type=str_to_bool, default=False)

        logger.debug(f'item_id: {item_id}; classifications: {classifications}; last_n_hours: {last_n_hours}; tag_source: {tag_source}; dataset_id: {dataset_id}; subset_tag: {subset_tag}; subset_percent: {subset_percent}')

        dataset_manager = get_dataset_manager(CLIENT_ID)

        # From actions uses only mode3
        training_item_system_message = f"{g.evaluation_system_message_common}{g.evaluation_system_message_extra_mode3}"

        job_status = dataset_manager.process_classification_actions(
                        dataset_id=dataset_id,
                        tag_source=tag_source,
                        training_item_system_message=training_item_system_message,
                        training_item_user_message_premable=g.training_item_user_message_premable_mode3,
                        item_id=item_id,
                        classifications=classifications,
                        last_n_hours=last_n_hours,
                        subset_tag=subset_tag,
                        subset_percent=subset_percent,
                        is_exclude_agree=is_exclude_agree,
                        is_exclude_disagree=is_exclude_disagree,
                        is_async=is_async)

        job_id = job_status["job_id"]

        store_dataset_manager(job_id, dataset_manager)

        return resp.generate_response_with_data(job_status, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/from_files/<dataset_id>', methods=['POST'])
@require_api_auth
def populate_dataset_from_files(dataset_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        server_path = get_required_reqjson_val(reqjson, "server_path")
        max_items = get_reqjson_val(reqjson, "max_items", 0)
        file_regexp = get_reqjson_val(reqjson, "file_regexp", None)
        is_ignore_existing = get_reqjson_val(reqjson, "ignore_existing", False)

        update_messages_mode = get_reqjson_val(reqjson, "update_messages_mode", None)
        is_delete_persona = get_reqjson_val(reqjson, "delete_persona", False)

        is_async = request.args.get("async", type=str_to_bool, default=False)

        logger.debug(f"dataset_id: {dataset_id}; server_path: {server_path}; max_items: {max_items}; file_regexp: {file_regexp}; is_ignore_existing: {is_ignore_existing}; is_async: {is_async}")

        dataset_manager = get_dataset_manager(CLIENT_ID)

        custom_system_message = None
        custom_user_message = None

        if update_messages_mode:
            # From files uses mode2 or mode3
            if update_messages_mode == "mode2":
                custom_system_message = f"{g.evaluation_system_message_common}{g.evaluation_system_message_extra_mode2}"
                custom_user_message = f"{g.training_item_user_message_premable_mode2}"
            elif update_messages_mode == "mode3":
                custom_system_message = f"{g.evaluation_system_message_common}{g.evaluation_system_message_extra_mode3}"
                custom_user_message = f"{g.training_item_user_message_premable_mode3}"
            else:
                return resp.generate_response_with_data(f"Invalid update_messages_mode: {update_messages_mode}", 400)

        custom_system_message = None

        job_status = dataset_manager.process_location(
                        dataset_id=dataset_id,
                        local_path=server_path,
                        file_regexp=file_regexp,
                        max_items=max_items,
                        custom_system_message=custom_system_message,
                        custom_user_message=custom_user_message,
                        is_async=is_async,
                        is_ignore_existing=is_ignore_existing,
                        is_delete_persona=is_delete_persona)

        job_id = job_status["job_id"]

        store_dataset_manager(job_id, dataset_manager)

        return resp.generate_response_with_data(job_status, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/<dataset_type>/<dataset_id>/<job_id>', methods=['GET'])
@require_api_auth
def query_populate_dataset_job(dataset_type, dataset_id, job_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        logger.debug(f"dataset_id: {dataset_id}; dataset_type: {dataset_type}; job_id: {job_id}")

        if dataset_type == "from_actions":
            is_from_actions=True
        elif dataset_type == "from_files":
            is_from_actions=False        
        else:
            return resp.generate_response_with_data(f"Invalid dataset_type: {dataset_type}", 400)

        dataset_manager = get_dataset_manager(CLIENT_ID, job_id)
        if not dataset_manager:
            return resp.generate_response_with_data(f"Dataset manager not found for job: {job_id}", 404)

        job_status = dataset_manager.job_statuses.get(job_id, {})
        if not job_status:
            return resp.generate_response_with_data(f"Job not found: {job_id}", 404)

        return resp.generate_response_with_data(job_status, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/<dataset_type>', methods=['GET'])
@require_api_auth
def get_datasets(dataset_type):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        logger.debug(f"dataset_type: {dataset_type}")

        dataset_namespace_base = get_dataset_namespace_base_for_type(g.objectstore_ft_namespace_prefix, dataset_type)
        prefix = get_dataset_namespace_prefix(dataset_namespace_base)
        meta_suffix = get_dataset_meta_suffix()

        dataset_manager = get_dataset_manager(CLIENT_ID)
        objectstore_client = dataset_manager.get_objectstore_client()

        mappings = objectstore_client.get_mappings()

        datasets = []

        for mapping in mappings:
            if mapping['namespace_id'].startswith(prefix) and not mapping['namespace_id'].endswith(meta_suffix):
                dataset_item = {
                    "client_id": mapping["client_id"],
                    "namespace_id": mapping["namespace_id"],
                    "dataset_id": mapping["namespace_id"][len(prefix):]
                }
                datasets.append(dataset_item)

        response_json = {
            "status": "OK",
            "message": f"Retrieved {len(datasets)} datasets",
            "datasets": datasets,
            "current_time_ms": get_current_time_ms()
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/<dataset_type>/<dataset_id>', methods=['GET'])
@training_routes.route('/datasets/<dataset_type>/<dataset_id>/items/<item_id>', methods=['GET'])
@require_api_auth
def query_dataset(dataset_type, dataset_id, item_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        is_detail = request.args.get('detail', type=str_to_bool, default=False)

        page = request.args.get('page', default=1, type=int)
        count = request.args.get('count', default=10, type=int)

        logger.debug(f"dataset_id: {dataset_id}; dataset_type: {dataset_type}; item_id: {item_id}; page: {page}; count: {count}")

        if dataset_type == "from_actions":
            is_from_actions=True
        elif dataset_type == "from_files":
            is_from_actions=False        
        else:
            return resp.generate_response_with_data(f"Invalid dataset_type: {dataset_type}", 400)

        dataset_manager = get_dataset_manager(CLIENT_ID)

        content, remaining, meta_namespace, item_namespace = dataset_manager.query_dataset(
                        dataset_id=dataset_id,
                        item_id=item_id,
                        is_from_actions=is_from_actions,
                        is_detail=is_detail,
                        page=page,
                        count=count)

        message = f"Got {len(content)} items from dataset {dataset_id}.  There are {remaining} entries remaining"

        response_json = {
            "status": "OK",
            "message": message,
            "content": content,
            "dataset_id": dataset_id,
            "meta_namespace": meta_namespace,
            "item_namespace": item_namespace
        }

        if item_id:
            response_json["item_id"] = item_id
        # We care about the order in the response, for aesthetic reasons :)
        response_json.update({
            "count": count,
            "page": page,
            "remaining ": remaining,
            "current_time_ms ": get_current_time_ms()
        })

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/<dataset_type>/<source_dataset_id>/merge/<target_dataset_id>', methods=['POST'])
@require_api_auth
def merge_dataset(dataset_type, source_dataset_id, target_dataset_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        is_replace_existing = request.args.get('replace_existing', type=str_to_bool, default=False)

        dataset_manager = get_dataset_manager(CLIENT_ID)

        merge_status = dataset_manager.merge_into_dataset(dataset_type, source_dataset_id, target_dataset_id, is_replace_existing)

        return resp.generate_response_with_data(merge_status, 202)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/datasets/<dataset_type>/<dataset_id>', methods=['DELETE'])
@require_api_auth
def delete_dataset(dataset_type, dataset_id):

    CLIENT_ID, resp, _ = init_route(request)

    try:

        logger.debug(f"dataset_id: {dataset_id}; dataset_type: {dataset_type}")

        dataset_namespace_base = get_dataset_namespace_base_for_type(g.objectstore_ft_namespace_prefix, dataset_type)

        is_confirm = request.args.get('confirm', type=str_to_bool, default=False)
        if not is_confirm:
            return resp.generate_response_with_data("Missing required parameter: confirm=true", 400)

        meta_namespace = get_dataset_meta_namespace(dataset_namespace_base, dataset_id)
        item_namespace = get_dataset_namespace(dataset_namespace_base, dataset_id)

        manager = get_object_manager_for_files(CLIENT_ID)     # The type of manager doesn't matter here
        objectstore_client = manager.get_objectstore_client() # We just want the objectstore_client
        
        objectstore_client.clear_namespace(item_namespace)
        objectstore_client.clear_namespace(meta_namespace)

        response_json = {
            "status": "OK",
            "message": "Dataset cleared",
            "namespace_meta": meta_namespace,
            "namespace_items": item_namespace,
            "dataset_id": dataset_id,
            "current_time_ms": get_current_time_ms()
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/files', methods=['POST'])
@require_api_auth
def file_upload():

    CLIENT_ID, resp, _ = init_route(request)

    temp_file_path = None

    try:

        reqjson = get_reqjson(request)

        dataset_id = get_required_reqjson_val(reqjson, "dataset_id")
        dataset_type = get_required_reqjson_val(reqjson, "dataset_type")
        dataset_namespace_base = get_dataset_namespace_base_for_type(g.objectstore_ft_namespace_prefix, dataset_type)

        info = get_reqjson_val(reqjson, "info", None)
        additional_details = get_reqjson_val(reqjson, "additional_details", {})

        tag = get_reqjson_val(reqjson, "tag", None)     # This is tag to be *added* to file, not used in query

        manager = get_object_manager_for_files(CLIENT_ID)
        objectstore_client = manager.get_objectstore_client()
        openai_client_wrapper = manager.get_openai_client_wrapper()

        training_entry_meta_namespace = get_dataset_meta_namespace(dataset_namespace_base, dataset_id)
        training_entry_item_namespace = get_dataset_namespace(dataset_namespace_base, dataset_id)

        object_ids = objectstore_client.query_namespace(training_entry_meta_namespace, None)

        logger.debug(f"Retrieved list of {len(object_ids)} object IDs for tag {tag}")

        if not object_ids:
            return resp.generate_response_with_data("No data to process for tag: {tag}", 500)

        training_objects = []

        for object_id in object_ids:
            logger.debug(f"Processing object_id: {object_id}")
            this_training_obj = objectstore_client.retrieve_object(training_entry_item_namespace, object_id)
            if not this_training_obj:
                raise Exception(f"Unable to get object with ID {object_id}")
            logger.debug(f"Got object with object_id '{object_id}': {truncate_string(this_training_obj, 100)}")
            this_training_obj["messages"] = convert_pseudo_openai_training_entry(this_training_obj["messages"])
            #logger.debug(f"Got converted_messages: {this_training_obj['messages']}")

            training_objects.append(this_training_obj)

        openai_client = openai_client_wrapper.get_client()

        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp_file:

            temp_file_path = tmp_file.name
            logger.debug(f'Using tempfile: {temp_file_path}')
            for obj in training_objects:
                tmp_file.write(json.dumps(obj) + "\n")
            tmp_file.seek(0)
            openai_files_response = openai_client.files.create(file=Path(temp_file_path), purpose='fine-tune')

        fileobject_dict = dict_from_openai_object(openai_files_response)
        logger.debug(f"Got fileobject_dict: {fileobject_dict}")

        source_meta = {
            "content_meta_namespace": training_entry_meta_namespace,
            "content_object_namespace": training_entry_item_namespace,
            "content_object_ids": object_ids
        }

        file_meta = manager.create_object_meta(
                                tag,
                                fileobject_dict,
                                openai_files_response,
                                info,
                                additional_details,
                                source_meta)

        logger.debug(f"Built file_meta: {file_meta}")

        stored_item_id = manager.store_object_and_meta(fileobject_dict, file_meta, tag)

        message = f"Processing completed - {len(object_ids)} items processed, stored in object store as {stored_item_id}"

        response_json = {
            'status': 'OK',
            'message': message,
            'content_object_ids': object_ids,
            'dataset_id': dataset_id,
            'dataset_type': dataset_type,
            'tag': tag,
            'stored_file_id': stored_item_id,
            'stored_files_response': fileobject_dict,
            'namespace_files': manager.get_namespace_object(),
            'namespace_files_meta': manager.get_namespace_meta(),
            'current_time_ms': file_meta.get("meta_created_ms", get_current_time_ms())
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)

    finally:

        if temp_file_path:
            logger.debug(f"Deleting tempfile (if it exists): {temp_file_path}")
            try:
                os.remove(temp_file_path)
            except OSError:
                pass


@training_routes.route('/files/sync', methods=['POST'])
@require_api_auth
def files_sync():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        tag = get_arg(request, "tag", None)

        manager = get_object_manager_for_files(CLIENT_ID)

        return manager.sync_objects(resp, tag)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/files', methods=['GET'])
@training_routes.route('/files/<file_id>', methods=['GET'])
@require_api_auth
def file_query(file_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        include_deleted = request.args.get('include_deleted', type=str_to_bool, default=False)

        tag = get_arg(request, "tag", None)

        manager = get_object_manager_for_files(CLIENT_ID)

        object_ids_files_meta = manager.get_object_meta_id_list(tag, file_id)

        if file_id and not object_ids_files_meta:
            return resp.generate_response_with_data(f"File not found with id: {file_id}", 404)

        files = []

        for object_id in object_ids_files_meta:

            file_meta = manager.get_object_meta(object_id)
            if not file_meta:
                logger.error(f"Could not get file_meta for: {object_id}")
                continue;
            logger.debug(f"Found file: {file_meta}")

            if include_deleted:
                files.append(file_meta)
            else:
                if manager.is_object_marked_deleted(file_meta):
                    logger.debug(f"Ignoring file marked as deleted: {file_meta}")
                else:
                    files.append(file_meta)

        if len(files) == 0:
            return resp.generate_response_with_data("No files found", 404)

        current_time_ms = get_current_time_ms()
        message = f"Retrieved details of {len(files)} files"
        if tag:
            message+= f". Tag was: {tag}"

        response_json = {
            'status': 'OK',
            'message': message,
            'files': files,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/files/<file_id>', methods=['DELETE'])
@require_api_auth
def file_delete(file_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        if not file_id:
            raise ValueError("Missing required parameter: file_id")
 
        manager = get_object_manager_for_files(CLIENT_ID)
        openai_client_wrapper = manager.get_openai_client_wrapper()

        if not manager.object_exists(file_id):
            return resp.generate_response_with_data(f"File not found with id: {file_id}", 404)

        file_meta = manager.get_object_meta(file_id)
        if not file_meta:
            raise Exception(f"Unable to get file meta for: {file_id}!")

        if manager.is_object_marked_deleted(file_meta):
            raise ValueError(f"Can't delete file that is marked as deleted: {file_meta}")

        openai_deletion_status = openai_client_wrapper.delete_file(file_id)
        if not openai_deletion_status.deleted:
            logger.error(f"Got openai_deletion_status: {openai_deletion_status}")
            raise Exception(f"Unable to delete file in OpenAI: {file_meta['object_str']}!")

        manager.remove_object(file_id)
        manager.mark_object_deleted_from_objectstore(file_meta)
        manager.mark_object_deleted_from_openai(file_meta)
        manager.update_object_meta(file_meta)

        current_time_ms = get_current_time_ms()
        message = f"Removed file: {file_id}"

        response_json = {
            'status': 'OK',
            'message': message,
            'file': file_meta,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/jobs', methods=['POST'])
@require_api_auth
def job_create():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        reqjson = get_reqjson(request)

        file_id = get_required_reqjson_val(reqjson, "file_id")
        model_id = get_required_reqjson_val(reqjson, "model_id")

        n_epochs = get_reqjson_val(reqjson, "n_epochs", None)
        batch_size = get_reqjson_val(reqjson, "batch_size", None)
        learning_rate_multiplier = get_reqjson_val(reqjson, "learning_rate_multiplier", None)
        suffix = get_reqjson_val(reqjson, "suffix", None)

        info = get_reqjson_val(reqjson, "info", None)
        additional_details = get_reqjson_val(reqjson, "additional_details", {})

        tag = get_reqjson_val(reqjson, "tag", None)     # This is tag to be *added* to file, not used in query

        file_manager = get_object_manager_for_files(CLIENT_ID)

        if not file_manager.object_meta_exists(file_id):
            return resp.generate_response_with_data(f"No managed file meta exists for file_id: {file_id}", 404)

        file_meta = file_manager.get_object_meta(file_id)

        if file_manager.is_object_marked_deleted(file_meta):
            return resp.generate_response_with_data(f"Managed file is marked as deleted: {file_id}", 400)

        if not file_manager.object_exists(file_id):
            return resp.generate_response_with_data(f"No managed file object exists for file_id: {file_id}", 404)

        job_manager = get_object_manager_for_jobs(CLIENT_ID)

        objectstore_client = job_manager.get_objectstore_client()
        openai_client_wrapper = job_manager.get_openai_client_wrapper()

        openai_client = openai_client_wrapper.get_client()

        hyperparameters = {
            "n_epochs": n_epochs,
            "batch_size": batch_size,
            "learning_rate_multiplier": learning_rate_multiplier
        }
        hyperparameters = {k: v for k, v in hyperparameters.items() if v}

        additional_details["hyperparameters"] = hyperparameters
        if suffix:
            additional_details["suffix"] = suffix

        openai_jobs_response = openai_client.fine_tuning.jobs.create(
                        training_file=file_id,
                        validation_file=None,
                        model=model_id,
                        hyperparameters=hyperparameters,
                        suffix=suffix)

        jobobject_dict = dict_from_openai_object(openai_jobs_response)
        logger.debug(f"Got jobobject_dict: {jobobject_dict}")

        job_meta = job_manager.create_object_meta(
                                tag,
                                jobobject_dict,
                                openai_jobs_response,
                                info,
                                additional_details,
                                file_meta)

        logger.debug(f"Built job_meta: {job_meta}")

        stored_item_id = job_manager.store_object_and_meta(jobobject_dict, job_meta, tag)

        message = f"Processing completed - file '{file_id}' with model '{model_id}', stored as: {stored_item_id}"

        response_json = {
            'status': 'OK',
            'message': message,
            'file_id': file_id,
            'model_id': model_id,
            'tag': tag,
            'stored_job_id': stored_item_id,
            'stored_jobs_response': jobobject_dict,
            'namespace_jobs': job_manager.get_namespace_object(),
            'namespace_jobs_meta': job_manager.get_namespace_meta(),
            'current_time_ms': job_meta.get("meta_created_ms", get_current_time_ms())
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/jobs/sync', methods=['POST'])
@require_api_auth
def jobs_sync():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        tag = get_arg(request, "tag", None)

        manager = get_object_manager_for_jobs(CLIENT_ID)

        return manager.sync_objects(resp, tag)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/jobs', methods=['GET'])
@training_routes.route('/jobs/<job_id>', methods=['GET'])
@require_api_auth
def job_query(job_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        include_deleted = request.args.get('include_deleted', type=str_to_bool, default=False)

        tag = get_arg(request, "tag", None)

        manager = get_object_manager_for_jobs(CLIENT_ID)

        object_ids_jobs_meta = manager.get_object_meta_id_list(tag, job_id)

        if job_id and not object_ids_jobs_meta:
            return resp.generate_response_with_data(f"Job not found with id: {job_id}", 404)

        jobs = []

        for object_id in object_ids_jobs_meta:

            job_meta = manager.get_object_meta(object_id)
            if not job_meta:
                logger.error(f"Could not get job_meta for: {object_id}")
                continue;
            logger.debug(f"Found file: {job_meta}")

            if include_deleted:
                jobs.append(job_meta)
            else:
                if manager.is_object_marked_deleted(job_meta):
                    logger.debug(f"Ignoring job marked as deleted: {job_meta}")
                else:
                    jobs.append(job_meta)

        if len(jobs) == 0:
            return resp.generate_response_with_data("No jobs found", 404)

        current_time_ms = get_current_time_ms()
        message = f"Retrieved details of {len(jobs)} jobs"
        if tag:
            message+= f". Tag was: {tag}"

        response_json = {
            'status': 'OK',
            'message': message,
            'jobs': jobs,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/jobs/<job_id>', methods=['DELETE'])
@require_api_auth
def job_delete(job_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    # This does not delete the job from OpenAI, as there is no API support for this currently

    try:
 
        if not job_id:
            raise ValueError("Missing required parameter: job_id")
 
        manager = get_object_manager_for_jobs(CLIENT_ID)
        openai_client_wrapper = manager.get_openai_client_wrapper()

        if not manager.object_exists(job_id):
            return resp.generate_response_with_data(f"Job not found with id: {job_id}", 404)

        job_meta = manager.get_object_meta(job_id)
        if not job_meta:
            raise Exception(f"Unable to get job meta for: {job_id}!")

        if manager.is_object_marked_deleted(job_meta):
            raise ValueError(f"Can't delete job that is marked as deleted: {job_meta}")

        manager.remove_object(job_id)

        manager.mark_object_deleted_from_objectstore(job_meta)
        manager.mark_object_deleted_from_openai(job_meta)
        manager.update_object_meta(job_meta)

        current_time_ms = get_current_time_ms()
        message = f"Removed job: {job_id}"

        response_json = {
            'status': 'OK',
            'message': message,
            'job': job_meta,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/models/sync', methods=['POST'])
@require_api_auth
def models_sync():

    CLIENT_ID, resp, _ = init_route(request)

    try:

        tag = get_arg(request, "tag", None)
        is_presync = request.args.get('presync', type=str_to_bool, default=True)

        manager_jobs = get_object_manager_for_jobs(CLIENT_ID)
        manager_models = get_object_manager_for_models(CLIENT_ID)

        if is_presync:
            logger.debug(f"Pre-syncing jobs")
            manager_jobs.sync_objects(resp, tag)

        job_ids_meta = manager_jobs.get_object_ids_meta(tag)

        openai_client_wrapper = manager_models.get_openai_client_wrapper()

        job_ids_seen = []
        job_ids_processed = []
        job_ids_ignored = []
        job_ids_with_model_id = []
        job_ids_without_model_id = []
        model_meta_ids_processed = []
        model_meta_ids_ignored = []
        model_meta_ids_created = []
        model_meta_ids_existing = []
        model_ids_marked_deleted = []
        model_ids_updated = []

        for job_id_meta in job_ids_meta:

            logger.debug(f"Processing job meta id: {job_id_meta}")
            job_ids_seen.append(job_id_meta)

            job_meta = manager_jobs.get_object_meta(job_id_meta)
            logger.debug(f"Got job_meta: {job_meta}")

            if not job_meta:
                logger.error(f"Data consistency problem - {job_id_meta} obtained from manager_jobs.get_objects_meta could not be retrieved!")
                raise Exception(f"Unable to get file meta for object: {job_id_meta}")

            if manager_jobs.is_object_marked_deleted(job_meta):
                # Object marked deleted from openai- ignore
                logger.debug(f"Ignoring object marked as deleted: {job_id_meta}")
                job_ids_ignored.append(job_id_meta)
                continue

            job_ids_processed.append(job_id_meta)
            job_meta_object = job_meta.get("object", {})
            fine_tuned_model_id = job_meta_object.get("fine_tuned_model", None)

            if not fine_tuned_model_id:
                logger.debug(f"Ignoring object with no fine_tuned_model: {job_id_meta}")
                job_ids_without_model_id.append(job_id_meta)
                continue
            job_ids_with_model_id.append(job_id_meta)


            model_meta = None
            if manager_models.object_meta_exists(fine_tuned_model_id):
                model_meta = manager_models.get_object_meta(fine_tuned_model_id)

            if model_meta:
                logger.debug(f"Existing model_meta: {model_meta}")
                if manager_models.is_object_marked_deleted(model_meta):
                    logger.debug(f"Ignoring model marked as deleted: {model_meta}")
                    model_meta_ids_ignored.append(fine_tuned_model_id)
                    continue
            model_meta_ids_processed.append(job_id_meta)

            model, model_as_dict = openai_client_wrapper.get_model(fine_tuned_model_id)

            if model and not model_meta:
                model_meta = manager_models.create_object_meta(
                                    tag,
                                    model_as_dict,
                                    model,
                                    job_meta.get("info", None),
                                    job_meta.get("additional_details", {}),
                                    job_meta)
                model_meta_ids_created.append(fine_tuned_model_id)
                logger.debug(f"Created model_meta: {model_meta}")
            else:
                model_meta_ids_existing.append(fine_tuned_model_id)

            if not model:
                logger.warn(f"Unable to get fine_tuned_model with ID: {fine_tuned_model_id}")
                manager_models.mark_object_deleted_from_openai(model_meta)
                model_ids_marked_deleted.append(fine_tuned_model_id)
            else:
                manager_models.set_object_meta_object(model_meta, model_as_dict, model)

            logger.debug(f"Storing model_as_dict: {model_as_dict}")
            logger.debug(f"Storing model_meta: {model_meta}")

            logger.debug(f"namespace_models: {manager_models.get_namespace_object()}")
            logger.debug(f"namespace_models_meta: {manager_models.get_namespace_meta()}")

            stored_item_id = manager_models.store_object_and_meta(model_as_dict, model_meta, tag)
            model_ids_updated.append(stored_item_id)

        message = f"Managed model maintenance/query complete"
        if tag:
            message += " using tag: {tag}"

        response_json = {
            'status': 'OK',
            'message': message,
            'tag': tag,
            'namespace_models': manager_models.get_namespace_object(),
            'namespace_models_meta': manager_models.get_namespace_meta(),
            'counts': {
                "job_ids_seen": job_ids_seen,
                "job_ids_processed": job_ids_processed,
                "job_ids_ignored": job_ids_ignored,
                "job_ids_with_model_id": job_ids_with_model_id,
                "job_ids_without_model_id": job_ids_without_model_id,
                "model_meta_ids_processed": model_meta_ids_processed,
                "model_meta_ids_ignored": model_meta_ids_ignored,
                "model_meta_ids_created": model_meta_ids_created,
                "model_meta_ids_existing": model_meta_ids_existing,
                "model_ids_marked_deleted": model_ids_marked_deleted,
                "model_ids_updated": model_ids_updated
            }
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/models', methods=['GET'])
@training_routes.route('/models/<model_id>', methods=['GET'])
@require_api_auth
def model_query(model_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        include_deleted = request.args.get('include_deleted', type=str_to_bool, default=False)
        simple = request.args.get('simple', type=str_to_bool, default=False)

        tag = get_arg(request, "tag", None)

        manager = get_object_manager_for_models(CLIENT_ID)

        object_ids_models_meta = manager.get_object_meta_id_list(tag, model_id)

        if model_id and not object_ids_models_meta:
            return resp.generate_response_with_data(f"Model not found with id: {model_id}", 404)

        models = []

        for object_id in object_ids_models_meta:

            model_meta = manager.get_object_meta(object_id)
            if not model_meta:
                logger.error(f"Could not get model_meta for: {object_id}")
                continue;
            logger.debug(f"Found file: {model_meta}")

            if include_deleted:
                models.append(model_meta)
            else:
                if manager.is_object_marked_deleted(model_meta):
                    logger.debug(f"Ignoring model marked as deleted: {model_meta}")
                else:
                    models.append(model_meta)

        if len(models) == 0:
            return resp.generate_response_with_data("No models found", 404)

        current_time_ms = get_current_time_ms()
        message = f"Retrieved details of {len(models)} models"
        if tag:
            message+= f". Tag was: {tag}"

        models_return = models

        if simple:
            logger.debug(f"Returning SIMPLE view of models")
            models_return = []
            for model_meta in models:
                model_simple = {
                    "id": model_meta["id"],
                    "tag": model_meta["tag"],
                    "deleted_from_openai": model_meta["deleted_from_openai"],
                    "deleted_from_objectstore": model_meta["deleted_from_objectstore"],
                    "object": model_meta["object"],
                    "info": model_meta["info"],
                    "additional_details": model_meta["additional_details"],
                    "meta_created_ms": model_meta["meta_created_ms"]
                }
                job_meta = model_meta.get("source_meta")
                if job_meta:
                    model_simple["job_id"] = job_meta["id"]
                    job_meta_object = job_meta.get("object")
                    if job_meta_object:
                        model_simple["training_file_id"] = job_meta_object["training_file"]
                        model_simple["hyperparameters"] = job_meta_object["hyperparameters"]
                        model_simple["trained_tokens"] = job_meta_object["trained_tokens"]
                models_return.append(model_simple)

        response_json = {
            'status': 'OK',
            'message': message,
            'models': models_return,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/models/<model_id>', methods=['DELETE'])
@require_api_auth
def model_delete(model_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        if not model_id:
            raise ValueError("Missing required parameter: model_id")
 
        manager = get_object_manager_for_models(CLIENT_ID)
        openai_client_wrapper = manager.get_openai_client_wrapper()

        if not manager.object_exists(model_id):
            return resp.generate_response_with_data(f"Model not found with id: {model_id}", 404)

        model_meta = manager.get_object_meta(model_id)
        if not model_meta:
            raise Exception(f"Unable to get model meta for: {model_id}!")

        if manager.is_object_marked_deleted(model_meta):
            raise ValueError(f"Can't delete model that is marked as deleted: {model_meta}")

        openai_deletion_status = openai_client_wrapper.delete_model(model_id)
        if not openai_deletion_status.deleted:
            logger.error(f"Got openai_deletion_status: {openai_deletion_status}")
            raise Exception(f"Unable to delete model in OpenAI: {file_meta['object_str']}!")

        manager.remove_object(model_id)

        manager.mark_object_deleted_from_objectstore(model_meta)
        manager.mark_object_deleted_from_openai(model_meta)
        manager.update_object_meta(model_meta)

        current_time_ms = get_current_time_ms()
        message = f"Removed model_id: {model_id}"

        response_json = {
            'status': 'OK',
            'message': message,
            'model_id': model_meta,
            'current_time_ms': current_time_ms
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)


@training_routes.route('/files/resurrect/<file_id>', methods=['POST'])
@require_api_auth
def resurrect_file(file_id=None):

    CLIENT_ID, resp, _ = init_route(request)

    try:
 
        manager = get_object_manager_for_files(CLIENT_ID)

        file_meta = manager.get_object_meta(file_id)
        if not file_meta:
            raise Exception(f"Unable to get file meta for: {file_id}!")

        manager.mark_object_not_deleted(file_meta)
        manager.update_object_meta(file_meta)

        response_json = {
            'status': 'OK',
            'message': f"File resurrected: {file_id}",
            'file': file_meta,
            'current_time_ms': get_current_time_ms()
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as e:

        return resp.generate_response_with_exception(e)
