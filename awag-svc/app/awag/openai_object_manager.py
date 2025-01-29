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

from enum import Enum

from domestique.datetime import get_current_time_ms

from .shared_resources import logger, dict_from_openai_object



class ObjectType(Enum):

    FINE_TUNING_FILE = 1
    FINE_TUNING_JOB = 2
    MODEL = 3


class OpenAIObjectManager:

    def __init__(self, namespace_base, objectstore_client, openai_client_wrapper, object_type):

        self.namespace_base = namespace_base
        self.objectstore_client = objectstore_client
        self.openai_client_wrapper = openai_client_wrapper
        self.object_type = object_type
        self.get_data_function, self.namespace_object, self.namespace_meta = self._setup_type_specifics(object_type, namespace_base)


    def _setup_type_specifics(self, object_type, namespace_base):

        if object_type == ObjectType.FINE_TUNING_FILE:
            get_data_function = lambda oid: self.openai_client_wrapper.get_file(oid)
            namespace_object = namespace_base + "files"
        elif object_type == ObjectType.FINE_TUNING_JOB:
            get_data_function = lambda oid: self.openai_client_wrapper.get_fine_tuning_job(oid)
            namespace_object = namespace_base + "jobs"
        elif object_type == ObjectType.MODEL:
            get_data_function = lambda oid: self.openai_client_wrapper.get_model(oid)
            namespace_object = namespace_base + "models"
        else:
            raise ValueError(f"Unknown object type: {object_type}")
        namespace_meta = namespace_object + "_meta"

        return get_data_function, namespace_object, namespace_meta


    def get_namespace_object(self):

        return self.namespace_object


    def get_namespace_meta(self):

        return self.namespace_meta


    def get_objectstore_client(self):

        return self.objectstore_client


    def get_openai_client_wrapper(self):

        return self.openai_client_wrapper


    def create_object_meta(self, tag, object_dict, object_native=None, info=None, additional_details=None, source_meta=None):

        if not object_dict:
            raise ValueError(f"Missing object_dict")

        if not object_dict.get("id", None):
            raise ValueError(f"Missing object_dict.id")

        object_meta = {
            "id": object_dict.get("id"),
            "tag": tag,
            "deleted_from_openai": False,
            "deleted_from_objectstore": False,
            "object": object_dict,
            "object_str": str(object_native),
            "info": info,
            "additional_details": additional_details,
            "source_meta": source_meta,
            "meta_created_ms": get_current_time_ms()
        }

        return object_meta


    def set_object_meta_object(self, model_meta, object_dict=None, object_native=None):

        if object_dict:
            model_meta["object"] = object_dict

        if object_native:
            model_meta["object_str"] = str(object_native)


    def object_exists(self, object_id):

        return self.objectstore_client.object_exists(self.namespace_object, object_id)


    def object_meta_exists(self, object_id):

        return self.objectstore_client.object_exists(self.namespace_meta, object_id)


    def get_object_meta(self, object_id):

        return self.objectstore_client.retrieve_object(self.namespace_meta, object_id)


    def store_object_meta(self, object_meta, tag):

        object_id = object_meta["id"]
        return self.objectstore_client.store_object(self.namespace_meta, object_id, tag, object_meta)


    def store_object(self, object_dict, tag):

        object_id = object_dict["id"]
        return self.objectstore_client.store_object(self.namespace_object, object_id, tag, object_dict)


    def store_object_and_meta(self, object_dict, object_meta, tag):

        if not object_dict:
            raise ValueError(f"Missing object_dict")
        if not object_meta:
            raise ValueError(f"Missing object_meta")
        object_id_meta = object_meta["id"]
        if not object_dict["id"] == object_id_meta:
            raise ValueError(f"Mismatch between object_dict, object_meta for: {object_dict}, {object_id_meta}")
        object_id = self.store_object(object_dict, tag)
        if not object_id == object_id_meta:
            raise Exception(f"Error storing object - got bad response value back ({object_id}): {object_dict}")
        return self.store_object_meta(object_meta, tag)


    def update_object_meta(self, object_meta):

        object_id = object_meta["id"]
        logger.debug(f"Updating object_meta with object_id '{object_id}': {object_meta}")
        if not self.object_meta_exists(object_id):
            raise Exception(f"Cannot update meta for '{object_id}' as it does not exist!")
        return self.store_object_meta(object_meta, None)


    def update_object(self, object_dict):

        object_id = object_dict["id"]
        logger.debug(f"Updating object with object_id '{object_id}': {object_dict}")
        if not self.object_exists(object_id):
            raise Exception(f"Cannot update object for '{object_id}' as it does not exist!")
        return self.store_object(object_dict, None)


    def update_or_store_object(self, object_dict):

        object_id = object_dict["id"]
        logger.debug(f"Updating/storing object with object_id '{object_id}': {object_dict}")
        if self.object_exists(object_id):
            logger.debug(f"Object exists with object_id '{object_id}' - will do UPDATE")
            stored_id = self.update_object(object_dict)
        else:
            logger.debug(f"Object does not exist with object_id '{object_id}' - will do STORE")
            stored_id = self.store_object(object_dict, None)
        logger.debug(f"Stored object_id: {stored_id}")


    def get_object_ids(self, tag):

        return self.objectstore_client.query_namespace(self.namespace_object, tag)


    def get_object_ids_meta(self, tag):

        return self.objectstore_client.query_namespace(self.namespace_meta, tag)


    def sync_object_tags(self, object_meta):

        object_id = object_meta["id"]

        if self.is_object_marked_deleted_from_objectstore(object_meta):
            # Object marked deleted from our object store - ignore
            logger.debug(f"Not syncing object marked as deleted_from_objectstore: {object_id}")
            return

        if self.is_object_marked_deleted_from_openai(object_meta):
            # Object marked deleted from openai- ignore
            logger.debug(f"Not syncing object marked as deleted_from_openai: {object_id}")
            return

        if not self.object_exists(object_id):
            logger.debug(f"Can't sync tags for '{object_id}' as it does not exist in object namespace")
            return

        if not self.object_meta_exists(object_id):
            logger.debug(f"Can't sync tags for '{object_id}' as it does not exist in object meta namespace")
            return

        if self.objectstore_client.tags_match(self.namespace_object, object_id, self.namespace_meta, object_id):
            logger.debug(f"No need to sync tags for: {object_id}")
            return

        logger.debug(f"Syncing tags from object meta to object for: {object_id}")
        tags_from_meta = self.objectstore_client.get_object_tags(self.namespace_meta, object_id)
        logger.debug(f"Got tags from the object meta '{object_id}': {tags_from_meta}")
        self.objectstore_client.set_object_tags(self.namespace_object, object_id, tags_from_meta)
        logger.debug(f"Tags synced from meta to for obj: {object_id}")


    def remove_object(self, object_id):

        if not self.object_exists(object_id):
            return None
        return self.objectstore_client.delete_object(self.namespace_object, object_id)


    def remove_object_meta(self, object_id):

        if not self.object_meta_exists(object_id):
            return None
        return self.objectstore_client.delete_object(self.namespace_meta, object_id)


    def get_object_meta_id_list(self, tag, object_id=None):

        object_ids = []

        if object_id:
            if not self.object_meta_exists(object_id):
                return []
            else:
                return [object_id]
        else:
            return self.objectstore_client.query_namespace(self.namespace_meta, tag)


    def mark_object_not_deleted(self, object_meta):

        if not object_meta:
            raise ValueError("An object_meta is required")

        object_meta["deleted_from_objectstore"] = False
        object_meta["deleted_from_openai"] = False

        return object_meta


    def mark_object_deleted_from_objectstore(self, object_meta):

        if not object_meta:
            raise ValueError("An object_meta is required")

        object_meta["deleted_from_objectstore"] = True
        
        return object_meta


    def mark_object_deleted_from_openai(self, object_meta):

        if not object_meta:
            raise ValueError("An object_meta is required")

        object_meta["deleted_from_openai"] = True
        
        return object_meta


    def is_object_marked_deleted_from_openai(self, object_meta):

        if not object_meta:
            raise ValueError("An object_meta is required")

        if object_meta.get("deleted_from_openai", False):
            logger.debug(f"Object is marked deleted_from_openai: {object_meta}")
            return True
        else:
            return False


    def is_object_marked_deleted_from_objectstore(self, object_meta):

        if not object_meta:
            raise ValueError("An object_meta is required")

        if object_meta.get("deleted_from_objectstore", False):
            logger.debug(f"Object is marked deleted_from_objectstore: {object_meta}")
            return True
        else:
            return False


    def is_object_marked_deleted(self, object_meta):

        if self.is_object_marked_deleted_from_openai(object_meta):
            return True
        else:
            return self.is_object_marked_deleted_from_objectstore(object_meta)


    def sync_objects(self, resp, tag):

        try:

            # Retrieve lists of object IDs from the object store
            object_ids_meta = self.get_object_ids_meta(tag)
            object_ids = self.get_object_ids(tag)

            logger.debug(f"Retrieved list of {len(object_ids_meta)} META IDs for tag {tag}")
            logger.debug(f"Retrieved list of {len(object_ids)} IDs for tag {tag}")

            if not object_ids_meta:
                return resp.generate_response_with_data(f"No data to process for tag: {tag}", 404)

            set_object_ids_meta = set(object_ids_meta)
            set_object_ids = set(object_ids)

            object_ids_orphaned = list(set_object_ids - set_object_ids_meta)
            object_ids_deleted = list(set_object_ids_meta - set_object_ids)

            # Orphaned: files exist in object store but have no corresponding meta object
            logger.debug(f"Orphaned objects: {object_ids_orphaned}")
            # Deleted: meta objects exist in object store but have no corresponding file object
            logger.debug(f"Deleted objects: {object_ids_deleted}")

            for object_id_deleted in object_ids_deleted:
                # There exists meta for these objects, but no actual object in the object store
                # Need to check and update deleted_from_objectstore flag if needed
                logger.debug(f"Processing deleted object: {object_id_deleted}")
                object_meta = self.get_object_meta(object_id_deleted)
                if object_meta and not self.is_object_marked_deleted_from_objectstore(object_meta):
                    logger.debug(f"Marking deleted_from_objectstore and updating meta: {object_id_deleted}")
                    self.mark_object_deleted_from_objectstore(object_meta)
                    self.update_object_meta(object_meta)
                else:
                    logger.debug(f"No need to update meta for: {object_id_deleted}")

            object_ids_deleted_now = []
            object_ids_active = []
            object_ids_resurrected_now = []

            # Process each meta object...

            for object_id_meta in object_ids_meta:

                logger.debug(f"Processing meta file: {object_id_meta}")

                object_meta = self.get_object_meta(object_id_meta)

                if not object_meta:
                    # Should not happen unless race condition, but check anyway
                    logger.error(f"Data consistency problem - {object_id_meta} obtained from query_namespace could not be retrieved!")
                    raise Exception(f"Unable to get file meta for object: {object_id_meta}")
                if self.is_object_marked_deleted_from_openai(object_meta):
                    # Object marked deleted from openai- ignore
                    logger.debug(f"Ignoring object marked as deleted_from_openai: {object_id_meta}")
                    continue

                # Note that some types of object such as fine_tuning.job cannot currently be deleted
                # from OpenAI, so we need to rely on deleted_from_openai flag being set in the meta
                # object - do not try to resurrect objects marked as deleted_from_openai

                object_from_openai, object_from_openai_as_dict = self.get_data_function(object_id_meta)

                if not object_from_openai:

                    logger.debug(f"Got no object_from_openai for meta: {object_id_meta}")
                    if self.object_exists(object_id_meta):
                        logger.info(f"Removing object from objectstore: {object_id_meta}")
                        remove_object(object_id_meta)
                    self.mark_object_deleted_from_objectstore(object_meta)
                    self.mark_object_deleted_from_openai(object_meta)
                    logger.info(f"Marking object as deleted from OpenAI: {object_id_meta}")
                    if object_id_meta not in object_ids_deleted:
                        if object_id_meta not in object_ids_deleted_now:
                            object_ids_deleted_now.append(object_id_meta)

                else:

                    logger.debug(f"Got object_from_openai for meta '{object_id_meta}': {object_from_openai}")
                    logger.debug(f"Got object_from_openai_as_dict: {object_from_openai_as_dict}")
                    self.set_object_meta_object(object_meta, object_from_openai_as_dict, object_from_openai)
                    self.mark_object_not_deleted(object_meta)
                    object_ids_active.append(object_id_meta)
                    if not self.object_exists(object_id_meta):
                        logger.debug(f"Object has meta and exists in OpenAI but not object store '{object_id_meta}' - will resurrect")
                        self.update_or_store_object(object_from_openai_as_dict)
                        object_ids_resurrected_now.append(object_id_meta)
                        object_ids_deleted.remove(object_id_meta)
                        does_it_exist_now = self.object_exists(object_id_meta)
                        logger.debug(f"does_it_exist_now '{object_id_meta}': {does_it_exist_now}")

                # Always do objectstore update, as the objectstore will check for changes
                self.update_object_meta(object_meta)
                # The file in OpenAI may or may not have changed

                self.sync_object_tags(object_meta)

            current_time_ms = get_current_time_ms()
            message = f"Managed object maintenance/query complete"

            this_run = {
                "deleted_initial": object_ids_deleted,
                "deleted": object_ids_deleted_now,
                "resurrected": object_ids_resurrected_now,
                "deleted_final": object_ids_deleted,
            }

            response_json = {
                'status': 'OK',
                'message': message,
                'namespace_objects': self.get_namespace_object(),
                'namespace_objects_meta': self.get_namespace_meta(),
                'active_objects': object_ids_active,
                'orphaned_objects': object_ids_orphaned,
                'deleted_objects': object_ids_deleted,
                'this_run': this_run,
                'current_time_ms': current_time_ms
            }

            '''
            This method has the following file concepts:
                active_objects - both file and meta objects exist, and also exists in OpenAI
                orphaned_objects - object exists but has no meta (will need manual fixing)
                deleted_objects - meta object exists but does not exist in OpenAI (can be pruned in future)
                this_run.deleted_initial - already deleted objects at start of run (have meta, but no object)
                this_run.deleted - added to deleted_objects in this run
                this_run.resurrected - exists in OpenAI and has meta but not an object in the store - so have recreated it
                this_run.deleted_final - deleted_initial minus any resurrected; same as parent deleted_objects
                unmanaged_objects - exists in OpenAI but not in object store [not implemented here]
            '''

            return resp.generate_response_with_data(response_json, 200)

        except Exception as e:

            return resp.generate_response_with_exception(e)

