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

from collections import defaultdict 

from domestique.validation import Validator, NoiseLevel

from .shared_resources import logger


class OpenAIChatHandler:

    def __init__(self, namespace_base, objectstore_client, openai_client_wrapper, chat_system_message, chat_history_limit):

        Validator().check_all(
            namespace_base=namespace_base,
            objectstore_client=objectstore_client,
            openai_client_wrapper=openai_client_wrapper,
            chat_system_message=chat_system_message,
            chat_history_limit=chat_history_limit
            )

        self.namespace_base = namespace_base
        self.objectstore_client = objectstore_client
        self.openai_client_wrapper = openai_client_wrapper
        self.chat_system_message = chat_system_message
        self.chat_history_limit = chat_history_limit
        self.chat_history = []


    def get_namespace_base(self):

        return self.namespace_base


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def add_message_to_history(self, message):

        self.chat_history.append(message)
        if len(self.chat_history) > self.chat_history_limit:
            self.chat_history = self.chat_history[-self.chat_history_limit:]


    def get_chat_reponse(self, chat_request, model_id):

        Validator().check(["chat_request", "model_id"], chat_request=chat_request, model_id=model_id)

        openai_client_wrapper = self.get_openai_client_wrapper()

        self.add_message_to_history({"role": "system", "content": self.chat_system_message})
        self.add_message_to_history({"role": "user", "content": chat_request})

        completion_choice, info_json = openai_client_wrapper.run_chat_completions(self.chat_history, model_id)

        completion_choice_text = completion_choice.message.content

        self.add_message_to_history({"role": "assistant", "content": completion_choice_text})

        return completion_choice_text, info_json

