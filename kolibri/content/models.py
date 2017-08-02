"""
This is one of the Kolibri core components, the abstract layer of all contents.
To access it, please use the public APIs in api.py

The ONLY public object is ContentNode
"""
from __future__ import print_function

import uuid
from gettext import gettext as _

from django.core.urlresolvers import reverse
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.text import get_valid_filename
from jsonfield import JSONField
from kolibri.core.fields import DateTimeTzField
from le_utils.constants import content_kinds, file_formats, format_presets
from le_utils.constants.languages import LANGUAGE_DIRECTIONS
from mptt.models import MPTTModel, TreeForeignKey

from .utils import paths

PRESET_LOOKUP = dict(format_presets.choices)


class UUIDField(models.CharField):
    """
    Adaptation of Django's UUIDField, but with 32-char hex representation as Python representation rather than a UUID instance.
    """

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 32
        super(UUIDField, self).__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, uuid.UUID):
            return value.hex
        return value

    def deconstruct(self):
        name, path, args, kwargs = super(UUIDField, self).deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs

    def get_internal_type(self):
        return "UUIDField"

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            try:
                value = uuid.UUID(value)
            except AttributeError:
                raise TypeError(self.error_messages['invalid'] % {'value': value})
        return value.hex

    def from_db_value(self, value, expression, connection, context):
        return self.to_python(value)

    def to_python(self, value):
        if isinstance(value, uuid.UUID):
            return value.hex
        return value


@python_2_unicode_compatible
class ContentTag(models.Model):
    id = UUIDField(primary_key=True)
    tag_name = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return self.tag_name


@python_2_unicode_compatible
class ContentNode(MPTTModel):
    """
    The top layer of the contentDB schema, defines the most common properties that are shared across all different contents.
    Things it can represent are, for example, video, exercise, audio or document...
    """
    id = UUIDField(primary_key=True)
    parent = TreeForeignKey('self', null=True, blank=True, related_name='children', db_index=True)
    license = models.ForeignKey('License', null=True, blank=True)
    has_prerequisite = models.ManyToManyField('self', related_name='prerequisite_for', symmetrical=False, blank=True)
    related = models.ManyToManyField('self', symmetrical=True, blank=True)
    tags = models.ManyToManyField(ContentTag, symmetrical=False, related_name='tagged_content', blank=True)

    title = models.CharField(max_length=200)

    # the content_id is used for tracking a user's interaction with a piece of
    # content, in the face of possibly many copies of that content. When a user
    # interacts with a piece of content, all substantially similar pieces of
    # content should be marked as such as well. We track these "substantially
    # similar" types of content by having them have the same content_id.
    content_id = UUIDField(db_index=True)
    channel_id = UUIDField()

    description = models.CharField(max_length=400, blank=True, null=True)
    sort_order = models.FloatField(blank=True, null=True)
    license_owner = models.CharField(max_length=200, blank=True)
    author = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=200, choices=content_kinds.choices, blank=True)
    available = models.BooleanField(default=False)
    stemmed_metaphone = models.CharField(max_length=1800, blank=True)  # for fuzzy search in title and description
    lang = models.ForeignKey('Language', blank=True, null=True)

    class Meta:
        ordering = ('lft',)

    def __str__(self):
        return self.title

    def get_descendant_content_ids(self):
        """
        Retrieve a queryset of content_ids for non-topic content nodes that are
        descendants of this node.
        """
        return ContentNode.objects \
            .filter(lft__gte=self.lft, lft__lte=self.rght) \
            .exclude(kind=content_kinds.TOPIC) \
            .values_list("content_id", flat=True)


@python_2_unicode_compatible
class Language(models.Model):
    id = models.CharField(max_length=14, primary_key=True)
    lang_code = models.CharField(max_length=3, db_index=True)
    lang_subcode = models.CharField(max_length=10, db_index=True, blank=True, null=True)
    # Localized name
    lang_name = models.CharField(max_length=100, blank=True, null=True)
    lang_direction = models.CharField(max_length=3, choices=LANGUAGE_DIRECTIONS)

    def __str__(self):
        return self.lang_name


