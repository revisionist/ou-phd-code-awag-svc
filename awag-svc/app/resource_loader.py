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
import logging

logging.basicConfig(level=logging.INFO)
#logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("resource_loader")


class ResourceLoader:

    def __init__(self, resource_dir):

        absolute_path = os.path.abspath(resource_dir) 
        logger.debug(f"Initialising ResourceLoader using path: {absolute_path}")
        self.resource_dir = resource_dir


    def load_text(self, text_name, use_env=True):

        logger.debug(f"Attempting to load TEXT resource with name: {text_name} [use_env={use_env}]")

        if use_env:
            env_value = os.getenv(text_name)
            if env_value:
                logger.debug(f"Returning content for '{text_name}' from ENVIRONMENT\n{env_value}")
                return env_value
        
        file_path = os.path.join(self.resource_dir, 'text', f"{text_name}.txt")

        if not os.path.exists(file_path):

            raise FileNotFoundError(f"Text resource '{text_name}' not found at '{file_path}'")

        with open(file_path, 'r', encoding='utf-8') as file:
            text_content = file.read()
            logger.debug(f"Returning content for '{text_name}' from FILE\n{text_content}")
            return text_content


    def load_json(self, json_name, use_env=True):

        logger.debug(f"Attempting to load JSON resource with name: {json_name} [use_env={use_env}]")

        if use_env:
            env_value = os.getenv(json_name)
            if env_value:
                try:
                    json_content = json.loads(env_value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Environment variable '{json_name}' contains invalid JSON: {e}")
                logger.debug(f"Returning content for '{json_name}' from ENVIRONMENT\n{json_content}")
                return json_content

        file_path = os.path.join(self.resource_dir, 'json', f"{json_name}.json")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"JSON resource '{json_name}' not found at '{file_path}'")
        with open(file_path, 'r', encoding='utf-8') as file:
            json_content = json.load(file)

        logger.debug(f"Returning content for '{json_name}' from FILE\n{json_content}")
        return json_content

