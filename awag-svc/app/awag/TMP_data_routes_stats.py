# Copyright 2023-2024 David Goddard.
#
# This file is part of AwAg Data Services.
#
# AwAg Data Services is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License (AGPL), either
# version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# This file includes code based on boilerplate from Idris Rampurawala,
# originally under the MIT License. Original boilerplate code Copyright 2020
# by Idris Rampurawala. The full text of the MIT License for the original
# boilerplate code can be found in the accompanying file named
# 'LICENSE-MIT.txt' or at https://opensource.org/licenses/MIT.

import json
import time
import types
import ast
import io

from flask import Blueprint, current_app, g, jsonify, request, make_response
from flask import send_file

from datetime import datetime, timedelta
from collections import defaultdict
from io import StringIO

from domestique.logging import log_exception
from domestique.flask.request import get_reqjson, get_arg, get_reqjson_val, get_required_arg, get_required_reqjson_val
from domestique.flask.response import ResponseWrapper
from domestique.db import conn_rollback, conn_close, concat_sql
from domestique.db.sqlite import get_db_conn
from domestique.convert import str_to_bool

from authentication import require_api_auth

from .shared_resources import logger, init_route, get_agent_name_from_id

#from .awag_stats_engine import StatsEngine
from .awag_stats_engine_ext import StatsEngineExtended
from .awag_stats_engine_ext_df import StatsEngineExtendedDataFrames


stats_routes = Blueprint('stats_routes', __name__)


stats_table_base = "reporting_base"
stats_table_eval = "reporting_evaluation_feedback"


def init_db_tables(conn):

    pass


def log_exception(agent_id, e):

    message = f"An error occurred for agent_id '{agent_id}' in '{get_calling_method_name_quick(True)}': {e}"
    logger.exception(message, exc_info=False)
    return message


def recursive_defaultdict():

    return defaultdict(recursive_defaultdict)


def is_breakdown(request, breakdown_name, default=False):

    include_variants = get_arg(request, "includeVariants", None)
    # includeVariants parameter overrides if present
    if include_variants is not None:
        if include_variants:
            return True

    include_breakdowns = json.loads(get_arg(request, "includeBreakdowns", "{}"))
    return include_breakdowns.get(breakdown_name, default)


@stats_routes.before_request
def before_request():
  
    g.notes_dict = current_app.config["STATS_NOTES"]
    g.agent_lookup = current_app.config["AGENT_LOOKUP"]


