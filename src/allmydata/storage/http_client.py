"""
HTTP client that talks to the HTTP storage server.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from typing import Union, Set, Optional

from base64 import b64encode

import attr

# TODO Make sure to import Python version?
from cbor2 import loads, dumps
from collections_extended import RangeMap
from werkzeug.datastructures import Range, ContentRange
from twisted.web.http_headers import Headers
from twisted.web import http
from twisted.internet.defer import inlineCallbacks, returnValue, fail, Deferred
from hyperlink import DecodedURL
import treq
from treq.client import HTTPClient
from treq.testing import StubTreq

from .http_common import swissnum_auth_header, Secrets
from .common import si_b2a


def _encode_si(si):  # type: (bytes) -> str
    """Encode the storage index into Unicode string."""
    return str(si_b2a(si), "ascii")


class ClientException(Exception):
    """An unexpected error."""


def _decode_cbor(response):
    """Given HTTP response, return decoded CBOR body."""
    if response.code > 199 and response.code < 300:
        return treq.content(response).addCallback(loads)
    return fail(ClientException(response.code, response.phrase))


@attr.s
class ImmutableCreateResult(object):
    """Result of creating a storage index for an immutable."""

    already_have = attr.ib(type=Set[int])
    allocated = attr.ib(type=Set[int])


class StorageClient(object):
    """
    HTTP client that talks to the HTTP storage server.
    """

    def __init__(
        self, url, swissnum, treq=treq
    ):  # type: (DecodedURL, bytes, Union[treq,StubTreq,HTTPClient]) -> None
        """
        The URL is a HTTPS URL ("http://...").  To construct from a furl, use
        ``StorageClient.from_furl()``.
        """
        assert url.to_text().startswith("https://")
        self._base_url = url
        self._swissnum = swissnum
        self._treq = treq

    @classmethod
    def from_furl(cls, furl: DecodedURL) -> "StorageClient":
        """
        Create a ``StorageClient`` for the given furl.
        """
        assert furl.fragment == "v=1"
        assert furl.scheme == "pb"
        swissnum = furl.path[0].encode("ascii")
        certificate_hash = furl.user.encode("ascii")
        
    def _url(self, path):
        """Get a URL relative to the base URL."""
        return self._base_url.click(path)

    def _get_headers(self, headers):  # type: (Optional[Headers]) -> Headers
        """Return the basic headers to be used by default."""
        if headers is None:
            headers = Headers()
        headers.addRawHeader(
            "Authorization",
            swissnum_auth_header(self._swissnum),
        )
        return headers

    def _request(
        self,
        method,
        url,
        lease_renew_secret=None,
        lease_cancel_secret=None,
        upload_secret=None,
        headers=None,
        **kwargs
    ):
        """
        Like ``treq.request()``, but with optional secrets that get translated
        into corresponding HTTP headers.
        """
        headers = self._get_headers(headers)
        for secret, value in [
            (Secrets.LEASE_RENEW, lease_renew_secret),
            (Secrets.LEASE_CANCEL, lease_cancel_secret),
            (Secrets.UPLOAD, upload_secret),
        ]:
            if value is None:
                continue
            headers.addRawHeader(
                "X-Tahoe-Authorization",
                b"%s %s" % (secret.value.encode("ascii"), b64encode(value).strip()),
            )
        return self._treq.request(method, url, headers=headers, **kwargs)

    @inlineCallbacks
    def get_version(self):
        """
        Return the version metadata for the server.
        """
        url = self._url("/v1/version")
        response = yield self._request("GET", url)
        decoded_response = yield _decode_cbor(response)
        returnValue(decoded_response)


@attr.s
class UploadProgress(object):
    """
    Progress of immutable upload, per the server.
    """

    # True when upload has finished.
    finished = attr.ib(type=bool)
    # Remaining ranges to upload.
    required = attr.ib(type=RangeMap)


class StorageClientImmutables(object):
    """
    APIs for interacting with immutables.
    """

    def __init__(self, client):  # type: (StorageClient) -> None
        self._client = client

    @inlineCallbacks
    def create(
        self,
        storage_index,
        share_numbers,
        allocated_size,
        upload_secret,
        lease_renew_secret,
        lease_cancel_secret,
    ):  # type: (bytes, Set[int], int, bytes, bytes, bytes) -> Deferred[ImmutableCreateResult]
        """
        Create a new storage index for an immutable.

        TODO https://tahoe-lafs.org/trac/tahoe-lafs/ticket/3857 retry
        internally on failure, to ensure the operation fully succeeded.  If
        sufficient number of failures occurred, the result may fire with an
        error, but there's no expectation that user code needs to have a
        recovery codepath; it will most likely just report an error to the
        user.

        Result fires when creating the storage index succeeded, if creating the
        storage index failed the result will fire with an exception.
        """
        url = self._client._url("/v1/immutable/" + _encode_si(storage_index))
        message = dumps(
            {"share-numbers": share_numbers, "allocated-size": allocated_size}
        )
        response = yield self._client._request(
            "POST",
            url,
            lease_renew_secret=lease_renew_secret,
            lease_cancel_secret=lease_cancel_secret,
            upload_secret=upload_secret,
            data=message,
            headers=Headers({"content-type": ["application/cbor"]}),
        )
        decoded_response = yield _decode_cbor(response)
        returnValue(
            ImmutableCreateResult(
                already_have=decoded_response["already-have"],
                allocated=decoded_response["allocated"],
            )
        )

    @inlineCallbacks
    def write_share_chunk(
        self, storage_index, share_number, upload_secret, offset, data
    ):  # type: (bytes, int, bytes, int, bytes) -> Deferred[UploadProgress]
        """
        Upload a chunk of data for a specific share.

        TODO https://tahoe-lafs.org/trac/tahoe-lafs/ticket/3857 The
        implementation should retry failed uploads transparently a number of
        times, so that if a failure percolates up, the caller can assume the
        failure isn't a short-term blip.

        Result fires when the upload succeeded, with a boolean indicating
        whether the _complete_ share (i.e. all chunks, not just this one) has
        been uploaded.
        """
        url = self._client._url(
            "/v1/immutable/{}/{}".format(_encode_si(storage_index), share_number)
        )
        response = yield self._client._request(
            "PATCH",
            url,
            upload_secret=upload_secret,
            data=data,
            headers=Headers(
                {
                    "content-range": [
                        ContentRange("bytes", offset, offset + len(data)).to_header()
                    ]
                }
            ),
        )

        if response.code == http.OK:
            # Upload is still unfinished.
            finished = False
        elif response.code == http.CREATED:
            # Upload is done!
            finished = True
        else:
            raise ClientException(
                response.code,
            )
        body = yield _decode_cbor(response)
        remaining = RangeMap()
        for chunk in body["required"]:
            remaining.set(True, chunk["begin"], chunk["end"])
        returnValue(UploadProgress(finished=finished, required=remaining))

    @inlineCallbacks
    def read_share_chunk(
        self, storage_index, share_number, offset, length
    ):  # type: (bytes, int, int, int) -> Deferred[bytes]
        """
        Download a chunk of data from a share.

        TODO https://tahoe-lafs.org/trac/tahoe-lafs/ticket/3857 Failed
        downloads should be transparently retried and redownloaded by the
        implementation a few times so that if a failure percolates up, the
        caller can assume the failure isn't a short-term blip.

        NOTE: the underlying HTTP protocol is much more flexible than this API,
        so a future refactor may expand this in order to simplify the calling
        code and perhaps download data more efficiently.  But then again maybe
        the HTTP protocol will be simplified, see
        https://tahoe-lafs.org/trac/tahoe-lafs/ticket/3777
        """
        url = self._client._url(
            "/v1/immutable/{}/{}".format(_encode_si(storage_index), share_number)
        )
        response = yield self._client._request(
            "GET",
            url,
            headers=Headers(
                {"range": [Range("bytes", [(offset, offset + length)]).to_header()]}
            ),
        )
        if response.code == http.PARTIAL_CONTENT:
            body = yield response.content()
            returnValue(body)
        else:
            raise ClientException(
                response.code,
            )

    @inlineCallbacks
    def list_shares(self, storage_index):  # type: (bytes,) -> Deferred[Set[int]]
        """
        Return the set of shares for a given storage index.
        """
        url = self._client._url(
            "/v1/immutable/{}/shares".format(_encode_si(storage_index))
        )
        response = yield self._client._request(
            "GET",
            url,
        )
        if response.code == http.OK:
            body = yield _decode_cbor(response)
            returnValue(set(body))
        else:
            raise ClientException(
                response.code,
            )
