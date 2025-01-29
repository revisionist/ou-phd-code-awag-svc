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
import time

from enum import Enum

from flask import current_app

import pandas as pd
import numpy as np

from scipy.stats import pearsonr
from scipy.stats import pointbiserialr

from scipy.stats import chi2_contingency

from sklearn.metrics import cohen_kappa_score

from domestique.validation import Validator, NoiseLevel
from domestique.text import truncate_string
from domestique.logging import log_exception
from domestique.db import concat_sql, SQLGenerator

from .shared_resources import logger, get_dataset_namespace, get_dataset_meta_namespace, get_dataset_namespace_base_for_type


class StatsEngine:

    def __init__(self, agent_id, conn, stats_table_base, stats_table_eval, flask_app=None, notes_dict={}):

        Validator().check_all(
            agent_id=agent_id,
            conn=conn,
            stats_table_base=stats_table_base,
            stats_table_eval=stats_table_eval)

        self.agent_id = agent_id
        self.conn = conn
        self.stats_table_base = stats_table_base
        self.stats_table_eval = stats_table_eval
        self.flask_app = flask_app
        self.notes_dict = notes_dict


    def get_agent_id(self):

        return self.agent_id


    def get_conn(self):

        return self.conn


    def get_stats_table_base(self):

        return self.stats_table_base


    def get_stats_table_eval(self):

        return self.stats_table_eval


    def _generate_simple_dict(self, **kwargs):

        obj = {}
    
        for key, value in kwargs.items():
            if value is not None:
                obj[key] = value

        return obj


    def convert_numpy_to_native(self, obj):

        if isinstance(obj, dict):
            return {k: self.convert_numpy_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_numpy_to_native(i) for i in obj]
        elif isinstance(obj, (np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.float64, np.float32)):
            return float(obj)
        else:
            return obj


    def get_notes(self, notes_key, **kwargs):

        if notes_key not in self.notes_dict:
            return None
            #raise KeyError(f"Notes key '{notes_key}' not found in notes_dict")

        notes_template = self.notes_dict[notes_key]
        formatted_notes = {key: value.format(**kwargs) for key, value in notes_template.items()}

        return formatted_notes


    def _add_note(self, obj, note_obj):
    
        if obj and note_obj:
            obj["_note"] = note_obj


    def _add_filter_info(self, obj, filter_info_obj):
    
        if obj and filter_info_obj:
            obj["_filters"] = filter_info_obj


    def _add_note_item(self, note_obj, item_text, item_name="_"):
    
        if note_obj is not None and item_text:

            base_item_name = item_name
            counter = 1

            while item_name in note_obj:
                item_name = f"{base_item_name}{counter}"
                counter += 1

            note_obj[item_name] = item_text


    def _append_standard_notes(self, stats_json, is_include_notes=True, note=None, extra_note_text=None, **kwargs):

        if not is_include_notes:
            return

        filter_info = self._generate_simple_dict(**kwargs)

        if filter_info:
            self._add_filter_info(stats_json, filter_info)

        if extra_note_text and not note:
            note = {}
        self._add_note_item(note, extra_note_text)

        self._add_note(stats_json, note)

        return stats_json


    def _query_to_dataframe(self, sql_query, query_params):

        logger.debug(f"Getting dataframe from query: {sql_query}")

        return pd.read_sql_query(sql_query, self.get_conn(), params=query_params)


    def _sql_generator_to_dataframe(self, sql_generator, distinct=False):

        logger.debug(f"Getting dataframe from sql_generator: {sql_generator}")
        
        query_sql, query_params = sql_generator.get_query(distinct=distinct)

        logger.debug(f"Getting dataframe using query_sql:\n{query_sql}")
        logger.debug(f"With query_params:\n{query_params}")

        return self._query_to_dataframe(query_sql, query_params)


    def _build_sql_generator(self, table, select_items, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=[], group_items=None):

        if not table:
            raise ValueError("Value for table is missing or empty.")

        if not select_items:
            raise ValueError("Value for select_items is missing or empty.")

        required_params = {
            'agent_id': self.get_agent_id(),
            'tag_main': tag_main
        }

        optional_params = {
            'tag_eval': tag_eval,
            'persona_id': persona_id,
            'perspective_id': perspective_id,
            'classification_name': classification_name
        }

        sql_generator = SQLGenerator(froms=table)

        # Adding multiple select clauses at once
        sql_generator.add_select(select_items)
        sql_generator.add_where_not_null(not_null_columns)
        sql_generator.add_where(required_params, optional=False)
        sql_generator.add_where(optional_params, optional=True)
        sql_generator.add_group(group_items)

        return sql_generator


    def _get_dataframe(self, table, select_items, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=[], group_items=None, distinct=False):

        Validator().check(["tag_main", "table", "select_items"],
            tag_main=tag_main, table=table, select_items=select_items,
            tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id,
            perspective_id=perspective_id, not_null_columns=not_null_columns)

        sql_generator = self._build_sql_generator(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns, group_items)

        df = self._sql_generator_to_dataframe(sql_generator, distinct)

        if df.empty or len(df.dropna()) < 1:
            logger.debug(f"Dataframe empty: {select_items} from {table}; tag_main: {tag_main}, tag_eval: {tag_eval}, not_null_columns: {not_null_columns}")
            return None
        else:
            return df


    def _get_data_for_classification_manual_agrees(self, table, tag_main, tag_eval=None, classification_name=None, not_null_columns=[], group_items=None):

        select_items = [
                "COUNT(*) FILTER (WHERE classification_manual_agrees = 1) AS agrees_count",
                "COUNT(*) AS total_count"
                ]

        return self._get_dataframe(table, select_items, tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=None, perspective_id=None, not_null_columns=not_null_columns,
        group_items=group_items)


    def _get_data_for_classification_manual_agrees_detailed(self, table, tag_main, tag_eval=None, classification_name=None, not_null_columns=[], group_items="date"):

        select_items = [
            "DATE(record_timestamp) AS date",
            "COUNT(*) FILTER (WHERE classification_manual_agrees = 1) AS agrees_count",
            "COUNT(*) AS total_count"
        ]

        return self._get_dataframe(table, select_items, tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=None, perspective_id=None, not_null_columns=not_null_columns, group_items=group_items)


    def _get_data_for_manual_classification_agreement(self, table, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=["classification_orig", "classification_manual"]):

        select_items = not_null_columns

        return self._get_dataframe(table, select_items, tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=None, perspective_id=None, not_null_columns=not_null_columns)


    def _get_data_for_eval_correlation(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=['classification_manual_agrees', 'evaluation_likert_val']):

        table = self.get_stats_table_eval()
        select_items = ["classification_manual_agrees", "evaluation_likert_val", "feedback_evaluation_likert_val"]
        table = self.get_stats_table_eval()

        return self._get_dataframe(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)


    def _get_data_for_eval_correlation_mode3(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=['evaluation_agreement']):

        table = self.get_stats_table_eval()
        select_items = ["classification_manual_agrees", "evaluation_agreement", "evaluation_agreement_int"]
        table = self.get_stats_table_eval()

        return self._get_dataframe(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)


    def _get_data_for_eval_difference(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=[]):

        table = self.get_stats_table_eval()
        select_items = ["feedback_evaluation_difference_int"]

        return self._get_dataframe(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)


    def _get_data_for_get_evaluation_results_likert(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns = ['evaluation_likert_val']):
       
        table = self.get_stats_table_eval()

        select_items = [
            "evaluation_likert_val",
            "COUNT(*) AS count"
        ]
        group_items = ["evaluation_likert_val"]

        return self._get_dataframe(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns, group_items)


    def _get_data_for_evaluation_results_mode3(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=['evaluation_agreement']):

        table = self.get_stats_table_eval()

        select_items = [
            "evaluation_agreement_int",
            "COUNT(*) AS count"
        ]
        group_items = ["evaluation_agreement_int"]

        return self._get_dataframe(table, select_items, tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns, group_items)


    def _get_distinct_value_counts(self, field_name, table, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, not_null_columns=[]):

        select_items = [
            field_name,
            f"COUNT(*) AS count"
        ]

        group_items = [field_name]

        return self._get_dataframe(table, select_items, tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id, not_null_columns=not_null_columns, group_items=group_items)


    def get_classifications(self, tag_main):

        field = "classification_name"

        sql_generator = self._build_sql_generator(self.get_stats_table_base(), [field], tag_main)
        query_sql, query_params = sql_generator.get_query(distinct=True)
        df = self._query_to_dataframe(query_sql, query_params)

        return df[field].tolist()


    def get_percent_of_classification_manual_agrees(self, tag_main, tag_eval=None, classification_name=None, is_only_with_eval=False, is_only_with_feedback=False, note_text=None, is_include_notes=True):

        if tag_eval:
            table = self.get_stats_table_eval()
        else:
            table = self.get_stats_table_base()

        not_null_columns = []
        if is_only_with_eval:
            not_null_columns.append('evaluation_likert_val')
        if is_only_with_feedback:
            not_null_columns.append('feedback_evaluation_likert_val')

        not_null_columns_with_manual = not_null_columns.copy()
        not_null_columns_with_manual.append('classification_manual_agrees')

        df_with_manual = self._get_data_for_classification_manual_agrees(
                    table, tag_main,
                    tag_eval=tag_eval,
                    classification_name=classification_name,
                    not_null_columns=not_null_columns_with_manual)

        df_all = self._get_data_for_classification_manual_agrees(
                    table, tag_main,
                    tag_eval=tag_eval,
                    classification_name=classification_name,
                    not_null_columns=not_null_columns)

        df_time = self._get_data_for_classification_manual_agrees_detailed(
                    table, tag_main,
                    tag_eval=tag_eval,
                    classification_name=classification_name,
                    not_null_columns=not_null_columns_with_manual)

        percentage = None
        items_with_manual = 0
        total_items = 0

        if not df_with_manual is None:
            row = df_with_manual.iloc[0]
            count_agree = int(row['agrees_count'])
            count_items = int(row['total_count'])
            percentage_agree = (count_agree / count_items) * 100 if count_items > 0 else None

            #percentage = float(df_with_manual.iloc[0]['percentage_agrees']) if pd.notnull(df_with_manual.iloc[0]['percentage_agrees']) else None
            #items_with_manual = int(df_with_manual.iloc[0]['total_count'])

        if not df_all is None:
            dataset_size = int(df_all.iloc[0]['total_count'])

        time_series_stats = []

        if not df_time is None:

            for _, ts_row in df_time.iterrows():

                ts_date = ts_row['date']
                ts_count_items = int(ts_row['total_count'])
                ts_count_agree = int(ts_row['agrees_count'])
                ts_percentage_agree = (ts_count_agree / ts_count_items) * 100 if ts_count_items > 0 else None

                ts_stats_json = {
                    "date": ts_date,
                    "count_items": ts_count_items,
                    "count_agree": ts_count_agree,
                    "percentage_agree": round(ts_percentage_agree, 2)
                }
                time_series_stats.append(ts_stats_json)

        note = self.get_notes("percent_of_classification_manual_agrees", tag_main=tag_main) 
        if tag_eval:
            note["dataset_size"] = f"Total number of items in the dataset '{tag_main}' having tag '{tag_eval}' with or without a manual classification record"
        else:
            note["dataset_size"] = f"Total number of items in the dataset '{tag_main}' with or without a manual classification record"

        self._add_note_item(note, note_text)

        stats_json = {
            "count_items": count_items,
            "count_agree": count_agree,
            "percentage_agree": round(percentage_agree, 2),
            "dataset_size": dataset_size,
            "time_series": time_series_stats
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name)

        return stats_json


    def get_percent_of_classification_manual_agrees_base(self, tag_main, classification_name=None, is_include_notes=True):

        note_text = f"This base statistic is for all records having data for main tag: '{tag_main}' (i.e. it is independent of evaluation tag)"

        return self.get_percent_of_classification_manual_agrees(tag_main, tag_eval=None, classification_name=classification_name, is_only_with_eval=False, is_only_with_feedback=False, note_text=note_text)


    def get_percent_of_classification_manual_agrees_having_eval(self, tag_main, tag_eval, classification_name=None, is_include_notes=True):

        if not tag_eval:
            raise ValueError("Value for tag_eval is missing or empty.")

        note_text = f"This statistic is for records with main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        return self.get_percent_of_classification_manual_agrees(tag_main, tag_eval=tag_eval, classification_name=classification_name, is_only_with_eval=True, is_only_with_feedback=False, note_text=note_text, is_include_notes=is_include_notes)


    def get_percent_of_classification_manual_agrees_having_eval_feedback(self, tag_main, tag_eval, classification_name=None, is_include_notes=True):

        if not tag_eval:
            raise ValueError("Value for tag_eval is missing or empty.")

        note_text = f"This statistic is for records with main tag '{tag_main}' that also have both an evaluation and feedback record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        return self.get_percent_of_classification_manual_agrees(tag_main, tag_eval=tag_eval, classification_name=classification_name, is_only_with_eval=True, is_only_with_feedback=True, note_text=note_text, is_include_notes=is_include_notes)


    def get_pearsonr_for_eval_feedback(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):

        not_null_columns = ['evaluation_likert_val', 'feedback_evaluation_likert_val']
        df = self._get_data_for_eval_correlation(tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)

        if df is None:
            logger.debug(f"No data for pearsonr_for_eval_feedback")
            return None

        df_eval_likert_val = df['evaluation_likert_val'].dropna()
        df_feedback_eval_likert_val = df['feedback_evaluation_likert_val'].dropna()

        std_eval = np.std(df_eval_likert_val)
        std_feedback = np.std(df_feedback_eval_likert_val)

        if std_eval == 0 and std_feedback == 0:
            # Assume that identical constant values imply a perfect positive correlation
            logger.warn(f"Both input arrays are constant for '{tag_eval}'.  Outputting fixed pearsonr_for_eval_feedback")
            #logger.debug(f"eval_likert_val: {df_eval_likert_val}")
            if np.array_equal(df_eval_likert_val, df_feedback_eval_likert_val):
                logger.warn(f"Outputting fixed pearsonr_for_eval_feedback: +1")
                corr = 1.0
            else:
                logger.warn(f"Outputting fixed pearsonr_for_eval_feedback: -1")
                corr = -1.0 
            p_value = 0.0
        elif std_eval == 0 or std_feedback == 0:
            corr = np.nan
            p_value = np.nan
            #logger.debug(f"eval_likert_val: {df_eval_likert_val}")
            #logger.debug(f"feedback_eval_likert_val: {df_feedback_eval_likert_val}")
            logger.error(f"One input array is constant for '{tag_eval}'.  Cannot create pearsonr_for_eval_feedback - correlation coefficient is not defined")
            if std_eval == 0:
                logger.error(f"Input array is constant for eval_likert_val")
            else:
                logger.error(f"Input array is constant for feedback_evaluation_likert_val")
        else:
            corr, p_value = pearsonr(df_eval_likert_val, df_feedback_eval_likert_val)

        note = self.get_notes("pearsonr_for_eval_feedback", tag_main=tag_main) 
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        stats_json = {
            "correlation": round(corr, 3),
            "p_value": round(p_value, 4),
            "item_count": len(df)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name)

        return stats_json


    def get_pointbiserialr_for_eval_agreement(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):

        not_null_columns = ['classification_manual_agrees', 'evaluation_likert_val']
        df = self._get_data_for_eval_correlation(tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)

        if df is None:
            logger.debug(f"No data for pointbiserialr_for_eval_agreement")
            return None

        df_classification_manual_agrees = df['classification_manual_agrees'].dropna()
        df_evaluation_likert_val = df['evaluation_likert_val'].dropna()

        std_c_m_a = np.std(df_classification_manual_agrees)
        std_e_l_v = np.std(df_evaluation_likert_val)

        if std_c_m_a == 0 and std_e_l_v == 0:
            # Assume that identical constant values imply a perfect positive correlation
            logger.warn(f"Both input arrays are constant for '{tag_eval}'.  Outputting fixed get_pointbiserialr_for_eval_agreement")
            logger.debug(f"classification_manual_agrees: {df_classification_manual_agrees}")
            if np.array_equal(df_classification_manual_agrees, df_evaluation_likert_val):
                logger.warn(f"Outputting fixed get_pointbiserialr_for_eval_agreement: +1")
                corr = 1.0
            else:
                logger.warn(f"Outputting fixed get_pointbiserialr_for_eval_agreement: -1")
                corr = -1.0 
            p_value = 0.0
        elif std_c_m_a == 0 or std_e_l_v == 0:
            corr = np.nan
            p_value = np.nan
            logger.debug(f"classification_manual_agrees: {df_classification_manual_agrees}")
            logger.debug(f"evaluation_likert_val: {df_evaluation_likert_val}")
            logger.error(f"One input array is constant for '{tag_eval}'.  Cannot create get_pointbiserialr_for_eval_agreement - correlation coefficient is not defined")
            if std_c_m_a == 0:
                logger.error(f"Input array is constant for classification_manual_agrees")
            else:
                logger.error(f"Input array is constant for evaluation_likert_val")
        else:
            corr, p_value = pointbiserialr(df_classification_manual_agrees, df_evaluation_likert_val)

        note = self.get_notes("pointbiserialr_for_eval_agreement", tag_main=tag_main) 
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        stats_json = {
            "correlation": round(corr, 3),
            "p_value": round(p_value, 4),
            "item_count": len(df)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json


    def get_pointbiserialr_for_eval_feedback_agreement(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):

        not_null_columns = ['classification_manual_agrees', 'feedback_evaluation_likert_val']
        df = self._get_data_for_eval_correlation(tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)

        if df is None:
            logger.debug(f"No data for pointbiserialr_for_eval_feedback_agreement")
            return None

        corr, p_value = pointbiserialr(df['classification_manual_agrees'], df['feedback_evaluation_likert_val'])

        note = self.get_notes("pointbiserialr_for_eval_feedback_agreement", tag_main=tag_main) 
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        stats_json = {
            "correlation": round(corr, 3),
            "p_value": round(p_value, 4),
            "item_count": len(df)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json


    def get_avg_and_spread_for_eval_difference(self, tag_main, tag_eval, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):

        not_null_columns = ['feedback_evaluation_difference_int']
        df = self._get_data_for_eval_difference(tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)

        if df is None:
            logger.debug("No data for avg_and_spread_for_eval_difference")
            return None

        df_item = df['feedback_evaluation_difference_int']

        if df is None:
            logger.debug("No data for avg_and_spread_for_eval_difference")
            return None

        mode_series = df_item.mode()

        counts_series = df_item.value_counts()
        counts_sorted = dict(sorted(counts_series.items(), key=lambda x: int(x[0])))

        #data_list = df['feedback_evaluation_difference_int'].tolist()

        note = self.get_notes("avg_and_spread_for_eval_difference", tag_main=tag_main) 
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        stats_json = {
            "average": round(df_item.mean(), 2),
            "stddev": round(df_item.std(), 2),
            "median": int(df_item.median()),
            "mode": mode_series.tolist(),
            #"items": data_list,
            "counts": counts_sorted,
            "item_count": len(df) # Note: assumes no nulls in df data
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json


    def get_text_stats(self, tag_main, tag_eval, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True, field_name=None):

        if field_name is None:
            raise ValueError("Missing required field_name")
 
        table = self.get_stats_table_eval()
        
        df = self._get_distinct_value_counts(field_name, table, tag_main, tag_eval,
            classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id,
            not_null_columns=[field_name])

        if df is None:
            logger.debug("No data for text_stats")
            return None

        total_count = df['count'].sum()
        df['percentage'] = (df['count'] / total_count) * 100

        df_sorted = df.sort_values(by='percentage', ascending=False)

        stats_json = {
            "occurrences": {},
            "item_count": int(total_count)
        }
        for _, row in df_sorted.iterrows():
            stats_json["occurrences"][row[field_name]] = {
                "count": int(row['count']),
                "percentage": round(row['percentage'], 2)  # rounding percentage to 2 decimal places
            }

        note = self.get_notes("text_stats", tag_main=tag_main, field_name=field_name) 
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        if is_include_notes:
            self._add_note(stats_json, note)

        return stats_json


    def get_phi_coefficient_for_mode3_agreement(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):

        """
        Calculate the Phi Coefficient to assess the relationship between
        evaluation_agreement_int and classification_manual_agrees for mode3 evaluations.
        """

        not_null_columns = ['classification_manual_agrees', 'evaluation_agreement_int']

        df = self._get_data_for_eval_correlation_mode3(tag_main, tag_eval, classification_name, persona_id, perspective_id, not_null_columns)

        if df is None:
            logger.debug(f"No data for phi_coefficient_for_mode3_agreement")
            return None

        contingency_table = pd.crosstab(df['classification_manual_agrees'], df['evaluation_agreement_int'])

        chi2, p_value, _, _ = chi2_contingency(contingency_table)

        # Calculate the Phi coefficient from the Chi-square value
        # Note: np.sqrt(chi2/N) where N is the total number of observations
        phi_coefficient = np.sqrt(chi2 / df.shape[0])

        contingency_cells = contingency_table.to_dict()
        logger.debug(f"contingency_cells: {contingency_cells}")

        contingency_cells_descriptive = {
            "disagree": {
                "both_disagree": contingency_cells.get(0, {}).get(0, 0),
                "only_eval_disagree": contingency_cells.get(0, {}).get(1, 0),
                "_note1": "In this case, the data is for 'disagree', where the mode3 eval and/or manual classification disagree with the evaluated classification",
                "_note2": "Where 'both_disagree', the mode3 eval matches the manual classification and is likely correct (true negative).  Where 'only_eval_disagree', the mode3 eval does not match with the manual classification and is likely incorrect (false negative)"
            },
            "agree": {
                "only_eval_agree": contingency_cells.get(1, {}).get(0, 0),
                "both_agree": contingency_cells.get(1, {}).get(1, 0),
                "_note1": "In this case, the data is for 'agree', where the mode3 eval and/or manual classification agree with the evaluated classification",
                "_note2": "Where 'both_agree', the mode3 eval matches the manual classification and is likely correct (true positive).  Where 'only_eval_agree', the mode3 eval does not match with the manual classification and is likely incorrect (false positive)"
            }
        }

        total_items = len(df)
        matches = df[df['classification_manual_agrees'] == df['evaluation_agreement_int']]
        mismatches = df[df['classification_manual_agrees'] != df['evaluation_agreement_int']]
        match_count = len(matches)
        mismatch_count = len(mismatches)
        match_percentage = (match_count / total_items) * 100 if total_items > 0 else 0
        mismatch_percentage = (mismatch_count / total_items) * 100 if total_items > 0 else 0

        # Adding the new stats as a sub-object
        additional_stats = {
            "total_items": total_items,
            "matches": {
                "count": match_count,
                "percentage": round(match_percentage, 2)
            },
            "mismatches": {
                "count": mismatch_count,
                "percentage": round(mismatch_percentage, 2)
            }
        }

        note = self.get_notes("phi_coefficient_for_mode3_agreement", tag_main=tag_main) 
        extra_note_text = None

        stats_json = {
            "phi_coefficient": round(phi_coefficient, 3),
            "p_value": round(p_value, 4),
            "contingency_cells_desc": contingency_cells_descriptive,
            "contingency_cells_raw": contingency_cells,
            "counts": additional_stats
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json


    def get_cohens_kappa_for_manual_classification_agreement(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):
        """
        Calculate Cohen's Kappa to evaluate the agreement between 'classification_orig'
        and 'classification_manual', adjusting for chance agreement.
        """

        if tag_eval:
            table = self.get_stats_table_eval()
        else:
            table = self.get_stats_table_base()

        logger.debug(f"ckfma classification_name: {classification_name}")

        df = self._get_data_for_manual_classification_agreement(table, tag_main, tag_eval, classification_name, persona_id, perspective_id)

        logger.debug(f"ckfma df: {df.head()}")
        logger.debug(f"ckfma df.size: {df.size}")
        
        print(df['classification_orig'].value_counts())
        print(df['classification_manual'].value_counts())
        print(f"Unique categories in orig: {set(df['classification_orig'])}")
        print(f"Unique categories in manual: {set(df['classification_manual'])}")
        
        logger.debug(f"ckfma s df['classification_orig']: {set(df['classification_orig'])}")
        logger.debug(f"ckfma s df['classification_manual']: {set(df['classification_manual'])}")

        if df is None:
            logger.debug(f"No data for cohens_kappa_for_manual_classification_agreement")
            return None

        kappa_score = cohen_kappa_score(df['classification_orig'], df['classification_manual'])

        note = self.get_notes("cohens_kappa_for_manual_classification_agreement", tag_main=tag_main) 

        stats_json = {
            "kappa_score": round(kappa_score, 3)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json


    def get_evaluation_results_likert(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):
        """
        Compute statistics for evaluation_likert_val grouped by classification_name with optional filters.
        Includes percentage agreement (Likert 4 and 5) and a weighted agreement score.
        """
        df = self._get_data_for_get_evaluation_results_likert(tag_main, tag_eval, classification_name, persona_id, perspective_id)

        if df is None or df.empty:
            return None

        total_count = df["count"].sum()

       # Calculate Likert distribution
        likert_distribution = df.set_index("evaluation_likert_val")["count"].reindex(range(1, 6), fill_value=0)
        percentages = (likert_distribution / total_count) * 100

        # Calculate mean, standard deviation, and agreement percentage
        mean_val = np.average(likert_distribution.index, weights=likert_distribution)
        stddev_val = np.std(likert_distribution.index, ddof=1)
        agreement_percentage = percentages.loc[4:5].sum()

        # Weighted Agreement Score
        weights = {1: 0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1}

        # Calculate weighted agreement score
        weights = {1: 0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1}
        weighted_sum = sum(likert_distribution * likert_distribution.index.map(weights))
        total_sum = likert_distribution.sum()
        weighted_score = weighted_sum / total_sum if total_sum > 0 else 0.0

        note = self.get_notes("evaluation_results_likert", tag_main=tag_main)
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode1 or mode2 evaluation (having an evaluationLikert)"

        stats_json = {
            "mean_likert": round(mean_val, 2),
            "stddev": round(stddev_val, 2),
            "agreement_percentage": round(agreement_percentage, 2),
            "weighted_agreement_score": round(weighted_score, 2),
            "distribution": percentages.to_dict(),
            "total_count": int(total_count)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)
        
        #return self.convert_numpy_to_native(stats_json)
        return stats_json


    def get_evaluation_results_mode3(self, tag_main, tag_eval=None, classification_name=None, persona_id=None, perspective_id=None, is_include_notes=True):
        """
        Compute binary agreement statistics based on evaluation_agreement_int (0 for disagree, 1 for agree).
        """
        df = self._get_data_for_evaluation_results_mode3(tag_main, tag_eval, classification_name, persona_id, perspective_id)

        if df is None or df.empty:
            return None

        total_count = df['count'].sum()

        # Distribution of 0 (disagree) and 1 (agree)
        agreement_distribution = df.set_index('evaluation_agreement_int')['count'].reindex([0, 1], fill_value=0)
        percentages = (agreement_distribution / total_count) * 100

        # Agreement statistics
        agreement_percentage = percentages.loc[1]
        weighted_agreement_score = agreement_distribution.loc[1] / total_count

        note = self.get_notes("evaluation_results_mode3", tag_main=tag_main)
        extra_note_text = f"This statistic has been calculated for data having main tag '{tag_main}' that also have an evaluation record for tag '{tag_eval}'.  Note that this refers to a mode3 evaluation (having an evaluationAgreement)"

        stats_json = {
            "agreement_percentage": round(agreement_percentage, 2),
            "weighted_agreement_score": round(weighted_agreement_score, 2),
            "distribution": percentages.to_dict(),
            "total_count": int(total_count)
        }

        self._append_standard_notes(stats_json, is_include_notes=is_include_notes, note=note, extra_note_text=extra_note_text, tag_main=tag_main, tag_eval=tag_eval, classification_name=classification_name, persona_id=persona_id, perspective_id=perspective_id)

        return stats_json