import tempfile
import uuid
import hashlib
import mimetypes
import os

from mock import patch

from django.core.management import call_command
from django.db import DataError
from django.test import TestCase
from django.test import TransactionTestCase
from le_utils.constants import content_kinds
from le_utils.constants import file_formats
from le_utils.constants import format_presets

from .sqlalchemytesting import django_connection_engine
from kolibri.core.content.models import ChannelMetadata
from kolibri.core.content.models import ContentNode
from kolibri.core.content.models import File
from kolibri.core.content.models import Language
from kolibri.core.content.models import LocalFile
from kolibri.core.content.utils.paths import get_content_storage_file_path
from kolibri.core.content.utils.delete_content import delete_unavailable_stored_files


def get_engine(connection_string):
    return django_connection_engine()


@patch("kolibri.core.content.utils.sqlalchemybridge.get_engine", new=get_engine)
class UnavailableContentDeletion(TransactionTestCase):

    def setUp(self):
        super(UnavailableContentDeletion, self).setUp()

        # create an unavailable contentnode
        self.unavailable_contentnode = ContentNode(
            title="wow",
            available=False,
            id=uuid.uuid4().hex,
            content_id=uuid.uuid4().hex,
            channel_id=uuid.uuid4().hex
        )
        self.unavailable_contentnode.save()

        self.hash = hashlib.md5("wow".encode()).hexdigest()
        self.extension = file_formats.PDF

        # with an associated stored local file
        self.stored_local_file = LocalFile(
            id=self.hash, extension=self.extension,
            available=True
        )
        self.stored_local_file.save()

        self.file = File(
            local_file=self.stored_local_file,
            contentnode=self.unavailable_contentnode,
            preset=format_presets.DOCUMENT,
            id=uuid.uuid4().hex
        )
        self.file.save()

        # actually store a dummy local file
        self.filename = "{}.{}".format(self.hash, self.extension)

        self.path = get_content_storage_file_path(self.filename)
        path_dir = os.path.dirname(self.path)
        if not os.path.exists(path_dir):
            os.makedirs(path_dir)
        tempfile = open(self.path, "w")
        tempfile.write("wow")
        tempfile.close()

    def test_delete_unavailable_stored_files(self):
        self.assertEqual(self.unavailable_contentnode.available, False)
        self.assertEqual(self.stored_local_file.available, True)
        self.assertEqual(os.path.exists(self.path), True)
        self.assertEqual(len(LocalFile.objects.get_unavailable_files()), 1)

        delete_unavailable_stored_files()

        self.assertEqual(os.path.exists(self.path), False)
        self.assertEqual(len(LocalFile.objects.get_unavailable_files()), 0)



