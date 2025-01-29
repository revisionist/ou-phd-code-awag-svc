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

from enum import Enum

import pandas as pd

from flask import current_app

from domestique.validation import Validator, NoiseLevel
from domestique.logging import log_exception

from .shared_resources import logger

from .awag_stats_engine import StatsEngine


class StatsEngineExtended(StatsEngine):

    LBL_ALL = "ALL"
    LBL_CLASS = "BY_CLASSIFICATION"
    LBL_TS = "TIMESERIES"
    STANDARD_NOTE_TEXT = "This statistic contains overall data as well as data broken down by individual classification"


    def __init__(self, agent_id, conn, stats_table_base, stats_table_eval, flask_app=None, notes_dict={}):

        super().__init__(agent_id, conn, stats_table_base, stats_table_eval, flask_app, notes_dict)


    def _get_stats_for_classification(self, tag_main, tag_eval=None, is_include_notes=True, stat_function=None, **kwargs):

        stats_json = {
            self.LBL_ALL: stat_function(tag_main, tag_eval, is_include_notes=is_include_notes, **kwargs),
            self.LBL_CLASS: {}
        }

        classifications = self.get_classifications(tag_main)
        for classification in classifications:
            stats_json[self.LBL_CLASS][classification] = stat_function(tag_main, tag_eval, classification_name=classification, is_include_notes=False, **kwargs)

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=None, extra_note_text=self.STANDARD_NOTE_TEXT, tag_main=tag_main, tag_eval=tag_eval)

        return stats_json


    def should_include_stat(self, value, is_include_empty):

        if value is None:
            is_empty = True
        elif isinstance(value, pd.DataFrame):
            is_empty = value.empty
        elif isinstance(value, (list, dict)):
            is_empty = not value
        elif isinstance(value, (str, bytes)):
            is_empty = len(value) == 0
        elif isinstance(value, (int, float)):
            is_empty = value == 0
        else:
            is_empty = not bool(value)

        return is_include_empty or not is_empty


    def get_percent_of_classification_manual_agrees_cl(self, tag_main, tag_eval=None, is_only_with_eval=False, is_only_with_feedback=False, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_percent_of_classification_manual_agrees,
            is_only_with_eval=is_only_with_eval, is_only_with_feedback=is_only_with_feedback)


    def get_percent_of_classification_manual_agrees_base_cl(self, tag_main, is_include_notes=True):

        note_text = f"This base statistic is for all records having data for main tag: '{tag_main}' (i.e. it is independent of evaluation tag)"

        return self.get_percent_of_classification_manual_agrees_cl(tag_main, tag_eval=None, is_include_notes=is_include_notes, is_only_with_eval=False, is_only_with_feedback=False, note_text=note_text)


    def get_pearsonr_for_eval_feedback_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_pearsonr_for_eval_feedback,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_pointbiserialr_for_eval_agreement_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_pointbiserialr_for_eval_agreement,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_pointbiserialr_for_eval_feedback_agreement_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_pointbiserialr_for_eval_feedback_agreement,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_avg_and_spread_for_eval_difference_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_avg_and_spread_for_eval_difference,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_text_stats_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True, field_name=None):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_text_stats,
            persona_id=persona_id, perspective_id=perspective_id,
            field_name=field_name)


    def get_phi_coefficient_for_mode3_agreement_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_phi_coefficient_for_mode3_agreement,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_cohens_kappa_for_manual_classification_agreement_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_cohens_kappa_for_manual_classification_agreement,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_evaluation_results_likert_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_evaluation_results_likert,
            persona_id=persona_id, perspective_id=perspective_id)


    def get_evaluation_results_mode3_cl(self, tag_main, tag_eval=None, persona_id=None, perspective_id=None, note_text=None, is_include_notes=True):

        return self._get_stats_for_classification(
            tag_main, tag_eval, is_include_notes=is_include_notes,
            stat_function=self.get_evaluation_results_mode3,
            persona_id=persona_id, perspective_id=perspective_id)
