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

import json
import sys
import time
import types
import os
import shutil

import numpy as np
import sklearn
from flask import Blueprint, current_app, g, jsonify, request
from sklearn import metrics
from sklearn.datasets import fetch_20newsgroups, load_files
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import (CountVectorizer,
                                             HashingVectorizer,
                                             TfidfTransformer, TfidfVectorizer)
from sklearn.feature_selection import SelectFromModel, SelectKBest, chi2
from sklearn.linear_model import (PassiveAggressiveClassifier, Perceptron,
                                  RidgeClassifier, SGDClassifier)
from sklearn.naive_bayes import BernoulliNB, ComplementNB, MultinomialNB
from sklearn.neighbors import KNeighborsClassifier, NearestCentroid
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC
from sklearn.utils.extmath import density
from sklearn.utils import Bunch
from werkzeug.local import LocalProxy

from domestique.text import truncate_string, tidy_and_truncate_string

from authentication import require_appkey, require_agent_in_json, require_agent_as_param
from .shared_resources import logger

from datetime import datetime

from collections import Counter

from .tasks import test_task


awag_ml = Blueprint('awag_ml', __name__)

persistent = types.SimpleNamespace()
persistent.defaults = types.SimpleNamespace()
persistent.defaults.id = ""
persistent.is_init = False

TRAIN = 'train'
TEST = 'test'
ALL = 'all'
CLASSIFIED = 'classified'


def getPipelineNB():
    clf = Pipeline([
        ('vect', CountVectorizer()),
        ('tfidf', TfidfTransformer()),
        ('clf', MultinomialNB()),
    ])
    return clf


def getPipelineSVM():
    clf = Pipeline([
        ('vect', CountVectorizer()),
        ('tfidf', TfidfTransformer()),
        ('clf', SGDClassifier(loss='modified_huber', penalty='l1',
                              alpha=1e-5, random_state=42,
                              max_iter=5, tol=None)),
    ])
    return clf


def get_len(dataset):

    if not dataset:
        return 0
    else:
        len(dataset.get("data", []))


def get_len(dataset):

    if not dataset:
        return 0
    else:
        return len(dataset.get("data", []))


def get_snippet(dataset, item_count, len):

    if not dataset:
        return ""
    else:
        retval = ""
        data = dataset.get("data", [])
        for item in data[:item_count]:
            if retval != "":
                retval += ", "
            retval += f"\"{truncate_string(item, len)}\""
            retval += " ... "
        return retval
    

def fit(agent_id, model_id, dataset):

    clf = get_clf(agent_id, model_id)
    logger.debug(f"Fitting classifier for {agent_id} and model {model_id}: {type(clf)}")
    logger.debug(f"Using dataset.data with size: {get_len(dataset)}: {get_snippet(dataset, 5, 20)}")

    is_fittable = True

    target = dataset.get("target", None)
    if target is None:
        key_counts = Counter().keys()
        value_counts = Counter().values()
    else:
        key_counts = Counter(dataset.target).keys()
        value_counts = Counter(dataset.target).values()
    logger.debug(f"Counter keys is: {key_counts}")
    logger.debug(f"Counter values is: {value_counts}")

    # Workaround for 'ValueError: The number of classes has to be greater than one; got 1 class'
    if len(key_counts) < len(dataset.get("target_names", [])):
        logger.warn(f"Will not do fit - dataset not complete (fewer targets than target names): {value_counts}")
        # This is the case if data not entered for each classification
        is_fittable = False
    if is_fittable:
        for count in value_counts:
            if count < 2:
                is_fittable = False
                continue
 
    if target is None:
        logger.warn("Will not do fit - no .target in dataset")
    elif not is_fittable:
        logger.warn(f"Will not do fit - dataset not complete: {value_counts}")
    else:
        clf.fit(dataset.get("data", []), dataset.target)

    logger.debug("Fit complete")


def classify(agent_id, model_id, data, target_names):

    if target_names is None:
        return None

    # print(target_names)

    clf = get_clf(agent_id, model_id)
    #logger.debug(f"clf: {clf}")

    predicted = clf.predict(data)
    logger.debug(f"type(predicted): {type(predicted)}")
    iterator = 0
    for doc, category in zip(data, predicted):
        # time.sleep(0.01)
        iterator += 1
        #if iterator <= 20:
            #logger.info('%r %s : %r' %
            #            (category, target_names[category], doc[:80]))
            # print('%r => %s' % (doc, target_names[category]))
            # print('%r => %s' % (iterator, target_names[category]))

    logger.debug(f"Got classification '{predicted}' of '{target_names}' for data: {tidy_and_truncate_string(str(data), 100)}")

    return predicted


