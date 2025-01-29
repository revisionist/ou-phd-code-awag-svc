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
import time
import random
import threading

from datetime import datetime
from dateutil import parser
from enum import Enum
from zoneinfo import ZoneInfo

from flask import current_app

from domestique.datetime import get_current_time_ms
from domestique.validation import Validator, NoiseLevel
from domestique.json import get_dict_from_dict_or_json_str
from domestique.text import truncate_string
from domestique.identifiers import generate_id
from domestique.logging import log_exception

from .shared_resources import logger, get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_base_for_type
from .shared_resources import generate_timestamp_with_ms, write_json_file
from .shared_resources import validate_persona, validate_subset_percent, get_likert_label
from .shared_resources import validate_mode1_evaluation_result, validate_mode2_mode3_evaluation_result

from .awag_evaluation_request_generator import AwAgEvaluationRequestGenerator


class AwAgEvaluationProcessor:

    def __init__(self,
            client_id,
            openai_client,
            evaluation_system_message_common,
            evaluation_system_message_extra,
            evaluation_result_schema,
            evaluation_user_messages,
            mode="mode1",
            evaluation_request_schema=None,
            default_model=None,
            awagdata_client=None,
            trace_file_path=None,
            flask_app=None):

        Validator().check_all(
            client_id=client_id,
            openai_client=openai_client,
            evaluation_system_message_common=evaluation_system_message_common,
            evaluation_system_message_extra=evaluation_system_message_extra,
            evaluation_user_messages=evaluation_user_messages,
            evaluation_result_schema=evaluation_result_schema)

        if mode == "mode1":
            if not evaluation_request_schema:
                raise ValueError("evaluation_request_schema is required for mode1")
            logger.debug("Init for mode1")
        elif mode == "mode2":
            logger.debug("Init for mode2")
        elif mode == "mode3":
            logger.debug("Init for mode3")
        else:
            raise ValueError(f"Invalid mode: {mode}")

        self.client_id = client_id
        self.mode = mode
        self.openai_client = openai_client
        self.awagdata_client = awagdata_client
        self.evaluation_system_message_common = evaluation_system_message_common
        self.evaluation_system_message_extra = evaluation_system_message_extra
        self.evaluation_request_schema = evaluation_request_schema
        self.evaluation_result_schema = evaluation_result_schema
        self.evaluation_user_messages = evaluation_user_messages
        self.default_model = default_model
        self.trace_file_path = trace_file_path
        self.flask_app = flask_app

        self.job_statuses = {}


    def get_namespace_base(self):

        return self.namespace_base


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def  _write_trace(self, prefix, mode, content, evaluation_results, info_json):

       if self.trace_file_path:
       
            if not os.path.exists(self.trace_file_path) or not os.access(self.trace_file_path, os.W_OK):
                logger.error(f"Unable to write trace to path: {self.trace_file_path:}.")
                return
       
            file_prefix = f"{prefix}_{mode}_{generate_timestamp_with_ms()}"
            write_json_file(self.trace_file_path, f"{file_prefix}_request.json", content)
            write_json_file(self.trace_file_path, f"{file_prefix}_response.json", evaluation_results)
            write_json_file(self.trace_file_path, f"{file_prefix}_info.json", info_json)


    def _perform_evaluation(self, messages, model, tools, tool_choice, openai_params={}):

        #logger.debug(f"Performing evaluation with model: {model}.  Messages:\n{messages}")
        logger.debug(f"Performing evaluation with model: {model}.")

        get_evaluations_response, info_json = self.openai_client.run_chat_completions(
                                    messages=messages,
                                    model=model,
                                    tools=tools,
                                    tool_choice=tool_choice,
                                    openai_params=openai_params)

        resp_message = get_evaluations_response.message
        tool_calls = resp_message.tool_calls

        finish_reason = get_evaluations_response.finish_reason

        if not tool_calls:
            ex_msg = f"Did not get tool_calls from OpenAI API response: {get_evaluations_response}"
            logger.error(ex_msg)
            logger.error(f"info_json: {info_json}")
            raise Exception(ex_msg)

        function = tool_calls[0].function
        evaluations_raw = function.arguments
        evaluations_obj = get_dict_from_dict_or_json_str(evaluations_raw)
        result_items = evaluations_obj.get("resultItems")
        logger.debug(f"Got result_items: {result_items}")

        # Additional information so we can record this
        info_json["additional_query_info"] = {
            "tools": tools,
            "messages": messages,
            "finish_reason": finish_reason
        }

        return result_items, info_json


    def get_evaluation(self, eval_request, model=None, is_use_request_schema=False, openai_params={}):

        Validator().check_all(noise_level=NoiseLevel.SILENT, eval_request=eval_request)

        if model is None:
            model=self.default_model

        logger.debug(f"Getting evaluation for request...: {truncate_string(eval_request, 100)}")

        if not model:
            raise ValueError("No model supplied to get_evaluation")
        else:
            logger.debug(f"Using model: {model}")

        try:

            system_message = f"{self.evaluation_system_message_common}\n{self.evaluation_system_message_extra}"
            messages = self.openai_client.append_system_message(system_message)

            if is_use_request_schema:
                logger.debug("Appending evaluation_request_schema")
                self.openai_client.append_system_message(f"{self.evaluation_request_schema}", messages)

            evaluation_user_messages = self.evaluation_user_messages.copy()
            for evaluation_user_message in evaluation_user_messages:
                if evaluation_user_message:
                    self.openai_client.append_user_message(evaluation_user_message, messages)
            self.openai_client.append_user_message(f"{eval_request}", messages)

            tools = [self.openai_client.get_tools_json_from_function_schema(self.evaluation_result_schema)]
            tool_choice = self.openai_client.get_tool_choice_json("get_evaluations")

            result_items, info_json = self._perform_evaluation(messages, model, tools, tool_choice, openai_params)

            self._write_trace(f"eval", self.mode, eval_request, result_items, info_json)

            return result_items, info_json

        except Exception as err:

            logger.error(f"Got Exception in get_evaluation: {err}")
            logger.error(f"Was processing eval_request: {eval_request}")
            return None, None


    def run_evaluations(self, tag_source, tags_dest, openai_model, persona, perspectives, items_to_process, openai_params={}, is_exclude_existing=True, subset_tag=None, subset_percent=None, is_most_recent=False, last_n_hours=None, by_uuid=None, is_async=False, is_dry_run=False, lightweight_mode=True):

        '''
        This code is a replication of evaluation processing code form the AwAg Java application; unfortunately
        this means it is quite complex.  The Java version started with the original 'mode1' implementation, which
        is able to create a compound evaluation request that combines multiple perspectives, classifications and
        items into one OpenAI query (with the original intent being efficiency of prompt tokens).  Modes 2 and 3
        followed, to present OpenAI with a more cleanly understood query structure with each item being presented
        in a more flat manner - also using different names for the benefit of OpenAI's processing.  As a result we
        have to take stored evaluation items of a specific structure and restructure them according to mode.
        Additionally, the feaures that record evaluation results are different from the original Java, because not
        all information is available in the same format.  On the other hand, by porting the functionality to this
        Python app, we are able to add more information, better track jobs and make easier test changes.
        '''

        Validator().check(["tag_source", "tags_dest", "openai_model", "persona", "perspectives", "items_to_process"],
                    tag_source=tag_source, tags_dest=tags_dest, openai_model=openai_model,
                    persona=persona, perspectives=perspectives, items_to_process=items_to_process,
                    is_exclude_existing=is_exclude_existing, subset_tag=subset_tag, subset_percent=subset_percent,
                    is_most_recent=is_most_recent, last_n_hours=last_n_hours, is_async=is_async, is_dry_run=is_dry_run, lightweight_mode=lightweight_mode)

        if self.awagdata_client is None:
            raise ValueError("Method run_evaluations requires awagdata_client to be set")

        mode = self.mode

        if subset_tag is not None:
            if subset_percent is None:
                raise ValueError("Missing subset_percent parameter")
            subset_percent = validate_subset_percent(subset_percent)

        persona_id, persona_name = validate_persona(persona)

        job_id = generate_id()

        # Only mode1 conforms to the Evaluation Request Schema
        if mode == "mode1":
            if lightweight_mode:
                logger.info(f"Running evaluations in {mode} LIGHTWEIGHT - will NOT use Evaluation Request Schema in OpenAI calls")
                is_use_request_schema=False
            else:
                logger.info(f"Running evaluations in {mode} - will use Evaluation Request Schema in OpenAI calls")
                is_use_request_schema=True
        else:
            logger.info(f"Running evaluations in {mode} - will NOT use Evaluation Request Schema in OpenAI calls")
            is_use_request_schema=False

        if not isinstance(tags_dest, list) or not tags_dest:
            raise ValueError("tags_dest must be a non-empty list")

        if is_exclude_existing:
            # Exclude existing based on the FIRST item in tags_dest
            exclude_tag = tags_dest[0]
        else:
            exclude_tag = None

        job_status = {
            "job_id": job_id,
            "status": "INITIATED",
            "message": f"Initialised processing for '{persona_name}' with job_id: {job_id}",
            "processed_items": 0,
            "remaining": -1,
            "init_remaining": -1,
            "items_to_process": items_to_process,
            "usage": {
                "completion_tokens": 0,
                "prompt_tokens": 0,
                "total_tokens": 0
            },
            "mode": mode,
            "is_use_request_schema": is_use_request_schema,
            "tag_source": tag_source,
            "tags_dest": tags_dest,
            "is_exclude_existing": is_exclude_existing,
            "exclude_tag": exclude_tag,
            "openai_model": openai_model,
            "eval_info": [],
            "persona": persona,
            "subset_tag": subset_tag,
            "subset_percent": subset_percent,
            "is_most_recent": is_most_recent,
            "last_n_hours": last_n_hours,
            "persona_id": persona_id,
            "persona_name": persona_name,
            "is_async": is_async,
            "is_error": False,
            "evaluations": []
        }
        if is_dry_run:
            job_status["is_dry_run"] = is_dry_run
            job_status["evaluation_success_data"] = []
            job_status["evaluation_failure_data"] = []
            job_status["eval_info_base"] = None
        self.job_statuses[job_id] = job_status

        def get_resp_perspective_from_far(formatted_evaluation_response):

            return {
                "perspectiveId": formatted_evaluation_response["perspectiveId"],
                "mode": self.mode,
                "evaluatedSelection": formatted_evaluation_response["evaluatedSelection"],
                "evaluationText": formatted_evaluation_response["evaluationText"]
            }

        def get_eval_info_base(mode, generated_request):

            # eval_info exists to generate an easily human readable summary for each evaluation
            # - this has been added for the Python version

            logger.debug(f"get_eval_info_base for generated_request: {generated_request}")

            eval_info_base = {
                "mode": mode,
                "persona": persona["id"],
                "evaluate_content": {},
                "evaluate_classifications": {}
            }

            for item in generated_request["items"]:

                if mode == "mode1":

                    item_id = item["itemId"]
                    evaluate_content = item["sent"]
                    if item["title"]:
                        evaluate_content += "\n" + item["title"]
                    if item["summary"]:
                        evaluate_content += "\n" + item["summary"]
                    eval_info_base["evaluate_content"][item_id] = evaluate_content
                    for evaluate_classification in item["classifications"]:
                        classification_id = evaluate_classification["name"]
                        if not item_id in eval_info_base["evaluate_classifications"]:
                            eval_info_base["evaluate_classifications"][item_id] = {}
                        eval_info_base["evaluate_classifications"][item_id][classification_id] = {
                            "classification_id": classification_id,
                            "classification_desc": evaluate_classification["desc"],
                            "classification_options": evaluate_classification["available"],
                            "classification_value": evaluate_classification["selected"]
                        }

                else:

                    item_id = item["id"]["itemId"]
                    classification_id = item["id"]["classificationId"]
                    # Expect eval_info_base["evaluate_content"] to be written to multiple times,
                    # but content will actually be same for each item due to mode2/3 structure
                    eval_info_base["evaluate_content"][item_id] = item["content"]
                    classification_contents = item["classification"]
                    if not item_id in eval_info_base["evaluate_classifications"]:
                        eval_info_base["evaluate_classifications"][item_id] = {}
                    eval_info_base["evaluate_classifications"][item_id][classification_id] = {
                        "classification_id": classification_id,
                        "classification_desc": classification_contents["description"],
                        "classification_options": classification_contents["fromAvailableClassifications"],
                        "classification_value": classification_contents["classifiedAs"]
                    }

            logger.debug(f"eval_info_base: {eval_info_base}")

            return eval_info_base

        def get_eval_info(eval_info_base, evaluation_result, classification_id=None):

            mode = eval_info_base["mode"]

            try:

                if mode == "mode1":

                    if not classification_id:
                        raise ValueError("get_eval_info requires classification_id for mode1")

                    item_id = evaluation_result["itemId"]
                    for evaluation in evaluation_result["evaluations"]:
                        if classification_id == evaluation["classificationName"]:
                            first_perspective = evaluation["perspectives"][0]   # Only supporting first!
                            evaluation_text = first_perspective["evaluationText"]
                            evaluation_result = first_perspective["evaluationLikert"]
                            break

                else:

                    if classification_id is not None:
                        # classification_id not needed due to flat structure of mode2/3 evaluation_result
                        logger.warn(f"get_eval_info will ignore classification_id for mode: {mode}")

                    ids = evaluation_result["id"]
                    item_id = ids["itemId"]
                    classification_id = ids["classificationId"]
                    evaluation_text = evaluation_result["evaluationText"]
                    if mode == "mode2":
                        evaluation_result = evaluation_result["evaluationLikert"]
                    else:
                        evaluation_result = evaluation_result["evaluationAgreement"]

                if not item_id in eval_info_base["evaluate_classifications"]:
                    logger.warn(f"eval_info_base does not contain item with id '{item_id}': {eval_info_base}")
                    eval_info_base["evaluate_classifications"][item_id] = {}
                if not item_id in eval_info_base["evaluate_classifications"]:
                    logger.warn(f"eval_info_base does not contain classification with id '{classification_id}': {eval_info_base}")
                classification = eval_info_base["evaluate_classifications"][item_id].get(classification_id)
                classification_text =  f"{classification['classification_value'].upper()} - {classification['classification_id']}"

                eval_info = {
                    "item": f"{item_id} - {mode} - {eval_info_base['persona']}",
                    "content": eval_info_base["evaluate_content"][item_id],
                    "classification": classification_text,
                    "evaluationText": evaluation_text,
                    "evaluationResult": evaluation_result
                }

                logger.debug(f"Built eval_info: {eval_info}")

                return eval_info

            except Exception as err:

                logger.error(f"Got Exception in get_eval_info: {err}")
                logger.error(f"Was processing evaluation_result: {evaluation_result}")
                return None


        def process_evaluations():

            nonlocal job_status

            with self.flask_app.app_context():  # So we can use context-dependent features such as logging

                try:

                    time.sleep(0.1) # Allow short time for calling function to return initial job_status
                    job_status["status"] = "PROCESSING"

                    logger.info(f"Started process_evaluations for tag_source: {tag_source}")

                    request_generator = AwAgEvaluationRequestGenerator(flask_app=self.flask_app)

                    page = 1
                    count = 20

                    limit_reached = False

                    # Evaluation failures cause the loop to skip and move on - give up if we have to skip
                    # too many items as it's probably a sign of network/token issues
                    max_skipped_count = 10
                    skipped_count = 0

                    while True:

                        if skipped_count >= max_skipped_count:
                            logger.debug(f"Skipped too many failed items ({skipped_count}) - giving up [top level]!")
                            break

                        if not is_dry_run:
                            record_evaluation_job_response = self.awagdata_client.record_evaluation_job(job_status)
                            logger.debug(f"record_evaluation_job_response: {record_evaluation_job_response}")

                        if limit_reached:
                            logger.debug("Limit reached")
                            break

                        logger.debug(f"Processing page {page} (count: {count})")

                        data, remaining = self.awagdata_client.fetch_evaluation_items(tag_source, exclude_tag, last_n_hours, subset_tag, subset_percent, is_most_recent, by_uuid, page, count)

                        if job_status["init_remaining"] < 0:
                            job_status["init_remaining"] = remaining
                        job_status["remaining"] = remaining

                        if not data:
                            if page == 1:
                                logger.warn(f"No data to process for tag: {tag_source}")
                                break
                            else:
                                logger.debug(f"No more data at page {page} (count: {count})")
                                break

                        for evaluation_item in data:

                            if skipped_count >= max_skipped_count:
                                logger.error(f"Skipped too many failed items ({skipped_count}) - giving up!")
                                break

                            generated_requests = request_generator.generate_requests_from_evaluation_items([evaluation_item], persona, perspectives, mode)

                            logger.debug(f"Generated {len(generated_requests)} requests")

                            if not is_dry_run:
                                record_evaluation_job_response = self.awagdata_client.record_evaluation_job(job_status)
                                logger.debug(f"record_evaluation_job_response: {record_evaluation_job_response}")

                            for generated_request in generated_requests:

                                logger.warn(f"skipped_count: {skipped_count}")

                                if skipped_count >= max_skipped_count:
                                    logger.error(f"Skipped too many failed items ({skipped_count}) - giving up!")
                                    break

                                evaluation_results, info_json = self.get_evaluation(
                                        eval_request=generated_request,
                                        model=openai_model,
                                        is_use_request_schema=is_use_request_schema,
                                        openai_params=openai_params)

                                if evaluation_results == None:
                                    # This should be rare.  We don't have enough information here to log the failure
                                    # so just skip it so we can continue processing
                                    is_error = True
                                    logger.warn(f"Unable to process evaluation - skipping")
                                    skipped_count += 1
                                    break

                                # Put cut-down version of info_json in the job_entry
                                info_for_job_entry = {
                                    "query_info": info_json["query_info"],
                                    "query_state": info_json["query_state"],
                                    "usage": info_json["usage"]
                                }

                                eval_info_base = get_eval_info_base(mode, generated_request)
                                if is_dry_run:
                                    job_status["eval_info_base"] = eval_info_base

                                request_items = generated_request["items"]

                                #logger.debug(f"evaluation_results: {evaluation_results}")
                                #logger.debug(f"info_for_job_entry: {info_for_job_entry}")

                                job_entry = {
                                    "request_items": request_items,
                                    "info": info_for_job_entry,
                                }

                                usage = info_json["usage"]
                                job_status["usage"]["completion_tokens"] += usage["completion_tokens"]
                                job_status["usage"]["prompt_tokens"] += usage["prompt_tokens"]
                                job_status["usage"]["total_tokens"] += usage["total_tokens"]

                                # query_info is similar but not identical to APIChatCompletionsQueryInfoEvaluate from Java
                                query_info = info_json["query_info"]
                                query_info["mode"] = mode
                                query_info["eval_request"] = generated_request

                                # Put the engine value into query_info so it is sent to the recorder.  We do it
                                # this way for compatability with existing code but it's not the best place for it
                                query_info["engine"] = info_json["engine"]

                                query_state = info_json["query_state"]
                                additional_query_info = info_json["additional_query_info"]

                                finish_reason = additional_query_info["finish_reason"]
                                if finish_reason == "stop" or finish_reason == function_call:
                                    logger.debug(f"Got non-error finish_reason: {finish_reason}")
                                    is_error = False
                                else:
                                    logger.error(f"Got error finish_reason: {finish_reason}")
                                    is_error = True
                                job_status["finish_reason"] = finish_reason

                                # Ref IEvaluationResponse from Java
                                formatted_evaluation_responses = []

                                job_status["is_error"] = is_error

                                if not is_error:

                                    for evaluation_result in evaluation_results:

                                        #logger.debug(f"Examining evaluation_result: {evaluation_result}")
                                        logger.debug(f"Examining mode {mode} evaluation_result")

                                        if mode == "mode1":

                                            is_evaluation_result_valid = validate_mode1_evaluation_result(evaluation_result)
                                            if not is_evaluation_result_valid:
                                                logger.error(f"Got bad evaluation_result: {evaluation_result}")
                                                is_error = True
                                                continue;

                                            item_id = evaluation_result["itemId"]

                                            for evaluation in evaluation_result["evaluations"]:

                                                logger.debug(f"Processing {mode} evaluation: {evaluation}")

                                                # EvaluationResponseMode1 implements IEvaluationResponse
                                                evaluation_reponse_mode1 = {
                                                    "itemId": item_id,   # Not actually in EvaluationResponseMode1!
                                                    "classificationName": evaluation["classificationName"],
                                                    "perspectives": evaluation["perspectives"]
                                                }

                                                formatted_evaluation_responses.append(evaluation_reponse_mode1)

                                                eval_info = get_eval_info(eval_info_base, evaluation_result, classification_id=evaluation["classificationName"])

                                                if eval_info is None:
                                                    # Ditch this whole evaluation_results set as None eval_info indicates bad response from OpenAI
                                                    is_error = True
                                                    formatted_evaluation_responses = []
                                                    break
                                                else:
                                                    formatted_evaluation_responses.append(evaluation_reponse_mode1)
                                                    job_status["eval_info"].append(eval_info)

                                        else:

                                            is_evaluation_result_valid = validate_mode2_mode3_evaluation_result(evaluation_result, mode)
                                            if not is_evaluation_result_valid:
                                                logger.error(f"Got bad evaluation_result: {evaluation_result}")
                                                is_error = True
                                                continue;

                                            logger.debug(f"Processing {mode} evaluation: {evaluation_result}")

                                            ids = evaluation_result["id"]
                                            item_id = ids["itemId"]

                                            evaluation_reponse = {
                                                "itemId": item_id,
                                                "perspectiveId": ids["perspectiveId"],
                                                "classificationName": ids["classificationId"],
                                                "evaluationText": evaluation_result["evaluationText"],
                                                "evaluatedSelection": evaluation_result["evaluatedSelection"],
                                            }
                                            
                                            if mode == "mode2":
                                                # EvaluationResponseMode2 implements IEvaluationResponse
                                                evaluation_reponse["evaluationLikert"] = evaluation_result["evaluationLikert"]
                                            elif mode == "mode3":
                                                # EvaluationResponseMode3 implements IEvaluationResponse
                                                evaluation_reponse["evaluationAgreement"] = evaluation_result["evaluationAgreement"]
                                            else:
                                                raise ValueError(f"Invalid mode: {mode}")

                                            eval_info = get_eval_info(eval_info_base, evaluation_result)
                                            if eval_info is None:
                                                # Ditch this whole evaluation_results set as None eval_info indicates bad response from OpenAI
                                                is_error = True
                                                formatted_evaluation_responses = []
                                                break
                                            else:
                                                formatted_evaluation_responses.append(evaluation_reponse)
                                                job_status["eval_info"].append(eval_info)

                                        #result["evaluationResponses"] = formatted_evaluation_responses
                                        job_entry["results"] = formatted_evaluation_responses

                                evaluation_perspectives_modified = []
                                # record_evaluation_failure/record_evaluation_data use different naming for perspectives
                                for evaluation_perspective in perspectives:
                                    evaluation_perspectives_modified.append({
                                        "perspectiveId": evaluation_perspective["id"],
                                        "perspectiveName": evaluation_perspective["name"],
                                        "perspectiveText": evaluation_perspective["text"],
                                    })

                                if is_error:

                                    logger.error(f"Got one or more bad evaluation_results")

                                    evaluation_failure_data = {
                                        "agent": self.client_id,
                                        "contextIdentifier": generated_request["context_identifier"],
                                        "queryInfo": query_info,
                                        "additionalQueryInfo": additional_query_info,
                                        "finishReason": finish_reason,
                                        "queryState": query_state,
                                        "mode": mode,
                                        "model": openai_model,
                                        "evaluationItem": evaluation_item,
                                        "evaluationPersona": persona,
                                        "evaluationPerspectives": evaluation_perspectives_modified,
                                        "evaluationRequest": generated_request
                                    }

                                    if is_dry_run:
                                        logger.info("DRY RUN - not storing evaluation failure data")
                                        logger.debug(f"evaluation_failure_data: {evaluation_failure_data}")
                                        job_status["evaluation_failure_data"].append(evaluation_failure_data)
                                    else:
                                        record_evaluation_data_response = self.awagdata_client.record_evaluation_failure(evaluation_failure_data)

                                else:

                                    # Ref EvaluateRecorderRestClient class in original Java

                                    # For legacy compatability
                                    expanded_query_state = query_state.copy()
                                    expanded_query_state["finish_reason"] = finish_reason
                                    expanded_query_state["usage"] = info_json["usage"]

                                    # contextId is a consequence of original mode1 design, where multiple
                                    # itemIds can be associated with a single query.  We give the query a
                                    # contextId so that query-level data can be recorded.  However, it adds
                                    # a level of complexity to each awagdata database entry

                                    context = {
                                        "contextId": generated_request["context_identifier"],
                                        "evaluationItems": [evaluation_item],
                                        "openaiApiCompletionsQueryInfo": query_info,
                                        "additionalQueryInfo": additional_query_info,
                                        "queryState": expanded_query_state
                                    }

                                    evaluate_time_text = evaluation_item["evaluateTime"]
                                    evaluate_time_obj = parser.parse(evaluate_time_text)
                                    evaluate_time_ms = int(evaluate_time_obj.timestamp() * 1000)

                                    if tags_dest:
                                        item_tags = tags_dest
                                    else:
                                        item_tags = evaluation_item["tags"]

                                    om_item = {
                                        "itemId": evaluation_item["contentItemSummary"]["itemId"],
                                        "tags": item_tags,
                                        "contentItemSummary": evaluation_item["contentItemSummary"],
                                        "classifications": evaluation_item["evaluateClassifications"],
                                        "evaluateSourceType": evaluation_item["evaluateSourceType"],
                                        "evaluateSourceOriginator": evaluation_item["evaluateSourceOriginator"],
                                        "evaluateSourceChannel": evaluation_item["evaluateSourceChannel"],
                                        "evaluateTimeText": evaluate_time_text,
                                        "evaluateTimeMs": evaluate_time_ms,
                                        "evaluateTitle": evaluation_item.get("evaluateTitle", None),
                                        "evaluateText": evaluation_item.get("evaluateText", None),
                                        "evaluationResponses": []
                                    }

                                    for far in formatted_evaluation_responses:

                                        # Equivalent to EvaluationResponseMode1, EvaluationResponseMode2, EvaluationResponseMode3

                                        # Name is slightly confusing; keeping for consistency with Java original
                                        # Each one of these is an item in the evaluationResponses list
                                        # Perspectives is a list because it can have multiple values for mode1
                                        om_classification = {
                                            "classificationName": far["classificationName"],
                                            "perspectives": []    # This is the classification *result*
                                        }

                                        if mode == "mode1":

                                            for persp in far["perspectives"]:
                                                # In this case, pass persp to get_resp_perspective_from_far()
                                                # - should have same structure as formatted_evaluation_response
                                                this_perspective = get_resp_perspective_from_far(persp)
                                                this_perspective["evaluationLikertVal"] = persp["evaluationLikert"]
                                                this_perspective["evaluationLikertText"] = get_likert_label(persp["evaluationLikert"])
                                                om_classification["perspectives"].append(this_perspective)

                                        elif mode == "mode2":

                                            this_perspective = get_resp_perspective_from_far(far)
                                            this_perspective["evaluationLikertVal"] = far["evaluationLikert"]
                                            this_perspective["evaluationLikertText"] = get_likert_label(far["evaluationLikert"])
                                            om_classification["perspectives"].append(this_perspective)

                                        elif mode == "mode3":

                                            this_perspective = get_resp_perspective_from_far(far)
                                            this_perspective["evaluationAgreement"] = far["evaluationAgreement"]
                                            om_classification["perspectives"].append(this_perspective)

                                        else:

                                            raise ValueError(f"Invalid mode: {mode}")

                                        om_item["evaluationResponses"].append(om_classification)

                                    evaluation_success_data = {
                                        "agent": self.client_id,
                                        "evaluationPersona": persona,
                                        "evaluationPerspectives": evaluation_perspectives_modified,
                                        "context": context,
                                        "evaluationRequest": generated_request,
                                        "items": [om_item]
                                    }

                                    if is_dry_run:
                                        logger.info("DRY RUN - not storing evaluation success data")
                                        logger.debug(f"evaluation_success_data: {evaluation_success_data}")
                                        job_status["evaluation_success_data"].append(evaluation_success_data)
                                    else:
                                        record_evaluation_data_response = self.awagdata_client.record_evaluation_data(evaluation_success_data)

                                job_status["evaluations"].append(job_entry)
                                
                                job_status["processed_items"] += 1

                            if items_to_process is not None and items_to_process > 0:
                                if job_status["processed_items"] >= items_to_process:
                                    logger.info(f"Stopping at passed limit of {items_to_process} items")
                                    limit_reached = True
                                    break

                        if remaining < 1:
                            logger.debug(f"No more data remaining after page {page} (count: {count})")
                            break

                        page += 1

                    job_status["message"] = f"Completed processing of {len(job_status['evaluations'])} items."
                    job_status["status"] = "COMPLETE"

                    if not is_dry_run:
                        record_evaluation_job_response = self.awagdata_client.record_evaluation_job(job_status)
                        logger.debug(f"record_evaluation_job_response: {record_evaluation_job_response}")

                    logger.debug(f"Completed process_actions for tag_source: {tag_source}")

                except Exception as e:

                    msg = f"Error in process_evaluations for tag_source: '{tag_source}': {e}"
                    job_status["status"] = "ERROR"
                    job_status["message"] = msg
                    logger.error(msg)
                    log_exception(self.client_id, e, include_traceback=True)

                self.job_statuses[job_id] = job_status

        if is_async:

            logger.debug(f"Started process_evaluations...")
            thread = threading.Thread(target=process_evaluations)
            thread.start()

        else:

            process_evaluations()

        return self.job_statuses.get(job_id)

