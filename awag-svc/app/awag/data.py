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

from flask import Blueprint, current_app, g

awag_data = Blueprint('awag_data', __name__)

from .data_routes_flow import flow_monitor_routes
awag_data.register_blueprint(flow_monitor_routes, url_prefix='/flow')

from .data_routes_summ import summarisation_routes
awag_data.register_blueprint(summarisation_routes, url_prefix='/summ')

from .data_routes_sim import simulation_routes
awag_data.register_blueprint(simulation_routes, url_prefix='/sim')

from .data_routes_eval import evaluation_routes
awag_data.register_blueprint(evaluation_routes, url_prefix='/eval')

from .data_routes_class import classification_routes
awag_data.register_blueprint(classification_routes, url_prefix='/class')

from .data_routes_misc import misc_routes
awag_data.register_blueprint(misc_routes, url_prefix='/misc')

from .data_routes_reporting import reporting_routes
awag_data.register_blueprint(reporting_routes, url_prefix='/reporting')

from .data_routes_train import training_routes
awag_data.register_blueprint(training_routes, url_prefix='/train')

from .data_routes_fixit import fixit_routes
awag_data.register_blueprint(fixit_routes, url_prefix='/fixit')

from .data_routes_chat import chat_routes
awag_data.register_blueprint(chat_routes, url_prefix='/chat')

from .data_routes_gentrain import gentraining_routes
awag_data.register_blueprint(gentraining_routes, url_prefix='/gentrain')

from .data_routes_subsets import subsets_routes
awag_data.register_blueprint(subsets_routes, url_prefix='/subsets')

from .data_routes_stats import stats_routes
awag_data.register_blueprint(stats_routes, url_prefix='/stats')

from .data_routes_maintain import maintenance_routes
awag_data.register_blueprint(maintenance_routes, url_prefix='/maintenance')