def is_agent_valid(agent_id):

    # Currently works simply by checking the agent container directory exists

    logger.debug("Checking validity of agent: " + agent_id)

    valid = True

    if not agent_id:
        valid = False

    container_dir = os.path.join(current_app.config['CONTAINER_PATH_ROOT'], agent_id)

    if not os.path.isdir(container_dir):
        valid = False

    if valid:
        logger.debug("Agent is valid: " + agent_id)
    else:
        logger.info("Agent is NOT valid: " + agent_id)

    return valid


def get_container_dir_for_agent(agent_id):

    logger.debug("Getting container_dir for agent: " + agent_id)
    container_dir = os.path.join(current_app.config['CONTAINER_PATH_ROOT'], agent_id)

    if not os.path.isdir(container_dir):
        os.mkdir(container_dir)
        logger.debug("Created directory: " + container_dir);

    logger.info("Container dir (" + agent_id + "): " + container_dir);

    return container_dir


def get_models_dir_for_agent(agent_id):

    logger.debug("Getting models_dir for agent: " + agent_id)
    container_dir = get_container_dir_for_agent(agent_id)

    models_dir = os.path.join(container_dir, current_app.config['CONTAINER_SUBDIR_MODELS'])

    if not os.path.isdir(models_dir):
        os.mkdir(models_dir)
        logger.debug("Created directory: " + models_dir);

    logger.info("Models dir (" + agent_id + "): " + models_dir);

    return models_dir


def get_deleted_dir_for_agent(agent_id):

    logger.debug("Getting deleted_dir for agent: " + agent_id)
    deleted_dir = os.path.join(current_app.config['CONTAINER_PATH_DELETED'], agent_id)

    if not os.path.isdir(deleted_dir):
        os.mkdir(deleted_dir)
        logger.debug("Created directory: " + deleted_dir);

    logger.info("Deleted dir (" + agent_id + "): " + deleted_dir);

    return deleted_dir


def get_models_metadata_filepath(agent_id):

    container_dir = get_container_dir_for_agent(agent_id)
    return os.path.join(container_dir, current_app.config['MODELS_METADATA_FILENAME'])


def load_model_metadata(agent_id):

    filepath = get_models_metadata_filepath(agent_id)
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return {}


def save_model_metadata(agent_id, model_metadata):

    filepath = get_models_metadata_filepath(agent_id)
    with open(filepath, 'w') as f:
        logger.debug("Saving model_metadata to: " + filepath)
        json.dump(model_metadata, f, indent=4)


def delete_model_metadata(agent_id, model_id):

    metadata = load_model_metadata(agent_id)

    if model_id in metadata:
        del metadata[model_id]
        save_model_metadata(agent_id, metadata)
        logger.info(f"All metadata for model {model_id} deleted.")
    else:
        logger.warn(f"No metadata found for model {model_id}.")


def get_model_metadata_item(agent_id, model_id, metadata_name):

    metadata = load_model_metadata(agent_id)
    this_model_metadata = metadata.get(model_id, {})
    return this_model_metadata.get(metadata_name, None)


def put_model_metadata_item(agent_id, model_id, metadata_name, metadata_value):

    metadata = load_model_metadata(agent_id)

    if model_id not in metadata:
        metadata[model_id] = {}
    metadata[model_id][metadata_name] = metadata_value

    save_model_metadata(agent_id, metadata)


def create_empty_dataset():

    # See https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_files.html

    dataset = Bunch()
    dataset.data = []
    dataset.target_names = []
    dataset.target = None
    dataset.filenames = None

    return dataset


