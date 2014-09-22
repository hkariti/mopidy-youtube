# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import re
import string
from urlparse import urlparse, parse_qs
from mopidy import backend
from mopidy.models import SearchResult, Track, Album, Artist
import pykka
import pafy
import requests
import unicodedata
from mopidy_youtube import logger

yt_api_endpoint = 'https://www.googleapis.com/youtube/v3/'
yt_key = 'AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4'


def resolve_track(track, stream=False):
    logger.debug("Resolving Youtube for track '%s'", track)
    if hasattr(track, 'uri'):
        return resolve_url(track.comment, stream)
    else:
        return resolve_url(track.split('.')[-1], stream)


def safe_url(uri):
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    safe_uri = unicodedata.normalize(
        'NFKD',
        unicode(uri)
    ).encode('ASCII', 'ignore')
    return re.sub(
        '\s+',
        ' ',
        ''.join(c for c in safe_uri if c in valid_chars)
    ).strip()


def parse_api_object(item):
    video_id = item['id']['videoId']
    title = item['snippet']['title']
    uri = 'youtube:video/%s.%s' % (
        safe_url(title), video_id
    )
    thumbnails = []
    for thumb in ['high', 'medium', 'default']:
        thumbnail = item['snippet']['thumbnails'].get(thumb)
        if thumbnail:
            thumbnails.append(thumbnail['url'])

    return track(uri, video_id, title, thumbnails=thumbnails)

def resolve_url(url, stream=False):
    video = pafy.new(url)
    if not stream:
        uri = 'youtube:video/%s.%s' % (
            safe_url(video.title), video.videoid
        )
    else:
        uri = video.getbestaudio()
        if not uri:  # get video url
            uri = video.getbest()
        logger.debug('%s - %s %s %s' % (
            video.title, uri.bitrate, uri.mediatype, uri.extension))
        uri = uri.url
    if not uri:
        return

    thumbnails = [video.bigthumbhd, video.bigthumb]
    return track(uri, video.videoid, video.title, video.length, thumbnails)

def track(uri, video_id, title, length=0, thumbnails=None):
    if not thumbnails:
        logger.debug("Using empty thumbnails list")
        thumbnails = list()

    if '-' in title:
        title = title.split('-')
        track_obj = Track(
            name=title[1].strip(),
            comment=video_id,
            length=length*1000,
            artists=[Artist(name=title[0].strip())],
            album=Album(
                name='Youtube',
                images=thumbnails
            ),
            uri=uri
        )
    else:
        track_obj = Track(
            name=title,
            comment=video_id,
            length=length*1000,
            album=Album(
                name='Youtube',
                images=thumbnails
            ),
            uri=uri
        )

    logger.debug("Created track object: %s" % track_obj)
    return track_obj


def search_youtube(q):
    query = {
        'part': 'id,snippet',
        'maxResults': 15,
        'type': 'video',
        'q': q,
        'key': yt_key
    }
    pl = requests.get(yt_api_endpoint+'search', params=query)
    playlist = []
    items = pl.json().get('items')
    logger.debug("%d Items from api call" % len(items))
    for item in items:
        try:
            track = parse_api_object(item)
            playlist.append(track)
        except Exception as e:
            logger.exception(e.message)

    logger.debug("Search resulted in %d items" % len(playlist))
    return playlist


def resolve_playlist(url):
    logger.info("Resolving Youtube for playlist '%s'", url)
    pl = pafy.get_playlist(url)
    playlist = []
    for yt_id in pl["items"]:
        try:
            video_id = yt_id["pafy"].videoid
            title = yt_id["playlist_meta"]["title"]
            uri = 'youtube:video/%s.%s' % (
                safe_url(title), video_id
            )
            thumbnails = [yt_id["playlist_meta"]["thumbnail"]]
            video = track(uri, video_id, title, thumbnails)
            playlist.append(video)
        except Exception as e:
            logger.exception(e.message)
    return playlist


class YoutubeBackend(pykka.ThreadingActor, backend.Backend):

    def __init__(self, config, audio):
        super(YoutubeBackend, self).__init__()
        self.config = config
        self.library = YoutubeLibraryProvider(backend=self)
        self.playback = YoutubePlaybackProvider(audio=audio, backend=self)

        self.uri_schemes = ['youtube', 'yt']


class YoutubeLibraryProvider(backend.LibraryProvider):

    def lookup(self, track):
        logger.debug("Logging up track: %s" % track)

        if 'yt:' in track:
            track = track.replace('yt:', '')

        if 'youtube.com' in track:
            url = urlparse(track)
            req = parse_qs(url.query)
            logger.debug("urlparse()ed track is %s" % url)
            logger.debug("parse_qs()ed url is %s" % req)
            if 'list' in req:
                return resolve_playlist(req.get('list')[0])
            else:
                return [resolve_url(track)]
        else:
            return [resolve_url(track)]

    def search(self, query=None, uris=None):
        if not query:
            return

        logger.debug("Got query: %s" % query)
        logger.debug("Got uris: %s" % uris)

        if 'uri' in query:
            search_query = ''.join(query['uri'])
            url = urlparse(search_query)
            if 'youtube.com' in url.netloc:
                req = parse_qs(url.query)
                if 'list' in req:
                    return SearchResult(
                        uri='youtube:search',
                        tracks=resolve_playlist(req.get('list')[0])
                    )
                else:
                    logger.info(
                        "Query is a specific track '%s'", search_query)
                    return SearchResult(
                        uri='youtube:search',
                        tracks=[resolve_url(search_query)]
                    )
        else:
            search_query = '|'.join(query.values()[0]).replace(' ', '|')
            logger.info("Searching Youtube for query '%s'", search_query)
            return SearchResult(
                uri='youtube:search',
                tracks=search_youtube(search_query)
            )


class YoutubePlaybackProvider(backend.PlaybackProvider):

    def play(self, track):
        track = resolve_track(track, True)
        return super(YoutubePlaybackProvider, self).play(track)
