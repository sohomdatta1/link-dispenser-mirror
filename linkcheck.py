import requests as r
import json
from urllib.parse import urlparse as parse_url
from socket import getaddrinfo, gaierror
from waybackpy import WaybackMachineCDXServerAPI, WaybackMachineSaveAPI, exceptions as wbpye
from dateutil import parser as date_parser
from uuid import uuid4
import re


headers = json.load(open('headers.json', encoding='utf-8'))
blocked_list = json.load(open('blocked.json', encoding='utf-8'))
ia_useragent = 'Wikimedia_Link_Dispenser/1.0'


def get_url_status_info(url: str, verify=True) -> dict:
    try:
        s = r.Session()
        resp = s.get(
            url,
            headers=headers,
            timeout=60,
            verify=verify,
            stream=True)
    except r.exceptions.TooManyRedirects as exc:
        resp = exc.response
    except r.exceptions.ConnectionError as _:
        print(url, _)
        if verify:
            # Our certificates might be out of date, doesn't matter
            # we will try once more this time with verification
            # disabled.
            return get_url_status_info(url, verify=False)
        return {
            "status": 1337,
            "url": url,
            "timeout": False,
            "history": [],
            "description": 'ConnectionError'
        }
    except r.exceptions.Timeout as _:
        return {
            "status": 1337,
            "url": url,
            "history": [],
            "timeout": True,
            "description": 'Other error'
        }
    except Exception as _:
        print(url, _)
        return {
            "status": 1337,
            "url": url,
            "history": [],
            "timeout": False,
            "description": 'Other error'
        }
    resp.close()
    history = []
    for i in range(1, len(resp.history)):
        res = resp.history[i - 1]
        history.append({
            "url": res.url,
            "status": res.status_code
        })

    if len(resp.history) == 1:
        history.append({
            "url": resp.history[0].url,
            "status": resp.status_code
        })

    if len(history) > 0:
        history[len(history) - 1]['url'] = resp.url

    status_code = history[0]['status'] if len(
        history) > 0 and resp.status_code == 200 else resp.status_code
    return {
        "status": status_code,
        "url": url,
        "blocked": could_be_blocked(url, resp),
        "history": history
    }


def get_dns_info(url: str) -> dict:
    u = parse_url(url)

    try:
        getaddrinfo(u.hostname, u.port or 443)
    except gaierror:
        return {
            "status": 0
        }

    return {
        "status": 1
    }


def save_iarchive_url(url: str) -> dict:
    ia_save_server_api = WaybackMachineSaveAPI(url, ia_useragent)
    try:
        url = ia_save_server_api.save()
    except wbpye.MaximumSaveRetriesExceeded as _:
        return {
            "status": 0
        }
    return {
        "status": 1,
        "archive_url": url,
        "timestamp": ia_save_server_api.timestamp()
    }


def get_iarchive_data(url: str, date: int) -> dict:
    ia_cdx_server_api = WaybackMachineCDXServerAPI(url, ia_useragent)

    try:
        near = ia_cdx_server_api.near(unix_timestamp=date)
    except wbpye.NoCDXRecordFound as _:
        return {
            "status": 0
        }
    except Exception as _:
        return {
            "status": 0
        }
    return {
        "status": 1,
        "archive_url": near.archive_url,
        "timestamp": near.datetime_timestamp.timestamp(),
    }


def could_be_spammy(url_resp: dict):
    if len(url_resp['history']) == 0:
        return False

    start_url_netloc = parse_url(url_resp['history'][0]['url']).netloc

    # doi will generally not be spam??
    if str(start_url_netloc).endswith('doi.org'):
        return False

    for resp in url_resp['history']:
        curr_resp_netloc = parse_url(resp['url']).netloc
        if not curr_resp_netloc.startswith(start_url_netloc):
            return True
    return False


def could_be_blocked(url, resp) -> bool:
    for url_regex in blocked_list:
        if (re.match(url_regex, url)):
            return True
    if resp.status_code == 403 and 'CF-RAY' in resp.headers:
        return True
    return False


def analyze_url(url: str) -> dict:
    json_data = get_url_status_info(url)
    json_data['spammy'] = could_be_spammy(json_data)
    json_data['uid'] = str(uuid4())
    if (json_data['status'] >= 200 and json_data['status']
            <= 299) and not json_data['spammy']:
        json_data['desc'] = 'ok'
        json_data['priority'] = 4
    elif json_data['status'] > 399 and json_data['status'] != 1337:
        json_data['desc'] = 'down'
        json_data['priority'] = 1
    elif ((json_data['status'] > 300 and json_data['status'] < 399) or len(json_data['history']) != 0) and not json_data['spammy']:
        json_data['desc'] = 'redirect'
        json_data['priority'] = 3
    elif json_data['spammy']:
        json_data['desc'] = 'spammy'
        json_data['priority'] = 2
    else:
        json_data['desc'] = 'down'
        json_data['priority'] = 1
    json_data['ok'] = json_data['status'] == 200 or json_data['spammy']
    if json_data['status'] > 399 or json_data['spammy']:
        json_data['dns'] = bool(get_dns_info(url)['status'])
        if not json_data['dns']:
            json_data['desc'] = 'dead'
            json_data['priority'] = 0
        json_data['archives'] = {
            "status": 0
        }
        # get_iarchive_data(url, int( tm.timestamp() ))
    else:
        json_data['archives'] = {
            "status": 0
        }
    return json_data