def init_dataset(agent_id, model_id, model_path):

    logger.debug(f"Initialising dataset for agent '{agent_id}' with model_id: {model_id}")
    logger.debug(f"Model path: {model_path}")

    container_subdir_train = current_app.config['CONTAINER_SUBDIR_TRAIN']
    container_subdir_test = current_app.config['CONTAINER_SUBDIR_TEST']

    container_path_train = os.path.join(model_path, container_subdir_train)
    container_path_test = os.path.join(model_path, container_subdir_test)

    logger.info(f"Value of container_path_train: {container_path_train}")
    logger.info(f"Value of container_path_test: {container_path_test}")
	
    data = get_data(agent_id, model_id)

    logger.debug(f"init_dataset got data for '{model_id}': {truncate_string(data, 150)}")

    data[TRAIN] = load_files(
        container_path_train, description=None, categories=None, load_content=True, shuffle=True, encoding="unicode_escape"
    )

    data[TEST][ALL] = load_files(
        container_path_test, description=None, categories=None, load_content=True, shuffle=True, encoding="utf-8", decode_error='strict', random_state=0
    )

    logger.debug(f"Initial '{model_id}' data[TRAIN]: {truncate_string(data[TRAIN], 150)}")
    logger.debug(f"Initial '{model_id}' data[TEST][ALL]: {truncate_string(data[TEST][ALL], 150)}")

    data_test_classified = data[TEST][CLASSIFIED]

    for file in os.listdir(container_path_test):
        d = os.path.join(container_path_test, file)
        if os.path.isdir(d):
            logger.info(f"Found test classification: '{file}' with path: {d}'")
            data_test_classified[file] = load_files(
                container_path_test, description=None, categories=[file], load_content=True, shuffle=True, encoding="utf-8", decode_error='strict', random_state=0
            )
            logger.debug(f"Loaded data_test_classified['{file}'']: {data_test_classified[file]}")

    logger.debug(f"'{model_id}' data[TRAIN].data has size: {len(data[TRAIN].data)}")
    logger.debug(f"'{model_id}' data[TEST][ALL].data has size: {len(data[TEST][ALL].data)}")
    for classification in data_test_classified:
        this_data = data_test_classified[classification]
        #logger.debug(f"classification: {classification}")
        #logger.debug(f"data_test_classified: {data_test_classified}")
        #logger.debug(f"type(data_test_classified): {type(data_test_classified)}")
        #logger.debug(f"this_data: {this_data}")
        #logger.debug(f"type(this_data): {type(this_data)}")
        logger.debug(f"Model '{model_id}' data[TEST][CLASSIFIED]['{classification}'].data has size: {len(this_data.data)}")
        it = np.nditer(this_data.target, flags=['c_index', 'zerosize_ok'])
        for x in it:
            logger.debug("%d: <%d> %s" % (it.index, x, tidy_and_truncate_string(this_data.data[it.index], 100)))
            #logger.debug("%d: <%d> %s" % (it.index, x, this_data.data[it.index]))

    if len(data[TRAIN].data) > 0:
        fit(agent_id, model_id, data[TRAIN])
    logger.info(f"Model '{model_id}' target_names: {data[TRAIN].target_names}")
    logger.info(f"Fit complete for model_id: {model_id}")


def get_clf(agent_id, model_id):

    if not hasattr(persistent, 'clf_dict'):
        logger.debug("Creating new clf_dict store")
        persistent.clf_dict = {}

    clf_key = (agent_id, model_id)
    if clf_key not in persistent.clf_dict:
        logger.debug(f"Creating new clf_dict for key: {clf_key}")
        persistent.clf_dict[clf_key] = getPipelineSVM()

    clf = persistent.clf_dict[clf_key]
    #logger.debug(f"Obtained clf_dict for key '{clf_key}': [{type(clf)}] {clf}")
    return clf


def get_data_dict(agent_id):

    if not hasattr(persistent, 'data_dict'):
        logger.info('get_data_dict - create new')
        persistent.data_dict = {}

    # lol https://stackoverflow.com/questions/10724766/pythons-hasattr-on-list-values-of-dictionaries-always-returns-false
    data_dict = persistent.data_dict.get(agent_id, {})
    persistent.data_dict[agent_id] = data_dict

    logger.debug(f"Method get_data_dict returning for agent '{agent_id}': {truncate_string(persistent.data_dict[agent_id], 120)}")

    return persistent.data_dict[agent_id]


def delete_data(agent_id, model_id):

    if model_id is None:
        return

    data_dict = get_data_dict(agent_id)

    if not model_id in data_dict:
        return

    logger.info('delete_data for model_id: ' + model_id)
    del data_dict[model_id]

    return 


