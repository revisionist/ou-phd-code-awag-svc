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
import re
import mimetypes
import time
import threading
import random

from datetime import datetime

from enum import Enum

from flask import current_app

from domestique.datetime import get_current_time_ms
from domestique.validation import Validator, NoiseLevel
from domestique.json import get_dict_from_dict_or_json_str
from domestique.text import truncate_string
from domestique.identifiers import generate_id, generate_shorter_id
from domestique.logging import log_exception

from .shared_resources import logger, get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_base_for_type
from .shared_resources import construct_openai_training_entry, construct_pseudo_openai_training_entry, convert_pseudo_openai_training_entry
from .shared_resources import validate_subset_percent


class DatasetManager:

    def __init__(self, namespace_base, objectstore_client, awagdata_client, flask_app=None):

        Validator().check_all(
            namespace_base=namespace_base,
            objectstore_client=objectstore_client,
            awagdata_client=awagdata_client)

        self.namespace_base = namespace_base
        self.objectstore_client = objectstore_client
        self.awagdata_client = awagdata_client
        self.flask_app = flask_app

        self.job_statuses = {}


    def get_namespace_base(self):

        return self.namespace_base


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def _is_include_item(self, item, is_exclude_agree, is_exclude_disagree):
    
        if item is None:
            return False

        classification_orig = item.get("classificationOrig")
        classification_new = item.get("classificationNew")

        is_agree = classification_new == classification_orig

        if is_exclude_agree and is_agree:
            return False

        if is_exclude_disagree and not is_agree:
            return False

        return True


    def construct_training_entry(self, item, training_item_system_message, training_item_user_message_premable=None):

        sent = datetime.utcnow().isoformat()

        item_id = generate_id()
        perspective_id = generate_shorter_id()
        classification_id = item["classificationName"]
        content = f"{sent}\n{item['bodyText']}"
        classification_desc = item["classificationDesc"]
        available_classifications = item["availableClassifications"]
        classification_orig = item["classificationOrig"]
        classification_new = item["classificationNew"]

        request = {
            "persona": None,
            "perspective": None,
            "items": []
        }

        id = {
            "itemId": item_id,
            "perspectiveId": perspective_id,
            "classificationId": classification_id
         }

        request["items"].append({
            "id": id,
            "content": content,
            "classification": {
                "description": classification_desc,
                "classifiedAs": classification_orig,
                "fromAvailableClassifications": available_classifications
            }
        })

        user_messages = []
        if training_item_user_message_premable:
            user_messages.append(training_item_user_message_premable)
        user_messages.append(request)

        if classification_new == classification_orig:

            evaluation_agreement = "AGREE"

            evaluation_text_a = f"I agree with the originally selected classification of '{classification_orig}' for classification '{classification_id}' as this is the most appropriate of the available classifications."
            evaluation_text_b = f"I agree with the selected classification '{classification_orig}' for '{classification_id}'."
            evaluation_text_c = f"I agree with the classification '{classification_orig}' - it seems the closest fit of the alternatives."
            evaluation_text_d = f"I agree with '{classification_orig}' as the classification for '{classification_id}'"
            evaluation_text_e = f"I agree with the selected classification of '{classification_orig}' for '{classification_id}' as this seems to be the closest fit."

        else:

            evaluation_agreement = "DISAGREE"

            evaluation_text_a = f"I disagree with the originally selected classification of '{classification_orig}' for classification '{classification_id}' - I would have chosen '{classification_new}' instead."
            evaluation_text_b = f"I don't agree with the originally selected classification of '{classification_orig}' for '{classification_id}' - I would have selected '{classification_new}' instead given the available options of {available_classifications}."
            evaluation_text_c = f"I disagree with the classification '{classification_orig}' for '{classification_id}' - I would have gone with '{classification_new}' instead as it seems a better fit."
            evaluation_text_d = f"I disagree that '{classification_orig}' is the best classification for '{classification_id}' - given the available options, I would instead have chosen '{classification_new}'"
            evaluation_text_e = f"I disagree with the originally selected classification of '{classification_orig}' for classification '{classification_id}' - I would have selected '{classification_new}' from the available options of {available_classifications}."

        evaluation_texts = [evaluation_text_a, evaluation_text_b, evaluation_text_c, evaluation_text_d, evaluation_text_e]
        random_evaluation_text = random.choice(evaluation_texts)

        response = {
            "id": {
                "itemId": item_id,
                "perspectiveId": perspective_id,
                "classificationId": classification_id
            },
            "evaluatedSelection": classification_orig,
            "evaluationAgreement": evaluation_agreement,
            "evaluationText": random_evaluation_text
        },

        return construct_pseudo_openai_training_entry(training_item_system_message, user_messages, response)


    def _sanitise_filename(self, filename):

        if not filename:
            return ""

        sanitised = filename.rsplit('.', 1)[0]
        sanitised = sanitised.replace(' ', '_').replace('\t', '_')
        sanitised = re.sub(r'[^a-zA-Z0-9.\~\-_\+\:\|\$\^]', '', sanitised)
        sanitised = sanitised.lower()

        return sanitised


    def _construct_training_item_id(self, filename):

        Validator().check(["filename"], filename=filename)

        return f"{self._sanitise_filename(filename)}"


    def _construct_actions_training_item_id(self, item_id, classification_name):

        Validator().check(["item_id", "classification_name"], item_id=item_id, classification_name=classification_name)

        return f"{item_id}~{classification_name}"


    def _remove_existing_training_item(self, item_id, item_meta_namespace, item_object_namespace):

        Validator().check_all(item_id=item_id, item_meta_namespace=item_meta_namespace, item_object_namespace=item_object_namespace)

        objectstore_client = self.get_objectstore_client()

        if not objectstore_client.object_exists(item_meta_namespace, item_id):
            logger.debug(f"Object meta with id '{item_id}' does not exist in namespace: {item_meta_namespace}")
            return

        objectstore_client.delete_object(item_object_namespace, item_id)

        return


    def _store_training_item(self, item_meta, item, item_meta_namespace, item_object_namespace):

        Validator().check_all(item_meta=item_meta, item=item, item_meta_namespace=item_meta_namespace, item_object_namespace=item_object_namespace)

        objectstore_client = self.get_objectstore_client()

        logger.debug(f"Storing meta: {item_meta}")
        stored_object_id = objectstore_client.store_object(item_meta_namespace, item_meta["id"], None, item_meta)
        objectstore_client.store_object(item_object_namespace, stored_object_id, None, item)

        return stored_object_id


    def _validate_json_file(self, file_path):

        try:
            with open(file_path, 'r', errors='replace') as file:
                json.load(file)
            return True
        except json.JSONDecodeError:
            return False


    def _process_file(self, dataset_id, file_directory, file_name, job_status=None, is_ignore_existing=False, custom_system_message=None, custom_user_message=None, is_delete_persona=False):

        Validator().check(["dataset_id", "file_directory", "file_name"],
            dataset_id=dataset_id, file_directory=file_directory, file_name=file_name, is_ignore_existing=is_ignore_existing, is_delete_persona=is_delete_persona)

        if not job_status:
            raise ValueError(f"Missing job_status!")

        file_path = os.path.join(file_directory, file_name)

        if not os.path.isfile(file_path) or not os.access(file_path, os.R_OK):
            raise ValueError(f"Invalid or inaccessible file: {file_path}")

        #if 'text' not in mimetypes.guess_type(file_path)[0]:
        #    job_status["files_remaining"] -= 1
        #    job_status["files_ignored"] += 1
        #    return 0, 1

        if not self._validate_json_file(file_path):
            raise ValueError(f"File contains invalid JSON: {file_path}")

        namespace_base = get_dataset_namespace_base_for_type(self.namespace_base, "from_files")
        item_meta_namespace = get_dataset_meta_namespace(namespace_base, dataset_id)
        item_object_namespace = get_dataset_namespace(namespace_base, dataset_id)
        logger.debug(f"Got item_meta_namespace: {item_meta_namespace}")
        logger.debug(f"Got item_object_namespace: {item_object_namespace}")

        training_item_id = self._construct_training_item_id(file_name)
        logger.debug(f"Got training_item_id: {training_item_id}")

        if is_ignore_existing:
            if self.objectstore_client.object_exists(item_meta_namespace, training_item_id):
                object_meta = self.objectstore_client.retrieve_object(item_meta_namespace, training_item_id)
                if object_meta.get("deleted_from_objectstore", False) or object_meta.get("deleted_from_openai", False):
                    logger.debug(f"Existing entry marked as deleted so will not skip: {training_item_id}")
                    pass
                else:
                    # Object exists and is not marked as deleted, skip processing
                    logger.debug(f"Skipping existing entry: {training_item_id}")
                    job_status["files_remaining"] -= 1
                    job_status["files_ignored"] += 1
                    return 0, 1

        with open(file_path, 'r', errors='replace') as infile:
            item_json = json.load(infile)

        logger.debug(f"Got item_json: {item_json}")

        if not "messages" in item_json:
            raise ValueError(f"File JSON does not contain messages: {file_path}\n{item_json}")

        messages = item_json["messages"]

        if is_delete_persona:
            # Process messages to remove persona where applicable
            for message in messages:
                if message["role"] == "user" and isinstance(message["content"], dict):
                    message["content"].pop("persona", None)
            logger.debug(f"Processed item_json for persona deletion: {item_json}")

        if custom_user_message:
            logger.debug(f"Using custom user message: {custom_user_message}")
            # Update first instance of user message with custom content
            for message in item_json["messages"]:
                if message["role"] == "user":
                    message["content"] = custom_user_message
                    break

        if custom_system_message:
            logger.debug(f"Using custom system message: {custom_system_message}")
            # Update first instance of system message with custom content
            for message in converted_messages:
                if message["role"] == 'system':
                    message["content"] = custom_system_message
                    break

        # Convert any pseudo-messages, which may have a non-string 'content'
        converted_messages = convert_pseudo_openai_training_entry(messages)
        logger.debug(f"Got converted_messages: {converted_messages}")

        item_meta = {
            "id": training_item_id,
            "dataset_id": dataset_id,
            "source_directory": file_directory,
            "source_file": file_name,
            "item_namespace": item_object_namespace,
            "meta_created_ms": get_current_time_ms()
        }

        item_json["messages"] = converted_messages

        item_counter = 0

        #self._remove_existing_training_item(training_item_id, item_meta_namespace, item_object_namespace)
        self._store_training_item(item_meta, item_json, item_meta_namespace, item_object_namespace)

        job_status["files_processed"] += 1
        job_status["files_remaining"] -= 1

        if job_status["files_remaining"] == 0:
            job_status["status"] = "COMPLETED"

        return 1, 0


    def process_location(self, dataset_id, local_path, file_regexp, max_items, custom_system_message=None, custom_user_message=None, is_async=False, is_ignore_existing=False, is_delete_persona=False):

        Validator().check(["dataset_id", "local_path"], dataset_id=dataset_id, local_path=local_path, is_async=is_async, is_delete_persona=is_delete_persona)

        if not os.path.isdir(local_path) or not os.access(local_path, os.R_OK):
            raise ValueError(f"Invalid or unreadable local_path: {local_path}")

        job_id = generate_id()

        files_to_process = len([f for f in os.listdir(local_path) if os.path.isfile(os.path.join(local_path, f)) and (file_regexp is None or re.match(file_regexp, f))])

        job_status = {
            "job_id": job_id,
            "status": "INITIATED",
            "message": f"Initialised processing with job_id: {job_id}",
            "dataset_id": dataset_id,
            "local_path": local_path,
            "file_regexp": file_regexp,
            "max_items": max_items,
            "files_to_process": files_to_process,
            "files_processed": 0,
            "files_ignored": 0,
            "files_remaining": files_to_process
        }
        self.job_statuses[job_id] = job_status

        def process_files():

            nonlocal job_status

            with self.flask_app.app_context():  # So we can use context-dependent features such as logging

                try:

                    time.sleep(0.1) # Allow short time for calling function to return initial job_status
                    job_status["status"] = "PROCESSING"

                    logger.debug(f"Started process_files for local_path: {local_path}")

                    max_files_reached = False

                    for file_name in sorted(os.listdir(local_path)):

                        if max_items > 0 and (max_files_reached or job_status["files_processed"] == max_items):
                            if not max_files_reached:
                                logger.warning(f"Reached max_items limit ({max_items}), additional files will be ignored")
                                max_files_reached = True
                            logger.debug(f"Ignoring file (limit): {file_name}")
                            job_status["files_ignored"] += 1
                            continue

                        if file_regexp and not re.match(file_regexp, file_name):
                            logger.debug(f"Ignoring file (regexp): {file_name}")
                            job_status["files_ignored"] += 1
                            continue

                        logger.debug(f"Processing file: {file_name}")

                        self._process_file(dataset_id, local_path, file_name, job_status, is_ignore_existing, custom_system_message, custom_user_message, is_delete_persona)

                        logger.debug(f"Done: {file_name}")

                    logger.debug(f"Completed process_files for local_path: {local_path}")
            
                    job_status["message"] = f"Completed processing of {job_status['files_processed']} files. Ignored {job_status['files_ignored']} files (non-matching or invalid)."
                    job_status["status"] = "COMPLETE"

                except Exception as e:

                    msg = f"Error in process_files for location: '{local_path}': {e}"
                    job_status["status"] = "ERROR"
                    job_status["message"] = msg
                    logger.error(msg)
                    log_exception(self.objectstore_client.client_id, e, include_traceback=True)

                self.job_statuses[job_id] = job_status

        if is_async:

            logger.debug(f"Started process_files...")
            thread = threading.Thread(target=process_files)
            thread.start()

        else:

            process_files()

        return self.job_statuses.get(job_id)


    def process_classification_actions(self, dataset_id, tag_source, training_item_system_message, item_id=None, classifications=[], last_n_hours=None, subset_tag=None, subset_percent=None, is_async=False, is_ignore_existing=False, is_exclude_agree=False, is_exclude_disagree=False, training_item_user_message_premable=None):

        Validator().check(["dataset_id", "tag_source", "training_item_system_message"], dataset_id=dataset_id, tag_source=tag_source,
                    training_item_system_message=training_item_system_message,
                    item_id=item_id, classifications=classifications, last_n_hours=last_n_hours,
                    is_exclude_agree=is_exclude_agree, is_exclude_disagree=is_exclude_disagree,
                    is_async=is_async)

        if subset_percent is not None:
            subset_percent = validate_subset_percent(subset_percent)
            if subset_tag is None:
                raise ValueError("Missing subset_tag parameter")

        job_id = generate_id()

        job_status = {
            "job_id": job_id,
            "status": "INITIATED",
            "message": f"Initialised processing with job_id: {job_id}",
            "dataset_id": dataset_id,
            "tag_source": tag_source,
            "item_id": item_id,
            "classifications": classifications,
            "last_n_hours": last_n_hours,
            "subset_tag": subset_tag,
            "subset_percent": subset_percent,
            "is_exclude_agree": is_exclude_agree,
            "is_exclude_disagree": is_exclude_disagree,
            "is_async": is_async,
            "stored_items": []
        }
        self.job_statuses[job_id] = job_status

        def process_actions():

            nonlocal job_status

            with self.flask_app.app_context():  # So we can use context-dependent features such as logging

                try:

                    time.sleep(0.1) # Allow short time for calling function to return initial job_status
                    job_status["status"] = "PROCESSING"

                    logger.debug(f"Started process_actions for tag_source: {tag_source}")

                    page = 1
                    count = 20

                    namespace_base = get_dataset_namespace_base_for_type(self.namespace_base, "from_actions")
                    item_meta_namespace = get_dataset_meta_namespace(namespace_base, dataset_id)
                    item_object_namespace = get_dataset_namespace(namespace_base, dataset_id)

                    while True:
                    
                        logger.debug(f"Processing page {page} (count: {count})")

                        data, remaining = self.awagdata_client.fetch_classification_actions(tag_source, page, count, item_id, classifications, last_n_hours, subset_tag, subset_percent)

                        if not data:
                            if page == 1:
                                logger.warn(f"No data to process for tag: {tag_source}")
                                break
                            else:
                                logger.debug(f"No more data at page {page} (count: {count})")
                                break

                        for item in data:

                            this_item_id = item["itemId"]

                            if not self._is_include_item(item, is_exclude_agree, is_exclude_disagree):
                                logger.debug(f"Excluding item based on exclusison settings: {this_item_id}")
                                continue

                            this_classification_name = item["classificationName"]
                            training_item_id = self._construct_actions_training_item_id(this_item_id, this_classification_name)

                            item_json = self.construct_training_entry(item, training_item_system_message, training_item_user_message_premable)
                            logger.debug(f"Constructed item_json for item {this_item_id} and classification '{this_classification_name}':\n{item_json}")

                            item_meta = {
                                "id": training_item_id,
                                "source_tag": tag_source,
                                "source_item_id": this_item_id,
                                "source_classification_name": this_classification_name,
                                "item_namespace": item_object_namespace,
                                "meta_created_ms": get_current_time_ms()
                            }

                            #self._remove_existing_training_item(this_item_id, item_meta_namespace, item_object_namespace)
                            self._store_training_item(item_meta, item_json, item_meta_namespace, item_object_namespace)

                            job_status["stored_items"].append(training_item_id)

                        if remaining < 1:
                            logger.debug(f"No more data remaining after page {page} (count: {count})")
                            break

                        page += 1

                    logger.debug(f"Completed process_actions for tag_source: {tag_source}")
            
                    job_status["message"] = f"Completed processing of {len(job_status['stored_items'])} items."
                    job_status["status"] = "COMPLETE"

                except Exception as e:

                    msg = f"Error in process_actions for tag_source: '{tag_source}': {e}"
                    job_status["status"] = "ERROR"
                    job_status["message"] = msg
                    logger.error(msg)
                    log_exception(self.objectstore_client.client_id, e, include_traceback=True)

                self.job_statuses[job_id] = job_status

        if is_async:

            logger.debug(f"Started process_actions...")
            thread = threading.Thread(target=process_actions)
            thread.start()

        else:

            process_actions()

        return self.job_statuses.get(job_id)


    def query_dataset(self, dataset_id, item_id=None, is_from_actions=False, is_detail=False, page=1, count=10):

        Validator().check(["dataset_id"], dataset_id=dataset_id,
                    item_id=item_id, is_from_actions=is_from_actions, is_detail=is_detail,
                    page=page, count=count)

        if is_from_actions:
            namespace_base = get_dataset_namespace_base_for_type(self.namespace_base, "from_actions")
        else:
            namespace_base = get_dataset_namespace_base_for_type(self.namespace_base, "from_files")

        item_meta_namespace = get_dataset_meta_namespace(namespace_base, dataset_id)
        item_object_namespace = get_dataset_namespace(namespace_base, dataset_id)

        objectstore_client = self.get_objectstore_client()

        total_items = 1
        end_index = 1
        item_meta = None
        item_meta_ids = []
        if item_id:
            if not objectstore_client.object_exists(item_meta_namespace, item_id):
                return [], 0, item_meta_namespace, item_object_namespace
            item_meta = objectstore_client.retrieve_object(item_meta_namespace, item_id)
            item_meta_ids = [item_id]
            logger.debug(f"Using single item_meta ID: {item_meta_ids}")
        else:
            all_meta_ids = objectstore_client.query_namespace(item_meta_namespace, None)
            logger.debug(f"Retrieved list of {len(all_meta_ids)} all_meta_ids IDs from object store")
            if count < 1:
                logger.debug(f"Passed count is {count} - will return all items")
                item_meta_ids = all_meta_ids
                end_index = len(item_meta_ids) - 1
                page = 1
            else:
                total_items = len(all_meta_ids)
                start_index = (page - 1) * count
                end_index = start_index + count
                item_meta_ids = all_meta_ids[start_index:end_index]
            logger.debug(f"Using paginated list of {len(item_meta_ids)} item_meta IDs")

        content = []
        item_count = 0

        for item_meta_id in item_meta_ids:

            meta, meta_id, meta_revision_id = objectstore_client.retrieve_object_with_details(item_meta_namespace, item_meta_id)

            content_item = {
                "id": meta_id,
            }

            if is_from_actions:
                content_item.update({
                    "source_tag": meta.get("source_tag"),
                    "source_item_id": meta.get("source_item_id"),
                    "source_classification_name": meta.get("source_classification_name")
                })
            else:
                content_item.update({
                    "source_directory": meta.get("source_directory"),
                    "source_file": meta.get("source_file"),
                })

            if is_detail:
                if not objectstore_client.object_exists(item_object_namespace, meta_id):
                    logger.error(f"Failed to find expected item {this_item_id} in namespace: {item_object_namespace}")
                    logger.error(f"Was processing item_meta: {meta}")
                    continue
                this_item = objectstore_client.retrieve_object(item_object_namespace, meta_id)
                logger.debug(f"Got item with id '{meta_id}': {truncate_string(this_item, 100)}")
                content_item.update({
                    "item_content": this_item.get("messages", []),
                    "revision": meta_revision_id,
                    "meta_created_ms": meta.get("meta_created_ms", 0)
                })

            content.append(content_item)

        remaining = max(0, total_items - end_index)

        count = len(content)

        logger.debug(f"Got {item_count} items from {len(item_meta_ids)} meta entries in dataset {dataset_id}.  There are {remaining} entries remaining")

        return content, remaining, item_meta_namespace, item_object_namespace


    def merge_into_dataset(self, dataset_type, source_dataset_id, target_dataset_id, is_replace_existing):

        Validator().check(["dataset_type", "source_dataset_id", "target_dataset_id"],
            dataset_type=dataset_type, source_dataset_id=source_dataset_id, target_dataset_id=target_dataset_id, is_replace_existing=is_replace_existing)

        objectstore_client = self.objectstore_client
        namespace_base = get_dataset_namespace_base_for_type(self.namespace_base, dataset_type)

        source_entry_meta_namespace = get_dataset_meta_namespace(namespace_base, source_dataset_id)
        source_entry_item_namespace = get_dataset_namespace(namespace_base, source_dataset_id)
        target_entry_meta_namespace = get_dataset_meta_namespace(namespace_base, target_dataset_id)
        target_entry_item_namespace = get_dataset_namespace(namespace_base, target_dataset_id)

        source_meta_ids = objectstore_client.query_namespace(source_entry_meta_namespace, None)

        entries_seen = 0
        entries_copied = 0
        entries_already_present_in_target = 0
        entries_ignored = 0

        def copy_item(item_id):

            logger.debug(f"Copying item with ID: {item_id}")

            items_copied = 0

            source_meta = objectstore_client.retrieve_object(source_entry_meta_namespace, item_id)
            logger.debug(f"Got source_meta: {source_meta}")

            if objectstore_client.object_exists(source_entry_item_namespace, item_id):
                logger.debug(f"Copying item: {item_id}")
                source_item = objectstore_client.retrieve_object(source_entry_item_namespace, item_id)
                logger.debug(f"Got source_item: {source_item}")
                objectstore_client.store_object(target_entry_meta_namespace, item_id, None, source_meta)
                objectstore_client.store_object(target_entry_item_namespace, item_id, None, source_item)
                items_copied += 1
            else:
                logger.warn(f"Did not find item: {item_id}!")

            return items_copied

        for source_meta_id in source_meta_ids:

            if not objectstore_client.object_exists(source_entry_meta_namespace, source_meta_id):
                # Should not happen, but check anyway
                logger.debug(f"No existing meta with ID: {source_meta_id}")
                entries_ignored += 1
                continue
            logger.debug(f"Source meta exists with ID: {source_meta_id}")

            source_meta = objectstore_client.retrieve_object(source_entry_meta_namespace, source_meta_id)
            logger.debug(f"Processing source_meta: {source_meta}")
            entries_seen += 1

            if source_meta.get("deleted_from_objectstore", False):
                logger.debug(f"Source meta marked as deleted so will not copy: {source_meta_id}")
                entries_ignored += 1
                continue

            entry_items_copied = 0

            if not objectstore_client.object_exists(target_entry_meta_namespace, source_meta_id):
                logger.debug(f"Entry NOT present in target for: {source_meta_id}")
                entry_items_copied = copy_item(source_meta_id)
                entries_copied += 1
            else:
                logger.debug(f"Entry ALREADY present in target for: {source_meta_id}")
                entries_already_present_in_target += 1
                if is_replace_existing:
                    entry_items_copied = copy_item(source_meta_id)
                    entries_copied += 1
                else:
                    target_meta = objectstore_client.retrieve_object(target_entry_meta_namespace, source_meta_id)
                    if target_meta.get("deleted_from_objectstore", False):
                        entry_items_copied = copy_item(source_meta_id)
                        entries_copied += 1
                    else:
                        logger.debug(f"Target meta exists and is not marked deleted so ignoring: {target_meta}")
                        entries_ignored += 1

            logger.debug(f"Copied {entry_items_copied} items for entry {source_meta_id}")

        logger.debug(f"Source processing complete")

        merge_status = {
            "status": "OK",
            "source_dataset_id": source_dataset_id,
            "target_dataset_id": target_dataset_id,
            "counts": {
                "entries_seen": entries_seen,
                "entries_copied": entries_copied,
                "entries_already_present_in_target": entries_already_present_in_target,
                "entries_ignored": entries_ignored
            },
            "message": f"Merge complete for {source_dataset_id} to {target_dataset_id}"
        }

        return merge_status, 200