@stats_routes.route('/get-general-stats', methods=['GET'])
@require_api_auth
def get_general_stats():

    agent_id, resp, conn = init_route(request)

    try:

        tag_main = get_required_arg(request, "tagMain")
        tag_eval = get_required_arg(request, "tagEval")

        persona_id = get_arg(request, "personaId", None)
        perspective_id = get_arg(request, "perspectiveId", None)
        classification_name = get_arg(request, "classificationName", None)

        is_include_breakdown_having_eval = is_breakdown(request, "having_eval", False)
        is_include_breakdown_having_feedback = is_breakdown(request, "having_feedback", False)
        #is_include_breakdown_classifications = is_breakdown(request, "classifications", False)
        is_include_breakdown_classifications = is_breakdown(request, "classifications", True)

        is_include_empty = request.args.get('includeEmpty', type=str_to_bool, default=True)

        conn = get_db_conn()

        stats_engine = StatsEngineExtended(agent_id, conn, stats_table_base, stats_table_eval, notes_dict=g.notes_dict)

        classifications_list = stats_engine.get_classifications(tag_main)

        if is_include_breakdown_classifications:
            percent_of_classification_manual_agrees_base = stats_engine.get_percent_of_classification_manual_agrees_base_cl(tag_main)
        else:
            percent_of_classification_manual_agrees_base = stats_engine.get_percent_of_classification_manual_agrees_base(tag_main, classification_name=classification_name)
        logger.debug(f"Got stat 'percent_of_classification_manual_agrees_base': {percent_of_classification_manual_agrees_base}")

        if is_include_breakdown_having_eval:
            percent_of_classification_manual_agrees_having_eval = stats_engine.get_percent_of_classification_manual_agrees_having_eval(tag_main, tag_eval, classification_name=classification_name)
            logger.debug(f"Got stat 'percent_of_classification_manual_agrees_having_eval': {percent_of_classification_manual_agrees_having_eval}")

        if is_include_breakdown_having_feedback:
            percent_of_classification_manual_agrees_having_eval_feedback = stats_engine.get_percent_of_classification_manual_agrees_having_eval_feedback(tag_main, tag_eval, classification_name=classification_name)
            logger.debug(f"Got stat 'percent_of_classification_manual_agrees_having_eval_feedback': {percent_of_classification_manual_agrees_having_eval_feedback}")

        cohens_kappa_for_manual_classification_agreement = stats_engine.get_cohens_kappa_for_manual_classification_agreement(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'cohens_kappa_for_manual_classification_agreement': {cohens_kappa_for_manual_classification_agreement}")

        if is_include_breakdown_classifications:
            pearsonr_for_eval_feedback = stats_engine.get_pearsonr_for_eval_feedback_cl(tag_main, tag_eval, persona_id, perspective_id)
        else:
            pearsonr_for_eval_feedback = stats_engine.get_pearsonr_for_eval_feedback(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'pearsonr_for_eval_feedback': {pearsonr_for_eval_feedback}")

        pointbiserialr_for_eval_agreement = stats_engine.get_pointbiserialr_for_eval_agreement(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'pointbiserialr_for_eval_agreement': {pointbiserialr_for_eval_agreement}")

        pointbiserialr_for_eval_feedback_agreement = stats_engine.get_pointbiserialr_for_eval_feedback_agreement(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'pointbiserialr_for_eval_feedback_agreement': {pointbiserialr_for_eval_feedback_agreement}")
        
        avg_and_spread_for_eval_difference = stats_engine.get_avg_and_spread_for_eval_difference(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'avg_and_spread_for_eval_difference': {avg_and_spread_for_eval_difference}")

        text_stats_evaluation_likert = stats_engine.get_text_stats(tag_main, tag_eval, classification_name, persona_id, perspective_id, field_name="evaluation_likert_text")
        logger.debug(f"Got stat 'text_stats_evaluation_likert': {text_stats_evaluation_likert}")

        text_stats_feedback_evaluation_likert = stats_engine.get_text_stats(tag_main, tag_eval, classification_name, persona_id, perspective_id, field_name="feedback_evaluation_likert_text")
        logger.debug(f"Got stat 'text_stats_feedback_evaluation_likert': {text_stats_feedback_evaluation_likert}")

        text_stats_evaluation_likert_simple = stats_engine.get_text_stats(tag_main, tag_eval, classification_name, persona_id, perspective_id, field_name="evaluation_likert_simple")
        logger.debug(f"Got stat 'text_stats_evaluation_likert_simple': {text_stats_evaluation_likert_simple}")

        text_stats_feedback_evaluation_likert_simple = stats_engine.get_text_stats(tag_main, tag_eval, classification_name, persona_id, perspective_id, field_name="feedback_evaluation_likert_simple")
        logger.debug(f"Got stat 'text_stats_feedback_evaluation_likert_simple': {text_stats_feedback_evaluation_likert_simple}")

        text_stats_feedback_evaluation_difference = stats_engine.get_text_stats(tag_main, tag_eval, classification_name, persona_id, perspective_id, field_name="feedback_evaluation_difference_text")
        logger.debug(f"Got stat 'text_stats_feedback_evaluation_difference': {text_stats_feedback_evaluation_difference}")

        phi_coefficient_for_mode3_eval_agreement = stats_engine.get_phi_coefficient_for_mode3_agreement(tag_main, tag_eval, classification_name, persona_id, perspective_id)
        logger.debug(f"Got stat 'phi_coefficient_for_mode3_eval_agreement': {phi_coefficient_for_mode3_eval_agreement}")

        statistics = {}
        likert_values = {}

        if stats_engine.should_include_stat(percent_of_classification_manual_agrees_base, is_include_empty):
            statistics["percent_of_classification_manual_agrees"] = {"base": percent_of_classification_manual_agrees_base}

        #if stats_engine.should_include_stat(percent_of_classification_manual_agrees_base_df, is_include_empty):
        #    statistics["percent_of_classification_manual_agrees_df"] = {"base": df_to_json(percent_of_classification_manual_agrees_base_df)}

        if is_include_breakdown_having_eval:
            if stats_engine.should_include_stat(percent_of_classification_manual_agrees_having_eval, is_include_empty):
                statistics["percent_of_classification_manual_agrees"].setdefault("having_eval", percent_of_classification_manual_agrees_having_eval)

        if is_include_breakdown_having_feedback:
            if stats_engine.should_include_stat(percent_of_classification_manual_agrees_having_eval_feedback, is_include_empty):
                statistics["percent_of_classification_manual_agrees"].setdefault("having_eval_feedback", percent_of_classification_manual_agrees_having_eval_feedback)

        if stats_engine.should_include_stat(cohens_kappa_for_manual_classification_agreement, is_include_empty):
            statistics["cohens_kappa_for_manual_classification_agreement"] = cohens_kappa_for_manual_classification_agreement

        if stats_engine.should_include_stat(pearsonr_for_eval_feedback, is_include_empty):
            statistics["r_for_eval_feedback"] = pearsonr_for_eval_feedback

        if stats_engine.should_include_stat(pointbiserialr_for_eval_agreement, is_include_empty):
            statistics["rpb_for_eval_agreement"] = pointbiserialr_for_eval_agreement

        if stats_engine.should_include_stat(pointbiserialr_for_eval_feedback_agreement, is_include_empty):
            statistics["rpb_for_eval_feedback_agreement"] = pointbiserialr_for_eval_feedback_agreement

        if stats_engine.should_include_stat(avg_and_spread_for_eval_difference, is_include_empty):
            statistics["avg_and_spread_for_eval_difference"] = avg_and_spread_for_eval_difference

        likert_keys = ["evaluation_likert", "feedback_evaluation_likert", "evaluation_likert_simple", "feedback_evaluation_likert_simple", "feedback_evaluation_difference"]
        likert_stats = [text_stats_evaluation_likert, text_stats_feedback_evaluation_likert, text_stats_evaluation_likert_simple, text_stats_feedback_evaluation_likert_simple, text_stats_feedback_evaluation_difference]

        for key, stat in zip(likert_keys, likert_stats):
            if stats_engine.should_include_stat(stat, is_include_empty):
                likert_values[key] = stat

        if likert_values:
            statistics["likert_values"] = likert_values

        if stats_engine.should_include_stat(phi_coefficient_for_mode3_eval_agreement, is_include_empty):
            statistics["phi_coefficient_for_mode3_eval_agreement"] = phi_coefficient_for_mode3_eval_agreement

        statistics["all_classifications_list"] = classifications_list

        response_data = {
            "filters": {
                "agent_id": agent_id,
                "tag_main": tag_main,
                "tag_eval": tag_eval,
                "classification_name": classification_name,
                "persona_id": persona_id,
                "perspective_id": perspective_id
            },
            "statistics": statistics
        }

        response_json = {
            "status": "OK",
            "message": "OK",
            "data": response_data
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as err:

        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)


@stats_routes.route('/get-tabular-stats', methods=['GET'])
@require_api_auth
def get_tabular_stats():

    agent_id, resp, conn = init_route(request)

    try:

        response_format = get_arg(request, "format", "json").lower()

        tag_main = get_required_arg(request, "tagMain")
        tags_eval_raw = get_required_arg(request, "tagsEval")

        persona_id = get_arg(request, "personaId", None)
        perspective_id = get_arg(request, "perspectiveId", None)

        tags_lit = ast.literal_eval(tags_eval_raw)
        if isinstance(tags_lit, list):
            tags_eval = tags_lit
        else:
            tags_eval = [tags_eval_raw]

        is_include_empty = request.args.get("includeEmpty", type=str_to_bool, default=True)
        is_minimal_latex = request.args.get("minimal", type=str_to_bool, default=False)

        conn = get_db_conn()

        stats_engine = StatsEngineExtendedDataFrames(agent_id, conn, stats_table_base, stats_table_eval, notes_dict=g.notes_dict)

        likert_fields = ["evaluation_likert_text", "feedback_evaluation_likert_text", "evaluation_likert_simple", "feedback_evaluation_likert_simple", "feedback_evaluation_difference_text"]

        if response_format == "excel":
            output_json = False
        else:
            output_json = True

        stats_df_pack, stats_json_pack = stats_engine.build_stats_pack(tag_main, tags_eval, likert_fields, persona_id, perspective_id, is_include_empty, output_json=output_json)

        agent_name = get_agent_name_from_id(g.agent_lookup, agent_id)

        '''
        percent_of_classification_manual_agrees_df, percent_of_classification_manual_agrees_ts_df_dict = stats_engine.get_percent_of_classification_manual_agrees_base_df(tag_main)
        logger.debug(f"Got stat 'percent_of_classification_manual_agrees_df': {percent_of_classification_manual_agrees_df}")
        '''
        def generate_filename(extension):

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = f"stats-{agent_name}-{tag_main}"
            if persona_id:
                filename += f"-{persona_id}"
            if perspective_id:
                filename += f"-{perspective_id}"
            return f"{filename}-{timestamp}.{extension}"

        if response_format == "latex":

            latex_content = stats_engine.convert_stats_pack_to_latex(agent_name, stats_df_pack, tag_main=tag_main, minimal=is_minimal_latex)

            filename = generate_filename("tex")

            response = make_response(latex_content)
            response.headers["Content-Disposition"] = f"attachment; filename={filename}"
            response.mimetype = "application/x-tex"
            return response

        elif response_format == "excel":

            engine="openpyxl"
            #engine = "xlsxwriter"

            filename = generate_filename("xlsx")

            excel_file = stats_engine.convert_stats_pack_to_excel(stats_df_pack, engine, tag_main=tag_main)

            return send_file(
                io.BytesIO(excel_file),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=filename
            )

        response_data = {
            "filters": {
                "agent_id": agent_id,
                "tag_main": tag_main,
                "tags_eval": tags_eval,
                "persona_id": persona_id,
                "perspective_id": perspective_id
            },
            "statistics": stats_json_pack
        }

        response_json = {
            "status": "OK",
            "message": "OK",
            "data": response_data
        }

        return resp.generate_response_with_data(response_json, 200)

    except Exception as err:

        return resp.generate_response_with_exception(err)

    finally:

        conn_close(conn)