def get_data(agent_id, model_id):

    logger.debug("get_data for agent '" + agent_id + "' and model: " + str(model_id))

    data_dict = get_data_dict(agent_id)

    model_id_use = model_id
    if model_id is None:
        model_id_use = persistent.defaults.id
        logger.info('get_data passed null model_id, using default: ' + model_id_use)
    else:
        logger.info('get_data for model_id: ' + model_id)

    if not model_id_use in data_dict:
        logger.info('get_data - create new item for id: ' + model_id_use)
        #data_dict[model_id_use] = types.SimpleNamespace()
        data_dict[model_id_use] = {}

    data = data_dict[model_id_use]

    if not TRAIN in data:
        logger.debug(f"get_data - create 'train' for id: {model_id_use}")
        #data[TRAIN] = types.SimpleNamespace()
        data[TRAIN] = create_empty_dataset()

    if not TEST in data:
        logger.debug(f"get_data - create 'test' for id: {model_id_use}")
        #data[TEST] = types.SimpleNamespace()
        data[TEST] = create_empty_dataset()

    if not ALL in data[TEST]:
        data[TEST][ALL] = create_empty_dataset()

    if not CLASSIFIED in data[TEST]:
        data[TEST][CLASSIFIED] = {}

    #logger.debug('get_data - returning: ' + repr(data))

    return data


def get_models(agent_id):

    logger.debug("Querying existing models for agent: " + agent_id)
    models = []

    models_dir = get_models_dir_for_agent(agent_id)
    logger.debug("Models container directory is: " + models_dir)

    for file in os.listdir(models_dir):
        d = os.path.join(models_dir, file)
        if os.path.isdir(d):
            logger.info(f"Found model directory: '{file}' with path: {d}")
            desc = get_model_desc(agent_id, file)
            models.append({"model_id": file, "model_desc": desc})

    logger.info('Got existing models: ' + str(models))

    return models


def get_model_desc(agent_id, model_id):

    return get_model_metadata_item(agent_id, model_id, 'desc')


def update_model_desc(agent_id, model_id, model_desc):

    if not is_model_existing(agent_id, model_id):
        logger.error(f"Model does not exist: {model_id}")
        return "Error: Model does not exist."

    put_model_metadata_item(agent_id, model_id, 'desc', model_desc)
    logger.info(f"Description for model {model_id} updated.")


def update_model_desc(agent_id, model_id, model_desc):

    if not is_model_existing(agent_id, model_id):
        logger.error(f"Model does not exist: {model_id}")
        return "Error: Model does not exist."

    put_model_metadata_item(agent_id, model_id, 'desc', model_desc)
    logger.info(f"Description for model {model_id} updated.")


def get_classification_name(agent_id, model_id, index):

    logger.debug(f"get_classification_name for agent '{agent_id}' with index: {index}")
    logger.debug(f"Model ID is: {model_id}")

    data = get_data(agent_id, model_id)
    data_test_all = data[TEST][ALL]

    logger.debug(f"len(data_test_all.target_names): {len(data_test_all.target_names)}")

    if index + 1 in range(1, len(data_test_all)):
        name = data_test_all.target_names[index]
        logger.debug(f"Classification at index {index} has name: {name}")
        return name
    else:
        logger.debug("data_test_all does not have entry with this index!")
        return None


def get_classification_index(agent_id, model_id, name):

    logger.debug(f"get_classification_index for agent '{agent_id}' for name: {name}")

    data = get_data(agent_id, model_id)
    data_test_all = data[TEST][ALL]

    if not hasattr(data_test_all, "target_names"):
        logger.debug("data_test_all has no target_names")
        setattr(data_test_all, 'target_names', [])

    if name in data_test_all.target_names:
        index = data_test_all.target_names.index(name)
        logger.debug(f"Classification '{name}' has index: {index}")
        return index
    else:
        logger.debug(f"Classification '{name}' not found in target names - adding...")
        data_test_all.target_names.append(name)
        index = data_test_all.target_names.index(name)
        logger.debug(f"Added new classification '{name}' with index: {index}")
        return index


def is_model_existing(agent_id, model_id):

    logger.debug(f"Checking if model exists for agent '{agent_id}': {model_id}")

    models = get_models(agent_id)
    model_ids = [model['model_id'] for model in models]

    if model_id in model_ids:
        logger.debug(f"Model does exist: {model_id}")
        return True
    else:
        logger.debug(f"Model does NOT exist: {model_id}")
        return False


