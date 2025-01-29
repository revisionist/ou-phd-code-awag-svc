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

from flask import current_app

import pandas as pd

from .shared_resources import logger


class StatsBuilderMultiIndexDF:

    def __init__(self, engine, flask_app=None):

        self.engine = engine
        self.flask_app = flask_app


    def get_multiindex_df(self, df_function, tag_main, tags_eval, **kwargs):

        logger.debug(f"Building multi-index DataFrame for {tag_main} & {tags_eval}")
        logger.debug(f"Passed df_function: {df_function}")
        logger.debug(f"Other arguments: {kwargs}")

        # Assume that stat_function has a function attribute called data_columns that
        # contains the data columns for that stat
        data_columns = getattr(df_function, "data_columns", [])

        combined_data = {}

        for tag_eval in tags_eval:
            df = df_function(tag_main, tag_eval=tag_eval, **kwargs)
            if df is None or df.empty:
                logger.debug(f"Did not get DataFrame for tag_eval: {tag_eval}")
            else:
                combined_data[tag_eval] = df

        if not combined_data:
            return pd.DataFrame()

        existing_tags_eval = list(combined_data.keys())
        all_columns = pd.MultiIndex.from_product([existing_tags_eval, data_columns], names=["tag_eval", "metric"])
        multiindex_df = pd.DataFrame(columns=all_columns)

        for tag_eval, df in combined_data.items():
            for col in data_columns:
                multiindex_df[(tag_eval, col)] = df[col]

        logger.debug(f"Built multi-index DataFrame using function {df_function}:\n{multiindex_df}")

        return multiindex_df