@python_2_unicode_compatible
class File(models.Model):
    """
    The second to bottom layer of the contentDB schema, defines the basic building brick for content.
    Things it can represent are, for example, mp4, avi, mov, html, css, jpeg, pdf, mp3...
    """
    id = UUIDField(primary_key=True)
    # The foreign key mapping happens here as many File objects can map onto a single local file
    local_file = models.ForeignKey('LocalFile')
    available = models.BooleanField(default=False)
    contentnode = models.ForeignKey(ContentNode, related_name='files', blank=True, null=True)
    preset = models.CharField(max_length=150, choices=format_presets.choices, blank=True)
    lang = models.ForeignKey(Language, blank=True, null=True)
    supplementary = models.BooleanField(default=False)
    thumbnail = models.BooleanField(default=False)
    priority = models.IntegerField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["priority"]

    class Admin:
        pass

    def get_preset(self):
        """
        Return the preset.
        """
        return PRESET_LOOKUP.get(self.preset, _('Unknown format'))

    def get_download_filename(self):
        """
        Return a valid filename to be downloaded as.
        """
        title = self.contentnode.title
        filename = "{} ({}).{}".format(title, self.get_preset(), self.local_file.extension)
        valid_filename = get_valid_filename(filename)
        return valid_filename

    def get_download_url(self):
        """
        Return the download url.
        """
        new_filename = self.get_download_filename()
        return reverse('downloadcontent', kwargs={'filename': self.local_file.get_filename(), 'new_filename': new_filename})


@python_2_unicode_compatible
class LocalFile(models.Model):
    """
    The bottom layer of the contentDB schema, defines the local state of files on the device storage.
    """
    # ID should be the checksum of the file
    id = UUIDField(primary_key=True)
    extension = models.CharField(max_length=40, choices=file_formats.choices, blank=True)
    available = models.BooleanField(default=False)
    file_size = models.IntegerField(blank=True, null=True)

    class Admin:
        pass

    def __str__(self):
        return '{checksum}.{extension}'.format(checksum=self.id, extension=self.extension)

    def get_filename(self):
        return self.__str__()

    def get_storage_url(self):
        """
        Return a url for the client side to retrieve the content file.
        The same url will also be exposed by the file serializer.
        """
        if self.available:
            return paths.get_content_storage_file_url(filename=self.get_filename(), baseurl="/")
        else:
            return None


@python_2_unicode_compatible
class License(models.Model):
    """
    Normalize the license of ContentNode model
    """
    license_name = models.CharField(max_length=50)
    license_description = models.CharField(max_length=400, null=True, blank=True)

    def __str__(self):
        return self.license_name


@python_2_unicode_compatible
class AssessmentMetaData(models.Model):
    """
    A model to describe additional metadata that characterizes assessment behaviour in Kolibri.
    This model contains additional fields that are only revelant to content nodes that probe a
    user's state of knowledge and allow them to practice to Mastery.
    ContentNodes with this metadata may also be able to be used within quizzes and exams.
    """
    id = UUIDField(primary_key=True)
    contentnode = models.ForeignKey(
        ContentNode, related_name='assessmentmetadata', blank=True, null=True
    )
    # A JSON blob containing a serialized list of ids for questions that the assessment can present.
    assessment_item_ids = JSONField(default=[])
    # Length of the above assessment_item_ids for a convenience lookup.
    number_of_assessments = models.IntegerField()
    # A JSON blob describing the mastery model that is used to set this assessment as mastered.
    mastery_model = JSONField(default={})
    # Should the questions listed in assessment_item_ids be presented in a random order?
    randomize = models.BooleanField(default=False)
    # Is this assessment compatible with being previewed and answer filled for display in coach reports
    # and use in summative and formative tests?
    is_manipulable = models.BooleanField(default=False)


@python_2_unicode_compatible
class ChannelMetadata(models.Model):
    """
    Holds metadata about all existing content databases that exist locally.
    """
    id = UUIDField(primary_key=True)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    author = models.CharField(max_length=400, blank=True)
    version = models.IntegerField(default=0)
    thumbnail = models.TextField(blank=True)
    last_updated = DateTimeTzField(null=True)
    # Minimum version of Kolibri that this content database is compatible with
    min_kolibri_version = models.CharField(max_length=50)

    class Admin:
        pass

    class Meta:
        abstract = True

    def __str__(self):
        return self.name