def add_classifications(agent_id, model_id, classifications):

    logger.debug(f"Adding classifications to model for agent '{agent_id}': {model_id}")
    if not is_model_existing(agent_id, model_id):
        logger.error(f"Model does not exist: {model_id}")
        return

    if classifications is None:
        return;

    models_dir = get_models_dir_for_agent(agent_id)
    if not os.path.isdir(models_dir):
        logger.error(f"Can't update model - model container directory doesn't exist: {models_dir}")
        return

    model_path = os.path.join(models_dir, model_id)
    if not os.path.isdir(model_path):
        logger.error(f"Can't update model - model directory doesn't exist: {model_path}")
        return
    logger.info(f"Path for model: {model_path}")

    container_subdir_train = current_app.config['CONTAINER_SUBDIR_TRAIN']
    container_subdir_test = current_app.config['CONTAINER_SUBDIR_TEST']
    container_path_train = os.path.join(model_path, container_subdir_train)
    container_path_test = os.path.join(model_path, container_subdir_test)

    for classification in classifications:
        logger.info(f"Creating classification: {classification}")
        class_trn = os.path.join(container_path_train, classification)
        class_tst = os.path.join(container_path_test, classification)
        if not os.path.isdir(class_trn):
            os.mkdir(class_trn)
            logger.debug("Created directory: " + class_trn);
        if not os.path.isdir(class_tst):
            os.mkdir(class_tst)
            logger.debug("Created directory: " + class_tst);

    delete_data(agent_id, model_id)
    init_dataset(agent_id, model_id, model_path)

    logger.info("Model updated (additions): " + model_id)


def delete_classifications(agent_id, model_id, classifications):

    logger.debug(f"Deleting classifications from model for agent '{agent_id}': {model_id}")
    if not is_model_existing(agent_id, model_id):
        logger.error("Model does not exist: " + model_id)
        return

    if classifications is None:
        return;

    models_dir = get_models_dir_for_agent(agent_id)
    if not os.path.isdir(models_dir):
        logger.error("Can't update model - model container directory doesn't exist: " + models_dir)
        return

    model_path = os.path.join(container_dir, model_id)
    if not os.path.isdir(model_path):
        logger.error("Can't update model - model directory doesn't exist: " + model_path)
        return
    logger.info("Path for model: " + model_path)

    container_subdir_train = current_app.config['CONTAINER_SUBDIR_TRAIN']
    container_subdir_test = current_app.config['CONTAINER_SUBDIR_TEST']
    container_path_train = os.path.join(model_path, container_subdir_train)
    container_path_test = os.path.join(model_path, container_subdir_test)

    for classification in classifications:
        logger.info("Deleting classification: " + classification)
        class_trn = os.path.join(container_path_train, classification)
        class_tst = os.path.join(container_path_test, classification)
        if os.path.isdir(class_trn):
            shutil.rmtree(class_trn)
            logger.debug("Deleted directory: " + class_trn);
        if os.path.isdir(class_tst):
            shutil.rmtree(class_tst)
            logger.debug("Deleted directory: " + class_tst);

    delete_data(agent_id, model_id)
    init_dataset(agent_id, model_id, model_path)

    logger.info("Model updated (deletions): " + model_id)


def create_model(agent_id, model_id, classifications):

    logger.debug(f"Creating model for agent '{agent_id}': {model_id}")
    if is_model_existing(agent_id, model_id):
        logger.error("Can't create model that already exists: " + model_id)
        return

    if classifications is None:
        classifications = []

    models_dir = get_models_dir_for_agent(agent_id)
    if not os.path.isdir(models_dir):
        logger.error("Can't create model - model container directory doesn't exist: " + models_dir)
        return

    model_path = os.path.join(models_dir, model_id)
    if os.path.isdir(model_path):
        logger.error("Can't create model - model container directory already exists: " + model_path)
        return

    logger.info('Path for model: ' + model_path)
    os.mkdir(model_path)

    container_subdir_train = current_app.config['CONTAINER_SUBDIR_TRAIN']
    container_subdir_test = current_app.config['CONTAINER_SUBDIR_TEST']
    container_path_train = os.path.join(model_path, container_subdir_train)
    container_path_test = os.path.join(model_path, container_subdir_test)
    os.mkdir(container_path_train)
    logger.info("Created training directory: " + container_path_train)
    os.mkdir(container_path_test)
    logger.info("Created test directory: " + container_path_test)

    for classification in classifications:
        class_trn = os.path.join(container_path_train, classification)
        os.mkdir(class_trn)
        logger.info("Created training directory for classification: " + class_trn)
        class_tst = os.path.join(container_path_test, classification)
        os.mkdir(class_tst)
        logger.info("Created test directory for classification: " + class_tst)

    init_dataset(agent_id, model_id, model_path)

    logger.info("Model created: " + model_id)


