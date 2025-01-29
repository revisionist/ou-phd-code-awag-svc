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

from enum import Enum

from datetime import datetime
from typing import List, Dict, Any

from flask import current_app

from domestique.datetime import get_current_time_ms
from domestique.validation import Validator, NoiseLevel
from domestique.json import get_dict_from_dict_or_json_str
from domestique.text import truncate_string
from domestique.identifiers import generate_id
from domestique.logging import log_exception

from .shared_resources import logger, get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_base_for_type


class AwAgEvaluationRequestGenerator:

    def __init__(self, openai_client=None, awagdata_client=None, flask_app=None):

        self.openai_client = openai_client
        self.awagdata_client = awagdata_client
        self.flask_app = flask_app

        self.job_statuses = {}


    def get_namespace_base(self):

        return self.namespace_base


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def build_item_mode1(self, id=None, title="", summary="", source_type=None, source_originator=None, source_channel=None, classifications=[]):

        Validator().check([], id=id, title=title, summary=summary,
            source_type=source_type, source_originator=source_originator, source_channel=source_channel,
            classifications=classifications)

        if not id:
            id = generate_id()

        sent = datetime.utcnow().isoformat()

        source = {
           "type": source_type,
           "originator": source_originator,
           "channel": source_channel
        }

        return {
            "itemId": id,
            "sent": sent,
            "title": title,
            "summary": summary,
            "source": source,
            "classifications": classifications
        }


    def create_base_request(self, mode, persona=None):

        if not mode:
            raise ValueError("Required: mode")

        return {
            "mode": mode,
            "context_identifier": generate_id(),
            "persona": persona,
            "items": []
        }


    def build_items_from_evalitem_mode1(self, evaluation_persona, evaluation_perspectives, evaluation_items):

        # Generates a mode1 evaluation request item from a fetch-evaluation-items item
        # See EvaluationQuery.toQueryJsonMode1() in original Java

        try:

            logger.debug(f"build_items_from_evalitem_mode1 passed items:\n{evaluation_items}")

            om_persona = {
                "name": evaluation_persona["name"],
                "definition": evaluation_persona["definition"]
            }

            om = self.create_base_request("mode1", om_persona)

            om["perspectives"] = evaluation_perspectives

            ls_items = []
            for evaluation_item in evaluation_items:
                om_item = {
                    "itemId": evaluation_item["contentItemSummary"]["itemId"],
                    "sent": evaluation_item["evaluateTime"],
                    "title": evaluation_item.get("evaluateTitle", ""),
                    "summary": evaluation_item.get("evaluateText", ""),
                    "source": {
                        "type": evaluation_item["evaluateSourceType"],
                        "originator": evaluation_item["evaluateSourceOriginator"],
                        "channel": evaluation_item["evaluateSourceChannel"]
                    },
                    "classifications": []
                }

                for classification_info in evaluation_item["evaluateClassifications"]:
                    om_classification = {
                        "name": classification_info["classificationName"],
                        "desc": classification_info["classificationDesc"],
                        "selected": classification_info["classificationValue"],
                        "available": classification_info["classificationOptions"]
                    }
                    om_item["classifications"].append(om_classification)

                om["items"].append(om_item)

            logger.debug(f"build_items_from_evalitem_mode1 returning:\n{om}")

            return om

        except KeyError as e:

            raise Exception(f"Got KeyError in build_items_from_evalitem_mode1 for item: {e}")


    def build_items_from_evalitem_mode2_mode3(self, mode, evaluation_persona, evaluation_perspectives, evaluation_items):

        # Generates a mode2 or 3 evaluation request item from a fetch-evaluation-items item
        # See EvaluationQuery.toQueryJsonMode2() & toQueryJsonMode3() in original Java

        try:

            ls_perspectives = []

            om_persona = {
                "name": evaluation_persona["name"],
                "definition": evaluation_persona["definition"]
            }

            for evaluation_perspective in evaluation_perspectives:

                # Note this differs from current Java implementation, which uses just evaluation_persona.definition here:
                om = self.create_base_request(mode, om_persona)
                om["perspective"] = evaluation_perspective["text"]

                for evaluation_item in evaluation_items:

                    itemId = evaluation_item["contentItemSummary"]["itemId"]

                    for classification_info in evaluation_item["evaluateClassifications"]:

                        om_id = {
                            "itemId": itemId,
                            "perspectiveId": evaluation_perspective["id"],
                            "classificationId": classification_info["classificationName"]
                        }
                        content = f"{evaluation_item['evaluateTime']}"
                        if "evaluateTitle" in evaluation_item:
                            content += f"\n{evaluation_item['evaluateTitle']}"
                        if "evaluateText" in evaluation_item:
                            content += f"\n{evaluation_item['evaluateText']}"

                        om_mode2_item = {
                            "id": om_id,
                            "content": content,
                            "classification": {
                                "description": classification_info["classificationDesc"],
                                "classifiedAs": classification_info["classificationValue"],
                                "fromAvailableClassifications": classification_info["classificationOptions"]
                            }
                        }

                        om["items"].append(om_mode2_item)

                ls_perspectives.append(om)

            return [om for om in ls_perspectives]

        except KeyError as e:

            raise Exception(f"Got KeyError in build_items_from_evalitem_mode2 for item: {e}")


    def build_classification(self, name, desc, available=[], selected=None):

        Validator().check(["name", "desc"], name=name, desc=desc, available=available, selected=selected)

        return {
           "name": name,
           "desc": desc,
           "available": available,
           "selected": selected
        }


    def build_perspective(self, id, name, text):

        Validator().check(["id", "name"], id=id, name=name, text=text)

        return {
           "id": id,
           "name": name,
           "text": text
        }


    def build_request_mode1(self, persona=None, perspectives=[], items=[]):

        # Used by generate_request_with_random_classifications and generate_request_from_evaluation_items

        Validator().check([], persona=persona, perspectives=perspectives, items=items)

        return {
           "persona": persona,
           "perspectives": perspectives,
           "items": items
        }


    def build_request_mode2(self, persona, text, perspective, classifications, item_id=None):

        # Used by generate_request_with_random_classifications only

        Validator().check_all(persona=persona, text=text, perspective=perspective, classifications=classifications)

        if not item_id:
            item_id = generate_id()

        sent = datetime.utcnow().isoformat()
        content = f"{sent}\n{text}"

        request = {
            "persona": persona,
            "perspective": perspective["text"],
            "items": []
        }

        for classification in classifications:

            id = {
                "itemId": item_id,
                "perspectiveId": perspective["id"],
                "classificationId": classification["name"]
             }

            request["items"].append({
                "id": id,
                "content": content,
                "classification": {
                    "description": classification["desc"],
                    "classifiedAs": classification["selected"],
                    "fromAvailableClassifications": classification["available"]
                }
            })

        return request


    def build_request_mode3(self, persona, text, perspective, classifications, item_id=None):

        # Used by generate_request_with_random_classifications only

        return self.build_request_mode2(persona, text, perspective, classifications, item_id)


    def generate_request_with_random_classifications(self, sim_text_category, persona=None, perspectives=[], classifications=[], source_type="Simulated Item", source_originator=None, source_channel=None, mode="mode1"):

        Validator().check(["sim_text_category", "mode"], sim_text_category=sim_text_category,
                    persona=persona, perspectives=perspectives, classifications=classifications,
                    source_type=source_type, source_originator=source_originator, mode=mode
        )

        if self.openai_client is None:
            raise Exception(f"OpenAI client must be set for generate_request_with_random_classifications")

        if self.awagdata_client is None:
            raise Exception(f"AwAg Data client must be set for generate_request_with_random_classifications")

        generated_content = self.awagdata_client.get_sim_text(sim_text_category, is_get_all=False)

        if not generated_content:
            raise Exception(f"Unable to get simulated content for category: {sim_text_category}")

        for classification in classifications:
            if classification.get("selected", None) is None and classification.get("available", None):
                classification["selected"] = random.choice(classification["available"])
                logger.debug(f"Randomised classification: {classification}")

        if mode == "mode1":

            if source_channel is None:
                source_channel=sim_text_category

            if not source_originator:
                source_originator = f"{generated_content.get('item_username')} <{generated_content.get('item_userid')}>"

            item = self.build_item_mode1(
                summary=generated_content.get("item_username"),
                source_type=source_type,
                source_originator=source_originator,
                source_channel=source_channel,
                classifications=classifications)

            # Randomise whether the title or summary contains the text
            chosen_property = random.choice(['title', 'summary'])
            item[chosen_property] = generated_content.get("item_text")

            request = self.build_request_mode1(persona, perspectives, [item])

        elif mode == "mode2":

            # Only currently supoprt single perspective with mode2
            perspective = perspectives[0]
            request = self.build_request_mode2(persona, generated_content.get("item_text"), perspective, classifications)

        elif mode == "mode3":

            # Only currently supoprt single perspective with mode3
            perspective = perspectives[0]
            request = self.build_request_mode3(persona, generated_content.get("item_text"), perspective, classifications)

        else:

            raise ValueError(f"Invalid mode: {mode}")

        logger.debug(f"Generated request: {request}")

        return request


    def generate_requests_from_evaluation_items(self, evaluation_items=[], persona=None, perspectives=[], mode="mode1"):

        # Generates a modeN evaluation request item from a fetch-evaluation-items item

        Validator().check_all(noise_level=NoiseLevel.SILENT, evaluation_items=evaluation_items, perspectives=perspectives)
        Validator().check(["mode"], mode=mode)

        if mode == "mode1":

            #items_list = self.build_items_from_evalitem_mode1(persona, perspectives, evaluation_items)
            #requests = [self.build_request_mode1(persona, perspectives, evaluation_items)]
            requests = [self.build_items_from_evalitem_mode1(persona, perspectives, evaluation_items)]

        elif mode == "mode2":

            requests = self.build_items_from_evalitem_mode2_mode3(mode, persona, perspectives, evaluation_items)

        elif mode == "mode3":

            requests = self.build_items_from_evalitem_mode2_mode3(mode, persona, perspectives, evaluation_items)

        else:

            raise ValueError(f"Invalid mode: {mode}")

        logger.debug(f"Generated requests: {requests}")

        return requests