def delete_model(agent_id, model_id):

    logger.debug("Deleting model for agent '" + agent_id + "': " + model_id)
    if not is_model_existing(agent_id, model_id):
        logger.warn("Can't delete model that doesn't exist: " + model_id)
        return

    models_dir = get_models_dir_for_agent(agent_id)
    model_path = os.path.join(models_dir, model_id)
    if not os.path.isdir(model_path):
        logger.warn("Can't delete model - model directory doesn't exist: " + model_path)
        return

    deleted_dir = get_deleted_dir_for_agent(agent_id)
    if not os.path.isdir(deleted_dir):
        logger.warn("Can't delete model - deleted directory doesn't exist: " + deleted_dir)
        return
    
    new_name = model_id + '_' + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    new_path = os.path.join(deleted_dir, new_name)
    dest = shutil.move(model_path, new_path)
    logger.debug("Moved model to: " + dest)

    delete_data(agent_id, model_id)
    delete_model_metadata(agent_id, model_id)

    logger.info("Model deleted: " + model_id)


def add_dataset_row(dataset, dataval, targetval):

    logger.debug(f"Add dataset row: {dataval} / {targetval}")

    dataset["data"] = np.append(dataset["data"], dataval)
    dataset["target"] = np.append(dataset["target"], targetval)

    return dataset


def add_dataset_rows(agent_id, model_id, dataset, rows):

    logger.debug(f"add_dataset_rows with initial size: {get_len(dataset)}")

    for row in rows:
        classification_raw = row['target']
        logger.debug(f"Passed classification: {classification_raw}")
        if classification_raw.isdigit():
            classification_index = int(classification_raw)
        else:
            classification_index =  get_classification_index(agent_id, model_id, classification_raw)
        if classification_index < 0:
            logger.error(f"Can't add row - unable to get classification index for: {classification_raw}")
            continue
        add_dataset_row(dataset, row['data'], classification_index)

    logger.debug(f"Final size: {get_len(dataset)}")

    return dataset


def add_train_files(agent_id, model_id, rows):

    models_dir = get_models_dir_for_agent(agent_id)
    if not os.path.isdir(models_dir):
        logger.error("Can't add rows - model container directory doesn't exist: " + models_dir)
        return

    model_path = os.path.join(models_dir, model_id)
    if not os.path.isdir(model_path):
        logger.error("Can't add rows - model directory does not exist: " + model_path)
        return
    logger.info("Path for model: " + model_path)

    train_path = os.path.join(model_path, current_app.config['CONTAINER_SUBDIR_TRAIN'])
    if not os.path.isdir(train_path):
        logger.error("Can't add rows - train directory does not exist: " + train_path)
        return

    logger.info("Writing data to train_path: " + train_path)

    for row in rows:
        classification_raw = row['target']
        logger.debug("Passed classification: " + classification_raw)
        if any(chr.isdigit() for chr in classification_raw):
            classification_index = int(classification_raw)
            classification_name = get_classification_name(agent_id, model_id, classification_index)
        else:
            classification_index = get_classification_index(agent_id, model_id, classification_raw)
            classification_name = classification_raw
        if classification_name is None or classification_index < 0:
            logger.error("Can't add file - unable to get classification values for: " + classification_raw)
            continue
        text = row['data']
        classification_path = os.path.join(train_path, classification_name)
        if not os.path.isdir(classification_path):
            logger.error("Can't add file - classification directory does not exist: " + classification_path)
            continue
        filename = classification_name + '_' + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + '.txt'
        class_trn = os.path.join(train_path, classification_name)
        filepath = os.path.join(class_trn, filename)
        text_file = open(filepath, "w")
        text_file.write(text)
        text_file.close()
        logger.info('Wrote text to file: ' + filepath)

    logger.info('Done')


# @awag.teardown_appcontext
def teardownClf(exception):
    clf = g.pop('clf', None)
    logger.info('teardownClf', clf)

    # No further action at this stage


@ awag_ml.before_request
def before_request_func():

    if persistent.is_init:
        logger.debug("Already initialised...")
        return
    else:
        logger.debug("Initialising...")
        persistent.is_init = True

    current_app.logger.name = 'awag_ml'

    persistent.defaults.id = current_app.config['DEFAULT_DATA_ID']

    logger.info("Performing first request initialisation...")
    logger.info('The scikit-learn version is {}.'.format(sklearn.__version__))

    # logger.info('current_app.config', current_app.config)

    container_path_root = current_app.config['CONTAINER_PATH_ROOT']
    logger.info('Value of container_path_root: ' + container_path_root)

    persistent.data_ids = {}#types.SimpleNamespace()

    for agent_id in os.listdir(container_path_root):
        agent_dir = get_container_dir_for_agent(agent_id);

        if os.path.isdir(agent_dir):
            logger.info('Found agent directory: ' + agent_id + ' with path: ' + agent_dir)
            persistent.data_ids[agent_id] = {}#types.SimpleNamespace()
            models_dir = get_models_dir_for_agent(agent_id);
            for file in os.listdir(models_dir):
                potential_model_path = os.path.join(models_dir, file)
                if os.path.isdir(potential_model_path):
                    logger.info('Found directory: ' + file + ' with path: ' + potential_model_path)
                    persistent.data_ids[agent_id][file] = potential_model_path
                    init_dataset(agent_id, file, potential_model_path)


@ awag_ml.route('/test', methods=['GET'])
def test():
    logger.info('Route: /test')
    test_task.delay()
    return 'Congratulations! Your awag-ml-app test route is running!'


@ awag_ml.route('/restricted', methods=['GET'])
@ require_appkey
def restricted():
    logger.info('Route: /restricted')
    return 'Congratulations! Your awag-ml-app restricted route is running via your API key!'


@ awag_ml.route('/scoretest', methods=['GET'])
def test_score():

    logger.info('Route: /scoretest')

    data = get_data(None, None)

    data_test_all = data[TEST][ALL]

    print(data_test_all.target_names)

    predicted = classify(
        "test",
        "test",
        data_test_all.data,
        data_test_all.target_names)

    for i in predicted:
        print(i, end=' ')
        print(data_test_all.target_names[i], end=' ')

    # predict_list = predicted.tolist()
    predict_list = []
    for i in predicted:
        predict_list.append(data_test_all.target_names[i])

    # print('Predicted: ' + predicted)
    # logger.info('Predicted: ' + predict_list)

    np.mean(predicted == data_test_all.target)

    test_task.delay()
    # return 'Route scoretest complete'
    return jsonify(predict_list)


@ awag_ml.route('/getmodels', methods=['GET'])
@ require_agent_as_param
def get_models_list():

    agent_id = request.args.get('agent')

    logger.info('Route: /getmodels : ' + agent_id)

    return jsonify(get_models(agent_id))


@ awag_ml.route('/classify', methods=['POST'])
@ require_agent_in_json
def classify_snippet():

    logger.info('Route: /classify')

    reqjson = request.json

    try:

        #logger.debug(f"Request JSON: {reqjson}")

        agent_id = reqjson.get('agent', None)
        model_id = reqjson.get('model', None)
        texts_to_classify = reqjson.get('data', None)

        if not all([agent_id, model_id, texts_to_classify]):
            logger.error('Bad request json!')
            return 'Bad JSON request', 400

        truncated_items = [tidy_and_truncate_string(text_item, 100) for text_item in texts_to_classify]
        text_to_classify_summary = ', '.join(truncated_items)

        for truncated in truncated_items:
            logger.debug(f"Text item: {truncated}")

        input_data_np = np.array(texts_to_classify)

        data = get_data(agent_id, model_id)
        data_test_all = data[TEST][ALL]
        #logger.debug('data[TEST][ALL]: ' + repr(data_test_all))
        #logger.debug('data[TRAIN]: ' + repr(data[TRAIN]))

        data_train = data.get(TRAIN, {})

        target_names = data_train.get('target_names')
        data_train_data = data_train.get('data')

        if data_train_data is None or len(data_train_data) < 1:
            logger.error(f"data_train_data size is empty!")
            return f"No training data for model: {model_id}", 501

        logger.debug(f"Handling /classify with: agent_id '{agent_id}', model_id: '{model_id}', data_train_data size: {len(data_train_data)}, target_names: {target_names}")

        predicted = classify(
            agent_id,
            model_id,
            input_data_np,
            target_names)

        predict_list = []
        
        if predicted is not None:
            for i in predicted:
                predict_list.append(data_test_all.target_names[int(i)])

        logger.debug(f"Got predicted {predicted} for '{model_id}' {predict_list}  --  {text_to_classify_summary}")

        response_obj = { "data": predict_list }

        response_json = jsonify(response_obj)
        #logger.debug(f"Response JSON:\n{response_json.get_data()}")

        return response_json
        
    except Exception as err:

            logger.exception("Exception in classify_snippet. Request JSON was: %s", str(reqjson))
            logger.error('Exception in classify_snippet!', exc_info=True)
            logger.error('Request JSON was: %s', str(reqjson))
            raise err
            


@ awag_ml.route('/getclassifications', methods=['POST'])
@ require_agent_in_json
def get_classifications():

    logger.info('Route: /getclassifications')

    reqjson = request.json

    #logger.debug(f"Request JSON: {reqjson}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)

    if not all([agent_id, model_id]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    data = get_data(agent_id, model_id)
    data_test_all = data[TEST][ALL]

    response_obj = { "classifications": data_test_all.target_names }

    response_json = jsonify(response_obj)
    logger.debug('Response JSON: ' + str(response_json.get_data()))

    return response_json


@ awag_ml.route('/addrows', methods=['POST'])
@ require_agent_in_json
def addrows():

    logger.info('Route: /addrows')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")
    logger.debug(f"Type: {type(reqjson)}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)

    if not all([agent_id, model_id]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    if 'items' in reqjson:
        logger.debug(f"Got items: {reqjson['items']}")
    else:
        return 'No data sent!'

    data = get_data(agent_id, model_id)

    add_dataset_rows(agent_id, model_id, data[TRAIN], reqjson['items'])
    fit(agent_id, model_id, data[TRAIN])
    add_train_files(agent_id, model_id, reqjson['items'])

    return 'Done'


@ awag_ml.route('/createmodel', methods=['POST'])
@ require_agent_in_json
def createmodel():

    logger.info('Route: /createmodel')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")
    logger.debug(f"Type: {type(reqjson)}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)
    model_desc = reqjson.get('desc', None)
    classifications = reqjson.get('classifications', [])

    if not all([agent_id, model_id, model_desc, classifications]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    create_model(agent_id, model_id, classifications)
    update_model_desc(agent_id, model_id, model_desc)

    return 'Done'


@ awag_ml.route('/getmodeldesc', methods=['GET'])
@ require_agent_as_param
def getmodeldesc():

    agent_id = request.args.get('agent')
    model_id = request.args.get('model')

    logger.info('Route: /getmodeldesc : ' + agent_id + " / " + model_id)

    return jsonify(get_model_desc(agent_id, model_id))


@ awag_ml.route('/updatemodeldesc', methods=['POST'])
@ require_agent_in_json
def updatemodeldesc():

    logger.info('Route: /updatemodeldesc')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)
    model_desc = reqjson.get('desc', None)

    if not all([agent_id, model_id, model_desc]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    response = update_model_desc(agent_id, model_id, model_desc)

    return response or 'Done'


@ awag_ml.route('/addclassifications', methods=['POST'])
@ require_agent_in_json
def addclassifications():

    logger.info('Route: /addclassifications')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")
    logger.debug(f"Type: {type(reqjson)}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)
    classifications = reqjson.get('classifications', [])

    if not all([agent_id, model_id]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    add_classifications(agent_id, model_id, classifications)

    return 'Done'


@ awag_ml.route('/delclassifications', methods=['POST'])
@ require_agent_in_json
def delclassifications():

    logger.info('Route: /delclassifications')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")
    logger.debug(f"Type: {type(reqjson)}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)
    classifications = reqjson.get('classifications', [])

    if not all([agent_id, model_id]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    delete_classifications(model_id, classifications)

    return 'Done'


@ awag_ml.route('/deletemodel', methods=['POST'])
@ require_agent_in_json
def deletemodel():

    logger.info('Route: /deletemodel')

    reqjson = request.json

    logger.debug(f"Request JSON: {reqjson}")
    logger.debug(f"Type: {type(reqjson)}")

    agent_id = reqjson.get('agent', None)
    model_id = reqjson.get('model', None)
    classifications = reqjson.get('classifications', [])

    if not all([agent_id, model_id]):
        logger.error('Bad request json!')
        return 'Bad JSON request', 400

    delete_model(agent_id, model_id)

    return 'Done'

